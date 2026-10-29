"""Bounded, public-GET-only independent research collection. No trading imports."""
import concurrent.futures as cf
import datetime as dt
import hashlib
import io
import json
from pathlib import Path
import re
import sqlite3
import threading
import time
import urllib.parse
import urllib.request

import pandas as pd

OUT = Path('independent_results')
RAW = OUT / 'raw'
BASE = 'https://external-api.kalshi.com/trade-api/v2'
SERIES = ['KXINX', 'KXTSAD', 'KXTSAW', 'KXHIGHNY', 'KXHIGHCHI',
          'KXHIGHTHOU', 'KXCPI', 'KXCPINDEX', 'KXGOLDD', 'KXBTC15M', 'KXPRES']
END = dt.datetime(2026, 10, 28, tzinfo=dt.timezone.utc)
START = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
lock = threading.Lock()
next_request = 0.0
manifest = []


def get(url, timeout=45):
    global next_request
    if not url.startswith(('https://external-api.kalshi.com/trade-api/v2/',
        'https://api.github.com/repos/chengxdadp/tsa-passenger-volume/',
        'https://raw.githubusercontent.com/chengxdadp/tsa-passenger-volume/',
        'https://www.clevelandfed.org/', 'https://mesonet.agron.iastate.edu/')):
        raise ValueError('Public-source allowlist rejection')
    if '/portfolio/' in url or '/orders' in url:
        raise ValueError('Account and order endpoints forbidden')
    for attempt in range(3):
        with lock:
            wait = max(0, next_request-time.monotonic())
            next_request = max(time.monotonic(),next_request)+.22
        time.sleep(wait)
        try:
            req = urllib.request.Request(url, headers={'User-Agent':'independent-prediction-research/1.0'}, method='GET')
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read(25_000_001)
            if len(body)>25_000_000: raise ValueError('Response exceeds 25 MB budget')
            with lock:
                manifest.append({'url':url,'retrieved_at':dt.datetime.now(dt.timezone.utc).isoformat(),
                                 'bytes':len(body),'sha256':hashlib.sha256(body).hexdigest()})
            return body
        except Exception as e:
            if attempt==2:
                with lock: manifest.append({'url':url,'error':str(e)[:200]})
                raise
            time.sleep(attempt+1)


def js(url): return json.loads(get(url))


def save(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,indent=1,allow_nan=False,default=str)+'\n')


def query(path, **params): return BASE+path+'?'+urllib.parse.urlencode(params)


def markets(series):
    rows={}; notes=[]
    for historical in (True,False):
        cursor=''; complete=False; path='/historical/markets' if historical else '/markets'
        for page in range(12):
            params={'series_ticker':series,'limit':1000,'max_close_ts':int(END.timestamp()),
                    'min_close_ts':int(START.timestamp())}
            if not historical:params['status']='settled'
            if cursor:params['cursor']=cursor
            try:d=js(query(path,**params))
            except Exception as e:
                notes.append({'historical':historical,'error':str(e)});break
            for m in d.get('markets',[]): rows[m['ticker']]=dict(m,archive_source=historical)
            cursor=d.get('cursor') or ''
            if not cursor:complete=True;break
        notes.append({'historical':historical,'pages':page+1,'complete':complete})
    selected=[]
    for m in rows.values():
        try:close=pd.Timestamp(m['close_time'])
        except Exception:continue
        if START<=close.to_pydatetime()<END and m.get('result') in ('yes','no','scalar'):
            selected.append(m)
    # Distinct event dates, not top-volume or best-performing markets.
    events={}
    for m in selected:
        e=m['event_ticker']; events[e]=max(events.get(e,''),m['close_time'])
    ordered=sorted(events,key=lambda e:(events[e],e))
    take=set(ordered[-30:])
    sample=[m for m in selected if m['event_ticker'] in take]
    save(RAW/'markets'/f'{series}.json',{'series':series,'notes':notes,
         'all_eligible_markets':len(selected),'all_eligible_events':len(events),'sample':sample})
    print('MARKETS',series,len(selected),len(sample),flush=True)
    return sample


def candle(m):
    ticker=m['ticker']; series=ticker.split('-')[0]
    close=pd.Timestamp(m['close_time']); opened=pd.Timestamp(m['open_time'])
    # One-minute bars for short crypto; hourly bars for the other screens.
    period=1 if series=='KXBTC15M' else 60
    start=max(opened,close-pd.Timedelta(hours=48))
    prefix='/historical/markets' if m['archive_source'] else f'/series/{series}/markets'
    url=query(f'{prefix}/{urllib.parse.quote(ticker,safe="")}/candlesticks',
              start_ts=int(start.timestamp()),end_ts=int(close.timestamp()),period_interval=period)
    try:
        d=js(url)
        save(RAW/'candles'/f'{ticker}.json',d)
        return {'ticker':ticker,'rows':len(d.get('candlesticks',[]))}
    except Exception as e:return {'ticker':ticker,'error':str(e)}


def tsa():
    commits=js('https://api.github.com/repos/chengxdadp/tsa-passenger-volume/commits?path=data/tsa_data.db&per_page=100')
    records=[];notes=[]
    for c in reversed(commits):
        sha=c['sha']; stamp=c['commit']['committer']['date']
        if stamp>END.isoformat().replace('+00:00','Z'):continue
        try:
            body=get(f'https://raw.githubusercontent.com/chengxdadp/tsa-passenger-volume/{sha}/data/tsa_data.db')
            p=RAW/'tsa'/f'{sha}.db';p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(body)
            con=sqlite3.connect(f'file:{p}?mode=ro',uri=True)
            vals=con.execute('SELECT date, passengers FROM passenger_data ORDER BY date').fetchall();con.close()
            for date,value in vals:records.append({'snapshot':stamp,'sha':sha,'date':date,'passengers':value})
            notes.append({'sha':sha,'snapshot':stamp,'rows':len(vals),'first':vals[0][0],'last':vals[-1][0]})
        except Exception as e:notes.append({'sha':sha,'error':str(e)})
    pd.DataFrame(records).to_csv(OUT/'tsa_vintages.csv',index=False)
    save(OUT/'tsa_sources.json',notes)
    print('TSA',len(notes),len(records),flush=True)


def weather(station):
    notes=[];raw=[]
    # Fixed 21-month window. Four-hourly GFS MOS runs, retained as issued.
    for start in pd.date_range('2025-01-01','2026-09-01',freq='MS'):
        stop=start+pd.offsets.MonthBegin(1)
        url='https://mesonet.agron.iastate.edu/cgi-bin/request/mos.py?'+urllib.parse.urlencode({
            'station':station,'model':'GFS','sts':start.strftime('%Y-%m-%dT%H:%MZ'),
            'ets':stop.strftime('%Y-%m-%dT%H:%MZ'),'format':'csv'})
        try:
            body=get(url,timeout=75);f=pd.read_csv(io.BytesIO(body));
            p=RAW/'weather'/f'{station}_{start:%Y%m}.csv';p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(body)
            raw.append(f);notes.append({'month':str(start.date()),'rows':len(f),'columns':list(f.columns)})
        except Exception as e:notes.append({'month':str(start.date()),'error':str(e)})
    for year in (2025,2026):
        try:save(RAW/'weather'/f'{station}_cli_{year}.json',js(f'https://mesonet.agron.iastate.edu/json/cli.py?station={station}&year={year}'))
        except Exception as e:notes.append({'cli':year,'error':str(e)})
    save(OUT/f'weather_{station}_sources.json',notes)
    print('WEATHER',station,sum(len(f) for f in raw),flush=True)


def macro():
    url='https://www.clevelandfed.org/indicators-and-data/inflation-nowcasting'
    try:
        body=get(url); (RAW/'cleveland_nowcasting.html').write_bytes(body)
        links=sorted(set(re.findall(r'(?:src|href)=["\']([^"\']+)["\']',body.decode(errors='replace'))))
        links=[urllib.parse.urljoin(url,x) for x in links if any(k in x.lower() for k in ['nowcast','inflation','.csv','.xlsx','.json'])]
        save(OUT/'macro_links.json',links)
    except Exception as e:save(OUT/'macro_links.json',{'error':str(e)})


def main():
    OUT.mkdir(exist_ok=True);RAW.mkdir(exist_ok=True)
    if (OUT/'manifest.json').exists():
        print('Using previously archived collection; no new data requested.',flush=True)
        return
    save(OUT/'run_metadata.json',{'started_at':dt.datetime.now(dt.timezone.utc).isoformat(),
        'protocol_sha256':hashlib.sha256(Path('independent_research/PROTOCOL.md').read_bytes()).hexdigest(),
        'cutoff':END.isoformat(),'scope':'public data; no account APIs; no trading'})
    try:save(OUT/'kalshi_cutoff.json',js(BASE+'/historical/cutoff'))
    except Exception as e:save(OUT/'kalshi_cutoff.json',{'error':str(e)})
    allmarkets=[]
    with cf.ThreadPoolExecutor(max_workers=4) as pool:
        jobs={pool.submit(markets,s):s for s in SERIES}
        for f in cf.as_completed(jobs):
            try:allmarkets+=f.result()
            except Exception as e:print('FAIL',jobs[f],str(e),flush=True)
    save(OUT/'market_sample.json',allmarkets)
    with cf.ThreadPoolExecutor(max_workers=4) as pool:
        statuses=list(pool.map(candle,allmarkets))
    save(OUT/'candle_coverage.json',statuses)
    with cf.ThreadPoolExecutor(max_workers=4) as pool:
        jobs={pool.submit(tsa):'tsa',pool.submit(weather,'KJFK'):'jfk',pool.submit(weather,'KORD'):'ord',pool.submit(macro):'macro'}
        for f in cf.as_completed(jobs):
            try:f.result()
            except Exception as e:save(OUT/f'{jobs[f]}_error.json',{'error':str(e)})
    save(OUT/'manifest.json',manifest)
    print('COLLECTION_COMPLETE',len(manifest),flush=True)


if __name__=='__main__':main()
