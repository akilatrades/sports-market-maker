"""Additional diagnostics, labeled exploratory; no trading-return claims."""
import base64
import gzip
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

import analyze


def main():
    out=Path('independent_results')
    # Transfer a byte-identical compressed copy in small text parts for reproducibility.
    raw=(out/'raw'/'nowcast_month.json').read_bytes()
    encoded=base64.b64encode(gzip.compress(raw,mtime=0)).decode()
    transfer=out/'macro_transfer';transfer.mkdir(exist_ok=True)
    pieces=[encoded[i:i+400_000] for i in range(0,len(encoded),400_000)]
    for i,piece in enumerate(pieces):(transfer/f'{i:03}.txt').write_text(piece)
    analyze.save('macro_transfer_manifest.json',{'raw_sha256':hashlib.sha256(raw).hexdigest(),'raw_bytes':len(raw),'parts':len(pieces)})
    obj=json.loads(raw.decode('utf-8-sig'))
    def schema(x,depth=0):
        if depth>4:return type(x).__name__
        if isinstance(x,dict):return {k:schema(v,depth+1) for k,v in list(x.items())[:16]}
        if isinstance(x,list):return {'length':len(x),'first':schema(x[0],depth+1) if x else None}
        return x
    analyze.save('macro_schema.json',schema(obj))
    # A stricter seasonal yardstick, deliberately not relabeled as a new holdout.
    vintages=pd.read_csv(out/'tsa_vintages.csv',parse_dates=['date','snapshot']).set_index(['snapshot','date']).passengers
    f=pd.read_csv(out/'tsa_predictions.csv',parse_dates=['date','snapshot'])
    f['annual_naive']=[vintages.loc[(r.snapshot,r.date-pd.Timedelta(days=364))] for r in f.itertuples()]
    test=f[f.date>='2026-07-01']
    b=(test.annual_naive-test.actual).abs();m=(test.challenger-test.actual).abs()
    analyze.save('tsa_annual_benchmark.json',{
        'label':'Exploratory benchmark added after the primary scores were inspected; not a new holdout.',
        'targets':len(test),'annual_naive_mae':b.mean(),'challenger_mae':m.mean(),
        'relative_mae_improvement':1-m.mean()/b.mean(),'paired_improvement':analyze.bootstrap(b-m)})
    f.to_csv(out/'tsa_annual_benchmark_predictions.csv',index=False)
    # Standard-taker-fee stress, not a claim about each historical fee schedule.
    candidates=pd.read_csv(out/'structural_positive_candidates.csv')
    rows=[]
    for r in candidates.itertuples():
        prices=[]
        for ticker,side in [(r.leg1,'yes'),(r.leg2,'no')]:
            cs=json.loads((out/'raw'/'candles'/f'{ticker}.json').read_text())['candlesticks']
            target=int(pd.Timestamp(r.timestamp).timestamp())
            c=next(c for c in cs if c['end_period_ts']==target)
            price=analyze.dollars(c['yes_ask']) if side=='yes' else 1-analyze.dollars(c['yes_bid'])
            prices.append(price)
        fees=[math.ceil((.07*p*(1-p)*100)-1e-12)/100 for p in prices]
        rows.append({'event':r.event,'timestamp':r.timestamp,'leg1':r.leg1,'leg2':r.leg2,
                     'yes_cost':prices[0],'no_cost':prices[1],'raw_margin':r.margin_before_costs,
                     'standard_taker_fee_stress':sum(fees),'net_margin_fee_stress':r.margin_before_costs-sum(fees),
                     'net_margin_1cent_per_leg_slippage':r.margin_before_costs-.02})
    result=pd.DataFrame(rows)
    result.to_csv(out/'structural_fee_stress.csv',index=False)
    analyze.save('structural_fee_stress.json',{
        'label':'Sensitivity only: standard 0.07*p*(1-p) taker fee, each 1-contract leg rounded up to a cent; historical series waivers not certified.',
        'candidates':len(result),'events':result.event.nunique() if len(result) else 0,
        'positive_after_fee_stress':int((result.net_margin_fee_stress>1e-9).sum()) if len(result) else 0,
        'positive_after_1cent_per_leg_slippage':int((result.net_margin_1cent_per_leg_slippage>1e-9).sum()) if len(result) else 0,
        'best_margin_after_fee_stress':result.net_margin_fee_stress.max() if len(result) else None})


if __name__=='__main__':main()
