from __future__ import annotations

import json
import random
from datetime import date, timedelta
from pathlib import Path
from typing import Any

VENDORS = [
    "Sharma Traders",
    "Deshmukh Electricals",
    "Nagpur Steel Co",
    "Vidarbha Logistics",
    "Orange City Packaging",
    "Sitabuldi Hardware",
    "Kamptee Cotton Mills",
    "Wardha Road Agencies",
    "Dharampeth Stationers",
    "Itwari Wholesale",
    "Amravati Auto Parts",
    "Hingna Industrial Supply",
]

CATEGORY_PLAN = [
    ("tier1", 90),
    ("tier2", 70),
    ("tier3", 60),
    ("tier4", 40),
    ("nasty", 40),
]

NASTY_PLAN = ["ocr", "ambiguous", "multiref", "decoy"]


def build_golden(seed: int = 42) -> dict[str, Any]:
    rng = random.Random(seed)
    statement: list[dict[str, Any]] = []
    ledger: list[dict[str, Any]] = []
    labels: dict[str, list[str]] = {}
    categories: dict[str, str] = {}

    planned = [category for category, count in CATEGORY_PLAN for _ in range(count)]
    if len(planned) != 300:
        raise ValueError("golden plan must total 300 pairs")

    ledger_counter = 0
    decoy_counter = 0

    for index, category in enumerate(planned):
        pair_no = index + 1
        stmt_id = f"S{pair_no:04d}"
        amount = 200_000 + pair_no * 13_337
        base = date(2026, 10, 5) + timedelta(days=rng.randint(0, 18))
        direction = "debit" if pair_no % 3 else "credit"
        vendor = VENDORS[index % len(VENDORS)]
        invoice = 1000 + pair_no
        ref = str(10_000_000 + pair_no * 137)

        if category == "tier1":
            stmt_id, ledgers = _tier1(
                stmt_id, amount, base, direction, vendor, invoice, ref, statement, ledger, ledger_counter
            )
            labels[stmt_id] = [line["id"] for line in ledgers]
            ledger_counter += len(ledgers)
            categories[stmt_id] = "tier1"
            if pair_no % 5 == 0:
                decoy_counter, extra = _decoys(
                    amount, base, direction, vendor, ref, ledger, ledger_counter, decoy_counter, count=1
                )
                ledger_counter += len(extra)

        elif category == "tier2":
            stmt_id, ledgers = _tier2(
                stmt_id, amount, base, direction, vendor, invoice, ref, statement, ledger, ledger_counter, rng
            )
            labels[stmt_id] = [line["id"] for line in ledgers]
            ledger_counter += len(ledgers)
            categories[stmt_id] = "tier2"

        elif category == "tier3":
            stmt_id, ledgers = _tier3(
                stmt_id, amount, base, direction, vendor, invoice, statement, ledger, ledger_counter, rng
            )
            labels[stmt_id] = [line["id"] for line in ledgers]
            ledger_counter += len(ledgers)
            categories[stmt_id] = "tier3"

        elif category == "tier4":
            stmt_id, ledgers = _tier4(
                stmt_id, amount, base, direction, vendor, invoice, statement, ledger, ledger_counter, rng
            )
            labels[stmt_id] = [line["id"] for line in ledgers]
            ledger_counter += len(ledgers)
            categories[stmt_id] = "tier4"

        else:
            subtype = NASTY_PLAN[(pair_no - 1) % len(NASTY_PLAN)]
            stmt_id, ledgers, extra, decoy_counter = _nasty(
                subtype,
                stmt_id,
                amount,
                base,
                direction,
                vendor,
                invoice,
                ref,
                statement,
                ledger,
                ledger_counter,
                decoy_counter,
                rng,
            )
            labels[stmt_id] = [line["id"] for line in ledgers]
            ledger_counter += len(ledgers) + len(extra)
            categories[stmt_id] = f"nasty_{subtype}"

    statement.sort(key=lambda row: row["id"])
    ledger.sort(key=lambda row: row["id"])

    return {
        "version": "golden_v1",
        "seed": seed,
        "normalizer_version": "normalizer_v1",
        "pairs": len(labels),
        "statement": statement,
        "ledger": ledger,
        "labels": dict(sorted(labels.items())),
        "categories": dict(sorted(categories.items())),
    }


def build_demo(seed: int = 99) -> dict[str, Any]:
    golden = build_golden(seed=seed)
    by_category: dict[str, list[dict[str, Any]]] = {}
    for stmt in golden["statement"]:
        by_category.setdefault(golden["categories"][stmt["id"]], []).append(stmt)

    plan = [
        ("tier1", 88),
        ("tier2", 35),
        ("tier3", 25),
        ("tier4", 8),
        ("nasty_ocr", 2),
        ("nasty_ambiguous", 2),
        ("nasty_multiref", 2),
        ("nasty_decoy", 2),
    ]
    selection: list[dict[str, Any]] = []
    for category, count in plan:
        selection.extend(by_category.get(category, [])[:count])

    labels = {stmt["id"]: golden["labels"][stmt["id"]] for stmt in selection}
    needed_ledger = sorted({ledger_id for ids in labels.values() for ledger_id in ids})
    ledger_by_id = {row["id"]: row for row in golden["ledger"]}
    ledger = [ledger_by_id[ledger_id] for ledger_id in needed_ledger]

    extras: list[dict[str, Any]] = []
    extra_count = max(0, 180 - len(selection))
    for index in range(extra_count):
        day = date(2026, 10, 5) + timedelta(days=index % 20)
        extras.append(
            _record(
                f"U{index + 1:04d}",
                f"NEFT/{30_000_000 + index * 911} Unmatched Vendor {index + 1} INVOICE {9000 + index}",
                900_000 + index * 17_003,
                day,
                "debit" if index % 2 else "credit",
            )
        )
    statement = sorted(selection + extras, key=lambda row: row["id"])
    ledger.sort(key=lambda row: row["id"])

    return {
        "version": "demo_v1",
        "seed": seed,
        "normalizer_version": "normalizer_v1",
        "pairs": len(labels),
        "statement": statement,
        "ledger": ledger,
        "labels": dict(sorted(labels.items())),
        "categories": {stmt["id"]: golden["categories"][stmt["id"]] for stmt in selection},
        "watermark": "SAMPLE DATA",
    }


def _record(
    record_id: str,
    text: str,
    amount: int,
    day: date,
    direction: str,
    source: str = "csv",
    date_format: str = "iso",
) -> dict[str, Any]:
    date_text = day.isoformat() if date_format == "iso" else day.strftime("%d/%m/%Y")
    return {
        "id": record_id,
        "text": text,
        "amount_paise": amount,
        "date": date_text,
        "direction": direction,
        "source": source,
    }


def _tier1(stmt_id, amount, base, direction, vendor, invoice, ref, statement, ledger, ledger_counter):
    statement.append(
        _record(stmt_id, f"NEFT/{ref} {vendor} INVOICE {invoice}", amount, base, direction)
    )
    ledger_id = f"L{ledger_counter + 1:04d}"
    line = _record(ledger_id, f"NEFT {ref} {vendor} INV {invoice}", amount, base, direction)
    ledger.append(line)
    return stmt_id, [line]


def _tier2(stmt_id, amount, base, direction, vendor, invoice, ref, statement, ledger, ledger_counter, rng):
    statement.append(
        _record(stmt_id, f"RTGS {ref} {vendor} INVOICE {invoice}", amount, base, direction)
    )
    variant = ref[:-1] + str((int(ref[-1]) + rng.randint(1, 8)) % 10)
    offset = rng.randint(1, 3)
    ledger_id = f"L{ledger_counter + 1:04d}"
    line = _record(
        ledger_id,
        f"RTGS {variant} {vendor} INV {invoice}",
        amount,
        base + timedelta(days=offset),
        direction,
    )
    ledger.append(line)
    return stmt_id, [line]


def _tier3(stmt_id, amount, base, direction, vendor, invoice, statement, ledger, ledger_counter, rng):
    statement.append(
        _record(stmt_id, f"UPI {vendor} INVOICE {invoice} SETTLEMENT", amount, base, direction)
    )
    delta = max(1, round(amount * 0.003))
    ledger_amount = amount + delta
    offset = rng.randint(4, 6)
    ledger_id = f"L{ledger_counter + 1:04d}"
    line = _record(
        ledger_id,
        f"UPI {vendor} INV {invoice} SETTLEMENT RECEIVED",
        ledger_amount,
        base + timedelta(days=offset),
        direction,
    )
    ledger.append(line)
    return stmt_id, [line]


def _tier4(stmt_id, amount, base, direction, vendor, invoice, statement, ledger, ledger_counter, rng):
    statement.append(
        _record(stmt_id, f"IMPS BATCH {vendor} INVOICE {invoice}", amount, base, direction)
    )
    parts = rng.choice([2, 3, 4])
    if parts == 2:
        weights = [0.37, 0.63]
    elif parts == 3:
        weights = [0.21, 0.33, 0.46]
    else:
        weights = [0.13, 0.21, 0.27, 0.39]
    splits = [int(amount * weight) for weight in weights[:-1]]
    splits.append(amount - sum(splits))
    lines = []
    for part_no, split in enumerate(splits):
        ledger_id = f"L{ledger_counter + part_no + 1:04d}"
        line = _record(
            ledger_id,
            f"{vendor} INVOICE {invoice} PART {part_no + 1}",
            split,
            base + timedelta(days=rng.randint(0, 2)),
            direction,
        )
        ledger.append(line)
        lines.append(line)
    return stmt_id, lines


def _decoys(amount, base, direction, vendor, ref, ledger, ledger_counter, decoy_counter, count=1):
    added = []
    other_vendors = ["Ridhpur Papers", "Gondia Tools", "Bhandara Fabrics"]
    for _ in range(count):
        decoy_counter += 1
        ledger_id = f"LX{ledger_counter + len(added) + 1:04d}{decoy_counter:02d}"
        other_vendor = other_vendors[decoy_counter % len(other_vendors)]
        other_ref = str(90_000_000 + decoy_counter * 733)
        line = _record(
            ledger_id,
            f"NEFT {other_ref} {other_vendor} INVOICE 9{decoy_counter:03d}",
            amount,
            base,
            direction,
        )
        ledger.append(line)
        added.append(line)
    return decoy_counter, added


def _nasty(
    subtype,
    stmt_id,
    amount,
    base,
    direction,
    vendor,
    invoice,
    ref,
    statement,
    ledger,
    ledger_counter,
    decoy_counter,
    rng,
):
    extra: list[dict[str, Any]] = []
    if subtype == "ocr":
        ocr_ref = _ocrify(ref)
        statement.append(
            _record(
                stmt_id,
                f"NEFT/{ocr_ref} {vendor} INVOICE {invoice}",
                amount,
                base,
                direction,
                source="ocr",
                date_format="dmy",
            )
        )
        ledger_id = f"L{ledger_counter + 1:04d}"
        line = _record(ledger_id, f"NEFT {ref} {vendor} INV {invoice}", amount, base, direction)
        ledger.append(line)
        return stmt_id, [line], extra, decoy_counter

    if subtype == "ambiguous":
        statement.append(
            _record(
                stmt_id,
                f"NEFT {ref} {vendor} INVOICE {invoice}",
                amount,
                base,
                direction,
                date_format="dmy",
            )
        )
        ledger_id = f"L{ledger_counter + 1:04d}"
        line = _record(
            ledger_id,
            f"NEFT {ref} {vendor} INV {invoice}",
            amount,
            base + timedelta(days=rng.randint(15, 20)),
            direction,
        )
        ledger.append(line)
        return stmt_id, [line], extra, decoy_counter

    if subtype == "multiref":
        account = str(5_000_000_000 + invoice)
        statement.append(
            _record(
                stmt_id,
                f"NEFT/{account}/{ref} {vendor} INVOICE {invoice}",
                amount,
                base,
                direction,
            )
        )
        ledger_id = f"L{ledger_counter + 1:04d}"
        line = _record(ledger_id, f"NEFT {ref} {vendor} INV {invoice}", amount, base, direction)
        ledger.append(line)
        decoy_counter, extra = _decoys(
            amount, base, direction, vendor, ref, ledger, ledger_counter + 1, decoy_counter, count=2
        )
        return stmt_id, [line], extra, decoy_counter

    statement.append(
        _record(stmt_id, f"NEFT/{ref} {vendor} INVOICE {invoice}", amount, base, direction)
    )
    ledger_id = f"L{ledger_counter + 1:04d}"
    line = _record(ledger_id, f"NEFT {ref} {vendor} INV {invoice}", amount, base, direction)
    ledger.append(line)
    decoy_counter, extra = _decoys(
        amount, base, direction, vendor, ref, ledger, ledger_counter + 1, decoy_counter, count=3
    )
    return stmt_id, [line], extra, decoy_counter


def _ocrify(ref: str) -> str:
    mapping = {"0": "O", "1": "l", "5": "S", "8": "B", "2": "Z", "6": "G"}
    changed = []
    for index, char in enumerate(ref):
        if index in (2, 5) and char in mapping:
            changed.append(mapping[char])
        else:
            changed.append(char)
    return "".join(changed)


def write_golden(path: str | Path, seed: int = 42) -> dict[str, Any]:
    golden = build_golden(seed=seed)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(golden, indent=2, sort_keys=True), encoding="utf-8")
    return golden


def load_golden(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))
