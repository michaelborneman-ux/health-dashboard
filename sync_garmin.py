"""Sync Garmin running data into the Health Dashboard from a CSV export.

How to export: Garmin Connect website -> Activities -> All Activities ->
"Export CSV". Save (or leave) the file as Activities.csv in Downloads,
then run this script (Sync Garmin.bat). Writes public/data/garmin-data.js.
"""

import csv
import json
import os
import sys
from datetime import date, datetime, timedelta

WEEKLY_GOAL_KM = 25          # sub-score = weekly km vs this goal, capped at 100
CSV_FILE = os.path.expanduser("~/Downloads/Activities.csv")
OUT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "public", "data", "garmin-data.js")


def num(s):
    """Parse Garmin CSV numbers like '2,496' / '2.38' / '--'."""
    s = (s or "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return 0.0


def duration_secs(s):
    """'00:14:48' or '00:14:48.2' -> seconds."""
    try:
        parts = [float(p) for p in s.split(":")]
        secs = 0.0
        for p in parts:
            secs = secs * 60 + p
        return secs
    except (ValueError, AttributeError):
        return 0.0


def fmt_pace(seconds_per_km):
    m, s = divmod(round(seconds_per_km), 60)
    return f"{m}:{s:02d}"


def main():
    if not os.path.exists(CSV_FILE):
        raise RuntimeError(f"CSV not found: {CSV_FILE}\n"
                           "Export it from Garmin Connect -> Activities -> Export CSV.")

    today = date.today()
    days = [today - timedelta(days=i) for i in range(6, -1, -1)]  # 7 days ending today

    km_by_day = {d: 0.0 for d in days}
    today_km = today_secs = today_kcal = 0.0
    total_rows = runs = 0

    with open(CSV_FILE, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            total_rows += 1
            if "running" not in (row.get("Activity Type") or "").lower():
                continue
            try:
                d = datetime.strptime(row["Date"][:10], "%Y-%m-%d").date()
            except (ValueError, KeyError):
                continue
            if d not in km_by_day:
                continue
            runs += 1
            km = num(row.get("Distance"))
            km_by_day[d] += km
            if d == today:
                today_km += km
                today_secs += duration_secs(row.get("Time"))
                today_kcal += num(row.get("Calories"))

    weekly_km = sum(km_by_day.values())
    score = min(100, round(100 * weekly_km / WEEKLY_GOAL_KM))

    max_km = max(km_by_day.values())
    bars = [round(100 * km_by_day[d] / max_km) if max_km else 0 for d in days]

    if today_km > 0:
        value = f"{today_km:.1f}"
        sub = f"Avg pace {fmt_pace(today_secs / today_km)} /km · {round(today_kcal)} kcal"
    else:
        value = "0"
        sub = f"No run yet today · {weekly_km:.1f} km this week"

    # fetchedAt reflects when the CSV was exported, so an old export
    # correctly shows as "Not synced" on the dashboard.
    exported = datetime.fromtimestamp(os.path.getmtime(CSV_FILE))

    payload = {
        "fetchedAt": exported.isoformat(timespec="seconds"),
        "value": value,
        "unit": "km today",
        "sub": sub,
        # Running volume is both the behavior and the outcome, so process
        # and goal share the weekly-km score.
        "score": score,
        "processScore": score,
        "goalScore": score,
        "bars": bars,
        "days": [d.strftime("%a")[0] for d in days],
    }

    os.makedirs(os.path.dirname(OUT_FILE), exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        f.write("window.GARMIN_DATA = " + json.dumps(payload, indent=2) + ";\n")

    print(f"OK: {runs} run(s) in the last 7 days, {weekly_km:.1f} km total, score {score}.")
    print(f"(CSV: {total_rows} activities, exported {exported:%Y-%m-%d %H:%M})")
    print(f"Wrote {OUT_FILE}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\nSync failed: {e}", file=sys.stderr)
        sys.exit(1)
