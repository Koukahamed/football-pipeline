import copy
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'report'))
from predictions import probabilities, forecast, update, summary, email_section

NOW = datetime(2026, 11, 3, 8, tzinfo=timezone.utc)


def match(mid=1, days=1, status='TIMED', h=None, a=None):
    return dict(id=mid, utcDate=(NOW + timedelta(days=days)).isoformat(), status=status, homeTeam={'id': 1, 'name': '<Home>'}, awayTeam={'id': 2, 'name': 'Away'}, score={'duration': 'REGULAR', 'fullTime': {'home': h, 'away': a}})


def league(matches, fresh=NOW):
    return {'test': {'matches': matches, 'freshness': {'matches': fresh.isoformat()}}}


class PredictionsTests(unittest.TestCase):
    def test_distribution_and_goal_thresholds(self):
        o, over, btts = probabilities(1.8, 1.2)
        self.assertAlmostEqual(sum(o.values()), 1)
        self.assertGreater(o['1'], o['2'])
        self.assertGreater(over['1.5'], over['2.5'])
        self.assertGreater(over['2.5'], over['3.5'])
        self.assertTrue(0 < btts < 1)
        self.assertAlmostEqual(over['2.5'], 1 - __import__('math').exp(-3) * (1 + 3 + 9/2))

    def test_future_scores_do_not_affect_forecast(self):
        target = match()
        base = forecast(target, [], [target], NOW)
        future = match(2, 2, 'FINISHED', 20, 0)
        result = forecast(target, [future], [target, future], NOW)
        self.assertEqual(base['outcome'], result['outcome'])

    def test_freeze_settle_and_no_retroactive_creation(self):
        with tempfile.TemporaryDirectory() as root:
            target = match()
            first = update(root, league([target, match(99, -1, 'FINISHED', 2, 0)]), NOW)
            self.assertEqual(len(first['records']), 1)
            original = copy.deepcopy(first['records'][0])
            second = update(root, league([target, match(33, -.1, 'FINISHED', 9, 0)]), NOW + timedelta(hours=1))
            self.assertEqual(original, second['records'][0])
            done = copy.deepcopy(target); done['status'] = 'FINISHED'; done['score']['fullTime'] = {'home': 2, 'away': 1}
            result = update(root, league([done]), NOW + timedelta(days=2))
            r = result['records'][0]
            self.assertEqual(r['evaluation']['total'], 3)
            self.assertEqual(r['evaluation']['actual'], '1')
            self.assertTrue(r['evaluation']['over']['2.5'])
            self.assertFalse(r['evaluation']['over']['3.5'])
            self.assertEqual(summary(result['records'])['count'], 1)
            self.assertEqual(r['issued_at'], original['issued_at'])
            self.assertEqual(r['outcome'], original['outcome'])

    def test_stale_data_and_started_matches_not_forecast(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertFalse(update(root, league([match()], NOW-timedelta(days=2)), NOW)['records'])
            self.assertFalse(update(root, league([match(days=0)]), NOW)['records'])
            self.assertFalse(update(root, league([match(status='IN_PLAY')]), NOW)['records'])

    def test_postponed_and_extra_time_excluded(self):
        for status, duration in [('POSTPONED', 'REGULAR'), ('FINISHED', 'EXTRA_TIME')]:
            with tempfile.TemporaryDirectory() as root:
                m=match(); update(root, league([m]), NOW)
                m['status']=status; m['score']={'duration':duration,'fullTime':{'home':2,'away':1}}
                result=update(root, league([m]), NOW+timedelta(days=2))
                self.assertEqual(result['summary']['count'], 0)

    def test_email_uses_frozen_record_and_escapes_names(self):
        with tempfile.TemporaryDirectory() as root:
            p=update(root, league([match()]), NOW)
            html, lines=email_section(p, '2026-11-04', timezone.utc)
            self.assertIn('&lt;Home&gt;', html)
            self.assertNotIn('<Home>', html)
            self.assertIn('1.5', str(p['records'][0]['over']))
            self.assertIn('Bilan veille', html)

if __name__ == '__main__':
    unittest.main()
