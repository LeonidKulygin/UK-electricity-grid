"""Audit NESO's 2025 GB settlement series; accepted input can also be local."""
import argparse
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
from urllib.request import urlopen
from zoneinfo import ZoneInfo

import pandas as pd

URL = (
    "https://api.neso.energy/dataset/8f2fe0af-871c-488d-8bad-960426f24601/"
    "resource/b2bde559-3455-4021-b179-dfe60c0337b0/download/demanddata_2025.csv"
)
DATE, PERIOD = "SETTLEMENT_DATE", "SETTLEMENT_PERIOD"
FLOW = tuple(f"{name}_FLOW" for name in (
    "IFA", "IFA2", "BRITNED", "MOYLE", "EAST_WEST", "NEMO", "NSL", "ELECLINK", "VIKING", "GREENLINK"
))
DEMAND = ("ND", "TSD", "ENGLAND_WALES_DEMAND")
RENEWABLES = tuple(f"EMBEDDED_{name}_{field}" for name in ("WIND", "SOLAR") for field in ("GENERATION", "CAPACITY"))
NUMERIC = (PERIOD, *DEMAND, *RENEWABLES, "NON_BM_STOR", "PUMP_STORAGE_PUMPING", "SCOTTISH_TRANSFER", *FLOW)


def expected_calendar():
    london = ZoneInfo("Europe/London")
    start = date(2025, 1, 1)
    calendar = {}
    for offset in range(365):
        day = start + timedelta(days=offset)
        midnight = datetime.combine(day, time.min, london).astimezone(timezone.utc)
        next_midnight = datetime.combine(day + timedelta(days=1), time.min, london).astimezone(timezone.utc)
        count = (next_midnight - midnight) // timedelta(minutes=30)
        calendar[day] = [midnight + timedelta(minutes=30 * period) for period in range(count)]
    return calendar


def audit(content):
    frame = pd.read_csv(BytesIO(content), dtype="string")
    missing_columns = set((DATE, *NUMERIC)) - set(frame)
    if missing_columns:
        raise ValueError(f"Missing required columns: {sorted(missing_columns)}")
    calendar = expected_calendar()
    keys = {(day, index) for day, times in calendar.items() for index in range(1, len(times) + 1)}
    dates = pd.to_datetime(frame[DATE], format="%Y-%m-%d", errors="coerce").dt.date
    stats = {}
    for field in NUMERIC:
        column = frame[field].str.strip()
        missing = column.isna() | column.eq("").fillna(False)
        integer = column.str.fullmatch(r"[+-]?\d+", na=False)
        values = frame[field] = pd.to_numeric(column.where(integer)).astype("Int64")
        stats[field] = {
            "missing": int(missing.sum()), "invalid_integer": int((~integer & ~missing).sum()),
            "zeros": int(values.eq(0).sum()), "negative": int(values.lt(0).sum()),
            "min": int(values.min()) if values.count() else None,
            "max": int(values.max()) if values.count() else None,
        }
    observed = Counter(zip(dates, frame[PERIOD]))
    valid_keys = observed.keys() & keys
    timestamps = [calendar[day][period - 1] for day, period in sorted(valid_keys)]
    flags = {
        "nonpositive_demand": {name: int(frame[name].le(0).sum()) for name in DEMAND},
        "tsd_below_nd": int(frame.TSD.lt(frame.ND).sum()),
        "embedded_generation_above_capacity": {
            name: int(frame[f"EMBEDDED_{name}_GENERATION"].gt(frame[f"EMBEDDED_{name}_CAPACITY"]).sum())
            for name in ("WIND", "SOLAR")
        },
    }
    # Tukey outer fences are a review flag, not a reason to delete genuine peaks.
    for name in (*DEMAND, "EMBEDDED_WIND_GENERATION", "EMBEDDED_SOLAR_GENERATION", *FLOW):
        if not frame[name].count():
            continue
        lower, _, upper = frame[name].quantile([.25, .5, .75])
        spread = upper - lower
        stats[name]["outer_fence_flags"] = (
            int((frame[name].lt(lower - 3 * spread) | frame[name].gt(upper + 3 * spread)).sum())
            if spread else None
        )
    return {
        "sha256": sha256(content).hexdigest(), "rows": len(frame), "columns": len(frame.columns),
        "missing_keys": len(keys - observed.keys()), "unexpected_keys": len(observed.keys() - keys),
        "duplicate_key_rows": sum(count - 1 for count in observed.values()),
        "invalid_dates": int(dates.isna().sum()),
        "first_utc": timestamps[0].isoformat() if timestamps else None,
        "last_utc": timestamps[-1].isoformat() if timestamps else None,
        "clock_changes": {
            day.isoformat(): {"expected": len(times), "observed": sum(observed[day, p] for p in range(1, len(times) + 1))}
            for day, times in calendar.items() if len(times) != 48
        },
        "flags": flags, "numeric_fields": stats,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, help="Audit a previously downloaded CSV instead of fetching it")
    args = parser.parse_args()
    if args.csv:
        content = args.csv.read_bytes()
    else:
        with urlopen(URL, timeout=60) as response:
            content = response.read()
    result = audit(content)
    print(json.dumps(result, indent=2, allow_nan=False))
    invalid_keys = any(result[name] for name in ("missing_keys", "unexpected_keys", "duplicate_key_rows", "invalid_dates"))
    invalid_fields = any(field["missing"] or field["invalid_integer"] for field in result["numeric_fields"].values())
    return int(invalid_keys or invalid_fields)


if __name__ == "__main__":
    raise SystemExit(main())
