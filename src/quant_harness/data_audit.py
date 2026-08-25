from __future__ import annotations

from datetime import date
from pathlib import Path

REQUIRED_FIELDS = ("open", "high", "low", "close", "volume")


def audit_qlib_data(
    provider_uri: Path,
    *,
    required_start: str,
    required_end: str,
    instruments_name: str = "csi300",
) -> dict:
    findings = []
    calendar_path = provider_uri / "calendars" / "day.txt"
    instrument_path = provider_uri / "instruments" / f"{instruments_name}.txt"
    if not calendar_path.exists():
        findings.append("missing day calendar")
        calendars = []
    else:
        calendars = [
            line.strip()
            for line in calendar_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    if not instrument_path.exists():
        findings.append(f"missing instruments/{instruments_name}.txt")
        rows = []
    else:
        rows = [
            line.split("\t")
            for line in instrument_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    invalid_rows = []
    symbols = set()
    for index, row in enumerate(rows, start=1):
        if len(row) != 3:
            invalid_rows.append(index)
            continue
        symbol, start, end = row
        symbols.add(symbol.lower())
        try:
            if date.fromisoformat(start) > date.fromisoformat(end):
                invalid_rows.append(index)
        except ValueError:
            invalid_rows.append(index)
    if invalid_rows:
        findings.append(f"invalid instrument rows: {len(invalid_rows)}")
    calendar_sorted = calendars == sorted(set(calendars))
    if calendars and not calendar_sorted:
        findings.append("calendar is not strictly sorted and unique")
    coverage_ok = bool(
        calendars and calendars[0] <= required_start and calendars[-1] >= required_end
    )
    if not coverage_ok:
        findings.append("calendar does not cover required paper period")
    historical_membership = len(rows) > len(symbols)
    if rows and not historical_membership:
        findings.append("CSI300 file has no historical membership ranges")
    field_samples = {}
    feature_root = provider_uri / "features"
    for symbol in sorted(symbols)[:50]:
        directory = feature_root / symbol
        if not directory.exists():
            continue
        for field in REQUIRED_FIELDS:
            field_samples[field] = field_samples.get(field, 0) + int(
                (directory / f"{field}.day.bin").exists()
            )
    missing_sample_fields = [field for field in REQUIRED_FIELDS if field_samples.get(field, 0) == 0]
    if missing_sample_fields:
        findings.append("sample contains no files for: " + ", ".join(missing_sample_fields))
    return {
        "status": "ok" if not findings else "failed",
        "provider_uri": str(provider_uri),
        "calendar_start": calendars[0] if calendars else None,
        "calendar_end": calendars[-1] if calendars else None,
        "calendar_count": len(calendars),
        "calendar_sorted_unique": calendar_sorted,
        "required_start": required_start,
        "required_end": required_end,
        "coverage_ok": coverage_ok,
        "membership_row_count": len(rows),
        "unique_symbol_count": len(symbols),
        "historical_membership_ranges": historical_membership,
        "sample_field_file_counts": field_samples,
        "findings": findings,
    }
