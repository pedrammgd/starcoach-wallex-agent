"""BoxAPI via the official OpenAI SDK. No broker tools or automatic provider fallback."""
from __future__ import annotations

import math
import os
import re
import ssl
import time

from openai import OpenAI, DefaultHttpxClient

from .settings import key_configured

BASE_URLS = ('https://ai.boxapi.ir/ai/v1', 'https://ai.boxapi.ir/api/v1')
DEFAULT_MODEL = 'openai/gpt-5.4-mini'


def resolve_model(requested: str, catalog: list[str]) -> str | None:
    """Return an exact catalog ID. Never fuzzy-match variants or cross explicit vendors."""
    available=set(catalog)
    if requested in available:return requested
    if '/' in requested:
        # Some compatible catalogs use bare IDs. An explicit vendor never matches another vendor.
        bare=requested.rsplit('/',1)[-1]
        return bare if bare in available else None
    matches=sorted(m for m in available if m.rsplit('/',1)[-1]==requested)
    if len(matches)>1:raise ValueError('ambiguous unqualified BoxAPI model; configure its full catalog ID')
    return matches[0] if matches else None


def candidate_models(requested: str, catalog: list[str]) -> list[str]:
    resolved=[]
    for candidate in (requested,DEFAULT_MODEL,'openai/gpt-5.4-nano'):
        model=resolve_model(candidate,catalog)
        if model is not None and model not in resolved:resolved.append(model)
    return resolved


def safe_error(error: Exception) -> dict:
    # Never serialize provider messages, bodies, headers, URLs, or request objects.
    code = getattr(error, 'status_code', None)
    return {'error_type': type(error).__name__,
            'http_status': code if isinstance(code, int) else None}


class BoxAPIProvider:
    def __init__(self, model=DEFAULT_MODEL, *, base_url=None, timeout=None, attempts=2,
                 client=None, ca_file=None):
        self.base_url = (base_url or os.environ.get('BOXAPI_BASE_URL') or BASE_URLS[0]).rstrip('/')
        if self.base_url not in BASE_URLS:
            raise ValueError('BoxAPI base URL must be an official HTTPS endpoint')
        if not re.fullmatch(r'[A-Za-z0-9_.:/-]{1,120}', model):
            raise ValueError('invalid BoxAPI model ID')
        self.timeout = float(timeout if timeout is not None else os.environ.get('BOXAPI_TIMEOUT_SECONDS', '20'))
        if not math.isfinite(self.timeout) or not 1 <= self.timeout <= 60 or not 1 <= attempts <= 2:
            raise ValueError('invalid BoxAPI request budget')
        self.model, self.attempts, self.client = model, attempts, client
        self.ca_file = ca_file or os.environ.get('SSL_CERT_FILE')
        self.last_metadata = {}

    def get_client(self):
        if self.client is None:
            key = os.environ.get('BOXAPI_API_KEY')
            if not key_configured(key):
                raise ValueError('Replace YOUR_BOXAPI_API_KEY_HERE in project .env')
            # No redirect can forward this key elsewhere. Disable SDK retries; retry policy below.
            http = DefaultHttpxClient(verify=ssl.create_default_context(cafile=self.ca_file),
                                      follow_redirects=False)
            self.client = OpenAI(api_key=key, base_url=self.base_url, timeout=self.timeout,
                                 max_retries=0, http_client=http)
        return self.client

    def close(self):
        if self.client is not None:
            self.client.close()
            self.client = None

    def available_models(self) -> list[str]:
        page = self.get_client().models.list()
        # Bound pagination: never follow an API-supplied next-page URL with credentials.
        data = page.data
        if len(data) > 2000:
            raise ValueError('oversized BoxAPI catalog')
        return sorted({m.id for m in data if isinstance(m.id, str)})

    def __call__(self, context: dict) -> str:
        from .ai import PROMPT, SCHEMA, parse_decision
        from .journal import canonical
        if len(canonical(context)) > 12000:
            raise ValueError('oversized BoxAPI context')
        started = time.monotonic()
        self.last_metadata = {'provider': 'boxapi', 'base_url': self.base_url,
            'requested_model': self.model, 'attempts': 0, 'billing_unknown_attempts': 0,
            'schema_format': 'json_schema', 'usage': None}
        try:
            client = self.get_client()
            for attempt in range(self.attempts):
                self.last_metadata['attempts'] = attempt + 1
                try:
                    response = client.chat.completions.create(model=self.model,
                        messages=[{'role':'system','content':PROMPT},
                                  {'role':'user','content':canonical(context)}],
                        response_format={'type':'json_schema','json_schema':{
                            'name':'trade_proposal','strict':True,'schema':SCHEMA}},
                        max_completion_tokens=1024, stream=False, store=False)
                    break
                except Exception as error:
                    code = getattr(error, 'status_code', None)
                    # Timeout/connection failures are ambiguous and never automatically resent.
                    if code not in {429, 500, 502, 503, 504} or attempt + 1 == self.attempts:
                        raise
                    self.last_metadata['billing_unknown_attempts'] += 1
                    time.sleep(.5 * (attempt+1))
            usage = response.usage
            self.last_metadata.update({'returned_model': response.model,
                'usage': usage.model_dump(mode='json') if usage else None,
                'provider_reported_cost': (getattr(response, 'cost', None)
                    if type(getattr(response, 'cost', None)) in (int,float)
                    and math.isfinite(getattr(response, 'cost')) else None),
                'cost_unit': 'unverified; do not interpret as USD'})
            if len(response.choices) != 1:
                raise ValueError('BoxAPI must return exactly one completion')
            choice = response.choices[0]
            content = choice.message.content
            if choice.finish_reason != 'stop' or choice.message.refusal or not isinstance(content, str):
                raise ValueError('incomplete or refused BoxAPI decision')
            if len(content) > 8000:
                raise ValueError('oversized BoxAPI decision')
            # Treat compatible gateways as untrusted: validate locally even with strict schema.
            parse_decision(content)
            self.last_metadata['validated_json'] = True
            return content
        except Exception as error:
            self.last_metadata.update(safe_error(error))
            raise
        finally:
            self.last_metadata['latency_ms'] = round((time.monotonic()-started)*1000)


def discover_catalog(model=DEFAULT_MODEL, *, factory=BoxAPIProvider):
    """Read-only endpoint discovery on the two documented, allowlisted routes only."""
    configured = os.environ.get('BOXAPI_BASE_URL', BASE_URLS[0]).rstrip('/')
    if configured not in BASE_URLS:
        raise ValueError('invalid BoxAPI configured endpoint')
    probes = []
    for base in dict.fromkeys((configured, *BASE_URLS)):
        provider = factory(model, base_url=base, attempts=1)
        try:
            models = provider.available_models()
            if not models:
                raise ValueError('empty BoxAPI model catalog')
            probes.append({'base_url':base,'status':'CATALOG_OK','model_count':len(models)})
            return provider, models, probes
        except Exception as error:
            probes.append({'base_url':base,'status':'FAILED',**safe_error(error)})
            provider.close()
    return None, [], probes
