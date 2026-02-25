"""
load_duckdb.py
──────────────
Parse les JSON bruts et charge dans DuckDB (couche raw).
"""

import json
import duckdb
from pathlib import Path
from datetime import datetime

DATA_DIR = Path("data/raw")
DB_PATH  = Path("data/football.duckdb")
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

LEAGUES = ["epl", "ligue1", "bundesliga"]

con = duckdb.connect(str(DB_PATH))
con.execute("CREATE SCHEMA IF NOT EXISTS raw")


# ── Standings ────────────────────────────────────────────────────────────────

def load_standings():
    con.execute("DROP TABLE IF EXISTS raw.standings")
    con.execute("""
        CREATE TABLE raw.standings (
            league          VARCHAR,
            position        INTEGER,
            team_id         INTEGER,
            team_name       VARCHAR,
            played          INTEGER,
            won             INTEGER,
            draw            INTEGER,
            lost            INTEGER,
            goals_for       INTEGER,
            goals_against   INTEGER,
            goal_diff       INTEGER,
            points          INTEGER,
            extracted_at    TIMESTAMP
        )
    """)

    for league in LEAGUES:
        path = DATA_DIR / f"standings_{league}.json"
        if not path.exists():
            print(f"  ⚠️  Missing {path}")
            continue

        data = json.loads(path.read_text())
        table = data.get("standings", [{}])[0].get("table", [])
        now   = datetime.utcnow()

        rows = []
        for row in table:
            rows.append((
                league.upper(),
                row.get("position"),
                row.get("team", {}).get("id"),
                row.get("team", {}).get("name"),
                row.get("playedGames"),
                row.get("won"),
                row.get("draw"),
                row.get("lost"),
                row.get("goalsFor"),
                row.get("goalsAgainst"),
                row.get("goalDifference"),
                row.get("points"),
                now,
            ))

        con.executemany("INSERT INTO raw.standings VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        print(f"  ✅ standings_{league}: {len(rows)} équipes")


# ── Matches ──────────────────────────────────────────────────────────────────

def load_matches():
    con.execute("DROP TABLE IF EXISTS raw.matches")
    con.execute("""
        CREATE TABLE raw.matches (
            league          VARCHAR,
            match_id        INTEGER,
            match_date      TIMESTAMP,
            home_team       VARCHAR,
            away_team       VARCHAR,
            home_score      INTEGER,
            away_score      INTEGER,
            status          VARCHAR,
            matchday        INTEGER,
            extracted_at    TIMESTAMP
        )
    """)

    for league in LEAGUES:
        path = DATA_DIR / f"matches_{league}.json"
        if not path.exists():
            continue

        data    = json.loads(path.read_text())
        matches = data.get("matches", [])
        now     = datetime.utcnow()

        rows = []
        for m in matches:
            score = m.get("score", {}).get("fullTime", {})
            rows.append((
                league.upper(),
                m.get("id"),
                m.get("utcDate"),
                m.get("homeTeam", {}).get("name"),
                m.get("awayTeam", {}).get("name"),
                score.get("home"),
                score.get("away"),
                m.get("status"),
                m.get("matchday"),
                now,
            ))

        con.executemany("INSERT INTO raw.matches VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
        print(f"  ✅ matches_{league}: {len(rows)} matchs")


# ── Scorers ───────────────────────────────────────────────────────────────────

def load_scorers():
    con.execute("DROP TABLE IF EXISTS raw.scorers")
    con.execute("""
        CREATE TABLE raw.scorers (
            league          VARCHAR,
            player_id       INTEGER,
            player_name     VARCHAR,
            team_name       VARCHAR,
            goals           INTEGER,
            assists         INTEGER,
            penalties       INTEGER,
            extracted_at    TIMESTAMP
        )
    """)

    for league in LEAGUES:
        path = DATA_DIR / f"scorers_{league}.json"
        if not path.exists():
            continue

        data    = json.loads(path.read_text())
        scorers = data.get("scorers", [])
        now     = datetime.utcnow()

        rows = []
        for s in scorers:
            rows.append((
                league.upper(),
                s.get("player", {}).get("id"),
                s.get("player", {}).get("name"),
                s.get("team", {}).get("name"),
                s.get("goals"),
                s.get("assists"),
                s.get("penalties"),
                now,
            ))

        con.executemany("INSERT INTO raw.scorers VALUES (?,?,?,?,?,?,?,?)", rows)
        print(f"  ✅ scorers_{league}: {len(rows)} joueurs")


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("📦 Loading into DuckDB...\n")
    load_standings()
    load_matches()
    load_scorers()
    con.close()
    print("\n✅ DuckDB loaded successfully.")
