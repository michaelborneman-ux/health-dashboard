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

DAILY_GOAL_KM = 2.5          # process score = today's km vs this goal, capped at 100
PACE_GOAL_SEC_PER_KM = 300   # goal score = pace vs this target (5:00/km = 100)
PACE_PENALTY_PER_MIN = 20    # -20 pts per additional minute/km slower than the target
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
    day_set = set(days)

    # Tracked across the whole CSV (not just the 7-day window) so the pace
    # goal score can carry forward from the most recent run even if it was
    # more than a week ago.
    all_km, all_secs = {}, {}
    today_kcal = 0.0
    total_rows = runs_in_window = 0

    with open(CSV_FILE, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            total_rows += 1
            if "running" not in (row.get("Activity Type") or "").lower():
                continue
            try:
                d = datetime.strptime(row["Date"][:10], "%Y-%m-%d").date()
            except (ValueError, KeyError):
                continue
            km = num(row.get("Distance"))
            secs = duration_secs(row.get("Time"))
            all_km[d] = all_km.get(d, 0.0) + km
            all_secs[d] = all_secs.get(d, 0.0) + secs
            if d in day_set:
                runs_in_window += 1
                if d == today:
                    today_kcal += num(row.get("Calories"))

    km_by_day = {d: all_km.get(d, 0.0) for d in days}
    today_km = km_by_day[today]
    today_secs = all_secs.get(today, 0.0)
    weekly_km = sum(km_by_day.values())
    score = min(100, round(100 * today_km / DAILY_GOAL_KM))

    # Goal: pace-based, faster is better. Carries forward the most recent
    # day you ran at all, so a rest day doesn't zero it out.
    pace_day = max((d for d, km in all_km.items() if km > 0 and all_secs.get(d, 0) > 0),
                   default=None)
    if pace_day is not None:
        pace_secs_per_km = all_secs[pace_day] / all_km[pace_day]
        over_min = max(0, (pace_secs_per_km - PACE_GOAL_SEC_PER_KM) / 60)
        goal_score = max(0, min(100, round(100 - PACE_PENALTY_PER_MIN * over_min)))
    else:
        goal_score = 0

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
        "score": score,
        "processScore": score,
        "goalScore": goal_score,
        "bars": bars,
        "days": [d.strftime("%a")[0] for d in days],
    }

    os.makedirs(os.path.dirname(OUT_FILE), exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        f.write("window.GARMIN_DATA = " + json.dumps(payload, indent=2) + ";\n")

    print(f"OK: {runs_in_window} run(s) in the last 7 days, {weekly_km:.1f} km total, "
          f"today {today_km:.1f} km vs {DAILY_GOAL_KM} km goal (score {score}), "
          f"pace goal {goal_score}.")
    print(f"(CSV: {total_rows} activities, exported {exported:%Y-%m-%d %H:%M})")
    print(f"Wrote {OUT_FILE}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\nSync failed: {e}", file=sys.stderr)
        sys.exit(1)
