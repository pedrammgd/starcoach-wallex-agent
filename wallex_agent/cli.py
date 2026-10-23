from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time
from dataclasses import asdict
from contextlib import ExitStack

from .data import PublicWallex, contiguous_segments, digest, read_csv, write_csv
from .engine import Config, STRATEGIES
from .evaluation import benchmark, provenance
from .journal import Journal
from .safety import live_blockers, require_live
from .shadow import Shadow
from .settings import load_env,key_configured,update_model,active_llm


def dump(value):
    print(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),flush=True)


def config(path):
    return Config(**json.loads(Path(path).read_text())) if path else Config()


def main(argv=None):
    load_env()
    parser=argparse.ArgumentParser(description='Wallex causal research / public shadow; live disabled')
    parser.add_argument('--ca-file',default=os.environ.get('SSL_CERT_FILE'))
    parser.add_argument('--config')
    sub=parser.add_subparsers(dest='command',required=True)
    d=sub.add_parser('doctor');d.add_argument('--online',action='store_true')
    g=sub.add_parser('verify-gemini');g.add_argument('--online',action='store_true')
    v=sub.add_parser('verify-boxapi');v.add_argument('--online',action='store_true')
    v.add_argument('--compare',action='store_true');v.add_argument('--samples',type=int,default=2)
    m=sub.add_parser('markets');m.add_argument('--approved-file')
    f=sub.add_parser('fetch-data');f.add_argument('--symbol',required=True);f.add_argument('--days',type=int,default=90)
    f.add_argument('--output',required=True);f.add_argument('--split-gaps',action='store_true')
    b=sub.add_parser('backtest');b.add_argument('--data',required=True);b.add_argument('--symbol',required=True)
    b.add_argument('--output',default='reports/backtest')
    s=sub.add_parser('shadow');s.add_argument('--symbol',required=True);s.add_argument('--strategy',choices=STRATEGIES,default='momentum')
    s.add_argument('--journal',default='state/shadow.sqlite');s.add_argument('--cycles',type=int,default=1)
    s.add_argument('--poll-seconds',type=int,default=30)
    s.add_argument('--llm-provider',choices=['boxapi']);s.add_argument('--llm-model')
    for name in ('status','report'):
        p=sub.add_parser(name);p.add_argument('--journal',default='state/shadow.sqlite')
        if name=='report': p.add_argument('--output',default='reports/shadow.jsonl')
    for name in ('run','flatten'): sub.add_parser(name)
    a=parser.parse_args(argv)
    resources=ExitStack()
    try:
        cfg=config(a.config)
        if a.command in ('run','flatten'): require_live()
        client=PublicWallex(a.ca_file,'data/raw')
        if a.command=='doctor':
            result={'python':sys.version.split()[0],'mode':'RESEARCH_ONLY','source':provenance(),
                    'live_blockers':live_blockers(),'llm_provider':active_llm()[0],'llm_model':active_llm()[1],
                    'llm_configured':key_configured(os.environ.get('BOXAPI_API_KEY'))}
            if a.online:
                d=client.get('/v1/markets')
                result['public_markets_count']=len(d['result']['symbols'])
                result['public_success']=d.get('success') is True
            dump(result)
        elif a.command=='verify-boxapi':
            from .boxapi_verify import verify
            result=verify(online=a.online,compare=a.compare,samples=a.samples,
                          output='reports/boxapi_verification.json' if a.online else 'reports/boxapi_offline_verification.json')
            dump(result)
            if a.online and result['status']!='ONLINE_OK':return 2
        elif a.command=='verify-gemini':
            raise ValueError('Gemini is disabled; use verify-boxapi')
            # Legacy integration preserved below, inactive by policy.
            from .gemini import GeminiProvider,choose_model
            from .ai import Agent,parse_decision
            from importlib.metadata import version
            model=os.environ.get('GEMINI_MODEL','gemini-3.8-flash')
            if not a.online:
                journal=Journal(':memory:')
                agent=Agent(lambda ctx:'{"action":"HOLD","allocation":0,"confidence":0.8,"reason":"offline test double: no net edge"}',
                            journal,model='OFFLINE_TEST_DOUBLE')
                decision,trace=agent.decide({'expected_return':0,'roundtrip_cost':cfg.roundtrip_cost})
                journal.close()
                dump({'status':'OFFLINE_OK','sdk_version':version('google-genai'),'configured_model':model,
                      'key_configured':key_configured(os.environ.get('GEMINI_API_KEY')),
                      'decision':asdict(decision),'network_calls':0,'account_model_access':'NOT_VERIFIED',
                      'mode':'shadow','live_orders':False})
            else:
                if not key_configured(os.environ.get('GEMINI_API_KEY')):
                    raise ValueError('Replace YOUR_GEMINI_API_KEY_HERE in project .env before online verification')
                provider=GeminiProvider(model)
                available=provider.available_models()
                selected=choose_model(model,available)
                if selected!=model:update_model(selected)
                provider.model=selected
                journal=Journal('state/gemini_verify.sqlite')
                agent=Agent(provider,journal,model='gemini:'+selected,max_calls=2)
                decision,trace=agent.decide({'features':[1,0,0,0,0,0,0,0],'probability':0.5,
                    'expected_return':0,'volatility':0.01,'roundtrip_cost':cfg.roundtrip_cost,
                    'current_allocation':0,'risk_cap':cfg.max_allocation,
                    'candidate':{'target':0,'reason':'verification only; no profitable edge','edge':0}})
                dump({'status':'ONLINE_OK' if trace.get('status')=='ok' else 'FAILED_CLOSED',
                      'requested_model':model,'selected_model':selected,'model_catalog_verified':True,
                      'decision':asdict(decision),'usage':trace.get('provider_metadata'),
                      'mode':'shadow','live_orders':False})
                journal.close()
                if trace.get('status')!='ok':return 2
        elif a.command=='markets':
            data=client.get('/v1/markets')['result']['symbols']
            approved=json.loads(Path(a.approved_file).read_text()) if a.approved_file else []
            # This file is a research filter, NEVER proof of contest authorization.
            dump({'competition_allowlist_verified':False,'research_markets':[
                {k:v.get(k) for k in ('symbol','baseAsset','quoteAsset','stepSize','tickSize','minQty','minNotional')}
                for symbol,v in data.items() if symbol in approved]})
        elif a.command=='fetch-data':
            if not 1<=a.days<=730: raise ValueError('days must be 1..730')
            end=int(time.time())//cfg.interval*cfg.interval
            bars=client.history(a.symbol,end-a.days*86400,end,cfg.interval,split_gaps=a.split_gaps)
            segments=contiguous_segments(bars,cfg.interval)
            outputs=[]
            for i,segment in enumerate(segments):
                dest=a.output if len(segments)==1 else str(Path(a.output).with_suffix(''))+f'.segment-{i}.csv'
                write_csv(dest,segment)
                outputs.append({'file':dest,'bars':len(segment),'hash':digest(segment),
                                'start':segment[0].timestamp,'end':segment[-1].timestamp+cfg.interval})
            Path(a.output+'.manifest.json').write_text(json.dumps({'symbol':a.symbol,'segments':outputs,
                'competition_eligible':False,'interval':cfg.interval},indent=2))
            dump(outputs)
        elif a.command=='backtest':
            if not a.symbol.endswith('TMN'): raise ValueError('TMN research only')
            result=benchmark(read_csv(a.data,cfg.interval),cfg,a.output,a.symbol)
            dump({'selected':result['selected_on_validation'],'holdout':result['selected_holdout'],
                  'report':a.output,'competition_eligible':False})
        elif a.command=='shadow':
            if not 1<=a.cycles<=100000 or a.poll_seconds<10: raise ValueError('invalid poll budget')
            active_provider,active_model=active_llm()
            a.llm_provider=a.llm_provider or active_provider
            a.llm_model=a.llm_model or active_model
            if bool(a.llm_provider)!=bool(a.llm_model): raise ValueError('provider and model required together')
            from .runtime import ProcessLock
            resources.enter_context(ProcessLock(a.journal+'.lock'))
            journal=Journal(a.journal)
            resources.callback(journal.close)
            agent=None
            if a.llm_provider:
                from .ai import Agent,Provider
                provider=Provider(a.llm_provider,a.llm_model,a.ca_file)
                if provider.boxapi is not None:resources.callback(provider.boxapi.close)
                agent=Agent(provider,journal,
                            model=a.llm_provider+':'+a.llm_model)
            shadow=Shadow(journal,cfg,a.symbol,a.strategy,agent)
            for cycle in range(a.cycles):
                now=int(time.time());end=now//cfg.interval*cfg.interval
                try:
                    bars=client.history(a.symbol,end-500*cfg.interval,end,cfg.interval)
                    markets=client.get('/v1/markets')
                    observation=client.last_observation
                    if not observation or not observation['clock']['accepted']:
                        raise ValueError('clock/HTTP latency sanity check failed')
                    stats=markets['result']['symbols'][a.symbol]['stats']
                    event=shadow.step(bars,float(stats['bidPrice']),float(stats['askPrice']),int(time.time()),observation=observation)
                    dump({k:event.get(k) for k in ('status','new_decision','symbol','observed_at','reason','target','fill','equity')})
                except Exception as e:
                    journal.append(f'feed-error:{now}',{'type':type(e).__name__,'observed_at':now,
                                                      'action':'NO_ORDER','mode':'shadow'})
                    dump({'status':'BLOCKED_FEED','error_type':type(e).__name__,'action':'NO_ORDER'})
                if cycle+1<a.cycles: time.sleep(a.poll_seconds)
            journal.close()
        elif a.command in ('status','report'):
            if not Path(a.journal).exists(): raise ValueError('journal missing')
            journal=Journal(a.journal)
            count=journal.verify()
            if a.command=='report':
                Path(a.output).parent.mkdir(parents=True,exist_ok=True);journal.export(a.output)
            dump({'events':count,'chain':'verified','mode':'shadow','live_blockers':live_blockers()})
            journal.close()
        return 0
    except Exception as e:
        # Error types only for network/provider failures: never echo secrets or HTTP headers.
        from .boxapi import safe_error
        dump({'status':'ERROR','type':type(e).__name__,
              'detail':str(e) if isinstance(e,(ValueError,PermissionError)) else 'request failed; provider classification below',
              **safe_error(e)})
        return 2
    finally:
        resources.close()


if __name__=='__main__': raise SystemExit(main())
