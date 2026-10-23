import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from google.genai import types
from wallex_agent.ai import Agent,parse_decision
from wallex_agent.gemini import GeminiProvider,choose_model,safe_error
from wallex_agent.journal import Journal
from wallex_agent.settings import load_env,key_configured,update_model


def response(action='HOLD',allocation=0):
    return types.GenerateContentResponse(
        candidates=[types.Candidate(finish_reason='STOP',content=types.Content(parts=[types.Part(
            text=json.dumps({'action':action,'allocation':allocation,'confidence':.9,'reason':'features show uncertainty'}))]))],
        usage_metadata=types.GenerateContentResponseUsageMetadata(prompt_token_count=100,
            candidates_token_count=40,total_token_count=140),model_version='gemini-3.8-flash')


class GeminiTests(unittest.TestCase):
    def test_provider_error_redacts_arbitrary_message(self):
        class Error(Exception):
            code=400
            message='API key not valid; private=SECRET_EXAMPLE'
        result=safe_error(Error())
        self.assertEqual(result['category'],'INVALID_API_KEY')
        self.assertNotIn('SECRET',str(result))

    def test_client_timeout_and_no_hidden_sdk_retries(self):
        with patch.dict(os.environ,{'GEMINI_API_KEY':'offline-dummy-not-a-real-key'}):
            with patch('google.genai.Client') as factory:
                GeminiProvider('gemini-3.8-flash').get_client()
                options=factory.call_args.kwargs['http_options']
                self.assertEqual(options.timeout,15000)
                self.assertEqual(options.retry_options.attempts,1)

    def test_sdk_json_and_usage(self):
        calls=[]
        def generate(**kwargs):calls.append(kwargs);return response('ENTER',.1)
        provider=GeminiProvider('gemini-3.8-flash',client=SimpleNamespace(models=SimpleNamespace(generate_content=generate)))
        decision=parse_decision(provider({'features':[1,2],'roundtrip_cost':.009}))
        self.assertEqual(decision.action,'ENTER')
        self.assertEqual(calls[0]['config'].response_mime_type,'application/json')
        self.assertEqual(calls[0]['config'].max_output_tokens,1024)
        self.assertEqual(provider.last_metadata['usage']['total_token_count'],140)

    def test_transient_retry_bounded(self):
        class Transient(Exception):code=503
        calls=[]
        def generate(**kwargs):
            calls.append(kwargs)
            if len(calls)==1:raise Transient('not logged')
            return response()
        p=GeminiProvider('gemini-3.8-flash',client=SimpleNamespace(models=SimpleNamespace(generate_content=generate)))
        with patch('wallex_agent.gemini.time.sleep'):p({'x':1})
        self.assertEqual(len(calls),2)
        self.assertEqual(p.last_metadata['billing_unknown_attempts'],1)

    def test_auth_failure_no_retry_and_safe_hold(self):
        class Unauthorized(Exception):code=403
        calls=[]
        def fail(**kwargs):calls.append(1);raise Unauthorized('SECRET NEVER LOG')
        with tempfile.TemporaryDirectory() as d:
            j=Journal(str(Path(d)/'ai.db'))
            p=GeminiProvider('gemini-3.8-flash',client=SimpleNamespace(models=SimpleNamespace(generate_content=fail)))
            agent=Agent(p,j,model='gemini-3.8-flash')
            decision,trace=agent.decide({'expected_return':.01})
            self.assertEqual(decision.action,'HOLD');self.assertEqual(len(calls),1)
            self.assertNotIn('SECRET',str(trace));j.close()

    def test_placeholder_never_calls_client(self):
        with patch.dict(os.environ,{'GEMINI_API_KEY':'YOUR_GEMINI_API_KEY_HERE'}):
            with patch('google.genai.Client') as client:
                with self.assertRaises(ValueError):GeminiProvider('gemini-3.8-flash').get_client()
                client.assert_not_called()

    def test_catalog_selection_only_authenticated_options(self):
        models=[types.Model(name='models/gemini-3.8-flash',supported_actions=['generateContent']),
                types.Model(name='models/embedding',supported_actions=['embedContent'])]
        p=GeminiProvider('gemini-3.8-flash',client=SimpleNamespace(models=SimpleNamespace(list=lambda:models)))
        self.assertEqual(p.available_models(),['gemini-3.8-flash'])
        self.assertEqual(choose_model('missing',p.available_models()),'gemini-3.8-flash')
        with self.assertRaises(ValueError):choose_model('missing',['embedding'])

    def test_env_no_shell_and_preserve_secrets(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'.env';p.write_text('GEMINI_MODEL=old\nGEMINI_API_KEY=local-test\nUNKNOWN=$(danger)\n')
            with patch.dict(os.environ,{},clear=True):
                load_env(p);self.assertNotIn('UNKNOWN',os.environ)
                update_model('gemini-3.8-flash',p)
                self.assertIn('GEMINI_API_KEY=local-test',p.read_text())
                self.assertEqual(os.environ['GEMINI_MODEL'],'gemini-3.8-flash')
        self.assertFalse(key_configured('YOUR_GEMINI_API_KEY_HERE'))
