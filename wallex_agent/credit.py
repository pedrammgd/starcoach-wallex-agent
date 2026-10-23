"""Documented credit discovery. GET-only, fixed origin, no raw private logs.

Successful discovery never authorizes spot routing or enables live trading.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import time
from decimal import Decimal, InvalidOperation

import httpx

from .settings import key_configured, load_env

ORIGIN = 'https://api.wallex.ir'
PATHS = frozenset({'/v1/prop/user/packages/history', '/sub-accounts',
                   '/v1/prop/user/packages/overview', '/v1/prop/user/packages/active',
                   '/v1/account/balances-detail', '/v1/prop/packages', '/v1/account/fee'})


def fingerprint(value):
    return hashlib.sha256(str(value).encode()).hexdigest()[:12] if value else None


class ReadFailure(Exception):
    def __init__(self, status, kind):
        self.status, self.kind = status, kind
        super().__init__(kind)  # Never retain arbitrary provider messages/headers.


class CreditReader:
    def __init__(self, key, *, transport=None):
        if not key_configured(key):
            raise ValueError('WALLEX_API_KEY is missing or placeholder')
        self._key = key
        self.client = httpx.Client(base_url=ORIGIN, timeout=httpx.Timeout(20),
                                   follow_redirects=False, transport=transport)
        self.observations = []

    def close(self):
        self.client.close()

    def get(self, path, subaccount=None):
        if path not in PATHS and not re.fullmatch(r'/v1/prop/packages/[1-9][0-9]*', path):
            raise PermissionError('undocumented or non-allowlisted read refused')
        headers = {'X-API-Key': self._key, 'Accept': 'application/json'}
        if subaccount:
            if path not in {'/v1/prop/user/packages/active', '/v1/account/balances-detail'}:
                raise PermissionError('subaccount header unsupported for this operation')
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,160}', subaccount):
                raise ValueError('invalid subaccount identifier')
            headers['sub-account-client-id'] = subaccount
        started = time.monotonic()
        observation = {'path': path, 'method': 'GET', 'account_scoped': bool(subaccount),
                       'observed_at': datetime.now(timezone.utc).isoformat()}
        try:
            response = self.client.get(path, headers=headers)
            observation.update(http_status=response.status_code,
                               latency_ms=round((time.monotonic()-started)*1000),
                               server_date=response.headers.get('date'))
            # Error identifiers only: never persist provider messages or private bodies.
            try:
                envelope = response.json()
            except ValueError:
                envelope = None
            if isinstance(envelope, dict):
                containers = [envelope]
                containers += [envelope[k] for k in ('error', 'result')
                               if isinstance(envelope.get(k), dict)]
                for container in containers:
                    for field in ('code', 'error_code', 'errorCode'):
                        code = container.get(field)
                        if type(code) is int or (isinstance(code, str) and
                                re.fullmatch(r'[A-Z][A-Z0-9_]{0,63}|[0-9]{1,12}', code)):
                            observation['response_error_code'] = code
                            break
                    if 'response_error_code' in observation:
                        break
            observation.setdefault('response_error_code', None)
            if response.status_code != 200:
                raise ReadFailure(response.status_code, 'HTTP_ERROR')
            try:
                data = response.json()
            except ValueError:
                raise ReadFailure(200, 'INVALID_JSON') from None
            if not isinstance(data, dict) or data.get('success') is not True:
                raise ReadFailure(200, 'UNSUCCESSFUL_OR_INVALID_ENVELOPE')
            observation['success'] = True
            return data
        except httpx.HTTPError:
            observation['error'] = 'TRANSPORT_ERROR'
            raise ReadFailure(None, 'TRANSPORT_ERROR') from None
        finally:
            self.observations.append(observation)


def competition_name(value):
    return bool(re.search(r'star\s*coach|hackathon|استار\s*کوچ|هکاتون', str(value or ''), re.I))


def safe_package(package, detail, balances=None):
    """Only competition facts; exclude user IDs, arbitrary titles and identifiers."""
    def scalar(v):
        return v if isinstance(v, (str, int, float, bool)) or v is None else None
    return {
        'competition_name_matched': competition_name(package.get('title')),
        'name': 'Starcoach/hackathon' if competition_name(package.get('title')) else 'unverified',
        'account_fingerprint': fingerprint(detail.get('subAccountClientId')),
        'currency': scalar(package.get('currency')),
        'start_balance': scalar(package.get('startBalance')),
        'loan': scalar(package.get('loan')), 'assurance': scalar(package.get('assurance')),
        'status': scalar(detail.get('status')), 'account_type': scalar(detail.get('type')),
        'created_at': scalar(detail.get('createdAt')), 'expires_at': scalar(detail.get('expireAt')),
        'current_valuation_TMN': scalar((balances or {}).get('total', {}).get('TMN')),
        'daily_financing_fee': scalar(package.get('dailyFeeAfterDiscount')),
        'financing_fee_is_not_trading_fee': True,
    }


def verify(reader):
    report = {'observed_at': datetime.now(timezone.utc).isoformat(), 'live_orders': False,
              'authenticated_writes': 0, 'api_key_valid': None,
              'key_permissions': 'UNVERIFIED: read success does not prove trade/withdraw permissions',
              'competition_account_confirmed': False, 'routing_verified': False,
              'competition_wallet_confirmed': False, 'competition_wallets': [],
              'allowed_markets_verified': False, 'trading_fees_verified': False,
              'history': {}, 'competition_candidates': []}
    try:
        history = reader.get('/v1/prop/user/packages/history')
        report['api_key_valid'] = True
        rows = history.get('result')
        if not isinstance(rows, list):
            raise ReadFailure(200, 'HISTORY_SCHEMA_MISMATCH')
        report['history'] = {'status': 'OK', 'record_count': len(rows),
                             'competition_named_records': sum(competition_name(x.get('package_title')) for x in rows if isinstance(x, dict))}
    except ReadFailure as e:
        report['history'] = {'status': e.kind, 'http_status': e.status}
        if e.status == 401:
            # A credit-product denial is not proof that a scoped key is invalid.
            # One distinct, documented basic read can distinguish the two cases.
            try:
                reader.get('/v1/account/fee')
                report['api_key_valid'] = True
                report['basic_read_accepted'] = True
                report['fee_account_scope_still_unverified'] = True
            except ReadFailure as basic:
                report['api_key_valid'] = False if basic.status == 401 else None
                report['basic_read_error'] = {'kind': basic.kind, 'http_status': basic.status}
                report['observations'] = reader.observations
                return report  # Never retry the failed request or switch credentials/origins.
    try:
        accounts = reader.get('/sub-accounts').get('result')
        if not isinstance(accounts, list):
            raise ReadFailure(200, 'SUBACCOUNTS_SCHEMA_MISMATCH')
        report['api_key_valid'] = True
        report['subaccounts_read'] = True
        # Only retain competition-named accounts; personal account facts are discarded.
        named = [x for x in accounts if isinstance(x, dict) and competition_name(x.get('title'))]
        report['competition_subaccounts'] = [
            {'account_fingerprint': fingerprint(x.get('clientId')), 'active': x.get('isActive'),
             'suspended': x.get('isSuspend'), 'type': x.get('type')} for x in named]
        for account in named:
            if not account.get('isActive') or account.get('isSuspend') is not False:
                continue
            cid = account.get('clientId')
            if not isinstance(cid, str):
                continue
            wallet = {'account_fingerprint':fingerprint(cid), 'competition_name_matched':True,
                      'active':True, 'suspended':False, 'type':account.get('type'),
                      'nominal_start_balance_verified':False, 'expiry_verified':False}
            try:
                balances = reader.get('/v1/account/balances-detail', cid).get('result', {})
                tmn = balances.get('TMN', {})
                wallet['cash_TMN'] = {k:tmn.get(k) for k in ('total','available','freeze')}
                wallet['current_5m_TMN_match'] = all(Decimal(str(tmn.get(k))) == Decimal(v)
                    for k,v in [('total','5000000'),('available','5000000'),('freeze','0')])
                wallet['wallet_read_success'] = True
            except (ReadFailure,InvalidOperation) as e:
                wallet['wallet_read_success'] = False
                wallet['wallet_error'] = {'kind':e.kind,'http_status':e.status} if isinstance(e,ReadFailure) else {'kind':'INVALID_DECIMAL'}
            report['competition_wallets'].append(wallet)
            report['competition_wallet_confirmed'] = len(named) == 1 and wallet.get('current_5m_TMN_match') is True and account.get('type') == 'prop'
            active = reader.get('/v1/prop/user/packages/active', cid).get('result', {})
            p, d = active.get('packageDetail', {}), active.get('userPackageDetail', {})
            safe = safe_package(p, {**d, 'subAccountClientId': cid}, active.get('balancesHistory'))
            safe['subaccount_type'] = account.get('type')
            # start balance, current valuation, status and expiry are independent evidence.
            safe['nominal_5m_TMN_match'] = p.get('currency') == 'TMN' and str(p.get('startBalance')) == '5000000'
            safe['account_identity_candidate'] = safe['competition_name_matched'] and account.get('type') == 'prop'
            safe['active_status_verified'] = str(d.get('status', '')).upper() == 'ACTIVE'
            try:
                expiry = datetime.fromisoformat(str(d.get('expireAt', '')).replace('Z', '+00:00'))
                safe['unexpired_verified'] = expiry.tzinfo is not None and expiry > datetime.now(timezone.utc)
            except ValueError:
                safe['unexpired_verified'] = False
            safe['cash_TMN'] = wallet.get('cash_TMN')
            package_id = p.get('id')
            if type(package_id) is int and package_id > 0:
                package_data = reader.get('/v1/prop/packages/'+str(package_id)).get('result', {})
                unavailable = package_data.get('unavailableMarkets')
                if isinstance(unavailable, list) and all(isinstance(x, str) and x.isalnum() for x in unavailable):
                    safe['unavailable_markets'] = unavailable
                    safe['plan_restrictions_retrieved'] = True
                    # A blacklist is not proof of the organizer's complete allowlist.
                    safe['competition_allowlist_still_requires_confirmation'] = True
            report['competition_candidates'].append(safe)
        candidates = report['competition_candidates']
        report['competition_account_confirmed'] = len(candidates) == 1 and all(candidates[0][k] for k in
            ('nominal_5m_TMN_match', 'account_identity_candidate', 'active_status_verified', 'unexpired_verified'))
    except ReadFailure as e:
        report['subaccounts_error'] = {'kind': e.kind, 'http_status': e.status}
    report['observations'] = reader.observations
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--online', action='store_true')
    parser.add_argument('--output', default='reports/credit_readonly_verification.json')
    args = parser.parse_args(argv)
    if not args.online:
        parser.error('explicit --online required for authenticated GET discovery')
    load_env()
    if os.environ.get('ENABLE_LIVE_TRADING', 'false').lower() != 'false' or os.environ.get('TRADING_MODE', 'shadow') != 'shadow':
        parser.error('shadow mode and disabled live trading required')
    if not key_configured(os.environ.get('WALLEX_API_KEY')):
        report = {'api_key_valid': None, 'status': 'MISSING_KEY', 'authenticated_writes': 0}
    else:
        reader = CreditReader(os.environ['WALLEX_API_KEY'])
        try:
            report = verify(reader)
        finally:
            reader.close()
    dest = Path(args.output); dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n'); dest.chmod(0o600)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get('competition_account_confirmed') else 2


if __name__ == '__main__':
    raise SystemExit(main())
