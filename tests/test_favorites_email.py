import copy
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'report'))
import product
import send_email


class FavoritesEmailTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.fromisoformat('2026-11-25T10:00:00+01:00')
        self.match = {'id': 1, 'utcDate': '2026-11-25T20:00:00Z', 'status': 'TIMED'}
        self.record = {
            'match_id': 1, 'league': 'ucl', 'kickoff': self.match['utcDate'],
            'issued_at': '2026-11-24T08:00:00Z', 'pick': '1',
            'outcome': {'1': .70, 'N': .20, '2': .10},
            'home': {'name': '<Home>'}, 'away': {'name': 'Away'},
        }
        self.data = {
            'today': '2026-11-25', 'config': product.CONFIG,
            'predictions': {'records': [self.record]},
            'leagues': {'ucl': {'name': 'Champions League', 'matches': [self.match],
                                'freshness': {'matches': '2026-11-25T08:00:00Z'}}},
        }

    def test_threshold_and_escaping(self):
        html, plain = product.favorites_email_content(self.data, self.now)
        self.assertIn('Victoire &lt;Home&gt; · 70,0 %', html)
        self.assertIn('21:00', plain)
        self.record['outcome']['1'] = .69999
        self.assertIn('Aucun favori éligible', product.favorites_email_content(self.data, self.now)[1])

    def test_away_winner_and_ineligible_forecasts(self):
        self.record['pick'] = '2'
        self.record['outcome'] = {'1': .1, 'N': .15, '2': .75}
        self.assertIn('Victoire Away · 75,0 %', product.favorites_email_content(self.data, self.now)[1])
        for status in ('IN_PLAY', 'FINISHED', 'POSTPONED', 'CANCELLED'):
            with self.subTest(status=status):
                self.match['status'] = status
                self.assertIn('Aucun favori éligible', product.favorites_email_content(self.data, self.now)[1])
        self.match['status'] = 'TIMED'
        for key, value in [('pick', 'N'), ('kickoff', '2026-11-25T21:00:00Z'),
                           ('evaluation', {'status': 'excluded'}),
                           ('issued_at', '2026-11-26T08:00:00Z')]:
            data = copy.deepcopy(self.data)
            data['predictions']['records'][0][key] = value
            with self.subTest(key=key):
                self.assertIn('Aucun favori éligible', product.favorites_email_content(data, self.now)[1])

    def test_stale_data_europa_league_and_paris_date(self):
        self.data['leagues']['ucl']['freshness']['matches'] = '2026-11-23T08:00:00Z'
        self.assertIn('Aucun favori éligible', product.favorites_email_content(self.data, self.now)[1])
        self.data['leagues']['ucl']['freshness']['matches'] = '2026-11-25T08:00:00Z'
        self.match['utcDate'] = self.record['kickoff'] = '2026-11-25T23:30:00Z'
        self.assertIn('Aucun favori éligible', product.favorites_email_content(self.data, self.now)[1])
        self.match['utcDate'] = self.record['kickoff'] = '2026-11-25T20:00:00Z'
        self.data['leagues']['uel'] = self.data['leagues'].pop('ucl')
        self.record['league'] = 'uel'
        self.assertIn('Aucun favori éligible', product.favorites_email_content(self.data, self.now)[1])

    def test_preview_and_smtp_use_separate_messages(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(send_email, 'OUT', Path(directory)), \
                patch.object(send_email, 'dataset', return_value=self.data), \
                patch.object(send_email, 'email_content', return_value=('<p>Habituel</p>', 'Habituel')), \
                patch.object(send_email, 'favorites_email_content', return_value=('<p>Favoris</p>', 'Favoris')), \
                patch.object(send_email.smtplib, 'SMTP') as smtp, \
                patch.dict(os.environ, {'SMTP_HOST': 'example.test', 'SMTP_USER': 'sender@example.test',
                                        'SMTP_PASS': 'test', 'EMAIL_TO': 'recipient@example.test'}, clear=True):
            for flags in ([], ['--favorites-only']):
                with patch.object(sys, 'argv', ['send_email', '--preview-only', *flags]):
                    send_email.main()
            smtp.assert_not_called()
            self.assertEqual((Path(directory) / 'email_preview.html').read_text(), '<p>Habituel</p>')
            self.assertEqual((Path(directory) / 'email_favorites_preview.html').read_text(), '<p>Favoris</p>')
            for flags in ([], ['--favorites-only']):
                with patch.object(sys, 'argv', ['send_email', *flags]):
                    send_email.main()
            sent = smtp.return_value.__enter__.return_value.send_message.call_args_list
            self.assertEqual(len(sent), 2)
            self.assertIn('résultats et matchs du jour', str(sent[0].args[0]['Subject']))
            self.assertIn('Favoris ≥ 70 %', str(sent[1].args[0]['Subject']))
            self.assertEqual(sent[0].kwargs['to_addrs'], sent[1].kwargs['to_addrs'])
            self.assertEqual(sent[1].args[0].get_body(preferencelist=('plain',)).get_content(), 'Favoris\n')


if __name__ == '__main__':
    unittest.main()
