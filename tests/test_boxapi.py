import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import httpx2
from openai import OpenAI

from test_core import fixture
from wallex_agent.ai import Agent, Provider, parse_decision
from wallex_agent.boxapi import BoxAPIProvider, BASE_URLS, discover_catalog, resolve_model, candidate_models
from wallex_agent.boxapi_verify import verify
from wallex_agent.engine import Config
from wallex_agent.journal import Journal
from wallex_agent.settings import active_llm, load_env, update_boxapi
from wallex_agent.shadow import Shadow


def completion(action='ENTER', allocation=.1, **updates):
    body={'id':'offline-completion','created':1,'object':'chat.completion','model':'gpt-5.4-mini',
          'choices':[{'index':0,'finish_reason':'stop','message':{'role':'assistant','content':json.dumps({
              'action':action,'allocation':allocation,'confidence':.9,'reason':'candidate and risk_cap reviewed'})}}],
          'usage':{'prompt_tokens':100,'completion_tokens':40,'total_tokens':140}}
    body.update(updates)
    return body


def provider(handler):
    client=OpenAI(api_key='offline-dummy-key',base_url=BASE_URLS[0],max_retries=0,timeout=2,
                  http_client=httpx2.Client(transport=httpx2.MockTransport(handler),follow_redirects=False))
    return BoxAPIProvider(client=client)


class BoxAPITests(unittest.TestCase):
    def test_sdk_route_schema_and_token_usage(self):
        requests=[]
        def respond(request):
            requests.append(request)
            return httpx2.Response(200,json=completion())
        p=provider(respond)
        try:
            self.assertEqual(parse_decision(p({'risk_cap':.2})).action,'ENTER')
            request=requests[0]
            self.assertEqual(str(request.url),BASE_URLS[0]+'/chat/completions')
            body=json.loads(request.content)
            self.assertTrue(body['response_format']['json_schema']['strict'])
            self.assertFalse(body['store']);self.assertFalse(body['stream'])
            self.assertEqual(body['max_completion_tokens'],1024)
            self.assertEqual(p.last_metadata['usage']['total_tokens'],140)
            self.assertTrue(p.last_metadata['validated_json'])
            self.assertNotIn('offline-dummy-key',json.dumps(p.last_metadata))
        finally:p.close()

    def test_placeholder_never_constructs_sdk(self):
        with patch.dict(os.environ,{'BOXAPI_API_KEY':'YOUR_BOXAPI_API_KEY_HERE'}):
            with patch('wallex_agent.boxapi.OpenAI') as sdk:
                with self.assertRaises(ValueError):BoxAPIProvider().get_client()
                sdk.assert_not_called()

    def test_timeout_bound_redirect_policy_and_no_hidden_retries(self):
        with patch.dict(os.environ,{'BOXAPI_API_KEY':'offline-test'}):
            with patch('wallex_agent.boxapi.OpenAI') as sdk:
                with patch('wallex_agent.boxapi.DefaultHttpxClient') as http:
                    BoxAPIProvider(timeout=12).get_client()
                    self.assertEqual(sdk.call_args.kwargs['max_retries'],0)
                    self.assertEqual(sdk.call_args.kwargs['timeout'],12)
                    self.assertFalse(http.call_args.kwargs['follow_redirects'])
        for base in ['http://ai.boxapi.ir/ai/v1','https://evil.example/v1','https://ai.boxapi.ir@evil.example/ai/v1']:
            with self.assertRaises(ValueError):BoxAPIProvider(base_url=base)

    def test_503_retry_bounded_and_counted(self):
        calls=[]
        def respond(r):
            calls.append(1)
            return httpx2.Response(503,json={'error':{'message':'secret marker'}}) if len(calls)==1 else httpx2.Response(200,json=completion())
        p=provider(respond)
        try:
            with patch('wallex_agent.boxapi.time.sleep'):p({'risk_cap':.2})
            self.assertEqual(len(calls),2)
            self.assertEqual(p.last_metadata['billing_unknown_attempts'],1)
        finally:p.close()

    def test_auth_schema_and_timeouts_fail_closed_without_retry(self):
        for kind in (403,400,'timeout'):
            calls=[]
            def fail(request):
                calls.append(1)
                if kind=='timeout':raise httpx2.ReadTimeout('SECRET_MARKER',request=request)
                return httpx2.Response(kind,json={'error':{'message':'SECRET_MARKER'}})
            p=provider(fail);j=Journal(':memory:')
            try:
                decision,trace=Agent(p,j,model='boxapi:test').decide({'sample':kind})
                self.assertEqual(decision.action,'HOLD')
                self.assertEqual(trace['status'],'failed_closed');self.assertEqual(len(calls),1)
                self.assertNotIn('SECRET_MARKER',json.dumps(trace))
            finally:p.close();j.close()

    def test_rejects_truncation_refusal_invalid_bounds_and_extra_fields(self):
        for body in [completion(choices=[{'index':0,'finish_reason':'length','message':{'role':'assistant','content':'{}'}}]),
                     completion(allocation=.3),completion(choices=[{'index':0,'finish_reason':'stop','message':{'role':'assistant','content':'{}','refusal':'no'}}])]:
            p=provider(lambda r:httpx2.Response(200,json=body))
            try:
                with self.assertRaises(ValueError):p({'x':1})
            finally:p.close()

    def test_actual_sdk_adapter_changes_shadow_and_cannot_bypass_risk(self):
        bars=fixture(200);now=bars[-1].timestamp+3600;mid=bars[-1].close
        cfg=Config(initial_cash=10000,min_notional=1)
        for action,deadline,expected_positive in [('ENTER',None,True),('EXIT',None,False),('ENTER',now+600,False)]:
            p=provider(lambda r:httpx2.Response(200,json=completion(action,.1 if action=='ENTER' else 0)))
            j=Journal(':memory:')
            try:
                agent=Agent(p,j,model='boxapi:offline-test')
                event=Shadow(j,replace(cfg,deadline=deadline),'BTCTMN','buy_hold',agent).step(bars,mid,mid*1.001,now)
                self.assertEqual(event['target']>0,expected_positive)
                self.assertEqual(event['agent']['status'],'ok')
                self.assertEqual(event['agent']['provider_metadata']['provider'],'boxapi')
                self.assertGreater(j.verify(),0)
            finally:p.close();j.close()

    def test_endpoint_discovery_and_catalog_bound(self):
        created=[]
        def factory(model,**kwargs):
            created.append(kwargs['base_url'])
            code=404 if kwargs['base_url']==BASE_URLS[0] else 200
            p=provider(lambda r:httpx2.Response(code,json={'data':[{'id':'gpt-5.4-mini','object':'model','created':1,'owned_by':'test'}]}))
            p.base_url=kwargs['base_url']
            return p
        with patch.dict(os.environ,{'BOXAPI_BASE_URL':BASE_URLS[0]}):
            p,models,probes=discover_catalog(factory=factory)
        self.assertEqual(created,list(BASE_URLS));self.assertEqual(models,['gpt-5.4-mini'])
        self.assertEqual(probes[-1]['status'],'CATALOG_OK');p.close()

    def test_only_boxapi_active_and_provider_bridge(self):
        with patch.dict(os.environ,{'LLM_PROVIDER':'boxapi','BOXAPI_MODEL':'gpt-5.4-mini'}):
            self.assertEqual(active_llm(),('boxapi','gpt-5.4-mini'))
            with patch('wallex_agent.boxapi.BoxAPIProvider') as factory:
                p=Provider('boxapi','gpt-5.4-mini');p({'x':1})
                factory.return_value.assert_called_once_with({'x':1})
        with patch.dict(os.environ,{'LLM_PROVIDER':'gemini'}):
            with self.assertRaises(ValueError):active_llm()

    def test_env_preserves_old_credentials_and_online_placeholder_never_networks(self):
        with tempfile.TemporaryDirectory() as d:
            file=Path(d)/'.env';file.write_text('GEMINI_API_KEY=preserved-offline\nBOXAPI_API_KEY=preserved-box\n')
            with patch.dict(os.environ,{},clear=True):
                update_boxapi(BASE_URLS[1],'gpt-5.4-mini',file);load_env(file)
                self.assertEqual(os.environ['GEMINI_API_KEY'],'preserved-offline')
                self.assertEqual(os.environ['BOXAPI_API_KEY'],'preserved-box')
            env={'LLM_PROVIDER':'boxapi','BOXAPI_API_KEY':'YOUR_BOXAPI_API_KEY_HERE'}
            with patch.dict(os.environ,env,clear=True):
                with patch('wallex_agent.boxapi_verify.discover_catalog') as discover:
                    r=verify(online=True,output=str(Path(d)/'report.json'))
                    discover.assert_not_called();self.assertEqual(r['status'],'MISSING_KEY')
                    self.assertFalse(r['real_inference_verified'])

    def test_verification_selection_and_fresh_journal_with_mocked_http(self):
        import wallex_agent.boxapi_verify as module
        original=Path.cwd()
        with tempfile.TemporaryDirectory() as d:
            try:
                os.chdir(d)
                Path('.env').write_text('BOXAPI_API_KEY=offline-preserved-key\nGEMINI_API_KEY=offline-preserved-old\n')
                p=provider(lambda r:httpx2.Response(200,json=completion('HOLD',0)))
                env={'LLM_PROVIDER':'boxapi','BOXAPI_API_KEY':'offline-test','BOXAPI_MODEL':'gpt-5.4-mini'}
                with patch.dict(os.environ,env,clear=True):
                    with patch.object(module,'discover_catalog',return_value=(p,['gpt-5.4-mini'],[])):
                        with patch.object(module,'update_boxapi',side_effect=lambda base,model:update_boxapi(base,model,Path('.env'))):
                            report=verify(online=True,samples=2)
                self.assertEqual(report['status'],'ONLINE_OK')
                self.assertEqual(report['journal_events'],4)
                self.assertEqual(len(list(Path('state').glob('*.sqlite'))),1)
                self.assertIn('BOXAPI_API_KEY=offline-preserved-key',Path('.env').read_text())
                self.assertEqual(len(Path(report['decision_log']).read_text().splitlines()),4)
            finally:os.chdir(original)

    def test_verifier_rejects_entry_without_edge_or_missing_token_accounting(self):
        import wallex_agent.boxapi_verify as module
        original=Path.cwd()
        for body in [completion('ENTER',.1),completion('HOLD',0,usage=None)]:
            with tempfile.TemporaryDirectory() as d:
                try:
                    os.chdir(d)
                    p=provider(lambda r:httpx2.Response(200,json=body))
                    with patch.dict(os.environ,{'LLM_PROVIDER':'boxapi','BOXAPI_API_KEY':'offline-test'},clear=True):
                        with patch.object(module,'discover_catalog',return_value=(p,['gpt-5.4-mini'],[])):
                            with patch.object(module,'update_boxapi') as update:
                                report=verify(online=True,samples=1)
                                update.assert_not_called()
                    self.assertEqual(report['status'],'NO_QUALIFIED_MODEL')
                    self.assertFalse(report['model_trials'][0]['all_samples_valid'])
                finally:os.chdir(original)

    def test_model_resolution_preserves_exact_catalog_ids_and_versions(self):
        catalog=['openai/gpt-5.4-mini','openai/gpt-5.4-mini:batch',
                 'openai/gpt-5.4-nano','openai/gpt-5.4-mini-2099-01-01']
        self.assertEqual(resolve_model('gpt-5.4-mini',catalog),'openai/gpt-5.4-mini')
        self.assertEqual(resolve_model('openai/gpt-5.4-mini',catalog),'openai/gpt-5.4-mini')
        self.assertEqual(candidate_models('gpt-5.4-mini',catalog),
                         ['openai/gpt-5.4-mini','openai/gpt-5.4-nano'])
        self.assertIsNone(resolve_model('gpt-5.4-mini',['openai/gpt-5.4-mini:batch']))
        self.assertIsNone(resolve_model('another/gpt-5.4-mini',catalog))
        self.assertEqual(resolve_model('openai/gpt-5.4-mini',['gpt-5.4-mini']),'gpt-5.4-mini')

    def test_ambiguous_bare_model_is_not_silently_routed(self):
        catalog=['openai/shared','another/shared']
        with self.assertRaises(ValueError):resolve_model('shared',catalog)
        self.assertEqual(resolve_model('openai/shared',catalog),'openai/shared')

    def test_verification_sends_prefixed_id_to_real_sdk_transport(self):
        import wallex_agent.boxapi_verify as module
        original=Path.cwd();sent=[]
        def respond(request):
            model=json.loads(request.content)['model'];sent.append(model)
            return httpx2.Response(200,json=completion('HOLD',0,model=model))
        with tempfile.TemporaryDirectory() as d:
            try:
                os.chdir(d)
                p=provider(respond)
                with patch.dict(os.environ,{'LLM_PROVIDER':'boxapi','BOXAPI_API_KEY':'offline-test',
                                           'BOXAPI_MODEL':'gpt-5.4-mini'},clear=True):
                    with patch.object(module,'discover_catalog',return_value=(p,['openai/gpt-5.4-mini'],[])):
                        with patch.object(module,'update_boxapi') as update:
                            r=verify(online=True,samples=2)
                            self.assertEqual(update.call_args.args[1],'openai/gpt-5.4-mini')
                self.assertEqual(r['status'],'ONLINE_OK')
                self.assertEqual(sent,['openai/gpt-5.4-mini']*2)
                self.assertEqual(r['selected_model'],'openai/gpt-5.4-mini')
            finally:os.chdir(original)


if __name__=='__main__':unittest.main()
