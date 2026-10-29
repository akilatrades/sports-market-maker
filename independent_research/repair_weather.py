"""Retry only missing public weather months, serially and with backoff."""
import datetime as dt
import json
from pathlib import Path
import time
import urllib.parse

import pandas as pd

import collect


def main():
    notes=[]
    for name in ['month','year','quarter']:
        path=collect.RAW/f'nowcast_{name}.json'
        if path.exists():continue
        try:
            url=f'https://www.clevelandfed.org/-/media/files/webcharts/inflationnowcasting/nowcast_{name}.json?sc_lang=en'
            path.write_bytes(collect.get(url))
        except Exception as e:notes.append({'macro':name,'error':str(e)})
    for station in ['KJFK','KORD']:
        for start in pd.date_range('2025-01-01','2026-09-01',freq='MS'):
            path=collect.RAW/'weather'/f'{station}_{start:%Y%m}.csv'
            if path.exists():continue
            stop=start+pd.offsets.MonthBegin(1)
            url='https://mesonet.agron.iastate.edu/cgi-bin/request/mos.py?'+urllib.parse.urlencode({
                'station':station,'model':'GFS','sts':start.strftime('%Y-%m-%dT%H:%MZ'),
                'ets':stop.strftime('%Y-%m-%dT%H:%MZ'),'format':'csv'})
            time.sleep(10)
            try:
                body=collect.get(url,timeout=60)
                path.write_bytes(body)
                notes.append({'station':station,'month':str(start.date()),'status':'repaired'})
            except Exception as e:notes.append({'station':station,'month':str(start.date()),'error':str(e)})
            print(notes[-1],flush=True)
    collect.save(collect.OUT/'weather_repair.json',{'at':dt.datetime.now(dt.timezone.utc).isoformat(),
               'results':notes,'requests':collect.manifest})


if __name__=='__main__':main()
