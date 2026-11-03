"""Probe actual lineup access; publish counts only, never assume an empty list means no absences."""
import json
import os
from datetime import datetime
from fetch_data import Client, CONFIG, ROOT, RAW, TZ, write

def main():
    client = Client(os.environ['FOOTBALL_API_KEY'])
    results = []
    for key in ('ucl', 'epl'):
        path = RAW / f'matches_{key}.json'
        matches = json.loads(path.read_text()).get('matches', []) if path.exists() else []
        candidates = sorted([m for m in matches if m.get('status') == 'FINISHED'], key=lambda m: m['utcDate'], reverse=True)[:1]
        for m in candidates:
            item = {'match_id': m['id'], 'competition': key, 'status': 'unknown'}
            try:
                client.session.headers['X-Unfold-Lineups'] = 'true'
                data = client.get(f'matches/{m["id"]}')
                counts = {side: len(data.get(side, {}).get('lineup') or []) for side in ('homeTeam','awayTeam')}
                item.update(status='available' if all(counts.values()) else 'empty_or_not_entitled', lineup_counts=counts)
            except Exception as exc:
                code = getattr(getattr(exc, 'response', None), 'status_code', None)
                item.update(status='unavailable', http=code, error_type=type(exc).__name__)
            results.append(item)
    write(ROOT / 'data/predictions/team_news_access.json',
          {'checked_at': datetime.now(TZ).isoformat(), 'probes': results,
           'injuries': 'not_collected', 'rotations': 'not_inferred',
           'note': 'Historical lineup access does not prove availability before kickoff. No player adjustment applied.'})
    print(json.dumps(results))

if __name__ == '__main__':
    main()
