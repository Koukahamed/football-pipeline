"""
fetch_data.py  —  Daily Edition
────────────────────────────────
Récupère pour chaque ligue (EPL / Ligue 1 / Bundesliga) :
  - Les matchs du jour (status: SCHEDULED / LIVE / TIMED)
  - Les matchs d'hier terminés + leurs détails (buteurs, stats)
  - Le classement courant
  - Top scoreurs

API : football-data.org (plan gratuit, 10 req/min)
"""

import os
import time
import json
import requests
from datetime import datetime, timedelta, timezone
from pathlib import Path

API_KEY  = os.environ.get("FOOTBALL_API_KEY", "demo")
BASE_URL = "https://api.football-data.org/v4"
DATA_DIR = Path("data/raw")
DATA_DIR.mkdir(parents=True, exist_ok=True)

LEAGUES = {
    "EPL"        : "PL",
    "LIGUE1"     : "FL1",
    "BUNDESLIGA" : "BL1",
}

HEADERS = {"X-Auth-Token": API_KEY}

TODAY     = datetime.now(timezone.utc).date()
YESTERDAY = TODAY - timedelta(days=1)


def get(endpoint: str) -> dict:
    url  = f"{BASE_URL}/{endpoint}"
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    time.sleep(7)   # respect rate limit gratuit
    return resp.json()


def save(data: dict, filename: str):
    path = DATA_DIR / filename
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"  ✅ Saved → {path}")


# ── Matchs du jour ────────────────────────────────────────────────────────────

def fetch_today_matches(league_code: str, league_name: str):
    print(f"📅 Matchs du jour {league_name} ({TODAY})...")
    data = get(
        f"competitions/{league_code}/matches"
        f"?dateFrom={TODAY}&dateTo={TODAY}"
    )
    save(data, f"today_{league_name.lower()}.json")


# ── Matchs d'hier (terminés) ──────────────────────────────────────────────────

def fetch_yesterday_matches(league_code: str, league_name: str):
    print(f"🏆 Résultats d'hier {league_name} ({YESTERDAY})...")
    data = get(
        f"competitions/{league_code}/matches"
        f"?dateFrom={YESTERDAY}&dateTo={YESTERDAY}&status=FINISHED"
    )
    save(data, f"yesterday_{league_name.lower()}.json")

    # Pour chaque match terminé, récupérer les détails (buteurs, stats)
    matches = data.get("matches", [])
    details = []
    for m in matches:
        match_id = m.get("id")
        if not match_id:
            continue
        print(f"    🔍 Détails match {match_id}...")
        try:
            detail = get(f"matches/{match_id}")
            details.append(detail)
        except requests.HTTPError as e:
            print(f"    ⚠️  Erreur détails match {match_id}: {e}")
    save({"matches_details": details}, f"yesterday_details_{league_name.lower()}.json")


# ── Classement ────────────────────────────────────────────────────────────────

def fetch_standings(league_code: str, league_name: str):
    print(f"📊 Classement {league_name}...")
    data = get(f"competitions/{league_code}/standings")
    save(data, f"standings_{league_name.lower()}.json")


# ── Top scoreurs ──────────────────────────────────────────────────────────────

def fetch_scorers(league_code: str, league_name: str):
    print(f"⚽ Scoreurs {league_name}...")
    data = get(f"competitions/{league_code}/scorers?limit=10")
    save(data, f"scorers_{league_name.lower()}.json")


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"🚀 Daily fetch — {TODAY}\n")
    for name, code in LEAGUES.items():
        try:
            fetch_today_matches(code, name)
            fetch_yesterday_matches(code, name)
            fetch_standings(code, name)
            fetch_scorers(code, name)
        except requests.HTTPError as e:
            print(f"  ⚠️  Erreur pour {name}: {e}")

    meta = {
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "today": str(TODAY),
        "yesterday": str(YESTERDAY),
        "leagues": list(LEAGUES.keys()),
    }
    save(meta, "meta.json")
    print("\n✅ Extraction quotidienne terminée.")
