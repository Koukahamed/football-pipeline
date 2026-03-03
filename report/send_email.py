"""
send_email.py  —  Football Daily Premium
─────────────────────────────────────────
Envoie un email HTML avec :

📅 Matchs du jour
🏆 Récap d’hier (buteurs + stats)
⚽ Top scoreurs
📊 Classement premium (avec mouvement J-1)

Usage :
python report/send_email.py
"""

import os
import json
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from datetime import datetime, timezone, timedelta

DATA_DIR  = Path("data/raw")
HISTORY_DIR = Path("data/history")

TODAY     = datetime.now(timezone.utc).date()
YESTERDAY = TODAY - timedelta(days=1)

LEAGUE_META = {
    "epl": {
        "name": "Premier League",
        "flag": "🏴",
        "color": "#3d0c91",
        "light": "#6a3dd1",
    },
    "ligue1": {
        "name": "Ligue 1",
        "flag": "🇫🇷",
        "color": "#002395",
        "light": "#1a4fd6",
    },
    "bundesliga": {
        "name": "Bundesliga",
        "flag": "🇩🇪",
        "color": "#c8102e",
        "light": "#e84060",
    },
    "laliga": {
        "name": "La Liga",
        "flag": "🇪🇸",
        "color": "#c8102e",
        "light": "#e05a20",
    },
}

def load_json(filename: str) -> dict:
    path = DATA_DIR / filename
    if not path.exists():
        return {}
    return json.loads(path.read_text())

def parse_today_matches(league: str) -> list:
    data = load_json(f"today_{league}.json")
    matches = data.get("matches", [])

    result = []

    for m in matches:
        utc_dt = m.get("utcDate", "")
        try:
            dt = datetime.fromisoformat(utc_dt.replace("Z", "+00:00"))
            time_str = dt.strftime("%H:%M UTC")
        except Exception:
            time_str = "TBD"

        result.append({
            "home": m.get("homeTeam", {}).get("shortName") or m.get("homeTeam", {}).get("name"),
            "away": m.get("awayTeam", {}).get("shortName") or m.get("awayTeam", {}).get("name"),
            "time": time_str,
            "status": m.get("status")
        })

    return result

def parse_yesterday_results(league: str) -> list:
    data = load_json(f"yesterday_{league}.json")
    matches = data.get("matches", [])

    result = []

    for m in matches:
        score = m.get("score", {}).get("fullTime", {})

        result.append({
            "id": m.get("id"),
            "home": m.get("homeTeam", {}).get("name"),
            "away": m.get("awayTeam", {}).get("name"),
            "home_score": score.get("home"),
            "away_score": score.get("away"),
        })

    return result

def parse_top_scorers(league: str) -> list:
    data = load_json(f"scorers_{league}.json")
    scorers = data.get("scorers", [])[:5]

    result = []

    for s in scorers:
        result.append({
            "name": s.get("player", {}).get("name"),
            "team": s.get("team", {}).get("shortName") or s.get("team", {}).get("name"),
            "goals": s.get("goals"),
        })

    return result

def parse_standings(league: str, limit: int = 10) -> list:
    data_today = load_json(f"standings_{league}.json")
    standings = data_today.get("standings", [])

    if not standings:
        return []

    table_today = standings[0].get("table", [])

    yesterday_file = HISTORY_DIR / f"standings_{league}_{YESTERDAY}.json"

    previous_positions = {}

    if yesterday_file.exists():
        prev_data = json.loads(yesterday_file.read_text())
        prev_table = prev_data.get("standings", [])[0].get("table", [])

        for team in prev_table:
            previous_positions[team["team"]["name"]] = team["position"]

    result = []

    for team in table_today[:limit]:
        team_name = team["team"]["name"]
        current_pos = team["position"]
        previous_pos = previous_positions.get(team_name)

        movement = None
        if previous_pos:
            if current_pos < previous_pos:
                movement = "up"
            elif current_pos > previous_pos:
                movement = "down"
            else:
                movement = "same"

        result.append({
            "position": current_pos,
            "team": team["team"].get("shortName") or team_name,
            "points": team["points"],
            "diff": team["goalDifference"],
            "movement": movement
        })

    return result

def html_standings_section(league: str, meta: dict) -> str:
    standings = parse_standings(league)

    if not standings:
        return ""

    rows = ""

    for team in standings:

        # Leader
        if team["position"] == 1:
            bg = "background:#0f2f1f;"
            badge = "🔥 LEADER"
        elif team["position"] >= 18:
            bg = "background:#2a1015;"
            badge = ""
        else:
            bg = ""
            badge = ""

        # Movement
        arrow = ""
        if team["movement"] == "up":
            arrow = "▲"
        elif team["movement"] == "down":
            arrow = "▼"
        elif team["movement"] == "same":
            arrow = "•"

        rows += f"""
        <tr style="{bg}">
            <td>{team["position"]} {arrow}</td>
            <td>{team["team"]} {badge}</td>
            <td>{team["points"]} pts</td>
            <td>{team["diff"]}</td>
        </tr>
        """

    return f"""
    <h3>{meta["flag"]} {meta["name"]}</h3>
    <table width="100%">
        {rows}
    </table>
    """

def build_email_html():

    standings_html = ""
    for league, meta in LEAGUE_META.items():
        standings_html += html_standings_section(league, meta)

    return f"""
    <html>
    <body style="background:#0d0d1a;color:white;font-family:Arial;">
        <h1>⚽ Football Daily — {TODAY}</h1>

        <h2>📊 Classement</h2>
        {standings_html}

    </body>
    </html>
    """



  def send_email(html_content: str):

    smtp_host = os.environ.get("SMTP_HOST")
    smtp_port = int(os.environ.get("SMTP_PORT", 587))
    smtp_user = os.environ.get("SMTP_USER")
    smtp_pass = os.environ.get("SMTP_PASS")

    from_addr = os.environ.get("EMAIL_FROM", smtp_user)
    to_addrs = os.environ.get("EMAIL_TO", smtp_user).split(",")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"⚽ Football Daily — {TODAY}"
    msg["From"] = from_addr
    msg["To"] = ", ".join(to_addrs)

    msg.attach(MIMEText("Voir version HTML", "plain"))
    msg.attach(MIMEText(html_content, "html"))

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(from_addr, to_addrs, msg.as_string())


if __name__ == "__main__":

    html = build_email_html()

    try:
        send_email(html)
        print("✅ Email envoyé")
    except Exception as e:
        print(f"❌ Erreur : {e}")

