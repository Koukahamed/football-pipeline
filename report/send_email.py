"""
send_email.py  —  Daily Football Digest
─────────────────────────────────────────
Lit les JSON bruts (pas besoin de DuckDB pour l'email) et envoie
un email HTML avec :
  📅 MATCHS DU JOUR  — heure de coup d'envoi par ligue
  🏆 RÉCAP D'HIER    — scores, buteurs, stats du match

Variables d'environnement requises :
  FOOTBALL_API_KEY   (pour fetch_data.py, pas ici)
  EMAIL_FROM         ex: noreply@mondomaine.com
  EMAIL_TO           ex: moi@gmail.com  (séparés par virgule si plusieurs)
  SMTP_HOST          ex: smtp.gmail.com
  SMTP_PORT          ex: 587
  SMTP_USER          ex: moi@gmail.com
  SMTP_PASS          ex: app-password-gmail

Usage : python report/send_email.py
"""

import os
import json
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from datetime import datetime, timezone, timedelta

DATA_DIR  = Path("data/raw")
TODAY     = datetime.now(timezone.utc).date()
YESTERDAY = TODAY - timedelta(days=1)

LEAGUE_META = {
    "epl"       : {"name": "Premier League", "flag": "🏴󠁧󠁢󠁥󠁮󠁧󠁿", "color": "#3d0c91", "light": "#6a3dd1"},
    "ligue1"    : {"name": "Ligue 1",         "flag": "🇫🇷",         "color": "#002395", "light": "#1a4fd6"},
    "bundesliga": {"name": "Bundesliga",       "flag": "🇩🇪",         "color": "#c8102e", "light": "#e84060"},
    "laliga": {"name": "La Liga", "flag": "🇪🇸", "color": "#c8102e", "light": "#e05a20"},
}


# ── Parsers JSON ──────────────────────────────────────────────────────────────

def load_json(filename: str) -> dict:
    path = DATA_DIR / filename
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def parse_today_matches(league: str) -> list:
    """Retourne la liste des matchs du jour avec heure locale."""
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
            "home"  : m.get("homeTeam", {}).get("shortName") or m.get("homeTeam", {}).get("name", "?"),
            "away"  : m.get("awayTeam", {}).get("shortName") or m.get("awayTeam", {}).get("name", "?"),
            "time"  : time_str,
            "status": m.get("status", ""),
        })
    return result


def parse_yesterday_results(league: str) -> list:
    """Retourne les résultats d'hier avec score."""
    data = load_json(f"yesterday_{league}.json")
    matches = data.get("matches", [])
    result = []
    for m in matches:
        score = m.get("score", {}).get("fullTime", {})
        result.append({
            "id"        : m.get("id"),
            "home"      : m.get("homeTeam", {}).get("name", "?"),
            "away"      : m.get("awayTeam", {}).get("name", "?"),
            "home_score": score.get("home", 0),
            "away_score": score.get("away", 0),
        })
    return result


def parse_match_details(league: str) -> dict:
    """Retourne un dict {match_id: {goals: [], stats: {}}}"""
    data = load_json(f"yesterday_details_{league}.json")
    details_map = {}
    for detail in data.get("matches_details", []):
        match_id = detail.get("id")
        if not match_id:
            continue

        # Buteurs
        goals = []
        for g in detail.get("goals", []):
            scorer   = g.get("scorer", {}).get("name", "Inconnu")
            team     = g.get("team", {}).get("name", "")
            minute   = g.get("minute", "?")
            own_goal = g.get("type") == "OWN"
            assist   = (g.get("assist") or {}).get("name")
            goals.append({
                "scorer" : scorer,
                "team"   : team,
                "minute" : minute,
                "own_goal": own_goal,
                "assist" : assist,
            })

        # Stats du match (si dispo)
        stats = {}
        for s in detail.get("statistics", []):
            team_name = s.get("team", {}).get("name", "")
            stats[team_name] = s.get("statistics", {})

        details_map[match_id] = {"goals": goals, "stats": stats}
    return details_map


def parse_top_scorers(league: str) -> list:
    data = load_json(f"scorers_{league}.json")
    scorers = data.get("scorers", [])[:5]
    result = []
    for s in scorers:
        result.append({
            "name"  : s.get("player", {}).get("name", "?"),
            "team"  : s.get("team", {}).get("shortName") or s.get("team", {}).get("name", "?"),
            "goals" : s.get("goals", 0),
        })
    return result


# ── HTML Builders ─────────────────────────────────────────────────────────────

def html_today_section(league: str, meta: dict) -> str:
    matches = parse_today_matches(league)
    color   = meta["color"]
    light   = meta["light"]

    if not matches:
        body = f"""
        <tr><td style="padding:16px 24px;color:#999;font-size:14px;text-align:center;">
            Pas de match aujourd'hui
        </td></tr>"""
    else:
        body = ""
        for m in matches:
            live_badge = ""
            if m["status"] in ("IN_PLAY", "PAUSED"):
                live_badge = f'<span style="background:#00e676;color:#000;font-size:10px;font-weight:700;padding:2px 6px;border-radius:10px;margin-left:8px;">LIVE</span>'
            body += f"""
            <tr>
              <td style="padding:14px 24px;border-bottom:1px solid #2a2a3a;">
                <table width="100%" cellpadding="0" cellspacing="0">
                  <tr>
                    <td style="font-size:15px;font-weight:600;color:#e8e8f0;width:38%;">{m["home"]}</td>
                    <td style="text-align:center;width:24%;">
                      <span style="background:#1c1c2e;color:#aaa;font-size:12px;padding:4px 10px;border-radius:6px;white-space:nowrap;">{m["time"]}{live_badge}</span>
                    </td>
                    <td style="font-size:15px;font-weight:600;color:#e8e8f0;width:38%;text-align:right;">{m["away"]}</td>
                  </tr>
                </table>
              </td>
            </tr>"""

    return f"""
    <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:28px;background:#13131f;border-radius:12px;overflow:hidden;border:1px solid #2a2a3a;">
      <tr>
        <td style="background:linear-gradient(135deg,{color},{light});padding:14px 24px;">
          <span style="font-size:20px;">{meta["flag"]}</span>
          <span style="font-family:'Helvetica Neue',Arial,sans-serif;font-size:16px;font-weight:700;color:#fff;text-transform:uppercase;letter-spacing:0.05em;margin-left:8px;">{meta["name"]}</span>
        </td>
      </tr>
      {body}
    </table>"""


def html_yesterday_section(league: str, meta: dict) -> str:
    results = parse_yesterday_results(league)
    details = parse_match_details(league)
    color   = meta["color"]
    light   = meta["light"]

    if not results:
        return f"""
    <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:28px;background:#13131f;border-radius:12px;overflow:hidden;border:1px solid #2a2a3a;">
      <tr><td style="background:linear-gradient(135deg,{color},{light});padding:14px 24px;">
        <span style="font-size:20px;">{meta["flag"]}</span>
        <span style="font-family:'Helvetica Neue',Arial,sans-serif;font-size:16px;font-weight:700;color:#fff;text-transform:uppercase;letter-spacing:0.05em;margin-left:8px;">{meta["name"]}</span>
      </td></tr>
      <tr><td style="padding:16px 24px;color:#999;font-size:14px;text-align:center;">Pas de match hier</td></tr>
    </table>"""

    matches_html = ""
    for r in results:
        match_id    = r["id"]
        match_detail = details.get(match_id, {})
        goals_list  = match_detail.get("goals", [])
        stats_map   = match_detail.get("stats", {})

        home_score = r["home_score"]
        away_score = r["away_score"]
        result_tag = "home" if home_score > away_score else ("away" if away_score > home_score else "draw")

        home_bold = "font-weight:700;color:#fff;" if result_tag == "home" else "color:#bbb;"
        away_bold = "font-weight:700;color:#fff;" if result_tag == "away" else "color:#bbb;"
        score_bg  = "#ffd740" if result_tag == "draw" else color

        # Buteurs
        goals_html = ""
        if goals_list:
            goals_html += '<tr><td style="padding:4px 24px 12px 24px;">'
            goals_html += '<table width="100%" cellpadding="0" cellspacing="0">'
            for g in goals_list:
                own_str    = ' <span style="color:#ff5252;font-size:11px;">(CSC)</span>' if g["own_goal"] else ""
                assist_str = f' <span style="color:#888;font-size:11px;">► {g["assist"]}</span>' if g["assist"] else ""
                # which side
                side_color = color if not g["own_goal"] else "#ff5252"
                goals_html += f"""
                <tr>
                  <td style="padding:3px 0;font-size:13px;color:#ccc;">
                    <span style="color:{side_color};font-size:11px;margin-right:4px;">⚽</span>
                    <strong style="color:#e8e8f0;">{g["scorer"]}</strong>{own_str}
                    <span style="color:#666;margin:0 4px;">·</span>
                    <span style="color:#888;">{g["minute"]}'</span>
                    {assist_str}
                  </td>
                </tr>"""
            goals_html += '</table></td></tr>'

        # Stats clés (possession, tirs)
        stats_html = ""
        if stats_map:
            home_stats = stats_map.get(r["home"], {})
            away_stats = stats_map.get(r["away"], {})
            stat_items = []
            for key, label in [("SHOTS_ON_GOAL","Tirs cadrés"), ("CORNER_KICKS","Corners"), ("FOULS","Fautes")]:
                hv = home_stats.get(key, {}).get("value") or home_stats.get(key)
                av = away_stats.get(key, {}).get("value") or away_stats.get(key)
                if hv is not None and av is not None:
                    stat_items.append((label, hv, av))
            if stat_items:
                stats_html += '<tr><td style="padding:4px 24px 14px 24px;">'
                stats_html += '<table width="100%" cellpadding="0" cellspacing="0" style="background:#0d0d1a;border-radius:8px;overflow:hidden;">'
                for label, hv, av in stat_items:
                    stats_html += f"""
                    <tr>
                      <td style="padding:5px 12px;font-size:12px;color:#ccc;width:40%;text-align:right;">{hv}</td>
                      <td style="padding:5px 12px;font-size:11px;color:#666;text-align:center;width:20%;">{label}</td>
                      <td style="padding:5px 12px;font-size:12px;color:#ccc;width:40%;">{av}</td>
                    </tr>"""
                stats_html += '</table></td></tr>'

        matches_html += f"""
        <tr><td style="border-bottom:1px solid #1e1e2e;">
          <table width="100%" cellpadding="0" cellspacing="0">
            <tr>
              <td style="padding:14px 24px 10px 24px;">
                <table width="100%" cellpadding="0" cellspacing="0">
                  <tr>
                    <td style="font-size:15px;{home_bold}width:38%;">{r["home"]}</td>
                    <td style="text-align:center;width:24%;">
                      <span style="background:{score_bg};color:#000;font-family:'Helvetica Neue',Arial,sans-serif;font-size:18px;font-weight:800;padding:4px 14px;border-radius:8px;">{home_score} – {away_score}</span>
                    </td>
                    <td style="font-size:15px;{away_bold}width:38%;text-align:right;">{r["away"]}</td>
                  </tr>
                </table>
              </td>
            </tr>
            {goals_html}
            {stats_html}
          </table>
        </td></tr>"""

    return f"""
    <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:28px;background:#13131f;border-radius:12px;overflow:hidden;border:1px solid #2a2a3a;">
      <tr>
        <td style="background:linear-gradient(135deg,{color},{light});padding:14px 24px;">
          <span style="font-size:20px;">{meta["flag"]}</span>
          <span style="font-family:'Helvetica Neue',Arial,sans-serif;font-size:16px;font-weight:700;color:#fff;text-transform:uppercase;letter-spacing:0.05em;margin-left:8px;">{meta["name"]}</span>
        </td>
      </tr>
      {matches_html}
    </table>"""


def html_scorers_mini(league: str, meta: dict) -> str:
    scorers = parse_top_scorers(league)
    if not scorers:
        return ""
    rows = ""
    for i, s in enumerate(scorers):
        medal = ["🥇","🥈","🥉","4️⃣","5️⃣"][i] if i < 5 else f"{i+1}."
        rows += f"""
        <tr>
          <td style="padding:5px 0;font-size:13px;color:#aaa;">{medal}</td>
          <td style="padding:5px 8px;font-size:13px;color:#e8e8f0;font-weight:600;">{s["name"]}</td>
          <td style="padding:5px 0;font-size:12px;color:#888;">{s["team"]}</td>
          <td style="padding:5px 0 5px 8px;font-size:13px;color:{meta["light"]};font-weight:700;text-align:right;">{s["goals"]} ⚽</td>
        </tr>"""
    return f"""
    <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:12px;">
      <tr><td colspan="4" style="padding:0 0 6px 0;font-size:11px;color:#666;text-transform:uppercase;letter-spacing:0.1em;">
        {meta["flag"]} {meta["name"]}
      </td></tr>
      {rows}
    </table>"""


# ── Email HTML complet ────────────────────────────────────────────────────────

def build_email_html() -> str:
    today_str     = TODAY.strftime("%A %d %B %Y")
    yesterday_str = YESTERDAY.strftime("%d %B")

    # Sections matchs du jour
    today_sections = ""
    has_today = False
    for league, meta in LEAGUE_META.items():
        matches = parse_today_matches(league)
        if matches:
            has_today = True
            today_sections += html_today_section(league, meta)

    if not has_today:
        today_sections = """
        <tr><td style="padding:20px;text-align:center;color:#666;font-size:14px;">
            😴 Pas de match prévu aujourd'hui dans ces ligues.
        </td></tr>"""

    # Sections récap hier
    yesterday_sections = ""
    has_yesterday = False
    for league, meta in LEAGUE_META.items():
        results = parse_yesterday_results(league)
        if results:
            has_yesterday = True
            yesterday_sections += html_yesterday_section(league, meta)

    if not has_yesterday:
        yesterday_sections = """
        <p style="color:#666;font-size:14px;text-align:center;padding:20px 0;">
            Aucun résultat hier dans ces ligues.
        </p>"""

    # Top scoreurs
    scorers_html = ""
    for league, meta in LEAGUE_META.items():
        scorers_html += html_scorers_mini(league, meta)

    return f"""
<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>⚽ Football Daily — {today_str}</title>
</head>
<body style="margin:0;padding:0;background:#0a0a0f;font-family:'Helvetica Neue',Arial,sans-serif;">

  <!-- Wrapper -->
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0a0a0f;padding:32px 0;">
  <tr><td align="center">
  <table width="620" cellpadding="0" cellspacing="0" style="max-width:620px;width:100%;">

    <!-- HEADER -->
    <tr>
      <td style="background:linear-gradient(135deg,#0d0d1a 0%,#1a0a2e 50%,#0d0d1a 100%);border-radius:16px 16px 0 0;padding:36px 32px 28px;text-align:center;border:1px solid #2a2a3a;border-bottom:none;">
        <div style="font-size:48px;margin-bottom:12px;">⚽</div>
        <h1 style="margin:0;font-size:28px;font-weight:800;color:#fff;letter-spacing:-0.02em;text-transform:uppercase;">
          Football Daily
        </h1>
        <p style="margin:6px 0 0;color:#7070a0;font-size:13px;text-transform:uppercase;letter-spacing:0.1em;">
          {today_str}
        </p>
        <p style="margin:14px 0 0;display:inline-block;background:#1c1c2e;border:1px solid #2a2a3a;color:#7070a0;font-size:11px;padding:4px 14px;border-radius:20px;">
          🏴󠁧󠁢󠁥󠁮󠁧󠁿 Premier League &nbsp;·&nbsp; 🇫🇷 Ligue 1 &nbsp;·&nbsp; 🇩🇪 Bundesliga &nbsp;·&nbsp; 🇪🇸 La Liga
        </p>
      </td>
    </tr>

    <!-- BODY -->
    <tr>
      <td style="background:#0d0d1a;padding:0 32px 32px;border:1px solid #2a2a3a;border-top:none;border-radius:0 0 16px 16px;">

        <!-- ── MATCHS DU JOUR ── -->
        <table width="100%" cellpadding="0" cellspacing="0">
          <tr>
            <td style="padding:28px 0 16px;">
              <table width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td>
                    <h2 style="margin:0;font-size:20px;font-weight:800;color:#fff;text-transform:uppercase;letter-spacing:0.03em;">
                      📅 Matchs du jour
                    </h2>
                    <p style="margin:4px 0 0;color:#7070a0;font-size:12px;">Au programme aujourd'hui</p>
                  </td>
                </tr>
              </table>
            </td>
          </tr>
          <tr>
            <td>
              {today_sections}
            </td>
          </tr>
        </table>

        <!-- Divider -->
        <table width="100%" cellpadding="0" cellspacing="0" style="margin:8px 0 24px;">
          <tr><td style="border-top:1px solid #2a2a3a;"></td></tr>
        </table>

        <!-- ── RÉCAP D'HIER ── -->
        <table width="100%" cellpadding="0" cellspacing="0">
          <tr>
            <td style="padding-bottom:16px;">
              <h2 style="margin:0;font-size:20px;font-weight:800;color:#fff;text-transform:uppercase;letter-spacing:0.03em;">
                🏆 Récap du {yesterday_str}
              </h2>
              <p style="margin:4px 0 0;color:#7070a0;font-size:12px;">Résultats, buteurs &amp; stats</p>
            </td>
          </tr>
          <tr>
            <td>
              {yesterday_sections}
            </td>
          </tr>
        </table>

        <!-- Divider -->
        <table width="100%" cellpadding="0" cellspacing="0" style="margin:8px 0 24px;">
          <tr><td style="border-top:1px solid #2a2a3a;"></td></tr>
        </table>

        <!-- ── TOP SCOREURS ── -->
        <table width="100%" cellpadding="0" cellspacing="0">
          <tr>
            <td style="padding-bottom:16px;">
              <h2 style="margin:0;font-size:20px;font-weight:800;color:#fff;text-transform:uppercase;letter-spacing:0.03em;">
                ⚽ Top Scoreurs
              </h2>
              <p style="margin:4px 0 0;color:#7070a0;font-size:12px;">Meilleurs buteurs de la saison</p>
            </td>
          </tr>
          <tr>
            <td style="background:#13131f;border:1px solid #2a2a3a;border-radius:12px;padding:20px 24px;">
              {scorers_html}
            </td>
          </tr>
        </table>

      </td>
    </tr>

    <!-- FOOTER -->
    <tr>
      <td style="padding:20px 0;text-align:center;">
        <p style="margin:0;color:#3a3a5a;font-size:11px;">
          Données via <a href="https://football-data.org" style="color:#3a3a5a;">football-data.org</a>
          &nbsp;·&nbsp; Pipeline automatique GitHub Actions
          &nbsp;·&nbsp; Envoyé le {today_str}
        </p>
      </td>
    </tr>

  </table>
  </td></tr>
  </table>

</body>
</html>"""


# ── Envoi SMTP ────────────────────────────────────────────────────────────────

def send_email(html_content: str):
    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", 587))
    smtp_user = os.environ.get("SMTP_USER", "")
    smtp_pass = os.environ.get("SMTP_PASS", "")
    from_addr = os.environ.get("EMAIL_FROM", smtp_user)
    to_addrs  = [e.strip() for e in os.environ.get("EMAIL_TO", smtp_user).split(",") if e.strip()]

    if not smtp_user or not smtp_pass:
        raise ValueError("❌ SMTP_USER et SMTP_PASS doivent être définis en variables d'environnement.")

    today_str = TODAY.strftime("%A %d %B %Y")
    subject   = f"⚽ Football Daily — {today_str}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = from_addr
    msg["To"]      = ", ".join(to_addrs)

    # Fallback texte
    text_part = MIMEText(
        f"Football Daily — {today_str}\n\nOuvre ce mail dans un client compatible HTML pour voir le rapport complet.",
        "plain", "utf-8"
    )
    html_part = MIMEText(html_content, "html", "utf-8")

    msg.attach(text_part)
    msg.attach(html_part)

    print(f"📧 Connexion à {smtp_host}:{smtp_port}...")
    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.ehlo()
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(from_addr, to_addrs, msg.as_string())

    print(f"✅ Email envoyé → {to_addrs}")


# ── Preview HTML (debug) ──────────────────────────────────────────────────────

def save_preview(html_content: str):
    out = Path("report/output/email_preview.html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html_content, encoding="utf-8")
    print(f"💾 Preview sauvegardée → {out}")


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"🎨 Génération de l'email — {TODAY}\n")
    html = build_email_html()

    preview_only = os.environ.get("EMAIL_PREVIEW_ONLY", "false").lower() == "true"

    if preview_only:
        save_preview(html)
        print("ℹ️  Mode preview uniquement (EMAIL_PREVIEW_ONLY=true). Pas d'envoi.")
    else:
        save_preview(html)   # toujours sauvegarder la preview
        try:
            send_email(html)
        except Exception as e:
            print(f"⚠️  Erreur envoi : {e}")
            raise
