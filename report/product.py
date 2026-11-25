"""Shared presentation data for email, web and calendar."""
import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from html import escape
from dynamics import team_dynamics
from predictions import update, email_section, instant

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
                            dynamics=team_dynamics(resources['matches'], resources['standings'], ROOT / 'data/history', key, datetime.now(TZ)),
                            freshness={kind: value.get('_fetched_at') for kind, value in resources.items()})
    predictions = update(ROOT, leagues)
    return {'predictions': predictions, 'config': CONFIG, 'today': str(today), 'generated_at': datetime.now(TZ).isoformat(), 'meta': read('meta.json'), 'leagues': leagues}


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
    prediction_html, prediction_lines = email_section(data.get('predictions', {}), today, TZ)
    parts.append(prediction_html)
    plain.extend(prediction_lines)
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


def favorites_email_content(data, now=None):
    """Render today's unstarted, valid forecasts with a win probability >= 70%."""
    now = now or datetime.now(TZ)
    matches = {}
    for key, league in data['leagues'].items():
        if key not in ('epl', 'ligue1', 'bundesliga', 'laliga', 'seriea', 'ucl'):
            continue
        fetched = league.get('freshness', {}).get('matches')
        if not fetched or not timedelta(0) <= now - instant(fetched) < timedelta(hours=36):
            continue
        for match in league['matches']:
            matches[(key, str(match['id']))] = match
    selected = []
    for record in data.get('predictions', {}).get('records', []):
        match = matches.get((record['league'], str(record['match_id'])))
        if not match or match.get('status') not in ('TIMED', 'SCHEDULED'):
            continue
        kickoff = instant(record['kickoff'])
        if match['utcDate'] != record['kickoff'] or record.get('evaluation'):
            continue
        if not instant(record['issued_at']) <= now < kickoff or str(kickoff.astimezone(TZ).date()) != data['today']:
            continue
        if record['pick'] in ('1', '2') and record['outcome'][record['pick']] >= .70:
            selected.append(record)
    selected.sort(key=lambda record: record['kickoff'])
    title = 'Football Daily — Favoris ≥ 70 %'
    intro = f"{data['today']} · Matchs du jour · Horaires de Paris"
    plain = [title, intro, 'Probabilités estimées par le modèle.', '']
    cards = []
    for record in selected:
        home, away = team_name(record['home']), team_name(record['away'])
        winner = home if record['pick'] == '1' else away
        probability = f"{record['outcome'][record['pick']] * 100:.1f}".replace('.', ',') + ' %'
        hour = instant(record['kickoff']).astimezone(TZ).strftime('%H:%M')
        league = data['leagues'][record['league']]['name']
        plain.extend([f'{hour} · {league}', f'{home} – {away}', f'Victoire {winner} · {probability}', ''])
        cards.append('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 20px;border:1px solid #dce5e0;border-radius:12px"><tr><td style="padding:20px">'
                     f'<p style="margin:0 0 10px;color:#64748b;font-size:13px">{hour} · {escape(league)}</p>'
                     f'<h2 style="margin:0 0 16px;font-size:18px;line-height:1.5">{escape(home)} – {escape(away)}</h2>'
                     f'<p style="margin:0;color:#185a43;line-height:1.6"><strong>Victoire {escape(winner)} · {probability}</strong></p>'
                     '</td></tr></table>')
    if not selected:
        message = 'Aucun favori éligible à au moins 70 % dans les prévisions disponibles pour les matchs du jour.'
        cards.append(f'<p style="line-height:1.6">{message}</p>')
        plain.append(message)
    url = data['config']['dashboard_url']
    html = '<!doctype html><html lang="fr"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><body style="margin:0;background:#eaf0f6;font:16px Arial;color:#17243a"><main style="max-width:620px;margin:24px auto;padding:24px;background:white;border-radius:16px">' + f'<h1 style="font-size:24px">{escape(title)}</h1><p>{escape(intro)}</p><p style="margin:0 0 24px;color:#64748b;font-size:13px">Probabilités estimées par le modèle.</p>' + ''.join(cards) + f'<p><a href="{escape(url, quote=True)}">Consulter le site</a></p></main></body></html>'
    return html, '\n'.join(plain) + '\n' + url

