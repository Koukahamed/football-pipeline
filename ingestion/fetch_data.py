"""Retrieve a bounded Paris-date window; preserve last good responses on failure."""
import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import requests

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / 'config.json').read_text())
TZ = ZoneInfo(CONFIG['timezone'])
RAW = ROOT / 'data/raw'
HISTORY = ROOT / 'data/history'


def local_date(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(TZ).date()


class Client:
    def __init__(self, key):
        self.session = requests.Session()
        self.session.headers['X-Auth-Token'] = key
        self.last_call = 0

    def get(self, endpoint, params=None):
        for attempt in range(3):
            time.sleep(max(0, 6.2 - (time.monotonic() - self.last_call)))
            self.last_call = time.monotonic()
            try:
                response = self.session.get('https://api.football-data.org/v4/' + endpoint, params=params, timeout=30)
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt == 2:
                        response.raise_for_status()
                    try:
                        delay = float(response.headers.get('Retry-After', 15 * (attempt + 1)))
                    except ValueError:
                        delay = 30
                    time.sleep(min(120, max(6.2, delay)))
                    continue
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, dict):
                    raise ValueError('Invalid API response')
                return data
            except (requests.ConnectionError, requests.Timeout):
                if attempt == 2:
                    raise
        raise RuntimeError('API retries exhausted')


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    temporary.replace(path)


def retrieve(client, endpoint, filename, now, errors, params=None):
    path = RAW / filename
    try:
        data = client.get(endpoint, params)
        if ('/matches' in endpoint and not isinstance(data.get('matches'), list)
                or endpoint.endswith('/standings') and not isinstance(data.get('standings'), list)
                or endpoint.endswith('/scorers') and not isinstance(data.get('scorers'), list)):
            raise ValueError('Missing expected collection')
        data['_fetched_at'] = now.isoformat()
        write(path, data)
        return data
    except (requests.RequestException, ValueError, RuntimeError) as exc:
        # Never log request headers / credentials.
        status = getattr(getattr(exc, 'response', None), 'status_code', None)
        errors.append({'file': filename, 'error': f'HTTP {status}' if status else type(exc).__name__})
        return json.loads(path.read_text()) if path.exists() else {}


def main():
    key = os.environ.get('FOOTBALL_API_KEY')
    if not key:
        raise SystemExit('FOOTBALL_API_KEY is required')
    now = datetime.now(TZ)
    today = now.date()
    client = Client(key)
    errors = []
    for league, meta in CONFIG['leagues'].items():
        base = f"competitions/{meta['code']}"
        # Over-fetch UTC boundary dates, then filter exact local dates. dateTo is exclusive in v4.
        matches = retrieve(client, base + '/matches', f'matches_{league}.json', now, errors,
                           {'dateFrom': str(today - timedelta(days=8)), 'dateTo': str(today + timedelta(days=8))})
        if matches:
            items = matches.get('matches', [])
            for prefix, predicate in [
                ('today', lambda d: d == today),
                ('yesterday', lambda d: d == today - timedelta(days=1)),
                ('upcoming', lambda d: today <= d < today + timedelta(days=7))]:
                write(RAW / f'{prefix}_{league}.json', {'matches': [m for m in items if m.get('utcDate') and predicate(local_date(m['utcDate']))], '_fetched_at': matches.get('_fetched_at')})
        standings = retrieve(client, base + '/standings', f'standings_{league}.json', now, errors)
        if standings.get('_fetched_at') == now.isoformat():
            write(HISTORY / f'standings_{league}_{today}.json', standings)
        retrieve(client, base + '/scorers', f'scorers_{league}.json', now, errors, {'limit': 10})
    write(RAW / 'meta.json', {'extracted_at': now.isoformat(), 'today': str(today), 'errors': errors, 'leagues': list(CONFIG['leagues'])})
    for path in HISTORY.glob('standings_*.json'):
        if path.name[-15:-5] < str(today - timedelta(days=60)):
            path.unlink()
    print(f'Extraction complete: {len(errors)} unavailable resources (last good data retained).')
    if len(errors) == 3 * len(CONFIG['leagues']):
        raise SystemExit('All API resources failed; refusing publication/email')


if __name__ == '__main__':
    main()
