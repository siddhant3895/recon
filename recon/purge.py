"""Retention and purge job for Recon.

Enforces 30-day raw document retention policy from Build Spec §12.
Removes raw uploaded files whose purge_after timestamp has elapsed,
and writes an append-only audit event.
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
        cutoff_iso = utc_now_iso()

    storage_path = Path(storage_root)
    audit_events: list[dict[str, Any]] = []
    updated_records: list[dict[str, Any]] = []
    purged_count = 0

    for rec in upload_records:
        rec_copy = dict(rec)
        purge_after = rec.get("purge_after")
        storage_key = rec.get("storage_key")
        is_purged = rec.get("purged", False)

        if not is_purged and purge_after and purge_after <= cutoff_iso:
            file_path = storage_path / storage_key if storage_key else None
            bytes_freed = 0
            if file_path and file_path.exists() and file_path.is_file():
                try:
                    bytes_freed = file_path.stat().st_size
                    file_path.unlink()
                except OSError as err:
                    # Log error but do not hang
                    bytes_freed = 0

            rec_copy["purged"] = True
            rec_copy["purged_at"] = utc_now_iso()
            rec_copy["storage_key"] = None
            purged_count += 1

            audit_events.append(
                {
                    "at": utc_now_iso(),
                    "actor": "retention_worker",
                    "verb": "purge",
                    "object": f"upload:{rec.get('id')}",
                    "meta": {
                        "firm_id": rec.get("firm_id"),
                        "original_storage_key": storage_key,
                        "bytes_freed": bytes_freed,
                        "policy": "30_day_raw_retention",
                    },
                }
            )
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
