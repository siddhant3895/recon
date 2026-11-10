from __future__ import annotations

import argparse
import json
import random
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from .engine import run_matching
from .export import compute_run_id, export_csv, export_xlsx
from .golden import load_golden, write_golden
from .metrics import category_breakdown, evaluate, lines_from_golden
from .models import Line
from .normalizer import NormalizationError, normalize_record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="recon", description="Recon reconciliation prep engine")
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build-golden", help="generate the deterministic golden dataset")
    build.add_argument("--out", default="data/golden.json")
    build.add_argument("--seed", type=int, default=42)

    accuracy = sub.add_parser("accuracy", help="run the engine over the golden set and report metrics")
    accuracy.add_argument("--data", default="data/golden.json")
    accuracy.add_argument("--json-out", default="data/accuracy_report.json")
    accuracy.add_argument("--md-out", default="data/accuracy_report.md")

    demo = sub.add_parser("demo", help="run the seeded demo and export XLSX + CSV")
    demo.add_argument("--data", default="data/golden.json")
    demo.add_argument("--out", default="out")
    demo.add_argument("--format", choices=["csv", "xlsx", "both"], default="both")

    match = sub.add_parser("match", help="match two JSON record files")
    match.add_argument("--statement", required=True)
    match.add_argument("--ledger", required=True)
    match.add_argument("--out", default="out")
    match.add_argument("--format", choices=["csv", "xlsx", "both"], default="both")

    run = sub.add_parser("run-json", help="emit the full deterministic run as JSON")
    run.add_argument("--data", default="data/golden.json")
    run.add_argument("--out", default="out/run.json")

    bench = sub.add_parser("benchmark", help="time a synthetic 5,000-row pair")
    bench.add_argument("--rows", type=int, default=5000)

    purge = sub.add_parser("purge", help="purge raw uploads older than 30 days and write audit records")
    purge.add_argument("--registry", default="data/uploads.json")
    purge.add_argument("--storage", default="data/storage")
    purge.add_argument("--audit-out", default="data/audit_purge.jsonl")

    serve = sub.add_parser("serve", help="launch the Recon web server & interactive review app")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true")

    args = parser.parse_args(argv)
    if args.command == "serve":
        import uvicorn
        uvicorn.run("recon.service:app", host=args.host, port=args.port, reload=args.reload)
        return 0
    if args.command == "build-golden":
        return _build_golden(args)
    if args.command == "accuracy":
        return _accuracy(args)
    if args.command == "demo":
        return _demo(args)
    if args.command == "match":
        return _match(args)
    if args.command == "run-json":
        return _run_json(args)
    if args.command == "benchmark":
        return _benchmark(args)
    if args.command == "purge":
        from .purge import purge_expired_uploads
        reg_path = Path(args.registry)
        if not reg_path.exists():
            print(json.dumps({"purged": 0, "message": "No upload registry found"}))
            return 0
        with reg_path.open("r", encoding="utf-8") as f:
            records = json.load(f)
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
    return 2


def _build_golden(args: argparse.Namespace) -> int:
    golden = write_golden(args.out, seed=args.seed)
    print(json.dumps({
        "written": str(Path(args.out)),
        "statement_lines": len(golden["statement"]),
        "ledger_lines": len(golden["ledger"]),
        "pairs": golden["pairs"],
        "categories": category_breakdown(golden),
    }, indent=2, sort_keys=True))
    return 0


def _accuracy(args: argparse.Namespace) -> int:
    golden = load_golden(args.data)
    report = evaluate(golden)
    report["categories"] = category_breakdown(golden)

    json_path = Path(args.json_out)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    md_path = Path(args.md_out)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(render_accuracy_markdown(report), encoding="utf-8")

    print(render_accuracy_markdown(report))
    return 0


def _demo(args: argparse.Namespace) -> int:
    golden = load_golden(args.data)
    stmt_lines, ledger_lines = lines_from_golden(golden)
    result = run_matching(stmt_lines, ledger_lines)
    out_dir = Path(args.out)
    paths = _write_exports(result, out_dir, args.format)
    print(json.dumps({
        "run_id": compute_run_id(result),
        "counts": result.counts,
        "exports": {name: str(path) for name, path in paths.items()},
    }, indent=2, sort_keys=True))
    return 0


def _match(args: argparse.Namespace) -> int:
    stmt_records = _read_records(args.statement)
    ledger_records = _read_records(args.ledger)
    stmt_lines, unparsed = _normalize_all(stmt_records, "stmt")
    ledger_lines, ledger_unparsed = _normalize_all(ledger_records, "ledger")
    unparsed.extend(ledger_unparsed)
    result = run_matching(stmt_lines, ledger_lines)
    paths = _write_exports(result, Path(args.out), args.format, unparsed=unparsed)
    payload = {
        "run_id": compute_run_id(result),
        "counts": result.counts,
        "unparsed": len(unparsed),
        "exports": {name: str(path) for name, path in paths.items()},
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def _run_json(args: argparse.Namespace) -> int:
    golden = load_golden(args.data)
    stmt_lines, ledger_lines = lines_from_golden(golden)
    result = run_matching(stmt_lines, ledger_lines)
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"written": str(target), "run_id": compute_run_id(result)}, indent=2, sort_keys=True))
    return 0


def _benchmark(args: argparse.Namespace) -> int:
    rows = args.rows
    rng = random.Random(7)
    stmt_lines: list[Line] = []
    ledger_lines: list[Line] = []
    base = date(2026, 9, 1)
    for index in range(rows):
        amount = 100_000 + index * 1_009
        day = base + timedelta(days=index % 28)
        ref = str(20_000_000 + index * 31)
        stmt_lines.append(normalize_record({
            "id": f"S{index:05d}",
            "text": f"NEFT/{ref} Bench Vendor {index}",
            "amount_paise": amount,
            "date": day.isoformat(),
            "direction": "debit" if index % 2 else "credit",
        }, "stmt"))
        ledger_lines.append(normalize_record({
            "id": f"L{index:05d}",
            "text": f"NEFT {ref} Bench Vendor {index}",
            "amount_paise": amount,
            "date": (day + timedelta(days=rng.randint(0, 2))).isoformat(),
            "direction": "debit" if index % 2 else "credit",
        }, "ledger"))

    started = time.perf_counter()
    result = run_matching(stmt_lines, ledger_lines)
    elapsed = time.perf_counter() - started
    payload = {
        "rows": rows,
        "elapsed_seconds": round(elapsed, 3),
        "under_90s": elapsed < 90.0,
        "counts": result.counts,
        "tiers": result.tiers,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if elapsed < 90.0 else 1


def _write_exports(result, out_dir: Path, fmt: str, unparsed=None) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    if fmt in {"csv", "both"}:
        csv_paths = export_csv(result, out_dir, unparsed=unparsed)
        paths.update({f"csv_{name}": path for name, path in csv_paths.items()})
    if fmt in {"xlsx", "both"}:
        paths["xlsx"] = export_xlsx(result, out_dir / "recon_export.xlsx", unparsed=unparsed)
    return paths


def _read_records(path: str) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("records", "lines", "statement", "ledger"):
            if isinstance(payload.get(key), list):
                return payload[key]
    raise SystemExit(f"{path}: expected a JSON list of records")


def _normalize_all(records: list[dict[str, Any]], side: str) -> tuple[list[Line], list[dict[str, Any]]]:
    lines: list[Line] = []
    unparsed: list[dict[str, Any]] = []
    for record in records:
        try:
            lines.append(normalize_record(record, side))  # type: ignore[arg-type]
        except NormalizationError as exc:
            unparsed.append({"id": record.get("id", ""), "side": side, "reason": str(exc), "raw": record})
    return lines, unparsed


def render_accuracy_markdown(report: dict[str, Any]) -> str:
    metrics = report["metrics"]
    dataset = report["dataset"]
    rows = [
        "# Recon accuracy report",
        "",
        f"Normalizer: `{report['normalizer_version']}`",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Auto-suggest precision | {metrics['precision_auto_suggest']:.2%} |",
        f"| Overall recall | {metrics['recall_overall']:.2%} |",
        f"| Top-1 recall | {metrics['recall_top1']:.2%} |",
        f"| Auto-suggest rate | {metrics['auto_suggest_rate']:.2%} |",
        f"| Review rate | {metrics['review_rate']:.2%} |",
        f"| Unmatched rate | {metrics['unmatched_rate']:.2%} |",
        f"| Gate violations | {dataset['gate_violations']} |",
        f"| Labelled pairs | {dataset['labelled_pairs']} |",
        "",
        "## Counts",
        "",
        "```json",
        json.dumps(report["counts"], indent=2, sort_keys=True),
        "```",
        "",
        "## What it does not catch",
        "",
        "- Screenshot or scan-only PDFs. v1 refuses them rather than guessing.",
        "- Matches outside the configured amount and date windows.",
        "- Parties whose narration and reference both change completely.",
        "- Anything requiring an accounting judgement rather than a data match.",
    ]
    if report.get("wrong_auto_suggests"):
        rows.extend(["", "## Wrong auto-suggests", "", "```json", json.dumps(report["wrong_auto_suggests"], indent=2), "```"])
    return "\n".join(rows) + "\n"


if __name__ == "__main__":
    sys.exit(main())
