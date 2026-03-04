"""
send_email.py  —  Football Daily Premium
─────────────────────────────────────────
Envoie un email HTML premium avec :

📅 Matchs du jour
🏆 Récap d'hier (buteurs + stats)
⚽ Top scoreurs
📊 Classement (avec mouvement J-1)

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

DATA_DIR    = Path("data/raw")
HISTORY_DIR = Path("data/history")

TODAY     = datetime.now(timezone.utc).date()
YESTERDAY = TODAY - timedelta(days=1)

DAY_FR = ["Lundi","Mardi","Mercredi","Jeudi","Vendredi","Samedi","Dimanche"]
MONTH_FR = ["","Janvier","Février","Mars","Avril","Mai","Juin",
            "Juillet","Août","Septembre","Octobre","Novembre","Décembre"]

def today_label():
    dt = datetime.now(timezone.utc)
    return f"{DAY_FR[dt.weekday()]} {dt.day} {MONTH_FR[dt.month]} {dt.year}"

LEAGUE_META = {
    "epl": {
        "name": "Premier League",
        "flag": "🏴",
        "country": "England",
        "accent": "#7B2FBE",
        "gradient": "linear-gradient(135deg, #1a0533 0%, #2d0a5e 100%)",
    },
    "ligue1": {
        "name": "Ligue 1",
        "flag": "🇫🇷",
        "country": "France",
        "accent": "#1565C0",
        "gradient": "linear-gradient(135deg, #00051f 0%, #001a6e 100%)",
    },
    "bundesliga": {
        "name": "Bundesliga",
        "flag": "🇩🇪",
        "country": "Germany",
        "accent": "#C62828",
        "gradient": "linear-gradient(135deg, #1a0000 0%, #5c0011 100%)",
    },
    "laliga": {
        "name": "La Liga",
        "flag": "🇪🇸",
        "country": "Spain",
        "accent": "#E65100",
        "gradient": "linear-gradient(135deg, #1a0800 0%, #6e2000 100%)",
    },
}

# ── DATA LOADING ───────────────────────────────────────────

def load_json(filename: str) -> dict:
    path = DATA_DIR / filename
    if not path.exists():
        return {}
    return json.loads(path.read_text())

def parse_today_matches(league: str) -> list:
    data = load_json(f"today_{league}.json")
    result = []
    for m in data.get("matches", []):
        utc_dt = m.get("utcDate", "")
        try:
            dt = datetime.fromisoformat(utc_dt.replace("Z", "+00:00"))
            time_str = dt.strftime("%H:%M")
        except Exception:
            time_str = "TBD"
        result.append({
            "home": m.get("homeTeam", {}).get("shortName") or m.get("homeTeam", {}).get("name", "?"),
            "away": m.get("awayTeam", {}).get("shortName") or m.get("awayTeam", {}).get("name", "?"),
            "time": time_str,
            "status": m.get("status", ""),
        })
    return result

def parse_yesterday_results(league: str) -> list:
    data = load_json(f"yesterday_{league}.json")
    details_data = load_json(f"yesterday_details_{league}.json")

    details_by_id = {}
    for d in details_data.get("matches_details", []):
        match = d.get("match", d)
        mid = match.get("id")
        if mid:
            details_by_id[mid] = match

    result = []
    for m in data.get("matches", []):
        score = m.get("score", {}).get("fullTime", {})
        match_id = m.get("id")
        scorers = []
        detail = details_by_id.get(match_id, {})
        for goal in detail.get("goals", []):
            name = goal.get("scorer", {}).get("name")
            minute = goal.get("minute")
            team = goal.get("team", {}).get("shortName") or goal.get("team", {}).get("name")
            if name:
                scorers.append({"name": name, "minute": minute, "team": team})
        result.append({
            "id": match_id,
            "home": m.get("homeTeam", {}).get("name", "?"),
            "away": m.get("awayTeam", {}).get("name", "?"),
            "home_score": score.get("home"),
            "away_score": score.get("away"),
            "scorers": scorers,
        })
    return result

def parse_top_scorers(league: str) -> list:
    data = load_json(f"scorers_{league}.json")
    result = []
    for s in data.get("scorers", [])[:5]:
        result.append({
            "name": s.get("player", {}).get("name", "?"),
            "team": s.get("team", {}).get("shortName") or s.get("team", {}).get("name", "?"),
            "goals": s.get("goals", 0),
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
        prev_standings = prev_data.get("standings", [])
        if prev_standings:
            for team in prev_standings[0].get("table", []):
                previous_positions[team["team"]["name"]] = team["position"]

    result = []
    for team in table_today[:limit]:
        team_name = team["team"]["name"]
        current_pos = team["position"]
        previous_pos = previous_positions.get(team_name)
        if previous_pos:
            movement = "up" if current_pos < previous_pos else ("down" if current_pos > previous_pos else "same")
        else:
            movement = None
        result.append({
            "position": current_pos,
            "team": team["team"].get("shortName") or team_name,
            "points": team["points"],
            "played": team.get("playedGames", 0),
            "won": team.get("won", 0),
            "draw": team.get("draw", 0),
            "lost": team.get("lost", 0),
            "diff": team["goalDifference"],
            "movement": movement,
        })
    return result


# ── HTML SECTIONS ──────────────────────────────────────────

def section_header(title: str, subtitle: str = "") -> str:
    sub = f'<div style="font-size:11px;letter-spacing:3px;text-transform:uppercase;color:#888;margin-top:4px;">{subtitle}</div>' if subtitle else ""
    return f"""
    <table width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 8px 0;">
      <tr>
        <td style="padding:0 0 16px 0;">
          <div style="display:inline-block;background:linear-gradient(90deg,#00ff87,#60efff);border-radius:2px;width:32px;height:3px;margin-bottom:12px;"></div>
          <div style="font-family:'Georgia',serif;font-size:22px;font-weight:700;color:#ffffff;letter-spacing:-0.5px;">{title}</div>
          {sub}
        </td>
      </tr>
    </table>
    """

def league_pill(meta: dict) -> str:
    return f"""
    <span style="display:inline-block;background:{meta['accent']}22;border:1px solid {meta['accent']}55;
      border-radius:20px;padding:3px 12px;font-size:10px;letter-spacing:2px;text-transform:uppercase;
      color:{meta['accent']};font-weight:700;margin-bottom:14px;">
      {meta['flag']}&nbsp; {meta['name']}
    </span>
    """

def html_today_section_all() -> str:
    blocks = ""
    total = 0
    for league, meta in LEAGUE_META.items():
        matches = parse_today_matches(league)
        if not matches:
            continue
        total += len(matches)
        rows = ""
        for m in matches:
            live = m["status"] in ("IN_PLAY", "PAUSED", "HALFTIME")
            live_dot = '<span style="display:inline-block;width:7px;height:7px;background:#00ff87;border-radius:50%;margin-right:6px;"></span>' if live else ""
            time_color = "#00ff87" if live else "#aaa"
            rows += f"""
            <tr>
              <td style="padding:10px 14px;font-size:13px;color:{time_color};font-weight:600;white-space:nowrap;width:70px;">
                {live_dot}{m['time']}
              </td>
              <td style="padding:10px 8px;font-size:14px;color:#fff;font-weight:700;text-align:right;">{m['home']}</td>
              <td style="padding:10px 10px;font-size:11px;color:#555;text-align:center;font-weight:700;letter-spacing:1px;">VS</td>
              <td style="padding:10px 8px;font-size:14px;color:#fff;font-weight:700;text-align:left;">{m['away']}</td>
            </tr>
            <tr><td colspan="4" style="padding:0;"><div style="height:1px;background:linear-gradient(90deg,transparent,#222,transparent);"></div></td></tr>
            """
        blocks += f"""
        <div style="margin-bottom:20px;">
          {league_pill(meta)}
          <table width="100%" cellpadding="0" cellspacing="0"
            style="background:#111;border-radius:12px;overflow:hidden;border:1px solid #1e1e1e;">
            {rows}
          </table>
        </div>
        """
    if not blocks:
        return '<p style="color:#555;font-style:italic;text-align:center;padding:30px 0;">Aucun match programmé aujourd\'hui.</p>'
    return blocks

def html_yesterday_section_all() -> str:
    blocks = ""
    for league, meta in LEAGUE_META.items():
        results = parse_yesterday_results(league)
        if not results:
            continue
        rows = ""
        for m in results:
            hs = m["home_score"]
            aws = m["away_score"]
            score_str = f"{hs} – {aws}" if hs is not None else "– –"
            if hs is not None and aws is not None:
                home_w = hs > aws
                away_w = aws > hs
            else:
                home_w = away_w = False

            home_style = "color:#fff;font-weight:800;" if home_w else "color:#aaa;font-weight:600;"
            away_style = "color:#fff;font-weight:800;" if away_w else "color:#aaa;font-weight:600;"

            # Buteurs groupés par équipe
            home_goals = [s for s in m["scorers"] if s["team"] == m["home"] or (not away_w and not home_w)]
            scorer_lines = ""
            if m["scorers"]:
                scorer_lines = "<br>".join(
                    f'<span style="color:#00ff87;font-size:10px;">⚽</span>'
                    f'<span style="color:#777;font-size:10px;"> {s["name"]} {s["minute"] or ""}\'</span>'
                    for s in m["scorers"]
                )

            rows += f"""
            <tr>
              <td style="padding:14px 16px;vertical-align:top;">
                <div style="{home_style}font-size:13px;">{m['home']}</div>
                <div style="{away_style}font-size:13px;margin-top:6px;">{m['away']}</div>
              </td>
              <td style="padding:14px 16px;text-align:center;vertical-align:middle;white-space:nowrap;">
                <div style="font-size:22px;font-weight:900;color:#fff;letter-spacing:-1px;font-family:'Georgia',serif;">{score_str}</div>
              </td>
              <td style="padding:14px 16px;vertical-align:top;text-align:right;">
                {scorer_lines}
              </td>
            </tr>
            <tr><td colspan="3" style="padding:0;"><div style="height:1px;background:linear-gradient(90deg,transparent,#222,transparent);"></div></td></tr>
            """
        if rows:
            blocks += f"""
            <div style="margin-bottom:20px;">
              {league_pill(meta)}
              <table width="100%" cellpadding="0" cellspacing="0"
                style="background:#111;border-radius:12px;overflow:hidden;border:1px solid #1e1e1e;">
                {rows}
              </table>
            </div>
            """
    if not blocks:
        return '<p style="color:#555;font-style:italic;text-align:center;padding:30px 0;">Aucun résultat hier.</p>'
    return blocks

def html_scorers_section_all() -> str:
    blocks = ""
    for league, meta in LEAGUE_META.items():
        scorers = parse_top_scorers(league)
        if not scorers:
            continue
        rows = ""
        for i, s in enumerate(scorers):
            if i == 0:
                rank_style = f"background:{meta['accent']};color:#fff;"
                name_style = "color:#fff;font-weight:800;"
            else:
                rank_style = "background:#1e1e1e;color:#888;"
                name_style = "color:#ccc;font-weight:600;"

            bar_w = int((s["goals"] / scorers[0]["goals"]) * 100) if scorers[0]["goals"] else 0

            rows += f"""
            <tr>
              <td style="padding:12px 16px;vertical-align:middle;width:32px;">
                <div style="{rank_style}width:24px;height:24px;border-radius:50%;display:inline-block;
                  text-align:center;line-height:24px;font-size:11px;font-weight:700;">{i+1}</div>
              </td>
              <td style="padding:12px 8px;vertical-align:middle;">
                <div style="{name_style}font-size:13px;">{s['name']}</div>
                <div style="color:#555;font-size:10px;letter-spacing:1px;text-transform:uppercase;margin-top:2px;">{s['team']}</div>
                <div style="margin-top:6px;background:#1a1a1a;border-radius:2px;height:3px;width:100%;">
                  <div style="background:linear-gradient(90deg,{meta['accent']},{meta['accent']}88);height:3px;border-radius:2px;width:{bar_w}%;"></div>
                </div>
              </td>
              <td style="padding:12px 16px;vertical-align:middle;text-align:right;white-space:nowrap;">
                <span style="font-size:20px;font-weight:900;color:#fff;font-family:'Georgia',serif;">{s['goals']}</span>
                <span style="font-size:10px;color:#555;margin-left:3px;">buts</span>
              </td>
            </tr>
            <tr><td colspan="3" style="padding:0;"><div style="height:1px;background:linear-gradient(90deg,transparent,#1a1a1a,transparent);"></div></td></tr>
            """
        blocks += f"""
        <div style="margin-bottom:20px;">
          {league_pill(meta)}
          <table width="100%" cellpadding="0" cellspacing="0"
            style="background:#111;border-radius:12px;overflow:hidden;border:1px solid #1e1e1e;">
            {rows}
          </table>
        </div>
        """
    return blocks or '<p style="color:#555;font-style:italic;text-align:center;padding:30px 0;">Données indisponibles.</p>'

def html_standings_section_all() -> str:
    blocks = ""
    for league, meta in LEAGUE_META.items():
        standings = parse_standings(league)
        if not standings:
            continue
        rows = ""
        for team in standings:
            pos = team["position"]
            if pos == 1:
                row_bg = "background:linear-gradient(90deg,#0d2b1a,#111);"
                pos_style = f"background:{meta['accent']};color:#fff;"
                name_style = "color:#fff;font-weight:800;"
            elif pos >= 18:
                row_bg = "background:linear-gradient(90deg,#2a0a0a,#111);"
                pos_style = "background:#3a1515;color:#e57373;"
                name_style = "color:#e57373;font-weight:600;"
            else:
                row_bg = ""
                pos_style = "background:#1a1a1a;color:#888;"
                name_style = "color:#ccc;font-weight:600;"

            mv = team["movement"]
            if mv == "up":
                arrow = '<span style="color:#00ff87;font-size:10px;">▲</span>'
            elif mv == "down":
                arrow = '<span style="color:#f44336;font-size:10px;">▼</span>'
            else:
                arrow = '<span style="color:#333;font-size:10px;">—</span>'

            rows += f"""
            <tr style="{row_bg}">
              <td style="padding:10px 12px;width:36px;text-align:center;">
                <div style="{pos_style}width:24px;height:24px;border-radius:6px;display:inline-block;
                  text-align:center;line-height:24px;font-size:11px;font-weight:700;">{pos}</div>
              </td>
              <td style="padding:10px 8px;">
                <div style="{name_style}font-size:13px;">{team['team']}</div>
              </td>
              <td style="padding:10px 6px;text-align:center;color:#555;font-size:10px;width:16px;">{arrow}</td>
              <td style="padding:10px 8px;text-align:right;width:60px;">
                <span style="font-size:14px;font-weight:800;color:#fff;">{team['points']}</span>
                <span style="font-size:9px;color:#444;margin-left:2px;">pts</span>
              </td>
              <td style="padding:10px 12px;text-align:right;width:50px;">
                <span style="font-size:11px;color:#555;">{'+' if team['diff'] > 0 else ''}{team['diff']}</span>
              </td>
            </tr>
            <tr><td colspan="5" style="padding:0;"><div style="height:1px;background:linear-gradient(90deg,transparent,#1a1a1a,transparent);"></div></td></tr>
            """

        # Zone header
        zone_header = f"""
        <tr style="background:#0a0a0a;">
          <td colspan="5" style="padding:6px 12px;">
            <span style="font-size:9px;letter-spacing:2px;text-transform:uppercase;color:#333;">POS</span>
            <span style="font-size:9px;letter-spacing:2px;text-transform:uppercase;color:#333;margin-left:40px;">ÉQUIPE</span>
            <span style="font-size:9px;letter-spacing:2px;text-transform:uppercase;color:#333;float:right;">DIFF &nbsp;&nbsp;&nbsp; PTS</span>
          </td>
        </tr>
        """

        blocks += f"""
        <div style="margin-bottom:24px;">
          {league_pill(meta)}
          <table width="100%" cellpadding="0" cellspacing="0"
            style="background:#111;border-radius:12px;overflow:hidden;border:1px solid #1e1e1e;">
            {zone_header}
            {rows}
          </table>
        </div>
        """
    return blocks or '<p style="color:#555;font-style:italic;text-align:center;padding:30px 0;">Données indisponibles.</p>'


# ── EMAIL BUILDER ──────────────────────────────────────────

def build_email_html() -> str:

    today_label = today_label_str = today_label()

    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Football Daily — {TODAY}</title>
</head>
<body style="margin:0;padding:0;background:#090909;font-family:'Helvetica Neue',Helvetica,Arial,sans-serif;">

<!-- WRAPPER -->
<table width="100%" cellpadding="0" cellspacing="0" style="background:#090909;min-height:100vh;">
<tr><td align="center" style="padding:32px 16px 64px;">

<!-- CARD -->
<table width="620" cellpadding="0" cellspacing="0" style="max-width:620px;width:100%;">

  <!-- ══ HEADER ══════════════════════════════════════════ -->
  <tr>
    <td style="background:linear-gradient(160deg,#0e0e0e 0%,#111 40%,#0a1a0f 100%);
      border-radius:20px 20px 0 0;padding:48px 40px 36px;position:relative;
      border:1px solid #1c1c1c;border-bottom:none;">

      <!-- Glow orb -->
      <div style="position:absolute;top:-40px;right:40px;width:180px;height:180px;
        background:radial-gradient(circle,#00ff8733 0%,transparent 70%);pointer-events:none;"></div>

      <div style="font-size:10px;letter-spacing:4px;text-transform:uppercase;color:#00ff87;
        font-weight:700;margin-bottom:20px;">⚽ &nbsp;Football Daily Premium</div>

      <div style="font-family:'Georgia',serif;font-size:42px;font-weight:700;color:#ffffff;
        line-height:1;letter-spacing:-2px;margin-bottom:8px;">
        Le Brief<br><span style="color:#00ff87;">du Jour</span>
      </div>

      <div style="font-size:13px;color:#444;margin-top:16px;letter-spacing:1px;">
        {today_label_str.upper()} &nbsp;·&nbsp; 4 LIGUES &nbsp;·&nbsp; ÉDITION PREMIUM
      </div>

      <!-- Divider line -->
      <div style="margin-top:32px;height:1px;background:linear-gradient(90deg,#00ff87,#60efff,transparent);"></div>
    </td>
  </tr>

  <!-- ══ STATS BAR ════════════════════════════════════════ -->
  <tr>
    <td style="background:#0e0e0e;padding:0;border-left:1px solid #1c1c1c;border-right:1px solid #1c1c1c;">
      <table width="100%" cellpadding="0" cellspacing="0">
        <tr>
          <td style="padding:20px;text-align:center;border-right:1px solid #1a1a1a;">
            <div style="font-size:24px;font-weight:900;color:#fff;font-family:'Georgia',serif;">4</div>
            <div style="font-size:9px;letter-spacing:2px;color:#444;text-transform:uppercase;margin-top:4px;">Ligues</div>
          </td>
          <td style="padding:20px;text-align:center;border-right:1px solid #1a1a1a;">
            <div style="font-size:24px;font-weight:900;color:#00ff87;font-family:'Georgia',serif;">EN DIRECT</div>
            <div style="font-size:9px;letter-spacing:2px;color:#444;text-transform:uppercase;margin-top:4px;">Stats Live</div>
          </td>
          <td style="padding:20px;text-align:center;">
            <div style="font-size:24px;font-weight:900;color:#fff;font-family:'Georgia',serif;">{str(TODAY.strftime("%d/%m"))}</div>
            <div style="font-size:9px;letter-spacing:2px;color:#444;text-transform:uppercase;margin-top:4px;">Édition</div>
          </td>
        </tr>
      </table>
    </td>
  </tr>

  <!-- ══ BODY ════════════════════════════════════════════ -->
  <tr>
    <td style="background:#0e0e0e;padding:40px;border:1px solid #1c1c1c;border-top:none;border-bottom:none;">

      <!-- ─ MATCHS DU JOUR ─ -->
      <div style="margin-bottom:48px;">
        {section_header("Matchs du Jour", f"Programme · {today_label_str}")}
        {html_today_section_all()}
      </div>

      <!-- ─ SEPARATOR ─ -->
      <div style="height:1px;background:linear-gradient(90deg,transparent,#1e1e1e,transparent);margin-bottom:48px;"></div>

      <!-- ─ RÉSULTATS HIER ─ -->
      <div style="margin-bottom:48px;">
        {section_header("Récap d'Hier", "Résultats & Buteurs")}
        {html_yesterday_section_all()}
      </div>

      <!-- ─ SEPARATOR ─ -->
      <div style="height:1px;background:linear-gradient(90deg,transparent,#1e1e1e,transparent);margin-bottom:48px;"></div>

      <!-- ─ TOP SCOREURS ─ -->
      <div style="margin-bottom:48px;">
        {section_header("Top Buteurs", "Classement des meilleurs attaquants")}
        {html_scorers_section_all()}
      </div>

      <!-- ─ SEPARATOR ─ -->
      <div style="height:1px;background:linear-gradient(90deg,transparent,#1e1e1e,transparent);margin-bottom:48px;"></div>

      <!-- ─ CLASSEMENTS ─ -->
      <div style="margin-bottom:0;">
        {section_header("Classements", "Top 10 · Mouvement J-1")}
        {html_standings_section_all()}
      </div>

    </td>
  </tr>

  <!-- ══ FOOTER ═══════════════════════════════════════════ -->
  <tr>
    <td style="background:#080808;border-radius:0 0 20px 20px;padding:32px 40px;
      border:1px solid #1c1c1c;border-top:1px solid #141414;text-align:center;">
      <div style="font-size:10px;letter-spacing:3px;text-transform:uppercase;color:#333;margin-bottom:8px;">
        Football Daily Premium
      </div>
      <div style="font-size:11px;color:#2a2a2a;">
        Données via football-data.org &nbsp;·&nbsp; Généré automatiquement chaque jour
      </div>
      <div style="margin-top:20px;height:1px;background:linear-gradient(90deg,transparent,#1a1a1a,transparent);"></div>
      <div style="margin-top:20px;font-size:10px;color:#222;">
        © {TODAY.year} Football Daily · Tous droits réservés
      </div>
    </td>
  </tr>

</table>
<!-- END CARD -->

</td></tr>
</table>
<!-- END WRAPPER -->

</body>
</html>"""


# ── SEND ───────────────────────────────────────────────────

def send_email(html_content: str):
    smtp_host = os.environ.get("SMTP_HOST")
    smtp_port = int(os.environ.get("SMTP_PORT", 587))
    smtp_user = os.environ.get("SMTP_USER")
    smtp_pass = os.environ.get("SMTP_PASS")

    from_addr = os.environ.get("EMAIL_FROM", smtp_user)
    to_addrs  = os.environ.get("EMAIL_TO", smtp_user).split(",")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"⚽ Football Daily — {today_label()}"
    msg["From"]    = from_addr
    msg["To"]      = ", ".join(to_addrs)

    msg.attach(MIMEText("Ouvrez cet email dans un client compatible HTML.", "plain"))
    msg.attach(MIMEText(html_content, "html"))

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(from_addr, to_addrs, msg.as_string())
        print(f"✅ Email envoyé à : {', '.join(to_addrs)}")


if __name__ == "__main__":
    html = build_email_html()

    # Preview locale (optionnel)
    preview = Path("data/preview_email.html")
    preview.parent.mkdir(parents=True, exist_ok=True)
    preview.write_text(html)
    print(f"👁  Preview → {preview}")

    try:
        send_email(html)
    except Exception as e:
        print(f"❌ Erreur envoi : {e}")
