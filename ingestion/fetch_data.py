"""
fetch_data.py
─────────────
Récupère via football-data.org (plan gratuit) :
  - Classements EPL / Ligue 1 / Bundesliga
  - Matchs des 7 derniers jours
  - Top scoreurs

API gratuite : https://www.football-data.org/
Limite : 10 req/min — on attend entre chaque appel.
"""

import os
import time
import json
import requests
from datetime import datetime, timedelta
from pathlib import Path

API_KEY  = os.environ.get("FOOTBALL_API_KEY", "demo")
BASE_URL = "https://api.football-data.org/v4"
DATA_DIR = Path("data/raw")
DATA_DIR.mkdir(parents=True, exist_ok=True)

LEAGUES = {
    "EPL"        : "PL",   # Premier League
    "LIGUE1"     : "FL1",  # Ligue 1
    "BUNDESLIGA" : "BL1",  # Bundesliga
}

HEADERS = {"X-Auth-Token": API_KEY}


def get(endpoint: str) -> dict:
    url = f"{BASE_URL}/{endpoint}"
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    time.sleep(7)  # Respect rate limit gratuit (10 req/min)
    return resp.json()


def save(data: dict, filename: str):
    path = DATA_DIR / filename
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"  ✅ Saved → {path}")


def fetch_standings(league_code: str, league_name: str):
    print(f"📊 Standings {league_name}...")
    data = get(f"competitions/{league_code}/standings")
    save(data, f"standings_{league_name.lower()}.json")


def fetch_matches(league_code: str, league_name: str):
    today     = datetime.utcnow().date()
    week_ago  = today - timedelta(days=7)
    print(f"📅 Matches {league_name} ({week_ago} → {today})...")
    data = get(
        f"competitions/{league_code}/matches"
        f"?dateFrom={week_ago}&dateTo={today}&status=FINISHED"
    )
    save(data, f"matches_{league_name.lower()}.json")


def fetch_scorers(league_code: str, league_name: str):
    print(f"⚽ Scorers {league_name}...")
    data = get(f"competitions/{league_code}/scorers?limit=20")
    save(data, f"scorers_{league_name.lower()}.json")


if __name__ == "__main__":
    print("🚀 Starting data extraction...\n")
    for name, code in LEAGUES.items():
        try:
            fetch_standings(code, name)
            fetch_matches(code, name)
            fetch_scorers(code, name)
        except requests.HTTPError as e:
            print(f"  ⚠️  Error for {name}: {e}")

    # Sauvegarder la date d'extraction
    meta = {"extracted_at": datetime.utcnow().isoformat(), "leagues": list(LEAGUES.keys())}
    save(meta, "meta.json")
    print("\n✅ Extraction complete.")