"""Retention and purge job for Recon.

Enforces 30-day raw document retention policy from Build Spec §12.
Removes raw uploaded files whose purge_after timestamp has elapsed,
and writes an append-only audit event.

Records with unparseable timestamps, or storage keys that would resolve outside
the storage root, are never deleted and never marked purged; they are surfaced
as purge_skip audit events so the registry can be repaired. A record whose
file cannot be deleted (for example a permissions error) keeps its storage key
and is surfaced as a purge_failed audit event instead of being marked purged.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _audit_event(rec: dict[str, Any], verb: str, meta: dict[str, Any]) -> dict[str, Any]:
    return {
        "at": utc_now_iso(),
        "actor": "retention_worker",
        "verb": verb,
        "object": f"upload:{rec.get('id')}",
        "meta": {
            "firm_id": rec.get("firm_id"),
            "original_storage_key": rec.get("storage_key"),
            "policy": "30_day_raw_retention",
            **meta,
        },
    }


def purge_expired_uploads(
    upload_records: list[dict[str, Any]],
    storage_root: Path | str,
    cutoff_iso: str | None = None,
) -> tuple[int, list[dict[str, Any]], list[dict[str, Any]]]:
    """Inspects upload records, removes expired files, and generates audit rows.

    Returns:
        (purged_count, updated_records, audit_events)
    """
    if cutoff_iso is None:
        cutoff_dt = datetime.now(timezone.utc)
    else:
        cutoff_dt = _parse_iso(cutoff_iso)
        if cutoff_dt is None:
            raise ValueError(f"cutoff_iso is not a parseable ISO-8601 timestamp: {cutoff_iso!r}")

    storage_root_path = Path(storage_root).resolve()

    audit_events: list[dict[str, Any]] = []
    updated_records: list[dict[str, Any]] = []
    purged_count = 0

    for rec in upload_records:
        rec_copy = dict(rec)
        purge_after = rec.get("purge_after")
        storage_key = rec.get("storage_key")

        if rec.get("purged", False) or purge_after in (None, ""):
            updated_records.append(rec_copy)
            continue

        expires_at = _parse_iso(purge_after)
        if expires_at is None:
            audit_events.append(
                _audit_event(rec, "purge_skip", {"reason": "purge_after is not a parseable ISO-8601 timestamp"})
            )
            updated_records.append(rec_copy)
            continue
        if expires_at > cutoff_dt:
            updated_records.append(rec_copy)
            continue

        bytes_freed = 0
        deletion_error: str | None = None
        if isinstance(storage_key, str) and storage_key:
            try:
                file_path = (storage_root_path / storage_key).resolve()
                inside_root = file_path.is_relative_to(storage_root_path)
            except (OSError, RuntimeError, ValueError):
                file_path = None
                inside_root = False
            if not inside_root:
                audit_events.append(
                    _audit_event(rec, "purge_skip", {"reason": "storage_key escapes the storage root"})
                )
                updated_records.append(rec_copy)
                continue
            if file_path.exists() and file_path.is_file():
                try:
                    bytes_freed = file_path.stat().st_size
                    file_path.unlink()
                except OSError as err:
                    deletion_error = str(err)
                    bytes_freed = 0

        if deletion_error is None:
            rec_copy["purged"] = True
            rec_copy["purged_at"] = utc_now_iso()
            rec_copy["storage_key"] = None
            purged_count += 1
            audit_events.append(_audit_event(rec, "purge", {"bytes_freed": bytes_freed}))
        else:
            audit_events.append(_audit_event(rec, "purge_failed", {"reason": deletion_error, "bytes_freed": 0}))
        updated_records.append(rec_copy)

    return purged_count, updated_records, audit_events


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Purge raw uploads older than 30 days")
    parser.add_argument("--registry", default="data/uploads.json", help="Path to upload registry JSON")
    parser.add_argument("--storage", default="data/storage", help="Path to raw storage root")
    parser.add_argument("--audit-out", default="data/audit_purge.jsonl", help="Append audit events here")
    args = parser.parse_args(argv)

    reg_path = Path(args.registry)
    if not reg_path.exists():
        print(json.dumps({"purged": 0, "message": "No upload registry found"}))
        return 0

    try:
        with reg_path.open("r", encoding="utf-8") as f:
            records = json.load(f)
    except Exception as err:
        print(f"Error reading registry: {err}", file=os.sys.stderr)
        return 1

    purged, updated, audits = purge_expired_uploads(records, args.storage)

    with reg_path.open("w", encoding="utf-8") as f:
        json.dump(updated, f, indent=2)

    if audits:
        audit_path = Path(args.audit_out)
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        with audit_path.open("a", encoding="utf-8") as f:
            for event in audits:
                f.write(json.dumps(event) + "\n")

    print(json.dumps({"purged": purged, "audit_events_written": len(audits)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
