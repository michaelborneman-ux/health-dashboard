"""Sync Withings sleep + weight data into the Health Dashboard.

One-time setup (free):
  1. Go to https://developer.withings.com/dashboard and sign in with your
     normal Withings account.
  2. Create an application: type "Public API integration", any name
     (e.g. "Health Dashboard"), callback URL exactly:  http://localhost:8912
  3. Copy the Client ID and Client Secret — this script asks for them on
     first run and stores them in ~/.withings/ (outside OneDrive).

First run opens your browser to authorize; afterwards tokens auto-refresh
and the sync is zero-prompt. Writes public/data/withings-data.js next to index.html.
"""

import json
import os
import secrets
import sys
import threading
import webbrowser
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import requests

SLEEP_GOAL_H = 8             # sleep sub-score = duration vs goal, blended with efficiency
GOAL_WEIGHT_KG = 80          # weight sub-score = 100 minus penalty per kg above goal
PENALTY_PER_KG = 4

CALLBACK_PORT = 8912
DEFAULT_REDIRECT_URI = f"http://localhost:{CALLBACK_PORT}"
CONF_DIR = os.path.expanduser("~/.withings")
CONF_FILE = os.path.join(CONF_DIR, "config.json")
TOKEN_FILE = os.path.join(CONF_DIR, "tokens.json")
OUT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "public", "data", "withings-data.js")

AUTH_URL = "https://account.withings.com/oauth2_user/authorize2"
API_TOKEN = "https://wbsapi.withings.net/v2/oauth2"
API_MEASURE = "https://wbsapi.withings.net/measure"
API_SLEEP = "https://wbsapi.withings.net/v2/sleep"
SCOPE = "user.metrics,user.activity"


# ---------------------------------------------------------------- auth

def load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def save_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)


def get_app_credentials():
    conf = load_json(CONF_FILE) or {}
    if not (conf.get("client_id") and conf.get("client_secret")):
        print(__doc__)
        conf["client_id"] = input("Client ID: ").strip()
        conf["client_secret"] = input("Client Secret: ").strip()
    if not conf.get("redirect_uri"):
        print("\nCallback URL — must match the Withings app registration EXACTLY")
        print("(open your app at https://developer.withings.com/dashboard and copy it).")
        entered = input(f"Callback URL [{DEFAULT_REDIRECT_URI}]: ").strip()
        conf["redirect_uri"] = entered or DEFAULT_REDIRECT_URI
    save_json(CONF_FILE, conf)
    return conf


def api_token_request(params):
    r = requests.post(API_TOKEN, data={"action": "requesttoken", **params}, timeout=30)
    j = r.json()
    if j.get("status") != 0:
        raise RuntimeError(f"Withings token error: {j}")
    return j["body"]


def oauth_flow(conf):
    """Full browser authorization; returns token dict."""
    state = secrets.token_hex(16)
    result = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            q = parse_qs(urlparse(self.path).query)
            result["code"] = q.get("code", [None])[0]
            result["state"] = q.get("state", [None])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h2>Authorized. You can close this window.</h2>")

        def log_message(self, *a):
            pass

    port = urlparse(conf["redirect_uri"]).port or CALLBACK_PORT
    server = HTTPServer(("localhost", port), Handler)
    url = AUTH_URL + "?" + urlencode({
        "response_type": "code",
        "client_id": conf["client_id"],
        "scope": SCOPE,
        "redirect_uri": conf["redirect_uri"],
        "state": state,
    })
    print("Opening browser for Withings authorization...")
    print(f"(If it doesn't open, paste this in a browser:\n{url}\n)")
    threading.Timer(1.0, webbrowser.open, [url]).start()
    server.handle_request()  # wait for the single callback
    server.server_close()

    if not result.get("code") or result.get("state") != state:
        raise RuntimeError("Authorization failed or was cancelled.")

    tokens = api_token_request({
        "grant_type": "authorization_code",
        "client_id": conf["client_id"],
        "client_secret": conf["client_secret"],
        "code": result["code"],
        "redirect_uri": conf["redirect_uri"],
    })
    save_json(TOKEN_FILE, tokens)
    print("Authorized — tokens saved.\n")
    return tokens


def get_access_token(conf):
    tokens = load_json(TOKEN_FILE)
    if tokens and tokens.get("refresh_token"):
        try:
            tokens = api_token_request({
                "grant_type": "refresh_token",
                "client_id": conf["client_id"],
                "client_secret": conf["client_secret"],
                "refresh_token": tokens["refresh_token"],
            })
            save_json(TOKEN_FILE, tokens)
            return tokens["access_token"]
        except Exception as e:
            print(f"Token refresh failed ({e}); re-authorizing...")
    return oauth_flow(conf)["access_token"]


def api_call(url, token, params):
    r = requests.post(url, data=params, headers={"Authorization": f"Bearer {token}"}, timeout=30)
    j = r.json()
    if j.get("status") != 0:
        raise RuntimeError(f"Withings API error at {url}: {j}")
    return j["body"]


# ---------------------------------------------------------------- data

def fmt_hm(seconds):
    h, m = divmod(round(seconds / 60), 60)
    return f"{h}h {m:02d}m"


def build_sleep(token, days):
    body = api_call(API_SLEEP, token, {
        "action": "getsummary",
        "startdateymd": days[0].isoformat(),
        "enddateymd": days[-1].isoformat(),
    })
    by_day = {}
    for s in body.get("series", []):
        d = s.get("date")
        data = s.get("data", {})
        asleep = (data.get("deepsleepduration") or 0) + (data.get("lightsleepduration") or 0) \
               + (data.get("remsleepduration") or 0)
        if not asleep:
            continue
        in_bed = max(1, (s.get("enddate") or 0) - (s.get("startdate") or 0))
        by_day[d] = {
            "asleep": asleep,
            "deep": data.get("deepsleepduration") or 0,
            "efficiency": min(100, round(100 * asleep / in_bed)),
        }
    if not by_day:
        return None

    def night_score(n):
        duration = min(100, round(100 * (n["asleep"] / 3600) / SLEEP_GOAL_H))
        return round((duration + n["efficiency"]) / 2)

    last = by_day[max(by_day)]
    goal_score = night_score(last)                       # state: last night
    process = round(sum(night_score(n) for n in by_day.values()) / len(by_day))

    secs = [by_day.get(d.isoformat(), {}).get("asleep", 0) for d in days]
    mx = max(secs)
    return {
        "value": fmt_hm(last["asleep"]),
        "unit": "",
        "sub": f"Deep {fmt_hm(last['deep'])} · {last['efficiency']}% efficiency",
        "score": goal_score,          # back-compat for older dashboard builds
        "processScore": process,      # avg night quality across the week
        "goalScore": goal_score,
        "bars": [round(100 * s / mx) if mx else 0 for s in secs],
        "days": [d.strftime("%a")[0] for d in days],
    }


def build_weight(token, days):
    start = datetime.combine(days[0], datetime.min.time())
    body = api_call(API_MEASURE, token, {
        "action": "getmeas",
        "meastypes": "1",           # 1 = weight
        "category": "1",            # real measurements
        "startdate": int(start.timestamp()),
        "enddate": int(datetime.now().timestamp()),
    })
    by_day = {}
    for grp in sorted(body.get("measuregrps", []), key=lambda g: g["date"]):
        for m in grp.get("measures", []):
            if m["type"] == 1:
                kg = m["value"] * (10 ** m["unit"])
                by_day[date.fromtimestamp(grp["date"]).isoformat()] = kg
    if not by_day:
        return None

    ordered = [by_day[k] for k in sorted(by_day)]
    current, first = ordered[-1], ordered[0]
    delta = current - first
    # Goals: distance from target weight. Process: this week's trend —
    # losing >=0.5 kg/week scores 100, holding steady ~70, gaining drops fast.
    goal_score = max(0, min(100, round(100 - PENALTY_PER_KG * max(0, current - GOAL_WEIGHT_KG))))
    process = max(0, min(100, round(70 - 60 * delta)))

    # bars: carry last known weight forward across gaps, map week range to 70–100
    series, last_kg = [], None
    for d in days:
        last_kg = by_day.get(d.isoformat(), last_kg)
        series.append(last_kg)
    known = [v for v in series if v is not None]
    lo, hi = min(known), max(known)
    def bar(v):
        if v is None:
            return 0
        return 85 if hi == lo else round(70 + 30 * (v - lo) / (hi - lo))
    return {
        "value": f"{current:.1f}",
        "unit": "kg",
        "sub": f"{delta:+.1f} kg this week · goal {GOAL_WEIGHT_KG}".replace("-", "−"),
        "score": goal_score,
        "processScore": process,
        "goalScore": goal_score,
        "bars": [bar(v) for v in series],
        "days": [d.strftime("%a")[0] for d in days],
    }


def main():
    conf = get_app_credentials()
    token = get_access_token(conf)

    today = date.today()
    days = [today - timedelta(days=i) for i in range(6, -1, -1)]

    print("Fetching sleep...")
    sleep = build_sleep(token, days)
    print("Fetching weight...")
    weight = build_weight(token, days)

    payload = {
        "fetchedAt": datetime.now().isoformat(timespec="seconds"),
        "sleep": sleep,
        "weight": weight,
    }
    os.makedirs(os.path.dirname(OUT_FILE), exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        f.write("window.WITHINGS_DATA = " + json.dumps(payload, indent=2) + ";\n")

    print(f"OK: sleep {'ok' if sleep else 'no data'}, weight {'ok' if weight else 'no data'}.")
    print(f"Wrote {OUT_FILE}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\nSync failed: {e}", file=sys.stderr)
        sys.exit(1)
