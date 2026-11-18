"""Reproduce a bounded 2025 MELS and REMIT sample, with a B1610 denominator."""
import argparse
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

BASE = "https://data.elexon.co.uk/bmrs/api/v1/"
WINDOWS = {"2025-01-15": 35, "2025-04-15": 37, "2025-07-15": 37, "2025-10-15": 37}
FUELS = {"BIOMASS", "CCGT", "COAL", "NPSHYD", "NUCLEAR", "OCGT", "PS", "WIND"}


def fetch(endpoint, params, cache, filename):
    target = cache / filename if cache is not None else None
    if target is not None and target.exists():
        return json.loads(target.read_bytes())
    url = BASE + endpoint + ("?" + urlencode(params) if params else "")
    with urlopen(url, timeout=60) as response:
        content = response.read()
    data = json.loads(content)
    if target is not None:
        with target.open("xb") as snapshot:
            snapshot.write(content)
    return data


def timestamp(value):
    return datetime.fromisoformat(value)


def mel_sample(day, period, reference, cache):
    start, end = f"{day}T17:00:00Z", f"{day}T17:05:00Z"
    records = fetch("datasets/MELS", {"from": start, "to": end, "format": "json"}, cache, f"mels-{day}.json")["data"]
    outturn = fetch("datasets/B1610", {"settlementDate": day, "settlementPeriod": period, "format": "json"},
                    cache, f"b1610-{day}.json")["data"]
    all_positive = {r["bmUnit"] for r in outturn if r["bmUnit"] and r["quantity"] > 0}
    candidates = {
        r["bmUnit"] for r in outturn
        if r["bmUnit"] in reference and r["quantity"] > 0
        and r["nationalGridBmUnitId"] == reference[r["bmUnit"]]["nationalGridBmUnit"]
    }
    cutoff = timestamp(end)
    latest = {}
    eligible_rows = 0
    for row in records:
        unit = row["bmUnit"]
        if unit not in candidates or row["nationalGridBmUnit"] != reference[unit]["nationalGridBmUnit"]:
            continue
        notification = timestamp(row["notificationTime"])
        if not (notification <= cutoff and timestamp(row["timeFrom"]) <= cutoff < timestamp(row["timeTo"])):
            continue
        eligible_rows += 1
        revision = notification, row["notificationSequence"]
        if unit not in latest or revision > latest[unit][0]:
            latest[unit] = (revision, row)

    return {
        "date": day, "settlement_period": period, "mels_window_utc": [start, end],
        "mels_rows": len(records), "mels_distinct_bmu": len({r["bmUnit"] for r in records if r["bmUnit"]}),
        "b1610_rows": len(outturn), "b1610_runs": sorted({r["settlementRunType"] for r in outturn}),
        "positive_b1610_units": len(all_positive), "sample_denominator": len(candidates),
        "positive_units_excluded_by_reference_filter": len(all_positive - candidates),
        "eligible_mels_rows_before_deduplication": eligible_rows, "matched_as_of_cutoff": len(latest),
        "pct_of_sample": round(100 * len(latest) / len(candidates), 1) if candidates else None,
    }


def remit_sample(cache):
    params = {"from": "2025-01-15T00:00:00Z", "to": "2025-01-16T00:00:00Z", "profileOnly": "true"}
    latest = fetch("remit/list/by-event", {**params, "latestRevisionOnly": "true"}, cache, "remit-list.json")["data"]
    all_revisions = fetch("remit/list/by-event", {**params, "latestRevisionOnly": "false"}, cache, "remit-revisions.json")["data"]
    revisions = Counter(row["mrid"] for row in all_revisions)
    detail = fetch("remit/807235", {}, cache, "remit-807235.json")["data"][0]
    listed = next((row for row in all_revisions if row["id"] == detail["id"]), None)
    profile = detail["outageProfile"]
    return {
        "event_window": params, "latest_rows": len(latest), "latest_distinct_ids": len({r["id"] for r in latest}),
        "latest_distinct_mrids": len({r["mrid"] for r in latest}),
        "all_revision_rows": len(all_revisions), "all_distinct_ids": len({r["id"] for r in all_revisions}),
        "all_distinct_mrids": len(revisions), "mrids_with_multiple_rows": sum(count > 1 for count in revisions.values()),
        "detail": {
            **{key: detail[key] for key in ("id", "mrid", "revisionNumber", "eventType", "unavailabilityType",
                                           "eventStartTime", "eventEndTime", "publishTime", "normalCapacity",
                                           "availableCapacity", "unavailableCapacity")},
            "identity_matches_revision_index": bool(listed and all(
                listed[key] == detail[key] for key in ("mrid", "revisionNumber", "publishTime")
            )),
            "profile_steps": len(profile),
            "profile_contiguous": (
                profile[0]["startTime"] == detail["eventStartTime"]
                and profile[-1]["endTime"] == detail["eventEndTime"]
                and all(timestamp(p["startTime"]) < timestamp(p["endTime"]) for p in profile)
                and all(a["endTime"] == b["startTime"] for a, b in zip(profile, profile[1:]))
            ),
            "profile_capacity_in_bounds": all(0 <= p["capacity"] <= detail["normalCapacity"] for p in profile),
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, help="Save and reuse raw JSON responses in this directory")
    args = parser.parse_args()
    if args.cache is not None:
        args.cache.mkdir(parents=True, exist_ok=True)
    standing_data = fetch("reference/bmunits/all", {}, args.cache, "bmu.json")
    reference = {
        r["elexonBmUnit"]: r for r in standing_data
        if r["bmUnitType"] == "T" and (r["elexonBmUnit"] or "").startswith("T_")
        and r["fuelType"] in FUELS and r["nationalGridBmUnit"] and not r["interconnectorId"]
        and float(r["generationCapacity"] or 0) > 0
    }
    print(json.dumps({
        "reference_candidates": len(reference),
        "MELS": [mel_sample(day, period, reference, args.cache) for day, period in WINDOWS.items()],
        "REMIT": remit_sample(args.cache),
    }, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
