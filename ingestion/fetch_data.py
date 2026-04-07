"""
fetch_data.py  —  Daily Edition (Improved Data Product Version)
───────────────────────────────────────────────────────────────
Récupère pour chaque ligue :
  - Matchs du jour
  - Matchs d'hier + détails (buteurs)
  - Matchs à venir (IMPORTANT)
  - Classement
  - Top scoreurs
  - Snapshot classement pour comparaison J-1

+ Ajouts :
  - Gestion des réponses vides
  - Enrichissement statut match
  - Logs propres
"""

import os
import time
import json
import requests
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ───────────────────────────────────────────────────────────
# CONFIG
# ───────────────────────────────────────────────────────────

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
    "ucl": "CL",
}

HEADERS = {"X-Auth-Token": API_KEY}

TODAY     = datetime.now(timezone.utc).date()
YESTERDAY = TODAY - timedelta(days=1)

# ───────────────────────────────────────────────────────────
# HELPERS
# ───────────────────────────────────────────────────────────

def get(endpoint: str) -> dict:
    url = f"{BASE_URL}/{endpoint}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        time.sleep(6)  # rate limit
        return resp.json()
    except requests.RequestException as e:
        print(f"❌ API ERROR → {endpoint} → {e}")
        return {}

def save(data: dict, filename: str):
    path = DATA_DIR / filename
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"  ✅ Saved → {path}")

def save_standings_snapshot(league_name: str, data: dict):
    snapshot_file = HISTORY_DIR / f"standings_{league_name}_{TODAY}.json"
    snapshot_file.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"  📸 Snapshot → {snapshot_file}")

def enrich_match_status(match):
    status = match.get("status")

    match["is_finished"] = status == "FINISHED"
    match["is_live"] = status in ["IN_PLAY", "PAUSED"]
    match["is_upcoming"] = status == "SCHEDULED"

    return match

# ───────────────────────────────────────────────────────────
# MATCHS DU JOUR
# ───────────────────────────────────────────────────────────

def fetch_today_matches(code, name):
    print(f"\n📅 Matchs du jour {name}")
    data = get(f"competitions/{code}/matches?dateFrom={TODAY}&dateTo={TODAY}")

    matches = data.get("matches", [])
    if not matches:
        print(f"  ℹ️ Aucun match aujourd'hui")
    else:
        matches = [enrich_match_status(m) for m in matches]

    save({"matches": matches}, f"today_{name}.json")

# ───────────────────────────────────────────────────────────
# MATCHS D'HIER + DETAILS
# ───────────────────────────────────────────────────────────

def fetch_yesterday_matches(code, name):
    print(f"\n🏆 Résultats d'hier {name}")

    data = get(
        f"competitions/{code}/matches?dateFrom={YESTERDAY}&dateTo={YESTERDAY}&status=FINISHED"
    )

    matches = data.get("matches", [])
    if not matches:
        print("  ℹ️ Aucun match terminé hier")
        save({"matches": []}, f"yesterday_{name}.json")
        return

    matches = [enrich_match_status(m) for m in matches]
    save({"matches": matches}, f"yesterday_{name}.json")

    # détails (buteurs etc.)
    details = []

    for m in matches:
        match_id = m.get("id")
        if not match_id:
            continue

        detail = get(f"matches/{match_id}")
        if detail:
            details.append(detail)
            print(f"  ⚽ Détails match {match_id} OK")

    save({"matches_details": details}, f"yesterday_details_{name}.json")

# ───────────────────────────────────────────────────────────
# MATCHS A VENIR (IMPORTANT)
# ───────────────────────────────────────────────────────────

def fetch_upcoming_matches(code, name):
    print(f"\n📆 Prochains matchs {name}")

    data = get(f"competitions/{code}/matches?status=SCHEDULED")

    matches = data.get("matches", [])
    if not matches:
        print("  ℹ️ Aucun match programmé")
    else:
        matches = [enrich_match_status(m) for m in matches]

    save({"matches": matches}, f"upcoming_{name}.json")

# ───────────────────────────────────────────────────────────
# CLASSEMENT
# ───────────────────────────────────────────────────────────

def fetch_standings(code, name):
    print(f"\n📊 Classement {name}")

    data = get(f"competitions/{code}/standings")
    if not data:
        print("  ⚠️ Pas de classement dispo (phase KO ?)")
        return

    save(data, f"standings_{name}.json")
    save_standings_snapshot(name, data)

# ───────────────────────────────────────────────────────────
# SCOREURS
# ───────────────────────────────────────────────────────────

def fetch_scorers(code, name):
    print(f"\n⚽ Top scoreurs {name}")

    data = get(f"competitions/{code}/scorers?limit=10")
    if not data:
        print("  ⚠️ Pas de données scoreurs")
        return

    save(data, f"scorers_{name}.json")

# ───────────────────────────────────────────────────────────
# MAIN PIPELINE
# ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"🚀 Daily Football Data Pipeline — {TODAY}\n")

    for name, code in LEAGUES.items():
        print(f"\n================ {name.upper()} ================")

        try:
            fetch_today_matches(code, name)
            fetch_yesterday_matches(code, name)
            fetch_upcoming_matches(code, name)   # 🔥 NEW
            fetch_standings(code, name)
            fetch_scorers(code, name)

        except Exception as e:
            print(f"❌ Erreur globale {name}: {e}")

    # metadata run
    meta = {
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "today": str(TODAY),
        "yesterday": str(YESTERDAY),
        "leagues": list(LEAGUES.keys()),
        "pipeline_version": "v2",
    }

    save(meta, "meta.json")

    print("\n✅ Extraction terminée proprement.")
