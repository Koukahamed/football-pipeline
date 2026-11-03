"""Versioned pre-match forecasts. No retrospective predictions or in-play creation."""
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

VERSION = 'poisson-v1'
UTC = timezone.utc


def instant(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def goals(match):
    score = (match.get('score') or {}).get('fullTime') or {}
    h, a = score.get('home'), score.get('away')
    if match.get('status') != 'FINISHED' or not isinstance(h, int) or not isinstance(a, int):
        return None
    # Penalty shootouts / extra time are not comparable to 90-minute forecasts.
    if (match.get('score') or {}).get('duration') not in (None, 'REGULAR'):
        return None
    return h, a


def probabilities(home, away):
    # Renormalize negligible truncated tail, including unusually high goal rates.
    ph = [math.exp(-home) * home**k / math.factorial(k) for k in range(25)]
    pa = [math.exp(-away) * away**k / math.factorial(k) for k in range(25)]
    mass = sum(ph) * sum(pa)
    outcome = {'1': 0., 'N': 0., '2': 0.}
    over = {'1.5': 0., '2.5': 0., '3.5': 0.}
    btts = 0.
    for h, hp in enumerate(ph):
        for a, ap in enumerate(pa):
            p = hp * ap / mass
            outcome['1' if h > a else '2' if a > h else 'N'] += p
            for threshold in over:
                if h + a > float(threshold):
                    over[threshold] += p
            if h and a:
                btts += p
    return outcome, over, btts


def forecast(match, history, calendar, now):
    kickoff = instant(match['utcDate'])
    # Every feature is computed from completed matches available before issuance.
    past = [m for m in history if goals(m) is not None and now - timedelta(days=365) < instant(m['utcDate']) < now]
    home_id, away_id = match['homeTeam']['id'], match['awayTeam']['id']
    base_home = (sum(goals(m)[0] for m in past) + 20 * 1.45) / (len(past) + 20)
    base_away = (sum(goals(m)[1] for m in past) + 20 * 1.15) / (len(past) + 20)
    avg = (base_home + base_away) / 2
    features = {}
    opponent_rates = {}
    for m in past:
        for team, gf, ga in [(m['homeTeam']['id'], *goals(m)), (m['awayTeam']['id'], *goals(m)[::-1])]:
            totals = opponent_rates.setdefault(team, [5 * avg, 5 * avg, 5])
            totals[0] += gf
            totals[1] += ga
            totals[2] += 1

    def strength(team, venue):
        rows = sorted([m for m in past if team in (m['homeTeam'].get('id'), m['awayTeam'].get('id'))], key=lambda m: m['utcDate'])[-10:]
        attack, defense, weight_sum = avg * 5, avg * 5, 5.
        points = 0
        for i, m in enumerate(rows):
            is_home = m['homeTeam']['id'] == team
            gf, ga = goals(m) if is_home else goals(m)[::-1]
            w = .88 ** (len(rows) - 1 - i) * (1.4 if is_home == (venue == 'home') else .7)
            opponent = m['awayTeam']['id'] if is_home else m['homeTeam']['id']
            ogf, oga, on = opponent_rates.get(opponent, [avg, avg, 1])
            attack += w * gf / max(.5, min(2., oga / on / avg))
            defense += w * ga / max(.5, min(2., ogf / on / avg))
            weight_sum += w
            if i >= len(rows) - 5:
                points += 3 if gf > ga else 1 if gf == ga else 0
        completed_all = sorted([m for m in calendar if goals(m) is not None and instant(m['utcDate']) < now and team in (m['homeTeam'].get('id'), m['awayTeam'].get('id'))], key=lambda m: m['utcDate'])
        previous = instant(completed_all[-1]['utcDate']) if completed_all else None
        upcoming = sorted([instant(m['utcDate']) for m in calendar if m.get('id') != match['id'] and m.get('status') in ('TIMED', 'SCHEDULED') and instant(m['utcDate']) > kickoff and team in (m['homeTeam'].get('id'), m['awayTeam'].get('id'))])
        rest = round((kickoff - previous).total_seconds() / 86400, 1) if previous else None
        next_days = round((upcoming[0] - kickoff).total_seconds() / 86400, 1) if upcoming else None
        features[venue] = {'sample': len(rows), 'recent_points': points, 'recent_played': min(5, len(rows)), 'rest_days': rest, 'next_match_days': next_days}
        fatigue = .94 if rest is not None and rest < 3 else 1.
        return attack / weight_sum / avg * fatigue, defense / weight_sum / avg

    ha, hd = strength(home_id, 'home')
    aa, ad = strength(away_id, 'away')
    eh, ea = base_home * ha * ad, base_away * aa * hd
    h2h = [m for m in past if {m['homeTeam'].get('id'), m['awayTeam'].get('id')} == {home_id, away_id} and instant(m['utcDate']) > now - timedelta(days=730)][-5:]
    # Small, shrunk H2H contribution. It cannot dominate current form.
    if h2h:
        hh = sum(goals(m)[0 if m['homeTeam']['id'] == home_id else 1] for m in h2h)
        ah = sum(goals(m)[1 if m['homeTeam']['id'] == home_id else 0] for m in h2h)
        w = min(.08, len(h2h) * .02)
        eh = (1 - w) * eh + w * hh / len(h2h)
        ea = (1 - w) * ea + w * ah / len(h2h)
    eh, ea = min(4.5, max(.25, eh)), min(4.5, max(.25, ea))
    outcome, over, btts = probabilities(eh, ea)
    confidence = 'Données limitées' if min(features['home']['sample'], features['away']['sample']) < 5 else 'Base statistique disponible'
    notes = [f"Forme sur {features[v]['recent_played']} matchs : {features[v]['recent_points']} points ({'domicile' if v == 'home' else 'extérieur'})." for v in ('home', 'away')]
    notes += [f"{len(h2h)} confrontation(s) directe(s) disponible(s), poids maximal 8 %.", 'Attaque/défense pondérées sur 10 matchs et ajustées au niveau offensif/défensif des adversaires, avantage domicile et récupération courte (< 3 jours).']
    for venue, label in [('home', 'Domicile'), ('away', 'Extérieur')]:
        f = features[venue]
        notes.append(f"{label} : repos {f['rest_days'] if f['rest_days'] is not None else 'inconnu'} j ; prochaine échéance connue à {f['next_match_days'] if f['next_match_days'] is not None else '—'} j.")
    notes.append('Calendrier limité aux compétitions suivies. Prochaine échéance informative : aucune rotation supposée. Absences, compositions, xG et enjeux spécifiques non intégrés.')
    return dict(match_id=match['id'], kickoff=match['utcDate'], home=match['homeTeam'], away=match['awayTeam'], issued_at=now.isoformat(), model=VERSION, outcome=outcome, pick=max(outcome, key=outcome.get), over=over, expected_total=round(eh + ea, 2), btts=btts, features=features, confidence=confidence, notes=notes, baseline=dict(outcome={'1': .45, 'N': .27, '2': .28}, over={k: probabilities(base_home, base_away)[1][k] for k in over}))


def evaluate(record, match, now):
    if instant(record['issued_at']) >= instant(record['kickoff']):
        return
    if match.get('status') in ('CANCELLED', 'POSTPONED', 'SUSPENDED', 'AWARDED'):
        record['evaluation'] = {'status': 'excluded', 'reason': 'Annulé, reporté, suspendu ou attribué'}
        return
    # A shifted kickoff invalidates an earlier frozen fixture prediction.
    if match.get('utcDate') != record['kickoff']:
        record['evaluation'] = {'status': 'excluded', 'reason': 'Horaire modifié après émission'}
        return
    if match.get('status') == 'FINISHED' and (match.get('score') or {}).get('duration') not in (None, 'REGULAR'):
        record['evaluation'] = {'status': 'excluded', 'reason': 'Prolongations : score sur 90 minutes indisponible'}
        return
    score = goals(match)
    if score is None:
        return
    h, a = score
    actual = '1' if h > a else '2' if a > h else 'N'
    total = h + a
    over = {k: total > float(k) for k in record['over']}
    record['evaluation'] = dict(status='settled', evaluated_at=now.isoformat(), actual=actual, total=total, correct=record['pick'] == actual, over=over, btts=h > 0 and a > 0, brier=sum((p - int(k == actual))**2 for k, p in record['outcome'].items()), baseline_correct=actual == '1', baseline_brier=sum((p - int(k == actual))**2 for k, p in record['baseline']['outcome'].items()))


def summary(records):
    settled = [r for r in records if r.get('evaluation', {}).get('status') == 'settled']
    n = len(settled)
    result = {'count': n, 'correct': sum(r['evaluation']['correct'] for r in settled), 'baseline_correct': sum(r['evaluation']['baseline_correct'] for r in settled), 'brier': sum(r['evaluation']['brier'] for r in settled) / n if n else None, 'baseline_brier': sum(r['evaluation']['baseline_brier'] for r in settled) / n if n else None, 'over': {}}
    for k in ('1.5', '2.5', '3.5'):
        result['over'][k] = {'correct': sum((r['over'][k] >= .5) == r['evaluation']['over'][k] for r in settled), 'brier': sum((r['over'][k] - int(r['evaluation']['over'][k]))**2 for r in settled) / n if n else None}
    return result


def update(root, leagues, now=None):
    now = now or datetime.now(UTC)
    path = Path(root) / 'data/predictions/ledger.json'
    ledger = json.loads(path.read_text()) if path.exists() else {'records': []}
    records = ledger['records']
    index = {str(r['match_id']): r for r in records}
    calendar = {str(m['id']): m for l in leagues.values() for m in l['matches']}
    for key, league in leagues.items():
        # Current responses take priority over archived versions of the same match.
        history = {}
        for archive in sorted((Path(root) / 'data/history').glob(f'matches_{key}_*.json')):
            for m in json.loads(archive.read_text()).get('matches', []):
                history[str(m['id'])] = m
        history.update({str(m['id']): m for m in league['matches']})
        for archived_id, archived_match in history.items():
            if archived_id in index:
                evaluate(index[archived_id], archived_match, now)
        for match in league['matches']:
            mid = str(match['id'])
            if mid in index:
                evaluate(index[mid], match, now)
            elif league.get('freshness', {}).get('matches') and timedelta(0) <= now - instant(league['freshness']['matches']) < timedelta(hours=36) and match.get('status') in ('TIMED', 'SCHEDULED') and now < instant(match['utcDate']) <= now + timedelta(days=7):
                record = forecast(match, list(history.values()), list(calendar.values()), now)
                record['league'] = key
                records.append(record)
                index[mid] = record
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(ledger, ensure_ascii=False), encoding='utf-8')
    temp.replace(path)
    return {'records': sorted(records, key=lambda r: r['kickoff'], reverse=True), 'summary': summary(records), 'model': VERSION}


def email_section(predictions, today, tz):
    """Email-safe table cards; the text alternative keeps blank lines between fixtures."""
    from html import escape
    records = predictions.get('records', [])
    current = sorted([r for r in records if str(instant(r['kickoff']).astimezone(tz).date()) == today], key=lambda r: r['kickoff'])
    yesterday = str(datetime.fromisoformat(today).date() - timedelta(days=1))
    previous = [r for r in records if str(instant(r['kickoff']).astimezone(tz).date()) == yesterday and r.get('evaluation', {}).get('status') == 'settled']
    pct = lambda p: f'{p:.0%}'.replace('%', ' %')
    short = lambda team: team.get('shortName') or team.get('name') or 'Équipe'
    html = ['<h2 style="margin:32px 0 8px;font-size:23px;color:#17243a">Prédictions</h2>',
            '<p style="margin:0 0 20px;color:#64748b;font-size:13px;line-height:1.6">Les tendances du jour · 1 : domicile, N : nul, 2 : extérieur.<br>Modèle expérimental, probabilités non encore calibrées.</p>']
    lines = ['\nPrédictions · 1 / N / 2 et buts', 'Modèle statistique expérimental ; probabilités non encore calibrées.\n']
    for r in current:
        home, away = short(r['home']), short(r['away'])
        hour = instant(r['kickoff']).astimezone(tz).strftime('%H:%M')
        choice = {'1': 'Victoire ' + home, 'N': 'Match nul', '2': 'Victoire ' + away}[r['pick']]
        # All structure uses nested presentation tables and inline styles for mail clients.
        cells = []
        for key, label in [('1', home), ('N', 'Nul'), ('2', away)]:
            chosen = key == r['pick']
            bg, fg = ('#185a43', '#ffffff') if chosen else ('#f1f5f9', '#17243a')
            cells.append(f'<td width="33%" valign="top" style="padding:10px 4px;text-align:center;background:{bg};color:{fg};border:2px solid #ffffff;border-radius:8px"><div style="font-size:12px;line-height:1.4">{escape(key)} · {escape(label)}</div><div style="font-size:23px;font-weight:bold;line-height:1.5">{pct(r["outcome"][key])}</div></td>')
        goal_rows = []
        for key in ('1.5', '2.5', '3.5'):
            goal_rows.append(f'<tr><td style="padding:8px 0;border-bottom:1px solid #e2e8f0;color:#475569">Au moins {int(float(key)) + 1} buts</td><td align="right" style="padding:8px 0;border-bottom:1px solid #e2e8f0;font-weight:bold;color:#17243a">{pct(r["over"][key])}</td></tr>')
        total = f'{r["expected_total"]:.2f}'.replace('.', ',')
        form = []
        for venue, team in [('home', home), ('away', away)]:
            f = r.get('features', {}).get(venue, {})
            if f.get('recent_played'):
                form.append(f'{team} : {f["recent_points"]} pts sur {f["recent_played"]} matchs')
        html.append(f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="width:100%;margin:0 0 22px;border:1px solid #dce5e0;border-radius:12px;background:#ffffff"><tr><td style="padding:20px">'
                    f'<p style="margin:0 0 6px;font-size:12px;color:#64748b">COUP D’ENVOI · {hour} · PARIS</p>'
                    f'<h3 style="margin:0 0 14px;font-size:18px;line-height:1.5;color:#17243a">{escape(home)} – {escape(away)}</h3>'
                    f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="width:100%;table-layout:fixed"><tr>{"".join(cells)}</tr></table>'
                    f'<p style="margin:12px 0 18px;color:#185a43;font-size:14px;line-height:1.5"><strong>Tendance : {escape(choice)}</strong></p>'
                    f'<p style="margin:0 0 4px;font-size:12px;font-weight:bold;letter-spacing:1px;color:#64748b">BUTS DANS LE MATCH</p>'
                    f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="width:100%;font-size:14px;line-height:1.5">{"".join(goal_rows)}'
                    f'<tr><td style="padding:8px 0;color:#475569">Les deux équipes marquent</td><td align="right" style="padding:8px 0;font-weight:bold">{pct(r["btts"])}</td></tr></table>'
                    f'<p style="margin:8px 0 0;color:#64748b;font-size:13px;line-height:1.6">Total moyen estimé : <strong>{total} buts</strong></p>'
                    f'<p style="margin:16px 0 0;padding-top:12px;border-top:1px solid #e2e8f0;font-size:12px;line-height:1.8;color:#64748b">{escape(r["confidence"])}<br>{"<br>".join(escape(x) for x in form)}</p>'
                    '</td></tr></table>')
        outcome = ' | '.join(f'{k} : {pct(r["outcome"][k])}' for k in ('1', 'N', '2'))
        lines.extend([f'{hour} · {home} – {away}', outcome, 'Tendance : ' + choice])
        lines.extend(f'Au moins {int(float(k))+1} buts : {pct(r["over"][k])}' for k in ('1.5', '2.5', '3.5'))
        lines.extend([f'Les deux équipes marquent : {pct(r["btts"])}', f'Total moyen estimé : {total} buts', r['confidence'], *form, ''])
    if not current:
        message = 'Aucun pronostic émis avant le coup d’envoi pour les matchs du jour.'
        html.append(f'<p style="margin:16px 0;line-height:1.6">{message}</p>')
        lines.append(message)
    s = summary(previous)
    review = [f'{s["correct"]}/{s["count"]} issues justes.' if s['count'] else 'Aucun pronostic évaluable ; le suivi commence à la première émission.']
    if s['count']:
        review.extend(f'Seuil {k.replace(".", ",")} buts : {item["correct"]}/{s["count"]} justes.' for k, item in s['over'].items())
    html.append('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:8px 0 24px;width:100%;background:#f1f5f9;border-radius:10px"><tr><td style="padding:18px"><h3 style="margin:0 0 8px;color:#17243a;font-size:16px">Bilan de la veille</h3>' + ''.join(f'<p style="margin:6px 0;font-size:13px;line-height:1.6;color:#475569">{escape(x)}</p>' for x in review) + '</td></tr></table>')
    lines.extend(['Bilan veille', *review])
    return ''.join(html), lines
