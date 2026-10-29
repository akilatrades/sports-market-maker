"""Fixed month-end CPI forecast comparison using the Fed's dated archive."""
import json
from pathlib import Path

import numpy as np
import pandas as pd

import analyze


def chart_date(label, year, month):
    m, d = (int(x) for x in label.split('/'))
    y = year + (1 if m - month < -6 else -1 if m - month > 6 else 0)
    return pd.Timestamp(year=y, month=m, day=d)


def run(root=Path('independent_results')):
    data = json.loads((root / 'raw' / 'nowcast_month.json').read_text(encoding='utf-8-sig'))
    rows = []
    skipped = []
    for obj in data:
        year, month = (int(x) for x in obj['chart']['subcaption'].split('-'))
        target = pd.Timestamp(year=year, month=month, day=1)
        if (year, month) in [(2025, 10), (2025, 11)]:
            skipped.append({'month':str(target.date()), 'reason':'not official BLS month-over-month readings'})
            continue
        origin = target + pd.offsets.MonthEnd(0)
        labels = [c['label'] for c in obj['categories'][0]['category'] if c.get('vline') != 'true']
        dates = [chart_date(x, year, month) for x in labels]
        series = {x['seriesname']:x['data'] for x in obj['dataset']}
        forecasts = series['CPI Inflation']
        actuals = series['Actual CPI Inflation']
        assert len(dates) == len(forecasts) == len(actuals)
        fs = [(date,float(x['value'])) for date,x in zip(dates,forecasts) if str(x.get('value','')).strip() and date <= origin]
        ys = [(date,float(x['value'])) for date,x in zip(dates,actuals) if str(x.get('value','')).strip()]
        if not fs or len(ys)!=1:
            skipped.append({'month':str(target.date()),'reason':'missing month-end forecast or unique first-release label'})
            continue
        forecast_date, forecast = max(fs)
        release_date, actual = ys[0]
        if release_date <= origin:
            skipped.append({'month':str(target.date()),'reason':'outcome not after forecast origin'})
            continue
        rows.append({'date':target,'origin':origin,'forecast_date':forecast_date,
                     'release_date':release_date,'baseline':forecast,'actual':actual})
    frame = pd.DataFrame(rows).sort_values('date').reset_index(drop=True)
    for i,row in frame.iterrows():
        known = frame[(frame.date<row.date)&(frame.release_date<row.origin)].tail(24)
        if len(known)<12:continue
        frame.loc[i,'challenger'] = row.baseline + (known.actual-known.baseline).mean()
        frame.loc[i,'calibration_releases'] = len(known)
        frame.loc[i,'latest_calibration_release'] = known.release_date.max().isoformat()
    test = frame[(frame.date>='2024-01-01')&(frame.date<='2026-09-01')].dropna(subset=['challenger'])
    scores = {}
    for m in ['baseline','challenger']:
        e=test[m]-test.actual
        scores[m]={'mae_percentage_points':e.abs().mean(),'rmse_percentage_points':np.sqrt((e**2).mean()),'bias_percentage_points':e.mean()}
    improvement = (test.baseline-test.actual).abs()-(test.challenger-test.actual).abs()
    scores.update({'status':'forecast_component_completed','no_trading_pnl':True,
        'test_months':len(test),'first':test.date.min(),'last':test.date.max(),
        'mae_improvement':analyze.bootstrap(improvement,block=3),
        'relative_mae_improvement':1-scores['challenger']['mae_percentage_points']/scores['baseline']['mae_percentage_points'],
        'model':'Public month-end Cleveland Fed headline CPI nowcast plus trailing 24 released forecast errors; at least 12 required.',
        'excluded_substitute_targets':['2025-10','2025-11'],
        'limitations':['archived provider forecast/first-release labels, not independently captured vintages',
                       'unrounded headline CPI monthly change; not the rounded exchange payout target',
                       'small monthly sample; no execution or market-price comparison'],
        'all_eligible_forecasts':len(frame),'skipped':skipped})
    frame.to_csv(root/'macro_predictions.csv',index=False)
    (root/'macro_results.json').write_text(json.dumps(analyze.clean(scores),indent=2)+'\n')
    return scores


if __name__=='__main__':
    result = run()
    path = Path('independent_results/results.json')
    if path.exists():
        all_results = json.loads(path.read_text())
        all_results['macro'] = analyze.clean(result)
        path.write_text(json.dumps(all_results,indent=2)+'\n')
    print(json.dumps(analyze.clean(result),indent=2))
