"""
fetch_data.py  —  Daily Edition
────────────────────────────────
Récupère pour chaque ligue :
  - Matchs du jour
  - Matchs d'hier + détails (buteurs)
  - Classement
  - Top scoreurs
  - Snapshot classement pour comparaison J-1
"""

import os
import time
import json
import requests
from datetime import datetime, timedelta, timezone
from pathlib import Path

API_KEY  = os.environ.get("FOOTBALL_API_KEY", "demo")
BASE_URL = "https://api.football-data.org/v4"

DATA_DIR    = Path("data/raw")
HISTORY_DIR = Path("data/history")

DATA_DIR.mkdir(parents=True, exist_ok=True)
HISTORY_DIR.mkdir(parents=True, exist_ok=True)

LEAGUES = {
    "epl": "PL",
    "ligue1": "FL1",
    "bundesliga": "BL1",
    "laliga": "PD",
}

HEADERS = {"X-Auth-Token": API_KEY}

TODAY     = datetime.now(timezone.utc).date()
YESTERDAY = TODAY - timedelta(days=1)


def get(endpoint: str) -> dict:
    url = f"{BASE_URL}/{endpoint}"
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    time.sleep(7)  # respect rate limit gratuit
    return resp.json()


def save(data: dict, filename: str):
    path = DATA_DIR / filename
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"  ✅ Saved → {path}")


def save_standings_snapshot(league_name: str, data: dict):
    snapshot_file = HISTORY_DIR / f"standings_{league_name}_{TODAY}.json"
    snapshot_file.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"  📸 Snapshot → {snapshot_file}")


# ── MATCHS DU JOUR ─────────────────────────────────────────

def fetch_today_matches(code, name):
    print(f"📅 Matchs du jour {name}")
    data = get(f"competitions/{code}/matches?dateFrom={TODAY}&dateTo={TODAY}")
    save(data, f"today_{name}.json")


# ── MATCHS D'HIER ──────────────────────────────────────────

def fetch_yesterday_matches(code, name):
    print(f"🏆 Résultats d'hier {name}")
    data = get(
        f"competitions/{code}/matches?dateFrom={YESTERDAY}&dateTo={YESTERDAY}&status=FINISHED"
    )
    save(data, f"yesterday_{name}.json")

    matches = data.get("matches", [])
    details = []

    for m in matches:
        match_id = m.get("id")
        if not match_id:
            continue
        try:
            detail = get(f"matches/{match_id}")
            details.append(detail)
            print(f"  ⚽ Détails match {match_id} OK")
        except requests.HTTPError as e:
            print(f"  ⚠️ Détails match {match_id} ignorés : {e}")

    save({"matches_details": details}, f"yesterday_details_{name}.json")


# ── CLASSEMENT ─────────────────────────────────────────────

def fetch_standings(code, name):
    print(f"📊 Classement {name}")
    data = get(f"competitions/{code}/standings")
    save(data, f"standings_{name}.json")
    save_standings_snapshot(name, data)


# ── SCOREURS ───────────────────────────────────────────────

def fetch_scorers(code, name):
    print(f"⚽ Scoreurs {name}")
    data = get(f"competitions/{code}/scorers?limit=10")
    save(data, f"scorers_{name}.json")


# ── MAIN ───────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"🚀 Daily Fetch — {TODAY}\n")

    for name, code in LEAGUES.items():
        try:
            fetch_today_matches(code, name)
            fetch_yesterday_matches(code, name)
            fetch_standings(code, name)
            fetch_scorers(code, name)
        except requests.HTTPError as e:
            print(f"⚠️ Erreur {name}: {e}")

    meta = {
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "today": str(TODAY),
        "yesterday": str(YESTERDAY),
        "leagues": list(LEAGUES.keys()),
    }

    save(meta, "meta.json")

    print("\n✅ Extraction terminée.")
