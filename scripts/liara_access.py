"""Explicit project-scoped Liara CLI access. No deploy/create/restart/delete operations."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from wallex_agent.settings import load_env

CLI=ROOT/'.tools/liara-cli/node_modules/.bin/liara'


def target_args(env, *, require_app=False):
    keys=['LIARA_ACCOUNT','LIARA_TEAM_ID']+(['LIARA_APP_NAME'] if require_app else [])
    for key in keys:
        value=env.get(key,'')
        if not re.fullmatch(r'[A-Za-z0-9_.@-]{1,160}',value):
            raise ValueError('Set '+key+' in local .env; never fall back to the current personal account')
    result=['--account',env['LIARA_ACCOUNT'],'--team-id',env['LIARA_TEAM_ID']]
    if require_app:result+=['--app',env['LIARA_APP_NAME']]
    return result


def command(action,env):
    if action=='version':return [str(CLI),'--version']
    if action=='login':return [str(CLI),'login','--browser','chrome']
    if action=='whoami':return [str(CLI),'account','whoami','--json',*target_args(env)]
    if action=='apps':return [str(CLI),'app','list','--output','json',*target_args(env)]
    if action=='verify-boxapi':return [str(CLI),'shell',*target_args(env,require_app=True),'--command',
        'python -m wallex_agent.cli verify-boxapi --online --samples 2']
    if action=='probe':return [str(CLI),'shell',*target_args(env,require_app=True),'--command',
        'python -m wallex_agent.access probe --online --execution-site liara-runtime']
    raise ValueError('operation not allowed')


def main(argv=None):
    load_env()
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['version','login','whoami','apps','probe','verify-boxapi'])
    args=parser.parse_args(argv)
    try:
        cmd=command(args.action,os.environ)
        if not CLI.exists():raise ValueError('project-scoped official CLI is not installed')
        # No API tokens or passwords in command line or output; browser handles authentication.
        # Interactive login is intentionally initiated by the operator.
        if args.action in {'version','login'}:return subprocess.call(cmd,cwd=ROOT)
        result=subprocess.run(cmd,cwd=ROOT,text=True,capture_output=True,timeout=90)
        if result.returncode:
            print(json.dumps({'status':'BLOCKED','operation':args.action,'exit_code':result.returncode,
                              'reason':'CLI authentication, team access or runtime unavailable; raw output redacted'}))
            return 2
        data=json.loads(result.stdout)
        if args.action=='whoami':
            identity=data.get('result',data) if isinstance(data,dict) else {}
            team=identity.get('team') or {}
            if team.get('id')!=os.environ['LIARA_TEAM_ID'] or team.get('member') is not True:
                raise ValueError('CLI did not verify membership of the explicitly selected hackathon team')
        if args.action=='verify-boxapi':
            print(json.dumps(data,indent=2));return 0
        if args.action=='probe':
            # Runtime probe emits only a fixed, redacted schema.
            allowed={'observed_at','execution_site_claim','deployment_region_verified','runtime_region_claim',
                     'region_evidence','live_orders','private_wallex_requests','generation_requests',
                     'wallex_public','boxapi_catalog','wallex_private'}
            data={k:v for k,v in data.items() if k in allowed}
            print(json.dumps(data,indent=2));return 0
        # Identity values are kept local; avoid forwarding arbitrary CLI payloads or tokens.
        print(json.dumps({'status':'CLI_READ_SUCCEEDED','operation':args.action,
                          'explicit_account_and_team':True,'item_count':len(data) if isinstance(data,list) else None,
                          'note':'Use the Liara panel to compare the selected team with team Kav'}))
        return 0
    except (ValueError,subprocess.TimeoutExpired,json.JSONDecodeError) as error:
        print(json.dumps({'status':'BLOCKED','error_type':type(error).__name__,
                          'reason':str(error) if type(error) is ValueError else 'CLI output redacted'}));return 2


if __name__=='__main__':raise SystemExit(main())
