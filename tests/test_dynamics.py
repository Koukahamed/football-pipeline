import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'report'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ingestion'))
from dynamics import team_dynamics, ranking_history
import fetch_data

NOW = datetime(2026, 10, 23, 16, tzinfo=timezone.utc)


def match(mid, day, home=1, away=2, goals=(2, 0), season=2026, status='FINISHED'):
    return {'id': mid, 'utcDate': f'2026-10-{day:02d}T12:00:00Z', 'season': {'id': season},
            'status': status, 'homeTeam': {'id': home, 'name': f'Team {home}'},
            'awayTeam': {'id': away, 'name': f'Team {away}'}, 'score': {'fullTime': dict(zip(('home', 'away'), goals))}}


def standings(day, position, season=2026, stage='REGULAR_SEASON'):
    return {'season': {'id': season}, '_fetched_at': f'2026-10-{day:02d}T09:00:00+02:00',
            'standings': [{'type': 'TOTAL', 'stage': stage, 'table': [
                {'team': {'id': 1, 'name': 'Team 1'}, 'position': position, 'points': 10, 'playedGames': 5}]}]}


class DynamicsTests(unittest.TestCase):
    def dynamics(self, matches):
        with tempfile.TemporaryDirectory() as folder:
            return team_dynamics({'matches': matches, '_scope': 'current_season'}, standings(23, 2), Path(folder), 'epl', NOW)

    def test_last_five_deduplicated_chronological_and_away_perspective(self):
        matches = [match(i, i, goals=(1, 1)) for i in range(1, 7)]
        matches += [match(6, 6, home=2, away=1, goals=(0, 3))]
        data = self.dynamics(list(reversed(matches[:-1])) + matches[-1:])
        team = next(t for t in data['teams'] if t['team']['id'] == 1)
        self.assertEqual([m['match_id'] for m in team['form']], [2, 3, 4, 5, 6])
        self.assertEqual([m['result'] for m in team['form']], ['D', 'D', 'D', 'D', 'W'])
        self.assertEqual(team['points'], 7)
        self.assertEqual((team['goals_for'], team['goals_against']), (7, 4))
        self.assertEqual(team['form'][-1]['venue'], 'away')

    def test_ignore_other_seasons_unfinished_missing_scores_and_future(self):
        data = self.dynamics([match(1, 1, season=2025), match(2, 2, status='IN_PLAY'),
                              match(3, 3, goals=(None, 0)), match(4, 24), match(5, 5, goals=(0, 2))])
        team = next(t for t in data['teams'] if t['team']['id'] == 1)
        self.assertEqual(team['played'], 1)
        self.assertEqual(team['form'][0]['result'], 'L')
        self.assertEqual(team['points'], 0)

    def test_empty_data_has_no_invented_results(self):
        data = self.dynamics([])
        self.assertEqual(data['teams'][0]['played'], 0)
        self.assertEqual(data['teams'][0]['form'], [])

    def test_rankings_only_same_season_phase_and_actual_observation_dates(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for day, payload in [(1, standings(1, 7, season=2025)), (2, standings(2, 6)),
                                 (4, standings(4, 4)), (5, standings(5, 3, stage='GROUP_STAGE'))]:
                (root / f'standings_epl_2026-10-{day:02d}.json').write_text(json.dumps(payload))
            result = ranking_history(root, 'epl', standings(23, 2))['1']
            self.assertEqual([p['date'] for p in result], ['2026-10-02', '2026-10-04', '2026-10-23'])
            self.assertEqual([p['position'] for p in result], [6, 4, 2])
            # A rendering with stale current standings must not create today's observation.
            self.assertEqual(ranking_history(root, 'epl', standings(4, 4))['1'][-1]['date'], '2026-10-04')

    def test_successful_season_fetch_marked_and_preserved_on_failure(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(fetch_data, 'RAW', Path(folder)):
            client = Mock()
            client.get.return_value = {'matches': [match(1, 1)]}
            result = fetch_data.retrieve(client, 'competitions/PL/matches', 'matches_epl.json', NOW, [])
            self.assertEqual(result['_scope'], 'current_season')
            client.get.side_effect = fetch_data.requests.Timeout()
            errors = []
            fallback = fetch_data.retrieve(client, 'competitions/PL/matches', 'matches_epl.json', NOW, errors)
            self.assertEqual(fallback, result)
            self.assertEqual(len(errors), 1)

    def test_extraction_archives_season_without_deleting_old_snapshots(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            history = root / 'history'
            history.mkdir()
            old = history / 'standings_epl_2025-01-01.json'
            old.write_text('{}')
            client = Mock()
            client.get.side_effect = [{'matches': [match(1, 1)]}, standings(23, 2), {'scorers': []}]
            with patch.object(fetch_data, 'RAW', root / 'raw'), patch.object(fetch_data, 'HISTORY', history), \
                    patch.object(fetch_data, 'CONFIG', {'leagues': {'epl': {'code': 'PL'}}}), \
                    patch.object(fetch_data, 'Client', return_value=client), \
                    patch.dict(fetch_data.os.environ, {'FOOTBALL_API_KEY': 'test'}):
                fetch_data.main()
            self.assertTrue(old.exists())
            self.assertTrue((history / 'matches_epl_2026.json').exists())
            self.assertEqual(client.get.call_args_list[0].args, ('competitions/PL/matches', None))


if __name__ == '__main__':
    unittest.main()
