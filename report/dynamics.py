"""Team form from scored final matches and observed (never reconstructed) rankings."""
import json
from datetime import datetime


def season_key(season):
    season = season or {}
    return season.get('id') or season.get('startDate')


def total_table(payload):
    return next((t for t in payload.get('standings', []) if t.get('type') == 'TOTAL'), {})


def ranking_history(directory, league, current):
    season = season_key(current.get('season'))
    scope = total_table(current)
    if season is None or not scope:
        return {}
    daily = {}
    for path in sorted(directory.glob(f'standings_{league}_*.json')):
        payload = json.loads(path.read_text())
        table = total_table(payload)
        if (season_key(payload.get('season')) != season
                or (table.get('stage'), table.get('group')) != (scope.get('stage'), scope.get('group'))):
            continue
        observed = payload.get('_fetched_at')
        if not observed:
            continue
        daily[observed[:10]] = payload
    # Include today's successful response even when rendering outside the ingestion workflow.
    observed = current.get('_fetched_at')
    if observed and observed >= daily.get(observed[:10], {}).get('_fetched_at', ''):
        daily[observed[:10]] = current
    result = {}
    for day, payload in sorted(daily.items()):
        for row in total_table(payload).get('table', []):
            if isinstance(row.get('position'), int) and row['position'] > 0:
                result.setdefault(str(row['team']['id']), []).append({
                    'date': day, 'position': row['position'], 'points': row.get('points'),
                    'played': row.get('playedGames'), 'observed_at': payload['_fetched_at']})
    return result


def team_dynamics(matches_payload, standings, history, league, now):
    current_season = season_key(standings.get('season'))
    unique = {m['id']: m for m in matches_payload.get('matches', []) if m.get('id') is not None}
    if current_season is None:
        seasons = [(m.get('utcDate', ''), season_key(m.get('season'))) for m in unique.values()]
        current_season = max(seasons, key=lambda item: item[0], default=('', None))[1]
    matches = [m for m in unique.values() if current_season is not None and season_key(m.get('season')) == current_season]
    teams = {str(r['team']['id']): r['team'] for r in total_table(standings).get('table', [])}
    positions = {str(r['team']['id']): r.get('position') for r in total_table(standings).get('table', [])}
    for m in matches:
        for side in ('homeTeam', 'awayTeam'):
            team = m.get(side) or {}
            if team.get('id') is not None:
                teams[str(team['id'])] = dict(team, **teams.get(str(team['id']), {}))
    played = []
    for m in matches:
        score = (m.get('score') or {}).get('fullTime') or {}
        if m.get('status') != 'FINISHED' or any(type(score.get(s)) is not int or score[s] < 0 for s in ('home', 'away')):
            continue
        try:
            kickoff = datetime.fromisoformat(m['utcDate'].replace('Z', '+00:00'))
            if kickoff.tzinfo is None or kickoff > now:
                continue
        except (ValueError, KeyError):
            continue
        played.append(m)
    played.sort(key=lambda m: (m['utcDate'], m['id']))
    rankings = ranking_history(history, league, standings)
    result = []
    for team_id, team in teams.items():
        recent = [m for m in played if team['id'] in (m['homeTeam']['id'], m['awayTeam']['id'])][-5:]
        form = []
        for m in recent:
            home = m['homeTeam']['id'] == team['id']
            own, other = ('home', 'away') if home else ('away', 'home')
            gf, ga = m['score']['fullTime'][own], m['score']['fullTime'][other]
            outcome = 'W' if gf > ga else 'L' if gf < ga else 'D'
            form.append({'match_id': m['id'], 'utcDate': m['utcDate'], 'opponent': m['awayTeam' if home else 'homeTeam'],
                         'venue': 'home' if home else 'away', 'goals_for': gf, 'goals_against': ga,
                         'result': outcome, 'points': {'W': 3, 'D': 1, 'L': 0}[outcome]})
        result.append({'team': team, 'position': positions.get(team_id), 'form': form,
                       'played': len(form), 'points': sum(m['points'] for m in form),
                       'goals_for': sum(m['goals_for'] for m in form), 'goals_against': sum(m['goals_against'] for m in form),
                       'ranking_history': rankings.get(team_id, [])})
    return {'season': current_season, 'full_season': matches_payload.get('_scope') == 'current_season',
            'fetched_at': matches_payload.get('_fetched_at'), 'teams': result}
