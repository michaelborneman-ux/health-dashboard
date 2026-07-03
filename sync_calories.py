"""Sync CalorieSnap data (via its GitHub Gist) into the Health Dashboard.

One-time setup: in CalorieSnap on your phone, open Settings and add a GitHub
token (gist scope). After its first sync the status line shows a gist id —
this script asks for that id once and stores it in ~/.caloriesnap/config.json.
Writes public/data/calories-data.js next to index.html.
"""

import json
import os
import sys
from datetime import date, datetime, timedelta

import requests

CONF_FILE = os.path.expanduser("~/.caloriesnap/config.json")
OUT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "public", "data", "calories-data.js")
GIST_FILE = "caloriesnap-summary.json"


def get_gist_id():
    try:
        with open(CONF_FILE, encoding="utf-8-sig") as f:
            conf = json.load(f)
        if conf.get("gist_id"):
            return conf["gist_id"]
    except (OSError, ValueError):
        pass
    print(__doc__)
    gist_id = input("Gist id (from CalorieSnap Settings): ").strip().split("/")[-1]
    os.makedirs(os.path.dirname(CONF_FILE), exist_ok=True)
    with open(CONF_FILE, "w", encoding="utf-8") as f:
        json.dump({"gist_id": gist_id}, f, indent=2)
    return gist_id


def day_score(calories, goal):
    """100 at goal, minus 2 points per 1% deviation, floor 0."""
    if not goal:
        return None
    deviation = abs(calories - goal) / goal
    return max(0, round(100 - 200 * deviation))


def main():
    gist_id = get_gist_id()
    print(f"Fetching gist {gist_id} ...")
    r = requests.get(f"https://api.github.com/gists/{gist_id}", timeout=30)
    r.raise_for_status()
    gist = r.json()
    if GIST_FILE not in gist.get("files", {}):
        raise RuntimeError(f"Gist has no {GIST_FILE} — has CalorieSnap synced yet?")
    summary = json.loads(gist["files"][GIST_FILE]["content"])

    goal = summary.get("goal")
    by_date = {d["date"]: d["calories"] for d in summary.get("days", [])}

    today = date.today()
    days = [today - timedelta(days=i) for i in range(6, -1, -1)]
    week = [by_date.get(d.isoformat(), 0) for d in days]
    today_cal = week[-1]

    # Process: adherence of completed, logged days to the goal (today is
    # partial; unlogged days are skipped — no entries more likely means
    # "didn't log" than "didn't eat").
    history = [day_score(c, goal) for c in week[:-1] if c > 0]
    history = [s for s in history if s is not None]
    process = round(sum(history) / len(history)) if history else 50

    # Goals: today's budget — full marks while within goal, penalized when over.
    if goal:
        goal_score = max(0, round(100 - 200 * max(0, today_cal / goal - 1)))
    else:
        goal_score = 50

    if goal:
        remaining = goal - today_cal
        sub = (f"{remaining} kcal remaining today" if remaining >= 0
               else f"{-remaining} kcal over goal today")
        unit = f"in / goal {goal:,}"
    else:
        sub = "No daily goal set in CalorieSnap"
        unit = "kcal in"

    mx = max(week)
    payload = {
        # generatedAt reflects the phone's last sync, so a stale phone
        # correctly shows as "Not synced" on the dashboard.
        "fetchedAt": summary.get("generatedAt", datetime.now().isoformat(timespec="seconds")),
        "value": f"{today_cal:,}",
        "unit": unit,
        "sub": sub,
        "score": process,
        "processScore": process,
        "goalScore": goal_score,
        "bars": [round(100 * c / mx) if mx else 0 for c in week],
        "days": [d.strftime("%a")[0] for d in days],
    }

    os.makedirs(os.path.dirname(OUT_FILE), exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        f.write("window.CALORIES_DATA = " + json.dumps(payload, indent=2) + ";\n")

    print(f"OK: today {today_cal} kcal, goal {goal}, process {process}, goal-score {goal_score}.")
    print(f"Wrote {OUT_FILE}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\nSync failed: {e}", file=sys.stderr)
        sys.exit(1)
