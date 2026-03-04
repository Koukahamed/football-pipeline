"""
send_email.py  —  Football Daily Premium
─────────────────────────────────────────
Envoie un email HTML avec :

📅 Matchs du jour
🏆 Récap d'hier (buteurs + stats)
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

    # Charger les détails pour récupérer les buteurs
    details_data = load_json(f"yesterday_details_{league}.json")
    details_by_id = {}
    for d in details_data.get("matches_details", []):
        match = d.get("match", d)  # certaines API wrappent dans "match"
        mid = match.get("id")
        if mid:
            details_by_id[mid] = match

    result = []

    for m in matches:
        score = m.get("score", {}).get("fullTime", {})
        match_id = m.get("id")

        # Extraire les buteurs depuis les détails
        scorers = []
        detail = details_by_id.get(match_id, {})
        for goal in detail.get("goals", []):
            scorer_name = goal.get("scorer", {}).get("name")
            minute = goal.get("minute")
            team = goal.get("team", {}).get("shortName") or goal.get("team", {}).get("name")
            if scorer_name:
                scorers.append({"name": scorer_name, "minute": minute, "team": team})

        result.append({
            "id": match_id,
            "home": m.get("homeTeam", {}).get("name"),
            "away": m.get("awayTeam", {}).get("name"),
            "home_score": score.get("home"),
            "away_score": score.get("away"),
            "scorers": scorers,
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


# ── SECTIONS HTML ──────────────────────────────────────────

def html_today_matches_section(league: str, meta: dict) -> str:
    matches = parse_today_matches(league)

    if not matches:
        return ""

    rows = ""
    for m in matches:
        rows += f"""
        <tr>
            <td style="padding:6px 10px;">{m["time"]}</td>
            <td style="padding:6px 10px;font-weight:bold;">{m["home"]}</td>
            <td style="padding:6px 10px;text-align:center;">vs</td>
            <td style="padding:6px 10px;font-weight:bold;">{m["away"]}</td>
        </tr>
        """

    return f"""
    <h3>{meta["flag"]} {meta["name"]}</h3>
    <table width="100%" style="border-collapse:collapse;">
        {rows}
    </table>
    """


def html_yesterday_results_section(league: str, meta: dict) -> str:
    results = parse_yesterday_results(league)

    if not results:
        return ""

    rows = ""
    for m in results:
        score_str = f"{m['home_score']} - {m['away_score']}" if m['home_score'] is not None else "- - -"

        scorers_str = ""
        if m["scorers"]:
            goals = ", ".join(
                f"{s['name']} {s['minute']}'" for s in m["scorers"]
            )
            scorers_str = f"<br><small style='color:#aaa;'>⚽ {goals}</small>"

        rows += f"""
        <tr>
            <td style="padding:6px 10px;font-weight:bold;">{m["home"]}</td>
            <td style="padding:6px 10px;text-align:center;font-weight:bold;font-size:1.1em;">{score_str}</td>
            <td style="padding:6px 10px;font-weight:bold;">{m["away"]}</td>
            <td style="padding:6px 10px;">{scorers_str}</td>
        </tr>
        """

    return f"""
    <h3>{meta["flag"]} {meta["name"]}</h3>
    <table width="100%" style="border-collapse:collapse;">
        {rows}
    </table>
    """


def html_top_scorers_section(league: str, meta: dict) -> str:
    scorers = parse_top_scorers(league)

    if not scorers:
        return ""

    rows = ""
    for i, s in enumerate(scorers, 1):
        rows += f"""
        <tr>
            <td style="padding:4px 10px;">{i}</td>
            <td style="padding:4px 10px;font-weight:bold;">{s["name"]}</td>
            <td style="padding:4px 10px;color:#aaa;">{s["team"]}</td>
            <td style="padding:4px 10px;text-align:center;">⚽ {s["goals"]}</td>
        </tr>
        """

    return f"""
    <h3>{meta["flag"]} {meta["name"]}</h3>
    <table width="100%" style="border-collapse:collapse;">
        {rows}
    </table>
    """


def html_standings_section(league: str, meta: dict) -> str:
    standings = parse_standings(league)

    if not standings:
        return ""

    rows = ""

    for team in standings:

        if team["position"] == 1:
            bg = "background:#0f2f1f;"
            badge = "🔥 LEADER"
        elif team["position"] >= 18:
            bg = "background:#2a1015;"
            badge = ""
        else:
            bg = ""
            badge = ""

        arrow = ""
        if team["movement"] == "up":
            arrow = "<span style='color:#4caf50;'>▲</span>"
        elif team["movement"] == "down":
            arrow = "<span style='color:#f44336;'>▼</span>"
        elif team["movement"] == "same":
            arrow = "<span style='color:#aaa;'>•</span>"

        rows += f"""
        <tr style="{bg}">
            <td style="padding:4px 10px;">{team["position"]} {arrow}</td>
            <td style="padding:4px 10px;">{team["team"]} {badge}</td>
            <td style="padding:4px 10px;text-align:center;">{team["points"]} pts</td>
            <td style="padding:4px 10px;text-align:center;">{team["diff"]}</td>
        </tr>
        """

    return f"""
    <h3>{meta["flag"]} {meta["name"]}</h3>
    <table width="100%" style="border-collapse:collapse;">
        {rows}
    </table>
    """


def build_email_html():

    today_html      = ""
    yesterday_html  = ""
    scorers_html    = ""
    standings_html  = ""

    for league, meta in LEAGUE_META.items():
        today_html     += html_today_matches_section(league, meta)
        yesterday_html += html_yesterday_results_section(league, meta)
        scorers_html   += html_top_scorers_section(league, meta)
        standings_html += html_standings_section(league, meta)

    return f"""
    <html>
    <body style="background:#0d0d1a;color:white;font-family:Arial;max-width:700px;margin:0 auto;padding:20px;">
        <h1 style="text-align:center;">⚽ Football Daily — {TODAY}</h1>

        <h2>📅 Matchs du jour</h2>
        {today_html if today_html else "<p style='color:#aaa;'>Aucun match aujourd'hui.</p>"}

        <h2>🏆 Récap d'hier</h2>
        {yesterday_html if yesterday_html else "<p style='color:#aaa;'>Aucun résultat hier.</p>"}

        <h2>⚽ Top Scoreurs</h2>
        {scorers_html if scorers_html else "<p style='color:#aaa;'>Données indisponibles.</p>"}

        <h2>📊 Classement</h2>
        {standings_html if standings_html else "<p style='color:#aaa;'>Données indisponibles.</p>"}

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
