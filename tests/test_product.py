import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'report'))
sys.path.insert(0, str(ROOT / 'ingestion'))
import fetch_data as fetch
import product
import send_email
import generate_dashboard


class ProductTests(unittest.TestCase):
    def test_paris_boundary_and_dst(self):
        self.assertEqual(str(fetch.local_date('2026-10-04T22:30:00Z')), '2026-10-05')
        self.assertEqual(str(fetch.local_date('2026-01-04T22:30:00Z')), '2026-01-04')
        self.assertEqual(str(fetch.local_date('2026-03-29T22:30:00Z')), '2026-03-30')

    def test_failure_preserves_last_good_response(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(fetch, 'RAW', Path(directory)):
            path = Path(directory) / 'matches_epl.json'
            old = {'matches': [], '_fetched_at': '2026-10-01T12:00:00Z'}
            path.write_text(json.dumps(old))
            client = Mock()
            client.get.side_effect = fetch.requests.Timeout()
            errors = []
            result = fetch.retrieve(client, 'competitions/PL/matches', path.name, datetime.now(fetch.TZ), errors)
            self.assertEqual(result, old)
            self.assertEqual(json.loads(path.read_text()), old)
            self.assertEqual(len(errors), 1)

    def test_429_retry(self):
        client = fetch.Client('test')
        rate_limit = Mock(status_code=429, headers={'Retry-After': '1'})
        success = Mock(status_code=200)
        success.json.return_value = {'matches': []}
        client.session.get = Mock(side_effect=[rate_limit, success])
        with patch.object(fetch.time, 'sleep'):
            self.assertEqual(client.get('matches'), {'matches': []})
        self.assertEqual(client.session.get.call_count, 2)

    def test_403_not_retried(self):
        client = fetch.Client('test')
        response = Mock(status_code=403)
        response.raise_for_status.side_effect = fetch.requests.HTTPError(response=response)
        client.session.get = Mock(return_value=response)
        with patch.object(fetch.time, 'sleep'), self.assertRaises(fetch.requests.HTTPError):
            client.get('matches')
        self.assertEqual(client.session.get.call_count, 1)

    def test_preview_never_sends_and_escapes_names(self):
        match = {'id': 1, 'utcDate': '2026-10-05T18:00:00Z', 'status': 'TIMED', 'homeTeam': {'id': 1, 'name': '<script>bad</script>'}, 'awayTeam': {'id': 2, 'name': 'Away'}, 'score': {'fullTime': {'home': None, 'away': None}}}
        data = {'today': '2026-10-05', 'config': product.CONFIG, 'meta': {'errors': [{'error': 'Timeout'}]}, 'leagues': {'epl': {'name': 'Premier League', 'matches': [match]}}}
        with tempfile.TemporaryDirectory() as directory, patch.object(send_email, 'OUT', Path(directory)), patch.object(send_email, 'dataset', return_value=data), patch.object(sys, 'argv', ['send_email', '--preview-only']), patch.object(send_email.smtplib, 'SMTP') as smtp:
            send_email.main()
            smtp.assert_not_called()
            html = (Path(directory) / 'email_preview.html').read_text()
            self.assertIn('&lt;script&gt;', html)
            self.assertNotIn('<script>bad', html)
            self.assertIn('20:00', html)
            self.assertIn('Données partielles', html)

    def test_missing_resources_render_dashboard(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(product, 'RAW', Path(directory)), patch.object(generate_dashboard, 'OUT', Path(directory)):
            generate_dashboard.main()
            data = json.loads((Path(directory) / 'data.json').read_text())
            self.assertEqual(len(data['leagues']), 5)
            self.assertTrue((Path(directory) / 'index.html').exists())


if __name__ == '__main__':
    unittest.main()
