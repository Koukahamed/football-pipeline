"""Shared presentation data for email, web and calendar."""
import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from html import escape

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / 'config.json').read_text())
TZ = ZoneInfo(CONFIG['timezone'])
RAW = ROOT / 'data/raw'
OUT = ROOT / 'report/output'
STATUS = {'FINISHED': 'Terminé', 'SCHEDULED': 'Programmé', 'TIMED': 'Programmé', 'IN_PLAY': 'En cours', 'PAUSED': 'Mi-temps', 'POSTPONED': 'Reporté', 'CANCELLED': 'Annulé', 'SUSPENDED': 'Suspendu', 'AWARDED': 'Attribué'}


def read(name):
    path = RAW / name
    return json.loads(path.read_text()) if path.exists() else {}


def dataset():
    today = datetime.now(TZ).date()
    leagues = {}
    for key, meta in CONFIG['leagues'].items():
        resources = {kind: read(f'{kind}_{key}.json') for kind in ('matches', 'standings', 'scorers')}
        tables = resources['standings'].get('standings', [])
        table = next((x.get('table', []) for x in tables if x.get('type') == 'TOTAL'), [])
        previous_path = ROOT / 'data/history' / f'standings_{key}_{today - timedelta(days=1)}.json'
        previous = json.loads(previous_path.read_text()) if previous_path.exists() else {}
        prev_table = next((x.get('table', []) for x in previous.get('standings', []) if x.get('type') == 'TOTAL'), [])
        positions = {x['team']['id']: x['position'] for x in prev_table}
        table = [dict(x, movement=positions[x['team']['id']] - x['position'] if x['team']['id'] in positions else None) for x in table]
        leagues[key] = dict(meta, matches=resources['matches'].get('matches', []), table=table,
                            scorers=resources['scorers'].get('scorers', []),
                            freshness={kind: value.get('_fetched_at') for kind, value in resources.items()})
    return {'config': CONFIG, 'today': str(today), 'generated_at': datetime.now(TZ).isoformat(), 'meta': read('meta.json'), 'leagues': leagues}


def match_date(match):
    return datetime.fromisoformat(match['utcDate'].replace('Z', '+00:00')).astimezone(TZ)


def team_name(team):
    return team.get('shortName') or team.get('name') or 'Équipe'


def match_label(match):
    score = (match.get('score') or {}).get('fullTime') or {}
    value = f"{score['home']} – {score['away']}" if score.get('home') is not None and score.get('away') is not None else match_date(match).strftime('%H:%M')
    return f"{team_name(match['homeTeam'])} · {value} · {team_name(match['awayTeam'])} — {STATUS.get(match['status'], match['status'])}"


def email_content(data):
    today = data['today']
    yesterday = str(datetime.fromisoformat(today).date() - timedelta(days=1))
    parts = []
    plain = [f'Football Daily — {today}', 'Horaires : Europe/Paris']
    if data['meta'].get('errors') or not data['meta'].get('extracted_at') or (datetime.now(TZ) - datetime.fromisoformat(data['meta']['extracted_at'])).total_seconds() > 36 * 3600:
        message = '⚠ Données partielles : certaines ressources n’ont pas été actualisées. Consultez les dates sur le dashboard.'
        parts.append(f'<p style="color:#a15c00">{message}</p>')
        plain.append(message)
    # Highlights are derived from scores, without invented commentary.
    finished = [m for l in data['leagues'].values() for m in l['matches'] if str(match_date(m).date()) == yesterday and m.get('status') == 'FINISHED']
    scored = [m for m in finished if all((m.get('score') or {}).get('fullTime', {}).get(k) is not None for k in ('home', 'away'))]
    if scored:
        best = max(scored, key=lambda m: sum(m['score']['fullTime'][k] for k in ('home', 'away')))
        highlight = 'Match le plus prolifique d’hier : ' + match_label(best)
        parts.append('<h2>À retenir</h2><p>' + escape(highlight) + '</p>')
        plain.append(highlight)
    for title, date in [('Résultats d’hier', yesterday), ('Aujourd’hui', today)]:
        parts.append(f'<h2>{title}</h2>')
        plain.append(title)
        count = 0
        for league in data['leagues'].values():
            matches = [m for m in league['matches'] if str(match_date(m).date()) == date]
            if matches:
                parts.append(f"<h3>{escape(league['name'])}</h3><p style='font-size:12px;color:#64748b'>Récupération : {escape(league.get('freshness', {}).get('matches') or 'indisponible')}</p>")
            for match in sorted(matches, key=lambda m: m['utcDate']):
                label = match_label(match)
                parts.append(f'<p style="padding:10px;background:#f1f5f9;border-radius:8px">{escape(label)}</p>')
                plain.append(label)
                count += 1
        if not count:
            message = 'Aucun match disponible pour cette journée.' if data['meta'].get('errors') else 'Aucun match dans les compétitions suivies.'
            parts.append(f'<p>{message}</p>')
            plain.append(message)
    favorites = set(data['config']['favorite_team_ids'])
    next_matches = sorted([m for l in data['leagues'].values() for m in l['matches'] if m['homeTeam'].get('id') in favorites or m['awayTeam'].get('id') in favorites], key=lambda m: m['utcDate'])
    next_matches = [m for m in next_matches if str(match_date(m).date()) >= today][:5]
    if next_matches:
        parts.append('<h2>Mes équipes · prochains matchs</h2>')
        for m in next_matches:
            parts.append(f"<p>{match_date(m):%d/%m} · {escape(match_label(m))}</p>")
    url = escape(data['config']['dashboard_url'], quote=True)
    html = '<!doctype html><html lang="fr"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><body style="margin:0;background:#eaf0f6;font:16px Arial;color:#17243a"><main style="max-width:620px;margin:24px auto;padding:24px;background:white;border-radius:16px">' + f'<h1>⚽ Football Daily</h1><p>{today} · Horaires de Paris</p>' + ''.join(parts) + f'<p><a style="display:inline-block;padding:14px;background:#185a43;color:white;border-radius:8px" href="{url}">Classements, buteurs et calendrier →</a></p><p style="font-size:12px;color:#64748b">Données football-data.org · Actualisation quotidienne, sans suivi en direct.</p></main></body></html>'
    return html, '\n'.join(plain) + '\n' + data['config']['dashboard_url']
