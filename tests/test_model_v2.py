import copy
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'report'))
from model_v2 import clean, examples, GoalModel, goal_matrix, distribution, calibrate_outcome, calibrate_goals, fit_predict, outcome_metrics
from predictions import update

NOW = datetime(2026, 11, 3, 8, tzinfo=timezone.utc)

def fixture(mid, date, h=1, a=2, score=(2,1), code='PL'):
    return {'id': mid, 'utcDate': date.isoformat(), 'status': 'FINISHED',
            'homeTeam': {'id':h,'name':str(h)}, 'awayTeam': {'id':a,'name':str(a)},
            'competition': {'code':code}, '_code':code,
            'score': {'duration':'REGULAR','fullTime':{'home':score[0],'away':score[1]}}}

def history():
    return [fixture(i, NOW-timedelta(days=200-i), h=i%6+1, a=(i+2)%6+1,
                    score=((i*7)%4,(i*3)%3), code='PL' if i%2 else 'CL') for i in range(90)]

class V2Tests(unittest.TestCase):
    def test_clean_deduplicates_excludes_invalid_extra_time_and_future(self):
        m=history()[0]
        extra=copy.deepcopy(m);extra['id']=400;extra['score']['duration']='EXTRA_TIME'
        future=fixture(401,NOW+timedelta(days=2))
        self.assertEqual(len(clean([m,m,extra,future], NOW)),1)

    def test_no_same_day_or_future_result_leakage(self):
        d=NOW-timedelta(days=10)
        first=fixture(1,d)
        second=fixture(2,d+timedelta(hours=2))
        later=fixture(3,d+timedelta(days=1))
        a,_=examples([first,second,later])
        changed=copy.deepcopy(first);changed['score']['fullTime']={'home':0,'away':5}
        b,_=examples([changed,second,later])
        self.assertEqual(a[1]['x'],b[1]['x'])
        self.assertNotEqual(a[2]['x'],b[2]['x'])
        self.assertEqual(a[0]['samples'][0]['sample'],0)

    def test_same_team_combines_domestic_and_european_results(self):
        rows,_=examples([fixture(1,NOW-timedelta(days=4),code='PL'),
                         fixture(2,NOW-timedelta(days=2),code='CL')])
        self.assertEqual(rows[1]['samples'][0]['sample'],1)

    def test_goal_distribution_coherent_after_calibration(self):
        g=goal_matrix(2.1,.8,-.06)
        self.assertAlmostEqual(g.sum(),1)
        self.assertTrue(np.all(g>=0))
        c=calibrate_goals(np.array([g]),1.15)[0]
        p,o=distribution(c)
        self.assertAlmostEqual(p.sum(),1)
        self.assertGreaterEqual(o[0],o[1])
        self.assertGreaterEqual(o[1],o[2])
        self.assertAlmostEqual(calibrate_outcome(np.array([[.6,.2,.2]]),1).sum(),1)

    def test_dc_fit_produces_valid_probabilities_for_unseen_teams(self):
        rows,_=examples(history())
        model=GoalModel(True).fit(rows)
        unseen=copy.deepcopy(rows[-1]);unseen['match']['homeTeam']['id']=999
        grids=model.predict([unseen])
        self.assertTrue(model.fit_diagnostics['converged'])
        self.assertAlmostEqual(grids[0].sum(),1)
        self.assertTrue(np.isfinite(grids).all())

    def test_logistic_probabilities_match_label_order(self):
        rows,_=examples([fixture(i,NOW-timedelta(days=100-i),score=((i%3),1)) for i in range(60)])
        p=fit_predict('elo_logistic',rows[:50],rows[50:])
        self.assertEqual(p.shape,(10,3))
        self.assertTrue(np.allclose(p.sum(axis=1),1))
        self.assertTrue(np.isfinite(outcome_metrics(p,rows[50:])['log_loss']))

    def test_v2_issues_new_revision_without_overwriting_legacy_then_freezes(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            m=fixture(1,NOW+timedelta(days=1));m['status']='TIMED'
            league={'test':{'matches':[m],'freshness':{'matches':NOW.isoformat()}}}
            old=update(root,league,NOW)['records'][0]
            candidate={'model':'v2-elo-dc-catboost-1','outcome':{'1':.2,'N':.3,'2':.5},
                       'over':{'1.5':.8,'2.5':.5,'3.5':.3},'btts':.6,'expected_total':2.7,
                       'baseline':{'outcome':{'1':.3,'N':.3,'2':.4}},
                       'features':{k:{'sample':20,'recent_played':5,'recent_points':9,'elo':1600} for k in ('home','away')}}
            dest=root/'data/predictions/serving.json'
            dest.write_text(json.dumps({'generated_at':NOW.isoformat(),'predictions':{'1':candidate}}))
            result=update(root,league,NOW+timedelta(hours=1))
            self.assertEqual(result['records'][0]['outcome'],candidate['outcome'])
            self.assertEqual(result['archived_records'][0]['outcome'],old['outcome'])
            frozen=copy.deepcopy(result['records'][0])
            result2=update(root,league,NOW+timedelta(hours=2))
            self.assertEqual(frozen,result2['records'][0])
            self.assertEqual(len(result2['archived_records']),1)
            m['status']='FINISHED'
            m['score']['fullTime']={'home':0,'away':1}
            settled=update(root,league,NOW+timedelta(days=2))
            self.assertTrue(settled['records'][0]['evaluation']['baseline_correct'])
            self.assertEqual(settled['by_model']['v2-elo-dc-catboost-1']['count'],1)
            self.assertEqual(settled['by_model']['poisson-v1']['count'],1)

if __name__=='__main__':
    unittest.main()
