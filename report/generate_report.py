"""
generate_report.py
──────────────────
Lit les données depuis DuckDB et génère un dashboard HTML
publié automatiquement sur GitHub Pages.
"""

import duckdb
import json
from pathlib import Path
from datetime import datetime

DB_PATH    = Path("data/football.duckdb")
OUTPUT_DIR = Path("report/output")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

LEAGUE_META = {
    "EPL"       : {"name": "Premier League", "flag": "🏴󠁧󠁢󠁥󠁮󠁧󠁿", "color": "#3d0c91"},
    "LIGUE1"    : {"name": "Ligue 1",         "flag": "🇫🇷",         "color": "#002395"},
    "BUNDESLIGA": {"name": "Bundesliga",       "flag": "🇩🇪",         "color": "#d00"},
}

con = duckdb.connect(str(DB_PATH))


def q(sql):
    return con.execute(sql).fetchall()


def fetch_data():
    standings = {}
    scorers   = {}
    matches   = {}
    week_stats = {}

    for league in ["EPL", "LIGUE1", "BUNDESLIGA"]:
        # Classement complet
        standings[league] = q(f"""
            SELECT position, team_name, played, won, draw, lost,
                   goals_for, goals_against, goal_diff, points, win_rate_pct
            FROM main_staging.stg_standings
            WHERE league = '{league}'
            ORDER BY position
        """)

        # Top scoreurs
        scorers[league] = q(f"""
            SELECT player_name, team_name, goals, assists
            FROM raw.scorers
            WHERE league = '{league}' AND goals IS NOT NULL
            ORDER BY goals DESC
            LIMIT 10
        """)

        # Matchs de la semaine
        matches[league] = q(f"""
            SELECT home_team, away_team, home_score, away_score,
                   result, total_goals, match_date
            FROM main_staging.stg_matches
            WHERE league = '{league}'
            ORDER BY match_date DESC
        """)

        # Stats hebdo
        ws = q(f"""
            SELECT COUNT(*) as nb, SUM(total_goals) as goals,
                   ROUND(AVG(total_goals),2) as avg_goals
            FROM main_staging.stg_matches
            WHERE league = '{league}'
        """)
        week_stats[league] = ws[0] if ws else (0, 0, 0)

    return standings, scorers, matches, week_stats


def render_standings_rows(rows):
    html = ""
    for r in rows:
        pos, team, played, won, draw, lost, gf, ga, gd, pts, wr = r
        badge = ""
        if pos == 1:   badge = "🥇"
        elif pos == 2: badge = "🥈"
        elif pos == 3: badge = "🥉"
        gd_str = f"+{gd}" if gd > 0 else str(gd)
        html += f"""
        <tr class="{'top3' if pos <= 3 else ''} {'zone-rel' if pos >= 18 else ''}">
            <td class="pos">{badge or pos}</td>
            <td class="team-name">{team}</td>
            <td>{played}</td>
            <td class="won">{won}</td>
            <td>{draw}</td>
            <td class="lost">{lost}</td>
            <td>{gf}</td>
            <td>{ga}</td>
            <td class="{'pos-diff' if gd >= 0 else 'neg-diff'}">{gd_str}</td>
            <td class="pts"><strong>{pts}</strong></td>
        </tr>"""
    return html


def render_scorers(rows, league_color):
    html = ""
    for i, r in enumerate(rows[:8]):
        name, team, goals, assists = r
        assists = assists or 0
        width = int(100 * goals / (rows[0][2] or 1))
        html += f"""
        <div class="scorer-row">
            <div class="scorer-info">
                <span class="scorer-rank">#{i+1}</span>
                <div>
                    <div class="scorer-name">{name}</div>
                    <div class="scorer-team">{team}</div>
                </div>
            </div>
            <div class="scorer-stats">
                <div class="goals-bar-wrap">
                    <div class="goals-bar" style="width:{width}%;background:{league_color}"></div>
                </div>
                <span class="goals-count">{goals} ⚽</span>
                <span class="assists-count">{assists} 🅰️</span>
            </div>
        </div>"""
    return html


def render_matches(rows):
    if not rows:
        return "<p class='no-matches'>Aucun match cette semaine.</p>"
    html = ""
    for r in rows[:6]:
        home, away, hs, as_, result, total, date = r
        winner_home = "bold" if result == "HOME_WIN" else ""
        winner_away = "bold" if result == "AWAY_WIN" else ""
        html += f"""
        <div class="match-card {'high-scoring' if total >= 4 else ''}">
            <span class="match-team {winner_home}">{home}</span>
            <span class="match-score">{hs} – {as_}</span>
            <span class="match-team right {winner_away}">{away}</span>
            {'<span class="goal-fire">🔥</span>' if total >= 4 else ''}
        </div>"""
    return html


def generate_html(standings, scorers, matches, week_stats):
    now = datetime.utcnow().strftime("%d %B %Y — %H:%M UTC")

    sections = ""
    for league_code, meta in LEAGUE_META.items():
        std  = standings.get(league_code, [])
        scr  = scorers.get(league_code, [])
        mtc  = matches.get(league_code, [])
        ws   = week_stats.get(league_code, (0, 0, 0))
        nb_matches, total_goals, avg_goals = ws

        sections += f"""
        <section class="league-section" id="{league_code.lower()}">
            <div class="league-header" style="border-color:{meta['color']}">
                <h2>{meta['flag']} {meta['name']}</h2>
                <div class="week-badges">
                    <span class="badge" style="background:{meta['color']}">
                        {nb_matches} matchs cette semaine
                    </span>
                    <span class="badge dark">{total_goals} buts · {avg_goals}/match</span>
                </div>
            </div>

            <div class="league-grid">
                <!-- Classement -->
                <div class="card standings-card">
                    <h3>Classement</h3>
                    <table class="standings-table">
                        <thead>
                            <tr>
                                <th>#</th><th>Équipe</th><th>J</th>
                                <th>V</th><th>N</th><th>D</th>
                                <th>BP</th><th>BC</th><th>GD</th><th>Pts</th>
                            </tr>
                        </thead>
                        <tbody>
                            {render_standings_rows(std)}
                        </tbody>
                    </table>
                </div>

                <!-- Right column -->
                <div class="right-col">
                    <!-- Scoreurs -->
                    <div class="card scorers-card">
                        <h3>⚽ Top Scoreurs</h3>
                        <div class="scorers-list">
                            {render_scorers(scr, meta['color'])}
                        </div>
                    </div>

                    <!-- Matchs de la semaine -->
                    <div class="card matches-card">
                        <h3>📅 Matchs de la semaine</h3>
                        <div class="matches-list">
                            {render_matches(mtc)}
                        </div>
                    </div>
                </div>
            </div>
        </section>"""

    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>⚽ Football Weekly Report</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@400;600;700;800&family=Barlow:wght@400;500;600&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg: #0a0a0f;
            --surface: #13131f;
            --surface2: #1c1c2e;
            --border: #2a2a3d;
            --text: #e8e8f0;
            --muted: #7070a0;
            --green: #00e676;
            --red: #ff5252;
            --gold: #ffd740;
        }}

        * {{ box-sizing: border-box; margin: 0; padding: 0; }}

        body {{
            font-family: 'Barlow', sans-serif;
            background: var(--bg);
            color: var(--text);
            min-height: 100vh;
        }}

        /* ── Header ── */
        header {{
            background: linear-gradient(135deg, #0a0a0f 0%, #1a0a2e 50%, #0a0a0f 100%);
            border-bottom: 1px solid var(--border);
            padding: 3rem 2rem 2rem;
            text-align: center;
            position: relative;
            overflow: hidden;
        }}
        header::before {{
            content: '⚽';
            position: absolute;
            font-size: 20rem;
            opacity: 0.03;
            top: -4rem;
            left: 50%;
            transform: translateX(-50%);
            pointer-events: none;
        }}
        header h1 {{
            font-family: 'Barlow Condensed', sans-serif;
            font-size: clamp(2.5rem, 6vw, 5rem);
            font-weight: 800;
            letter-spacing: -0.02em;
            text-transform: uppercase;
            background: linear-gradient(135deg, #fff 0%, var(--gold) 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }}
        .subtitle {{
            color: var(--muted);
            font-size: 0.95rem;
            margin-top: 0.5rem;
            letter-spacing: 0.1em;
            text-transform: uppercase;
        }}
        .update-time {{
            display: inline-block;
            margin-top: 1rem;
            background: var(--surface2);
            border: 1px solid var(--border);
            padding: 0.3rem 1rem;
            border-radius: 20px;
            font-size: 0.8rem;
            color: var(--muted);
        }}

        /* ── Nav ── */
        nav {{
            display: flex;
            justify-content: center;
            gap: 1rem;
            padding: 1.5rem 2rem;
            border-bottom: 1px solid var(--border);
            position: sticky;
            top: 0;
            background: rgba(10,10,15,0.95);
            backdrop-filter: blur(10px);
            z-index: 100;
        }}
        nav a {{
            color: var(--muted);
            text-decoration: none;
            font-family: 'Barlow Condensed', sans-serif;
            font-weight: 600;
            font-size: 1.1rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            padding: 0.4rem 1.2rem;
            border-radius: 6px;
            border: 1px solid transparent;
            transition: all 0.2s;
        }}
        nav a:hover {{
            color: var(--text);
            border-color: var(--border);
            background: var(--surface);
        }}

        /* ── Main layout ── */
        main {{ max-width: 1400px; margin: 0 auto; padding: 2rem; }}

        .league-section {{
            margin-bottom: 4rem;
            scroll-margin-top: 80px;
        }}

        .league-header {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            flex-wrap: wrap;
            gap: 1rem;
            padding-bottom: 1rem;
            margin-bottom: 1.5rem;
            border-bottom: 3px solid;
        }}
        .league-header h2 {{
            font-family: 'Barlow Condensed', sans-serif;
            font-size: 2rem;
            font-weight: 800;
            text-transform: uppercase;
            letter-spacing: 0.02em;
        }}

        .week-badges {{ display: flex; gap: 0.5rem; flex-wrap: wrap; }}
        .badge {{
            padding: 0.3rem 0.8rem;
            border-radius: 20px;
            font-size: 0.78rem;
            font-weight: 600;
            color: #fff;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }}
        .badge.dark {{ background: var(--surface2); border: 1px solid var(--border); color: var(--muted); }}

        .league-grid {{
            display: grid;
            grid-template-columns: 1fr 380px;
            gap: 1.5rem;
        }}
        @media (max-width: 1000px) {{
            .league-grid {{ grid-template-columns: 1fr; }}
        }}

        .right-col {{ display: flex; flex-direction: column; gap: 1.5rem; }}

        /* ── Cards ── */
        .card {{
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 1.5rem;
        }}
        .card h3 {{
            font-family: 'Barlow Condensed', sans-serif;
            font-size: 1.1rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: var(--muted);
            margin-bottom: 1rem;
        }}

        /* ── Standings table ── */
        .standings-table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 0.88rem;
        }}
        .standings-table thead th {{
            text-align: center;
            color: var(--muted);
            font-size: 0.7rem;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            padding: 0.4rem 0.5rem;
            border-bottom: 1px solid var(--border);
        }}
        .standings-table thead th:nth-child(2) {{ text-align: left; }}
        .standings-table tbody tr {{
            border-bottom: 1px solid rgba(255,255,255,0.04);
            transition: background 0.15s;
        }}
        .standings-table tbody tr:hover {{ background: var(--surface2); }}
        .standings-table td {{
            padding: 0.55rem 0.5rem;
            text-align: center;
            white-space: nowrap;
        }}
        .standings-table td.team-name {{ text-align: left; font-weight: 500; padding-left: 0.8rem; }}
        .standings-table td.pos {{ color: var(--muted); font-weight: 700; font-size: 0.85rem; }}
        .standings-table td.pts {{ font-size: 1rem; }}
        .standings-table td.won {{ color: var(--green); }}
        .standings-table td.lost {{ color: var(--red); }}
        .standings-table td.pos-diff {{ color: var(--green); }}
        .standings-table td.neg-diff {{ color: var(--red); }}
        .standings-table tr.top3 td.team-name {{ color: var(--gold); }}
        .standings-table tr.zone-rel {{ opacity: 0.6; }}

        /* ── Scorers ── */
        .scorer-row {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.5rem;
            padding: 0.6rem 0;
            border-bottom: 1px solid rgba(255,255,255,0.04);
        }}
        .scorer-info {{ display: flex; align-items: center; gap: 0.6rem; min-width: 0; }}
        .scorer-rank {{ color: var(--muted); font-size: 0.75rem; width: 20px; flex-shrink: 0; }}
        .scorer-name {{ font-weight: 600; font-size: 0.9rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 130px; }}
        .scorer-team {{ color: var(--muted); font-size: 0.75rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 130px; }}
        .scorer-stats {{ display: flex; align-items: center; gap: 0.5rem; flex-shrink: 0; }}
        .goals-bar-wrap {{ width: 50px; height: 4px; background: var(--surface2); border-radius: 2px; }}
        .goals-bar {{ height: 100%; border-radius: 2px; }}
        .goals-count {{ font-weight: 700; font-size: 0.85rem; min-width: 40px; text-align: right; }}
        .assists-count {{ color: var(--muted); font-size: 0.8rem; min-width: 35px; }}

        /* ── Matches ── */
        .match-card {{
            display: grid;
            grid-template-columns: 1fr auto 1fr;
            align-items: center;
            gap: 0.5rem;
            padding: 0.7rem 0;
            border-bottom: 1px solid rgba(255,255,255,0.04);
            font-size: 0.85rem;
            position: relative;
        }}
        .match-card.high-scoring {{ background: rgba(255,215,64,0.04); border-radius: 6px; padding: 0.7rem 0.5rem; }}
        .match-team {{ white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
        .match-team.right {{ text-align: right; }}
        .match-team.bold {{ font-weight: 700; color: var(--green); }}
        .match-score {{
            font-family: 'Barlow Condensed', sans-serif;
            font-size: 1.3rem;
            font-weight: 700;
            text-align: center;
            background: var(--surface2);
            padding: 0.15rem 0.6rem;
            border-radius: 6px;
            white-space: nowrap;
        }}
        .goal-fire {{ position: absolute; top: 0.2rem; right: 0; font-size: 0.7rem; }}
        .no-matches {{ color: var(--muted); font-size: 0.85rem; padding: 0.5rem 0; }}

        /* ── Footer ── */
        footer {{
            text-align: center;
            padding: 3rem 2rem;
            color: var(--muted);
            font-size: 0.8rem;
            border-top: 1px solid var(--border);
            margin-top: 2rem;
        }}
        footer a {{ color: var(--muted); }}
        footer strong {{ color: var(--text); }}

        /* ── Animations ── */
        .league-section {{ opacity: 0; transform: translateY(20px); animation: fadeUp 0.5s ease forwards; }}
        #epl {{ animation-delay: 0.1s; }}
        #ligue1 {{ animation-delay: 0.2s; }}
        #bundesliga {{ animation-delay: 0.3s; }}
        @keyframes fadeUp {{
            to {{ opacity: 1; transform: translateY(0); }}
        }}
    </style>
</head>
<body>
    <header>
        <h1>Football Weekly Report</h1>
        <p class="subtitle">Premier League · Ligue 1 · Bundesliga</p>
        <span class="update-time">🔄 Mis à jour le {now}</span>
    </header>

    <nav>
        <a href="#epl">🏴󠁧󠁢󠁥󠁮󠁧󠁿 Premier League</a>
        <a href="#ligue1">🇫🇷 Ligue 1</a>
        <a href="#bundesliga">🇩🇪 Bundesliga</a>
    </nav>

    <main>
        {sections}
    </main>

    <footer>
        <p>Pipeline de données par <strong>Hamed Savadogo</strong> —
        Données via <a href="https://football-data.org">football-data.org</a> ·
        Mis à jour automatiquement chaque lundi par GitHub Actions</p>
        <p style="margin-top:0.5rem">
            <a href="https://github.com/ton-user/football-pipeline">📂 Voir le code source</a>
        </p>
    </footer>
</body>
</html>"""


if __name__ == "__main__":
    print("🎨 Generating HTML report...")
    try:
        standings, scorers, matches, week_stats = fetch_data()
        html = generate_html(standings, scorers, matches, week_stats)
        out = OUTPUT_DIR / "index.html"
        out.write_text(html, encoding="utf-8")
        print(f"✅ Report generated → {out}")
    except Exception as e:
        print(f"⚠️  Error: {e}")
        # Génère un rapport minimal en cas d'erreur
        fallback = OUTPUT_DIR / "index.html"
        fallback.write_text(f"<h1>Report generation failed: {e}</h1>")
    finally:
        con.close()
