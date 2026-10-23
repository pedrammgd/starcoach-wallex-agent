"""Bounded public-market shadow + genuine BoxAPI decision evidence; zero exchange writes."""
from dataclasses import asdict
from datetime import datetime, timezone
import argparse
import json
import os
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))

from wallex_agent.ai import Agent, Provider
from wallex_agent.data import PublicWallex, read_csv, write_csv, digest
from wallex_agent.engine import Config, run
from wallex_agent.journal import Journal
from wallex_agent.model import WARMUP
from wallex_agent.runtime import ProcessLock
from wallex_agent.settings import load_env, active_llm
from wallex_agent.shadow import Shadow


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--online',action='store_true')
    args=parser.parse_args()
    if not args.online:parser.error('--online required; up to 3 BoxAPI decisions may be billed')
    load_env()
    if os.environ.get('TRADING_MODE','shadow')!='shadow' or os.environ.get('ENABLE_LIVE_TRADING','false')!='false':
        raise PermissionError('shadow-only evidence runner')
    provider_name,model=active_llm();provider=Provider(provider_name,model,os.environ.get('SSL_CERT_FILE'))
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    dest=Path('reports/final_online')/stamp;dest.mkdir(parents=True)
    report={'observed_at':stamp,'live_orders':False,'exchange_authenticated_requests':0,
            'execution_site':'local; Liara region not verified','model':model,'shadow':[],
            'real_inference_count':0,'nominal_AI_USD_reservation_is_not_verified_cost':True}
    with ProcessLock('state/final-online.lock'):
        journal=Journal('state/final-online-'+stamp+'.sqlite')
        agent=Agent(provider,journal,model='boxapi:'+model,max_calls=3)
        client=PublicWallex(os.environ.get('SSL_CERT_FILE'),'data/raw')
        cfg=Config(interval=60)
        shadow=Shadow(journal,cfg,'BTCTMN','cash',agent,review_flat=True)
        try:
            for cycle in range(2):
                now=int(time.time());end=now//60*60
                try:
                    bars=client.history('BTCTMN',end-400*60,end,60)
                    markets=client.get('/v1/markets');observed=client.last_observation
                    stats=markets['result']['symbols']['BTCTMN']['stats']
                    if not observed or not observed['clock']['accepted']:raise ValueError('clock sanity check failed')
                    event=shadow.step(bars,float(stats['bidPrice']),float(stats['askPrice']),int(time.time()),observation=observed)
                    report['shadow'].append({k:event.get(k) for k in ('status','observed_at','symbol','target','fill','equity','agent','decision_latency_ms','depth_verified')})
                except Exception as e:
                    report['shadow'].append({'status':'BLOCKED','error_type':type(e).__name__,'live_orders':False})
                if cycle==0:time.sleep(61)
            # First chronological training-period momentum candidate, chosen without future returns.
            bars=read_csv('data/BTCTMN_validated_segment_0.csv',3600)
            dev=bars[:len(bars)//2];historical_cfg=Config()
            baseline=run(dev,historical_cfg,'momentum')
            candidate=next((e for e in baseline['events'] if e['target_next_open']>0),None)
            if candidate:
                end_index=next(i for i,c in enumerate(dev) if c.timestamp==candidate['bar_open'])+1
                controlled=run(dev[:end_index],historical_cfg,'momentum',agent=agent)
                last=controlled['events'][-1]
                report['historical_training_candidate']={'symbol':'BTCTMN','kind':'historical training replay; NOT forward trading or profitability evidence',
                    'candidate_time':candidate['decision_at'],'closed_candle':candidate['candle'],
                    'baseline_target':candidate['target_next_open'],'AI_target_after_independent_risk':last['target_next_open'],
                    'agent':last['agent'],'reason':last['proposal']['reason'],'risk_reasons':last['reasons']}
            rows=journal.db.execute("SELECT body FROM events WHERE event_key LIKE 'ai-result:%'").fetchall()
            traces=[json.loads(x[0]) for x in rows]
            report['real_inference_count']=sum(x['status']=='ok' for x in traces)
            report['journal_events']=journal.verify();journal.export(str(dest/'decisions.jsonl'))
            report['token_usage']=[x.get('provider_metadata') for x in traces]
            # New data is sealed, not fed into selection or performance calculation.
            start=1792702800  # 2026-10-22 21:00 UTC; original research endpoint, not a contest cutoff.
            end=int(time.time())//3600*3600
            future=client.history('BTCTMN',start,end,3600,split_gaps=True)
            if future:
                path=Path('data/final_holdout_sealed_BTCTMN.csv');write_csv(path,future)
                report['sealed_new_holdout']={'file':str(path),'bars':len(future),'dataset_hash':digest(future),
                    'start':start,'end':end,'evaluated':False,'too_short_for_performance_claim':True}
        finally:
            journal.close()
            if provider.boxapi:provider.boxapi.close()
            (dest/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'report':str(dest/'summary.json'),**report},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
