"""No permissive fallback from challenge credit account to personal spot account."""
from datetime import datetime
from zoneinfo import ZoneInfo


def parse_tehran_deadline(value: str) -> int:
    dt=datetime.fromisoformat(value)
    if dt.tzinfo is None:
        raise ValueError('deadline must include explicit offset; do not infer trading cutoff')
    return int(dt.astimezone(ZoneInfo('Asia/Tehran')).timestamp())


def live_blockers() -> list[str]:
    # Cannot be cleared by environment booleans or a user-written JSON flag.
    return ['BLOCKED: isolated competition credit account identity and route not verified',
            'BLOCKED: official challenge market allowlist not verified',
            'BLOCKED: exact trading cutoff and timezone not verified',
            'BLOCKED: actual fee schedule and permissions not verified',
            'BLOCKED: explicit live-trading approval not received',
            'BLOCKED: production broker is intentionally unavailable pending verified contract']


def require_live() -> None:
    raise PermissionError('\n'.join(live_blockers()))
