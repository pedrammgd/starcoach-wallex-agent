"""Official Google GenAI SDK adapter; actual orders are outside this module."""
from __future__ import annotations
import os
import random
import time
from typing import Any

from .settings import key_configured


def safe_error(error: Exception) -> dict:
    """Classify known provider failures without logging arbitrary credential-bearing text."""
    code=getattr(error,'code',None)
    message=str(getattr(error,'message','')).lower()
    category=next((label for match,label in (
        ('location','LOCATION_UNSUPPORTED'),('api key not valid','INVALID_API_KEY'),
        ('api_key_invalid','INVALID_API_KEY'),('expired','CREDENTIAL_EXPIRED'),
        ('quota','QUOTA_LIMIT'),('permission','PERMISSION_DENIED'),('not found','NOT_FOUND'))
        if match in message),'UNCLASSIFIED_PROVIDER_ERROR')
    return {'provider_code':code if isinstance(code,int) else None,'category':category}


class GeminiProvider:
    def __init__(self,model: str, *, client=None, attempts: int=2, timeout_ms: int=15000):
        if attempts not in (1,2) or not 1000<=timeout_ms<=30000:
            raise ValueError('invalid Gemini request budget')
        self.model,self.client,self.attempts,self.timeout_ms=model,client,attempts,timeout_ms
        self.last_metadata: dict[str,Any]={}

    def get_client(self):
        if self.client is not None:return self.client
        key=os.environ.get('GEMINI_API_KEY')
        if not key_configured(key):raise ValueError('Gemini key missing or placeholder')
        from google import genai
        from google.genai import types
        self.client=genai.Client(api_key=key,http_options=types.HttpOptions(
            timeout=self.timeout_ms,retry_options=types.HttpRetryOptions(attempts=1)))
        return self.client

    def __call__(self,context: dict) -> str:
        from google.genai import types
        from .ai import PROMPT,DecisionSchema
        from .journal import canonical
        client=self.get_client()
        self.last_metadata={'provider':'gemini','requested_model':self.model,'attempts':0,
                            'usage':None,'billing_unknown_attempts':0}
        config=types.GenerateContentConfig(system_instruction=PROMPT,
            response_mime_type='application/json',response_json_schema=DecisionSchema.model_json_schema(),
            max_output_tokens=1024,thinking_config=types.ThinkingConfig(thinking_level='LOW'))
        for attempt in range(self.attempts):
            self.last_metadata['attempts']=attempt+1
            try:
                response=client.models.generate_content(model=self.model,contents=canonical(context),config=config)
                usage=response.usage_metadata
                self.last_metadata['usage']=usage.model_dump(mode='json',exclude_none=True) if usage else None
                self.last_metadata['returned_model_version']=getattr(response,'model_version',None)
                candidates=response.candidates or []
                if not candidates or str(candidates[0].finish_reason).split('.')[-1]!='STOP':
                    raise ValueError('Gemini incomplete/refused output')
                text=response.text
                if not isinstance(text,str) or len(text)>12000:raise ValueError('invalid Gemini output size')
                return text
            except Exception as error:
                code=getattr(error,'code',None)
                self.last_metadata['billing_unknown_attempts']+=1
                if code not in {429,500,502,503,504} or attempt+1>=self.attempts:
                    raise
                time.sleep(.5*(2**attempt)+random.random()*.1)
        raise RuntimeError('unreachable')

    def available_models(self) -> list[str]:
        models=[]
        for index,model in enumerate(self.get_client().models.list()):
            if index>=500:raise ValueError('model catalog exceeds bounded scan')
            name=(model.name or '').removeprefix('models/')
            actions=getattr(model,'supported_actions',None) or []
            if 'generateContent' in actions:models.append(name)
        return models


def choose_model(requested: str,available: list[str]) -> str:
    if requested in available:return requested
    # Explicitly authorized fallback, only from the authenticated catalog.
    for candidate in ('gemini-3.8-flash','gemini-3.6-flash','gemini-3.1-flash-lite','gemini-2.5-flash'):
        if candidate in available:return candidate
    raise ValueError('no supported approved fallback in authenticated catalog')
