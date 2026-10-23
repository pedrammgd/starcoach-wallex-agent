import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from wallex_agent.access import probe,readiness,validate_read_only
from wallex_agent.settings import key_configured,load_env

spec=importlib.util.spec_from_file_location('liara_access',Path('scripts/liara_access.py'))
liara=importlib.util.module_from_spec(spec);spec.loader.exec_module(liara)


class AccessTests(unittest.TestCase):
    def test_all_secret_placeholders_are_unconfigured(self):
        for value in ['',None,'YOUR_WALLEX_COMPETITION_READ_ONLY_API_KEY_HERE','YOUR_GEMINI_API_KEY_HERE','REPLACE_ME']:
            self.assertFalse(key_configured(value))

    def test_unsafe_flags_fail_before_network(self):
        for key,value in [('TRADING_MODE','live'),('ENABLE_LIVE_TRADING','true'),
                          ('WALLEX_ENABLE_TRANSFERS','true'),('WALLEX_ENABLE_WITHDRAWALS','true'),
                          ('WALLEX_PRIVATE_READS_ENABLED','true'),('WALLEX_READ_ONLY','false')]:
            with self.subTest(key=key):
                with self.assertRaises(ValueError):validate_read_only({key:value})

    def test_access_env_preserves_external_keys(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'.env';p.write_text('GEMINI_API_KEY=file-example\nWALLEX_API_KEY=YOUR_WALLEX_KEY\nWALLEX_READ_ONLY=true\nLIARA_TEAM_ID=team-example\n')
            with patch.dict(os.environ,{'GEMINI_API_KEY':'existing-example'},clear=True):
                load_env(p)
                self.assertEqual(os.environ['GEMINI_API_KEY'],'existing-example')
                self.assertFalse(key_configured(os.environ['WALLEX_API_KEY']))
                self.assertEqual(os.environ['LIARA_TEAM_ID'],'team-example')

    def test_probe_never_calls_private_or_generate(self):
        paths=[]
        class Public:
            def get(self,path):paths.append(path);return {'success':True,'result':{'symbols':{'BTCTMN':{}}}}
        class BoxAPI:
            def available_models(self):return ['gpt-5.4-mini']
        with patch.dict(os.environ,{},clear=True):
            r=probe('liara-runtime',wallex=Public(),boxapi=BoxAPI())
        self.assertEqual(paths,['/v1/markets'])
        self.assertFalse(r['generation_requests'])
        self.assertFalse(r['deployment_region_verified'])
        self.assertEqual(r['wallex_private']['status'],'NOT_ATTEMPTED')

    def test_error_contains_no_secret(self):
        class Failure(Exception):status_code=403;message='Permission denied SECRET_MARKER'
        class Public:
            def get(self,path):raise Failure()
        class BoxAPI:
            def available_models(self):raise Failure()
        with patch.dict(os.environ,{},clear=True):r=probe(wallex=Public(),boxapi=BoxAPI())
        self.assertNotIn('SECRET_MARKER',json.dumps(r))
        self.assertEqual(r['boxapi_catalog']['http_status'],403)

    def test_liara_no_personal_default_and_no_writes(self):
        for env in ({},{'LIARA_ACCOUNT':'a'},{'LIARA_TEAM_ID':'t'}):
            with self.assertRaises(ValueError):liara.target_args(env)
        env={'LIARA_ACCOUNT':'account-name','LIARA_TEAM_ID':'team-id','LIARA_APP_NAME':'hackathon-app'}
        command=liara.command('probe',env)
        self.assertIn('--team-id',command)
        self.assertIn('--account',command)
        self.assertNotIn('--api-token',command)
        for action in ['deploy','create','restart','delete','start','transfer']:
            with self.assertRaises(ValueError):liara.command(action,env)

    def test_liara_rejects_injected_target(self):
        with self.assertRaises(ValueError):liara.target_args({'LIARA_ACCOUNT':'a; echo x','LIARA_TEAM_ID':'t'})

    def test_no_claimed_account_verification_from_flags(self):
        with patch.dict(os.environ,{'WALLEX_API_KEY':'offline-example','WALLEX_ACCOUNT_SCOPE':'competition_credit',
                                   'WALLEX_CREDIT_ACCOUNT_ID':'test-id'},clear=True):r=readiness()
        self.assertFalse(r['wallex']['account_scope_verified'])
