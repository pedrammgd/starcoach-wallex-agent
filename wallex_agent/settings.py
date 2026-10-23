"""Small dotenv reader: no shell evaluation, no interpolation, no secret printing."""
import os
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
ENV_KEYS={'BOXAPI_API_KEY','BOXAPI_BASE_URL','BOXAPI_MODEL','BOXAPI_TIMEOUT_SECONDS','LLM_PROVIDER','GEMINI_API_KEY','GEMINI_MODEL','OPENAI_API_KEY','TRADING_MODE',
          'ENABLE_LIVE_TRADING','SSL_CERT_FILE','WALLEX_API_KEY','WALLEX_ACCOUNT_SCOPE',
          'WALLEX_CREDIT_ACCOUNT_ID','WALLEX_READ_ONLY','WALLEX_PRIVATE_READS_ENABLED',
          'WALLEX_ENABLE_WITHDRAWALS','WALLEX_ENABLE_TRANSFERS','LIARA_ACCOUNT',
          'LIARA_TEAM_ID','LIARA_APP_NAME','LIARA_RUNTIME_REGION'}


def load_env(path: Path | None = None) -> None:
    path=path or ROOT/'.env'
    if not path.exists():return
    for line in path.read_text().splitlines():
        line=line.strip()
        if not line or line.startswith('#'):continue
        key,separator,value=line.partition('=')
        if not separator or key.strip() not in ENV_KEYS:continue
        value=value.strip()
        if len(value)>1 and value[0]==value[-1] and value[0] in ('"',"'"):value=value[1:-1]
        os.environ.setdefault(key.strip(),value)


def key_configured(value: str | None) -> bool:
    return bool(value and value.strip() and not value.strip().upper().startswith('YOUR_')
                and value.strip().upper() not in {'CHANGE_ME','REPLACE_ME','UNSET'})


def update_model(value: str, path: Path | None = None) -> None:
    import re
    if not re.fullmatch('[A-Za-z0-9_.-]+',value):raise ValueError('invalid model ID')
    path=path or ROOT/'.env'
    lines=path.read_text().splitlines() if path.exists() else []
    lines=[line for line in lines if not line.startswith('GEMINI_MODEL=')]
    lines.append('GEMINI_MODEL='+value)
    path.write_text('\n'.join(lines)+'\n');path.chmod(0o600)
    os.environ['GEMINI_MODEL']=value


def active_llm() -> tuple[str, str]:
    """Only BoxAPI is enabled for the hackathon's active pipeline."""
    provider=os.environ.get('LLM_PROVIDER','boxapi')
    if provider!='boxapi':raise ValueError('Only BoxAPI is enabled; set LLM_PROVIDER=boxapi')
    return provider,os.environ.get('BOXAPI_MODEL','openai/gpt-5.4-mini')


def update_boxapi(base_url: str, model: str, path: Path | None = None) -> None:
    import re
    from .boxapi import BASE_URLS
    if base_url not in BASE_URLS or not re.fullmatch(r'[A-Za-z0-9_.:/-]{1,120}',model):
        raise ValueError('invalid verified BoxAPI configuration')
    path=path or ROOT/'.env'
    lines=path.read_text().splitlines() if path.exists() else []
    updates={'BOXAPI_BASE_URL':base_url,'BOXAPI_MODEL':model}
    lines=[line for line in lines if line.partition('=')[0] not in updates]
    lines.extend(key+'='+value for key,value in updates.items())
    path.write_text('\n'.join(lines)+'\n');path.chmod(0o600)
    os.environ.update(updates)
