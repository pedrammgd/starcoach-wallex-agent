"""Credential readiness and read-only connectivity; no private exchange calls or cloud writes."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
import urllib.error

from .data import PublicWallex
from .boxapi import BoxAPIProvider,safe_error
from .settings import ROOT,key_configured,load_env,active_llm


def validate_read_only(environ=None):
    env=os.environ if environ is None else environ
    expected={'TRADING_MODE':'shadow','ENABLE_LIVE_TRADING':'false','WALLEX_READ_ONLY':'true',
              'WALLEX_ENABLE_WITHDRAWALS':'false','WALLEX_ENABLE_TRANSFERS':'false',
              'WALLEX_PRIVATE_READS_ENABLED':'false'}
    invalid=[key for key,value in expected.items() if env.get(key,value).lower()!=value]
    if invalid:raise ValueError('access preparation requires safe flags: '+', '.join(invalid))


def readiness() -> dict:
    return {'mode':'shadow','live_orders':False,'private_wallex_requests':False,
            'wallex':{'key_configured':key_configured(os.environ.get('WALLEX_API_KEY')),
                      'dedicated_credit_account_id_configured':bool(os.environ.get('WALLEX_CREDIT_ACCOUNT_ID')),
                      'account_scope_verified':False,
                      'note':'separate credit-account keys documented; this credential not authenticated'},
            'boxapi':{'key_configured':key_configured(os.environ.get('BOXAPI_API_KEY')),
                      'model':active_llm()[1],'provider':'boxapi'},
            'liara':{'project_cli_installed':(ROOT/'.tools/liara-cli/node_modules/.bin/liara').exists(),
                     'account_selected':bool(os.environ.get('LIARA_ACCOUNT')),
                     'team_selected':bool(os.environ.get('LIARA_TEAM_ID')),
                     'app_selected':bool(os.environ.get('LIARA_APP_NAME')),
                     'runtime_region_verified':False,
                     'resource_creation_performed':False}}


def probe(execution_site: str='local', *, wallex=None, boxapi=None) -> dict:
    validate_read_only()
    active_llm()
    if execution_site not in {'local','liara-runtime'}:raise ValueError('invalid execution site')
    result={'observed_at':datetime.now(timezone.utc).isoformat(),'execution_site_claim':execution_site,
            'deployment_region_verified':False,'runtime_region_claim':os.environ.get('LIARA_RUNTIME_REGION','unverified'),
            'region_evidence':'self-reported context only; correlate with Liara runtime metadata',
            'live_orders':False,'private_wallex_requests':False,'generation_requests':False}
    started=time.monotonic()
    try:
        client=wallex or PublicWallex(os.environ.get('SSL_CERT_FILE'))
        data=client.get('/v1/markets')
        if data.get('success') is not True or not isinstance(data.get('result',{}).get('symbols'),dict):
            raise ValueError('invalid public markets shape')
        result['wallex_public']={'status':'OK','markets_count':len(data['result']['symbols']),
                                 'latency_ms':round((time.monotonic()-started)*1000)}
    except Exception as error:
        code=getattr(error,'code',None)
        result['wallex_public']={'status':'FAILED','error_type':type(error).__name__,
                                 'http_code':code if isinstance(code,int) else None}
    started=time.monotonic()
    if not key_configured(os.environ.get('BOXAPI_API_KEY')) and boxapi is None:
        result['boxapi_catalog']={'status':'MISSING_KEY','requested_model_available':None}
    else:
        try:
            _,model=active_llm()
            provider=boxapi or BoxAPIProvider(model,attempts=1)
            try:available=provider.available_models()
            finally:
                if boxapi is None:provider.close()
            result['boxapi_catalog']={'status':'OK','requested_model_available':model in available,
                                      'latency_ms':round((time.monotonic()-started)*1000)}
        except Exception as error:
            result['boxapi_catalog']={'status':'FAILED','error_type':type(error).__name__,**safe_error(error)}
    result['wallex_private']={'status':'NOT_ATTEMPTED','reason':'no authenticated competition-account contract/credential verification'}
    return result


def main(argv=None):
    load_env()
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['status','probe'])
    parser.add_argument('--online',action='store_true')
    parser.add_argument('--execution-site',choices=['local','liara-runtime'],default='local')
    parser.add_argument('--output')
    args=parser.parse_args(argv)
    try:
        validate_read_only()
        if args.command=='probe' and not args.online:raise ValueError('probe requires explicit --online')
        report=readiness() if args.command=='status' else probe(args.execution_site)
        if args.output:
            path=Path(args.output);path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
        print(json.dumps(report,indent=2,ensure_ascii=False))
        if args.command=='probe' and (report['wallex_public']['status']!='OK' or report['boxapi_catalog']['status']!='OK'):return 2
        return 0
    except ValueError as error:
        print(json.dumps({'status':'BLOCKED','reason':str(error)}));return 2


if __name__=='__main__':raise SystemExit(main())
