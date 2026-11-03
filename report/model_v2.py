"""Chronological model comparison and calibration; production predictions are separate from backtests."""
import hashlib
import json
import math
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
from scipy.optimize import minimize, minimize_scalar
from scipy.special import gammaln, softmax
from sklearn.linear_model import LogisticRegression
from catboost import CatBoostClassifier
from predictions import goals, instant

ROOT = Path(__file__).resolve().parents[1]
UTC = timezone.utc
VERSION = 'v2-elo-dc-catboost-1'
LABELS = ('1', 'N', '2')


def clean(matches, cutoff):
    """Latest response wins by id. Same-day outcomes are unavailable to historical features."""
    by_id = {}
    for m in matches:
        if (m.get('id') is not None and m.get('utcDate') and m.get('homeTeam', {}).get('id') is not None
                and m.get('awayTeam', {}).get('id') is not None):
            by_id[str(m['id'])] = m
    result = []
    for m in by_id.values():
        s = goals(m)
        if s is None or min(s) < 0 or instant(m['utcDate']) >= cutoff:
            continue
        result.append(dict(m, _code=m.get('_code') or m.get('competition', {}).get('code', 'UNKNOWN')))
    return sorted(result, key=lambda m: (instant(m['utcDate']), str(m['id'])))


class Ratings:
    def __init__(self, k=24, home=60):
        self.k, self.home = k, home
        self.ratings = defaultdict(lambda: 1500.)
        self.recent = defaultdict(list)
        self.year = None

    def season(self, date):
        year = date.year if date.month >= 7 else date.year - 1
        if self.year is not None and year > self.year:
            self.ratings = defaultdict(lambda: 1500., {t: 1500 + .85 * (v - 1500) for t, v in self.ratings.items()})
        self.year = year

    def features(self, m):
        day = instant(m['utcDate']).date()
        self.season(day)
        h, a = m['homeTeam']['id'], m['awayTeam']['id']
        rh, ra = self.ratings[h], self.ratings[a]
        result = [(rh - ra) / 400]
        samples = []
        for team in (h, a):
            rows = self.recent[team][-10:]
            five = rows[-5:]
            gf = np.mean([r[1] for r in rows]) if rows else 1.3
            ga = np.mean([r[2] for r in rows]) if rows else 1.3
            points = sum(3 if r[1] > r[2] else 1 if r[1] == r[2] else 0 for r in five)
            rest = min(14, (day - rows[-1][0]).days) if rows else 7
            result.extend([gf, ga, points / max(1, 3 * len(five)), rest / 7, min(30, len(self.recent[team])) / 30])
            samples.append({'sample': len(self.recent[team]), 'recent_played': len(five),
                            'recent_points': points, 'rest_days': rest, 'elo': round(self.ratings[team], 1)})
        # Three-day congestion count from completed fixtures only; no historical schedule reconstruction.
        for team in (h, a):
            result.append(sum(0 < (day - row[0]).days <= 7 for row in self.recent[team]) / 3)
        return result, samples

    def observe(self, m):
        h, a = m['homeTeam']['id'], m['awayTeam']['id']
        gh, ga = goals(m)
        expected = 1 / (1 + 10 ** (-(self.ratings[h] + self.home - self.ratings[a]) / 400))
        actual = 1 if gh > ga else .5 if gh == ga else 0
        change = self.k * (actual - expected)
        self.ratings[h] += change
        self.ratings[a] -= change
        day = instant(m['utcDate']).date()
        self.recent[h].append((day, gh, ga))
        self.recent[a].append((day, ga, gh))


def examples(matches, k=24, home=60):
    state = Ratings(k, home)
    groups = defaultdict(list)
    for m in matches:
        groups[instant(m['utcDate']).date()].append(m)
    rows = []
    for day in sorted(groups):
        batch = groups[day]
        # Do not update any result until every feature on this day has been computed.
        for m in batch:
            x, samples = state.features(m)
            gh, ga = goals(m)
            rows.append({'match': m, 'x': x, 'samples': samples,
                         'y': 0 if gh > ga else 2 if gh < ga else 1, 'score': (gh, ga), 'day': str(day)})
        for m in batch:
            state.observe(m)
    return rows, state


def goal_matrix(lam, mu, rho=0):
    k = np.arange(21)
    ph = np.exp(-lam + k * math.log(lam) - gammaln(k + 1))
    pa = np.exp(-mu + k * math.log(mu) - gammaln(k + 1))
    p = ph[:, None] * pa[None, :]
    p[0, 0] *= 1 - lam * mu * rho
    p[0, 1] *= 1 + lam * rho
    p[1, 0] *= 1 + mu * rho
    p[1, 1] *= 1 - rho
    p = np.maximum(p, 0)
    return p / p.sum()


TOTALS = np.add.outer(np.arange(21), np.arange(21))
OUTCOME_MASKS = (np.greater.outer(np.arange(21), np.arange(21)),
                 np.eye(21, dtype=bool),
                 np.less.outer(np.arange(21), np.arange(21)))


def distribution(p):
    outcome = np.array([p[mask].sum() for mask in OUTCOME_MASKS])
    over = np.array([p[TOTALS > k].sum() for k in (1.5, 2.5, 3.5)])
    return outcome, over


class GoalModel:
    """Joint weighted Dixon-Coles likelihood, L2 shrinkage, optional Elo covariate."""
    def __init__(self, use_elo=False, decay=365, penalty=.002):
        self.use_elo, self.decay, self.penalty = use_elo, decay, penalty

    def fit(self, rows):
        self.teams = {t: i for i, t in enumerate(sorted({m['match'][s]['id'] for m in rows for s in ('homeTeam', 'awayTeam')}))}
        self.comps = {c: i for i, c in enumerate(sorted({r['match']['_code'] for r in rows}))}
        n, nc = len(self.teams), len(self.comps)
        self.n, self.nc = n, nc
        hi = np.array([self.teams[r['match']['homeTeam']['id']] for r in rows])
        ai = np.array([self.teams[r['match']['awayTeam']['id']] for r in rows])
        ci = np.array([self.comps[r['match']['_code']] for r in rows])
        y = np.array([r['score'][0] for r in rows])
        z = np.array([r['score'][1] for r in rows])
        elo = np.array([r['x'][0] for r in rows])
        rest = np.array([r['x'][4] - r['x'][9] for r in rows])
        last = max(instant(r['match']['utcDate']) for r in rows)
        age = np.array([(last - instant(r['match']['utcDate'])).days for r in rows])
        weights = np.exp(-np.log(2) * age / self.decay)
        weights /= weights.sum()
        # intercept, home, competition, team attack, team weakness, Elo, rest, rho
        a0, d0 = 2 + nc, 2 + nc + n
        ie, ir, ip = d0 + n, d0 + n + 1, d0 + n + 2

        def objective(b):
            common = b[0] + b[2 + ci]
            logh = common + b[1] + b[a0 + hi] + b[d0 + ai] + b[ir] * rest
            loga = common + b[a0 + ai] + b[d0 + hi] - b[ir] * rest
            if self.use_elo:
                logh = logh + b[ie] * elo
                loga = loga - b[ie] * elo
            lh, la = np.clip(logh, -2.3, 1.79), np.clip(loga, -2.3, 1.79)
            lam, mu = np.exp(lh), np.exp(la)
            rho = b[ip]
            tau, th, ta, tr = np.ones(len(rows)), np.zeros(len(rows)), np.zeros(len(rows)), np.zeros(len(rows))
            for mask, tv, dh, da, dr in [
                ((y == 0) & (z == 0), 1 - lam * mu * rho, -mu * rho, -lam * rho, -lam * mu),
                ((y == 0) & (z == 1), 1 + lam * rho, np.full(len(rows), rho), np.zeros(len(rows)), lam),
                ((y == 1) & (z == 0), 1 + mu * rho, np.zeros(len(rows)), np.full(len(rows), rho), mu),
                ((y == 1) & (z == 1), np.full(len(rows), 1 - rho), np.zeros(len(rows)), np.zeros(len(rows)), -np.ones(len(rows)))]:
                tau[mask], th[mask], ta[mask], tr[mask] = tv[mask], dh[mask], da[mask], dr[mask]
            tau = np.maximum(tau, 1e-8)
            loss = np.sum(weights * (lam - y * lh + mu - z * la - np.log(tau)))
            gh = weights * (lam - y - th * lam / tau) * ((logh >= -2.3) & (logh <= 1.79))
            ga = weights * (mu - z - ta * mu / tau) * ((loga >= -2.3) & (loga <= 1.79))
            g = np.zeros(len(b))
            g[0], g[1] = (gh + ga).sum(), gh.sum()
            np.add.at(g, 2 + ci, gh + ga)
            np.add.at(g, a0 + hi, gh)
            np.add.at(g, a0 + ai, ga)
            np.add.at(g, d0 + ai, gh)
            np.add.at(g, d0 + hi, ga)
            g[ie] = np.sum((gh - ga) * elo) if self.use_elo else 0
            g[ir] = np.sum((gh - ga) * rest)
            g[ip] = -np.sum(weights * tr / tau)
            regular = np.ones(len(b)) * self.penalty
            regular[:2], regular[ip] = 0, 0
            loss += np.sum(regular * b * b)
            g += 2 * regular * b
            return loss, g

        start = np.zeros(ip + 1)
        start[0], start[1], start[ip] = math.log(1.2), .2, -.03
        bounds = [(-2, 2)] * len(start)
        bounds[ip] = (-.1, .025)
        if not self.use_elo:
            bounds[ie] = (0, 0)
        result = minimize(objective, start, jac=True, method='L-BFGS-B', bounds=bounds,
                          options={'maxiter': 350, 'ftol': 1e-9})
        if not np.isfinite(result.fun) or not result.success:
            raise RuntimeError('Dixon-Coles optimizer did not converge: ' + result.message)
        self.b = result.x
        self.fit_diagnostics = {'converged': bool(result.success), 'iterations': int(result.nit)}
        return self

    def predict(self, rows):
        b, n, nc = self.b, self.n, self.nc
        a0, d0 = 2 + nc, 2 + nc + n
        ie, ir, ip = d0 + n, d0 + n + 1, d0 + n + 2
        output = []
        for r in rows:
            h, a = r['match']['homeTeam']['id'], r['match']['awayTeam']['id']
            def team(t, offset):
                return b[offset + self.teams[t]] if t in self.teams else 0.
            c = self.comps.get(r['match']['_code'])
            base = b[0] + (b[2+c] if c is not None else 0)
            edge = (b[ie] * r['x'][0] if self.use_elo else 0) + b[ir] * (r['x'][4] - r['x'][9])
            lh = base + b[1] + team(h, a0) + team(a, d0) + edge
            la = base + team(a, a0) + team(h, d0) - edge
            output.append(goal_matrix(float(np.exp(np.clip(lh, -2.3, 1.79))),
                                      float(np.exp(np.clip(la, -2.3, 1.79))), b[ip]))
        return np.array(output)


def fit_predict(name, train, target):
    if not target:
        return []
    if name in ('dc', 'dc_elo'):
        return GoalModel(use_elo=name == 'dc_elo').fit(train).predict(target)
    x, y = np.array([r['x'] for r in train]), np.array([r['y'] for r in train])
    xt = np.array([r['x'] for r in target])
    if name == 'elo_logistic':
        # Only Elo difference: a deliberately small reference.
        model = LogisticRegression(C=1., max_iter=1000).fit(x[:, :1], y)
        p = model.predict_proba(xt[:, :1])
    elif name == 'catboost':
        model = CatBoostClassifier(iterations=250, depth=4, learning_rate=.04, l2_leaf_reg=10,
                                   loss_function='MultiClass', random_seed=42, thread_count=2,
                                   verbose=False, allow_writing_files=False)
        model.fit(np.column_stack([x, [r['match']['_code'] for r in train]]).tolist(), y, cat_features=[len(x[0])])
        p = model.predict_proba(np.column_stack([xt, [r['match']['_code'] for r in target]]).tolist())
    else:
        raise ValueError(name)
    result = np.zeros((len(target), 3))
    result[:, np.asarray(model.classes_, dtype=int)] = p
    return result


def rolling_predict(name, rows, start, end):
    result, targets = [], []
    eligible = [r for r in rows if start <= r['day'] < end]
    months = sorted({r['day'][:7] for r in eligible})
    for month in months:
        train = [r for r in rows if r['day'] < month + '-01']
        target = [r for r in eligible if r['day'].startswith(month)]
        if len(train) < 300:
            raise ValueError('Insufficient training history')
        result.extend(fit_predict(name, train, target))
        targets.extend(target)
    return np.asarray(result), targets


def outcome_metrics(p, rows):
    y = np.array([r['y'] for r in rows])
    p = np.clip(p, 1e-9, 1)
    onehot = np.eye(3)[y]
    return {'count': len(y), 'log_loss': float(-np.log(p[np.arange(len(y)), y]).mean()),
            'brier': float(np.square(p - onehot).sum(axis=1).mean()),
            'accuracy': float((p.argmax(axis=1) == y).mean())}


def goal_metrics(grids, rows):
    over = np.array([distribution(g)[1] for g in grids])
    total = np.array([sum(r['score']) for r in rows])
    truth = total[:, None] > np.array([1.5, 2.5, 3.5])
    return {'count': len(rows), 'mean_brier': float(np.square(over - truth).mean()),
            'thresholds': {str(k): {'brier': float(np.square(over[:, i] - truth[:, i]).mean()),
                                   'accuracy': float(((over[:, i] >= .5) == truth[:, i]).mean())}
                           for i, k in enumerate([1.5, 2.5, 3.5])}}


def calibrate_outcome(p, t):
    return softmax(np.log(np.clip(p, 1e-12, 1)) / t, axis=-1)


def calibrate_goals(grids, t):
    g = np.power(np.maximum(grids, 1e-15), 1/t)
    return g / g.sum(axis=(-1, -2), keepdims=True)


def reliability(p, rows):
    actual = np.eye(3)[[r['y'] for r in rows]]
    bins = []
    for lo in np.arange(0, 1, .1):
        mask = (p >= lo) & (p < lo + .1)
        if mask.any():
            bins.append({'from': round(float(lo), 1), 'count': int(mask.sum()),
                         'predicted': float(p[mask].mean()), 'observed': float(actual[mask].mean())})
    return bins


def load_matches(root):
    matches = []
    for pattern in ('data/training/*.json', 'data/history/matches_*.json', 'data/context/*.json', 'data/raw/matches_*.json'):
        for path in sorted(Path(root).glob(pattern)):
            data = json.loads(path.read_text())
            for m in data.get('matches', []):
                matches.append(dict(m, _code=m.get('competition', {}).get('code') or data.get('_competition', 'UNKNOWN')))
    return matches


def backtest(matches, now):
    year = now.year if now.month >= 7 else now.year - 1
    start, calibration_start, test_start, test_end = f'{year-2}-08-01', f'{year-1}-08-01', f'{year}-01-01', f'{year}-07-01'
    # Full 2024/25 selects models; first half 2025/26 calibrates; second half is untouched final test.
    rows, _ = examples(matches)
    ranges = {'validation': (start, calibration_start), 'calibration': (calibration_start, test_start), 'test': (test_start, test_end)}
    predictions = {period: {} for period in ranges}
    period_rows = {}
    for name in ('elo_logistic', 'dc', 'dc_elo', 'catboost'):
        for period, (lo, hi) in ranges.items():
            p, targets = rolling_predict(name, rows, lo, hi)
            if not len(targets):
                raise ValueError('Empty evaluation period: ' + period)
            period_rows[period] = targets
            predictions[period][name] = p
    for period in ranges:
        ps = predictions[period]
        ps['goal_ensemble'] = (ps['dc'] + ps['dc_elo']) / 2
        for name in ('dc', 'dc_elo', 'goal_ensemble'):
            ps[name + '_outcome'] = np.array([distribution(g)[0] for g in ps[name]])
        ps['ensemble'] = (ps['elo_logistic'] + ps['catboost'] + ps['dc_elo_outcome']) / 3
        # Train-only fixed frequencies; recomputed separately for each rolling month.
        fixed, goal_base = [], []
        for row in period_rows[period]:
            train = [r for r in rows if r['day'] < row['day'][:7] + '-01']
            counts = np.bincount([r['y'] for r in train], minlength=3) + 1
            fixed.append(counts/counts.sum())
            score = np.mean([r['score'] for r in train], axis=0)
            goal_base.append(goal_matrix(*score))
        ps['frequency'] = np.array(fixed)
        ps['poisson_reference'] = np.array(goal_base)
    outcome_names = ('frequency', 'elo_logistic', 'dc_outcome', 'dc_elo_outcome', 'catboost', 'ensemble')
    goal_names = ('poisson_reference', 'dc', 'dc_elo', 'goal_ensemble')
    validation = predictions['validation']
    outcome_scores = {n: outcome_metrics(validation[n], period_rows['validation']) for n in outcome_names}
    goal_scores = {n: goal_metrics(validation[n], period_rows['validation']) for n in goal_names}
    winner_o = min(outcome_scores, key=lambda n: outcome_scores[n]['log_loss'])
    winner_g = min(goal_scores, key=lambda n: goal_scores[n]['mean_brier'])
    cp, cr = predictions['calibration'], period_rows['calibration']
    to = float(minimize_scalar(lambda t: outcome_metrics(calibrate_outcome(cp[winner_o], t), cr)['log_loss'],
                               bounds=(.65, 2.5), method='bounded').x)
    tg = float(minimize_scalar(lambda t: goal_metrics(calibrate_goals(cp[winner_g], t), cr)['mean_brier'],
                               bounds=(.8, 1.3), method='bounded').x)
    # Keep identity if calibration does not improve its own independent calibration segment.
    if outcome_metrics(calibrate_outcome(cp[winner_o], to), cr)['log_loss'] >= outcome_metrics(cp[winner_o], cr)['log_loss']:
        to = 1.
    if goal_metrics(calibrate_goals(cp[winner_g], tg), cr)['mean_brier'] >= goal_metrics(cp[winner_g], cr)['mean_brier']:
        tg = 1.
    tp, tr = predictions['test'], period_rows['test']
    out = calibrate_outcome(tp[winner_o], to)
    grid = calibrate_goals(tp[winner_g], tg)
    final_o, final_g = outcome_metrics(out, tr), goal_metrics(grid, tr)
    reference = outcome_metrics(tp['elo_logistic'], tr)
    fixed_reference = outcome_metrics(tp['frequency'], tr)
    goal_ref = goal_metrics(tp['poisson_reference'], tr)
    # Predeclared deployment gate, not another tuning pass.
    promote_o = final_o['log_loss'] <= min(reference['log_loss'], fixed_reference['log_loss']) and final_o['brier'] <= reference['brier']
    promote_g = final_g['mean_brier'] <= goal_ref['mean_brier']
    by_comp = {}
    for code in sorted({r['match']['_code'] for r in tr}):
        idx = [i for i, r in enumerate(tr) if r['match']['_code'] == code]
        rr = [tr[i] for i in idx]
        by_comp[code] = {'outcome': outcome_metrics(out[idx], rr), 'goals': goal_metrics(grid[idx], rr)}
    return {'version': VERSION, 'generated_at': now.isoformat(), 'ranges': ranges,
            'selection': {'outcome': winner_o, 'goals': winner_g},
            'serving': {'outcome': winner_o if promote_o else 'elo_logistic',
                        'goals': winner_g if promote_g else 'poisson_reference',
                        'outcome_temperature': to if promote_o else 1.,
                        'goal_temperature': tg if promote_g else 1.},
            'promotion': {'outcome': bool(promote_o), 'goals': bool(promote_g)},
            'validation': {'outcome': outcome_scores, 'goals': goal_scores},
            'test': {'selected_outcome': final_o, 'selected_goals': final_g, 'elo_reference': reference,
                     'frequency_reference': fixed_reference, 'goal_reference': goal_ref,
                     'uncalibrated_outcome': outcome_metrics(tp[winner_o], tr),
                     'uncalibrated_goals': goal_metrics(tp[winner_g], tr),
                     'reliability': reliability(out, tr), 'by_competition': by_comp},
            'historical_matches': len(matches),
            'limitations': ['Historical backtest uses archived final scores, not point-in-time API snapshots.',
                           'Same-day results excluded from features; models refitted before each month.',
                           'No injuries, official lineups or xG used; future rotations are not inferred.',
                           'European strength links rely on collected competitions; unobserved leagues remain uncertain.',
                           'Global temperature calibration; no claim of perfect calibration for every competition.']}


def main():
    now = datetime.now(UTC)
    source = load_matches(ROOT)
    matches = clean(source, now.replace(hour=0, minute=0, second=0, microsecond=0))
    # Cache only completed historical evaluation seasons, so daily matches cannot change model selection.
    year = now.year if now.month >= 7 else now.year - 1
    past = [m for m in matches if instant(m['utcDate']).date().isoformat() < f'{year}-07-01']
    fingerprint = hashlib.sha256((Path(__file__).read_text() + json.dumps([(m['id'], m['utcDate'], goals(m), m['_code']) for m in past])).encode()).hexdigest()
    path = ROOT / 'data/predictions/model_report.json'
    report = json.loads(path.read_text()) if path.exists() else {}
    if report.get('fingerprint') != fingerprint:
        report = backtest(past, now)
        report['fingerprint'] = fingerprint
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, allow_nan=False))
    rows, state = examples(matches)
    future = {}
    for m in source:
        if m.get('status') in ('SCHEDULED','TIMED') and m.get('utcDate') and now < instant(m['utcDate']) <= now + timedelta(days=7) and m.get('homeTeam', {}).get('id') is not None and m.get('awayTeam', {}).get('id') is not None:
            future[str(m['id'])] = m
    targets = []
    for m in sorted(future.values(), key=lambda m: m['utcDate']):
        x, samples = state.features(m)
        targets.append({'match': m, 'x': x, 'samples': samples})
    predictions = {}
    if targets:
        dc = fit_predict('dc', rows, targets)
        de = fit_predict('dc_elo', rows, targets)
        elo = fit_predict('elo_logistic', rows, targets)
        cat = fit_predict('catboost', rows, targets)
        base_rates = np.mean([r['score'] for r in rows], axis=0)
        base_grid = np.array([goal_matrix(*base_rates)] * len(targets))
        counts = np.bincount([r['y'] for r in rows], minlength=3) + 1
        fixed = np.array([counts/counts.sum()] * len(targets))
        candidates_g = {'dc': dc, 'dc_elo': de, 'goal_ensemble': (dc+de)/2, 'poisson_reference': base_grid}
        candidates_o = {'elo_logistic': elo, 'catboost': cat, 'dc_outcome': np.array([distribution(g)[0] for g in dc]),
                        'dc_elo_outcome': np.array([distribution(g)[0] for g in de]), 'frequency': fixed}
        candidates_o['ensemble'] = (elo + cat + candidates_o['dc_elo_outcome']) / 3
        serving = report['serving']
        op = calibrate_outcome(candidates_o[serving['outcome']], serving['outcome_temperature'])
        gp = calibrate_goals(candidates_g[serving['goals']], serving['goal_temperature'])
        for i, target in enumerate(targets):
            m, samples = target['match'], target['samples']
            _, over = distribution(gp[i])
            predictions[str(m['id'])] = {'outcome': dict(zip(LABELS, map(float, op[i]))),
                'over': dict(zip(('1.5','2.5','3.5'), map(float, over))),
                'btts': float(gp[i, 1:, 1:].sum()), 'expected_total': round(float((gp[i]*TOTALS).sum()), 2),
                'features': dict(zip(('home','away'), samples)), 'model': VERSION,
                'issued_at': now.isoformat(), 'model_fingerprint': fingerprint,
                'model_components': serving, 'baseline': {'outcome': dict(zip(LABELS,map(float,elo[i])))}}
    dest = ROOT / 'data/predictions/serving.json'
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps({'generated_at': now.isoformat(), 'predictions': predictions}, ensure_ascii=False, allow_nan=False))
    # Small public report, kept distinct from prospectively issued predictions.
    out = ROOT / 'report/output'
    out.mkdir(parents=True, exist_ok=True)
    (out/'model_report.json').write_text(json.dumps(report, ensure_ascii=False, allow_nan=False))
    print(json.dumps({'serving': report['serving'], 'promotion': report['promotion'], 'test': report['test'],
                      'predictions': len(predictions)}, ensure_ascii=False))

if __name__ == '__main__':
    main()
