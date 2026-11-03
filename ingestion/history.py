"""Backfill prior complete seasons once; never silently accept the wrong season."""
import json
import os
from datetime import datetime
from pathlib import Path
from fetch_data import Client, CONFIG, ROOT, TZ, write

HISTORY_LEAGUES = {'epl': 'PL', 'ligue1': 'FL1', 'bundesliga': 'BL1', 'laliga': 'PD',
                  'ucl': 'CL', 'seriea': 'SA', 'portugal': 'PPL', 'netherlands': 'DED'}

def valid_season(data, year):
    rows = data.get('matches')
    return bool(rows) and all(str(m.get('season', {}).get('startDate', '')).startswith(str(year)) for m in rows)

def main():
    client = Client(os.environ['FOOTBALL_API_KEY'])
    now = datetime.now(TZ)
    year = now.year if now.month >= 7 else now.year - 1
    coverage = []
    for key, code in HISTORY_LEAGUES.items():
        for season in range(year - 3, year):
            path = ROOT / f'data/training/{key}_{season}.json'
            existing = json.loads(path.read_text()) if path.exists() else {}
            if not valid_season(existing, season):
                data = client.get(f'competitions/{code}/matches', {'season': season})
                if not valid_season(data, season):
                    raise RuntimeError(f'Wrong or empty season: {code} {season}')
                # Persist only public sporting fields used for modelling.
                rows = [{k: m[k] for k in ('id','utcDate','status','homeTeam','awayTeam','score','season','competition') if k in m} for m in data['matches']]
                write(path, {'matches': rows, '_fetched_at': now.isoformat(), '_competition': code, '_season': season})
            coverage.append({'competition': code, 'season': season})
        # Supplement model context without adding new leagues to the visible digest.
        if key not in CONFIG['leagues']:
            data = client.get(f'competitions/{code}/matches')
            data['_fetched_at'] = now.isoformat()
            write(ROOT / f'data/context/{key}.json', data)
    write(ROOT / 'data/training/coverage.json', {'collected_at': now.isoformat(), 'resources': coverage})
    print(f'Historical resources verified: {len(coverage)}')

if __name__ == '__main__':
    main()
