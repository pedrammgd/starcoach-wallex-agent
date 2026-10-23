"""Safety regression tests. All credentials/brokers here are explicit test doubles."""
import json
from pathlib import Path
import tempfile
import unittest
import contextlib
import io
import os
from unittest.mock import patch

import httpx

from wallex_agent.credit import CreditReader, ReadFailure, verify
from wallex_agent.closing import ClosingController, SettlementSimulator
from wallex_agent.engine import Config, Ledger
from wallex_agent.execution import Executor, Intent, OrderState
from wallex_agent.journal import Journal
from wallex_agent.runtime import ProcessLock, clock_observation, depth_capacity


class CreditTests(unittest.TestCase):
    def test_error_identifier_recorded_without_private_message(self):
        c = CreditReader('fixture-key-not-real', transport=httpx.MockTransport(
            lambda req: httpx.Response(401, json={'success': False,
                'error': {'code': 'ACCESS_DENIED', 'message': 'private account details'}})))
        with self.assertRaises(ReadFailure): c.get('/sub-accounts')
        self.assertEqual(c.observations[0]['response_error_code'], 'ACCESS_DENIED')
        self.assertNotIn('private account', json.dumps(c.observations)); c.close()

    def test_fixed_origin_no_redirect_no_write_and_auth_stop(self):
        requests=[]
        def handler(req):
            requests.append(req)
            return httpx.Response(401,json={'message':'arbitrary confidential error'})
        c=CreditReader('fixture-key-not-real',transport=httpx.MockTransport(handler))
        for path in ['https://evil.invalid/', '/v1/account/orders', '//evil.invalid/x', '/v1/prop/packages/1/../../orders']:
            with self.assertRaises(PermissionError):c.get(path)
        report=verify(c);c.close()
        self.assertIs(report['api_key_valid'],False);self.assertEqual(len(requests),2)
        self.assertEqual([r.url.path for r in requests],['/v1/prop/user/packages/history','/v1/account/fee'])
        self.assertEqual(requests[0].method,'GET');self.assertEqual(requests[0].url.host,'api.wallex.ir')
        self.assertNotIn('fixture-key',json.dumps(report));self.assertNotIn('confidential',json.dumps(report))
        c=CreditReader('fixture-key-not-real',transport=httpx.MockTransport(lambda r:httpx.Response(302,headers={'location':'https://evil.invalid'})))
        with self.assertRaises(ReadFailure):c.get('/sub-accounts')
        self.assertEqual(len(c.observations),1);c.close()

    def test_credit_history_denial_does_not_mislabel_valid_scoped_key(self):
        def handler(req):
            if req.url.path=='/v1/prop/user/packages/history':return httpx.Response(401,json={})
            return httpx.Response(200,json={'success':True,'result':[]})
        c=CreditReader('fixture-key-not-real',transport=httpx.MockTransport(handler));r=verify(c);c.close()
        self.assertTrue(r['api_key_valid']);self.assertTrue(r['basic_read_accepted'])
        self.assertFalse(r['competition_account_confirmed']);self.assertFalse(r['trading_fees_verified'])

    def test_wallet_is_confirmed_separately_when_package_metadata_is_denied(self):
        def handler(req):
            if req.url.path in ['/v1/prop/user/packages/history','/v1/prop/user/packages/active']:
                return httpx.Response(401,json={})
            data=[]
            if req.url.path=='/sub-accounts':data=[{'title':'هکاتون استارکوچ','clientId':'fixture','isActive':True,'isSuspend':False,'type':'prop'}]
            if req.url.path=='/v1/account/balances-detail':data={'TMN':{'total':'5000000','available':'5000000','freeze':'0'}}
            return httpx.Response(200,json={'success':True,'result':data})
        c=CreditReader('fixture-key-not-real',transport=httpx.MockTransport(handler));r=verify(c);c.close()
        self.assertTrue(r['competition_wallet_confirmed']);self.assertFalse(r['competition_account_confirmed'])
        self.assertFalse(r['routing_verified']);self.assertFalse(r['competition_wallets'][0]['expiry_verified'])

    def test_documented_discovery_and_identifiers_redacted(self):
        # Schema follows saved official generated pages 1379/1718/5356/3834/7293.
        cid='fixture_subaccount_only';responses={
            '/v1/prop/user/packages/history':[],
            '/sub-accounts':[{'title':'هکاتون استارکوچ','clientId':cid,'isActive':True,'isSuspend':False,'type':'prop','userId':999999}],
            '/v1/prop/user/packages/active':{'packageDetail':{'id':17,'title':'هکاتون استارکوچ','currency':'TMN','startBalance':'5000000'},
                'userPackageDetail':{'status':'ACTIVE','expireAt':'2099-01-01T00:00:00Z','type':'prop-public'},
                'balancesHistory':{'total':{'TMN':5000000}}},
            '/v1/account/balances-detail':{'TMN':{'total':'5000000','available':'5000000','freeze':'0'}},
            '/v1/prop/packages/17':{'unavailableMarkets':['WTMN']}}
        def handler(req):
            if req.url.path.endswith('/active') or req.url.path.endswith('balances-detail'):
                self.assertEqual(req.headers['sub-account-client-id'],cid)
            return httpx.Response(200,json={'success':True,'result':responses[req.url.path]})
        c=CreditReader('fixture-key-not-real',transport=httpx.MockTransport(handler));r=verify(c);c.close()
        self.assertTrue(r['competition_account_confirmed']);self.assertFalse(r['routing_verified'])
        self.assertFalse(r['allowed_markets_verified']);self.assertFalse(r['trading_fees_verified'])
        self.assertNotIn(cid,json.dumps(r));self.assertNotIn('999999',json.dumps(r))
        self.assertEqual(r['competition_candidates'][0]['unavailable_markets'],['WTMN'])

    def test_missing_expiry_or_ambiguous_identity_never_confirms(self):
        responses=[[],[{'title':'هکاتون','clientId':'fixture','isActive':True,'isSuspend':False,'type':'prop'}],
            {'packageDetail':{'title':'هکاتون','currency':'TMN','startBalance':'5000000'},'userPackageDetail':{}},{}]
        c=CreditReader('fixture-key-not-real',transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'success':True,'result':responses.pop(0)})))
        self.assertFalse(verify(c)['competition_account_confirmed']);c.close()


class ClosingTests(unittest.TestCase):
    def setup_controller(self, folder, deadline=2000, fraction=1):
        cfg=Config(initial_cash=5000000,min_notional=1,qty_step='0.000001')
        ledger=Ledger(cfg.initial_cash);ledger.fill(100,1000,cfg)
        j=Journal(str(Path(folder)/'journal.sqlite'))
        b=SettlementSimulator(ledger,cfg,fill_fraction=fraction)
        e=Executor(b,j)
        c=ClosingController(e,symbol='BTCTMN',deadline=deadline,buffer=100,
                            route_verified=True,allowed_markets=['BTCTMN'])
        return c,b,j

    def tick(self,c,b,now,capacity=1000):
        return c.tick(now,ledger=b.ledger,reference=1100,quantity_step='0.000001',min_notional=1,capacity=capacity)

    def test_entire_cutoff_reconciles_entry_realizes_TMN_and_restart(self):
        with tempfile.TemporaryDirectory() as d:
            c,b,j=self.setup_controller(d)
            # Existing entry submitted before cutoff; partial accepted fill persists.
            b.fill_fraction=.5
            cid,state=c.executor.execute(Intent('BTCTMN','BUY','10','1000','before-cutoff','simulated entry'))
            self.assertEqual(state.status,'PARTIAL')
            self.assertTrue(self.tick(c,b,1800)['entries_allowed'])
            b.fill_fraction=1
            report=self.tick(c,b,1900)
            self.assertEqual(c.executor.latest(cid).status,'CANCELED')
            self.assertTrue(report['settled']);self.assertEqual(report['remaining_assets']['BTC'],0)
            self.assertAlmostEqual(report['cash_TMN']-5000000,report['realized_pnl_TMN'])
            fills=b.ledger.trade_count;j.close()
            j=Journal(str(Path(d)/'journal.sqlite'))
            c=ClosingController(Executor(b,j),symbol='BTCTMN',deadline=2000,buffer=100,route_verified=True,allowed_markets=['BTCTMN'])
            self.assertTrue(self.tick(c,b,1901)['settled']);self.assertEqual(b.ledger.trade_count,fills)
            self.assertTrue(self.tick(c,b,2000)['settled']);j.verify();j.close()

    def test_unknown_deadline_route_and_pending_never_fake_flat(self):
        with tempfile.TemporaryDirectory() as d:
            c,b,j=self.setup_controller(d,deadline=None)
            self.assertEqual(self.tick(c,b,1900)['state'],'HALTED_UNKNOWN_DEADLINE')
            c.deadline=2000;c.route_verified=False
            self.assertEqual(self.tick(c,b,1900)['state'],'HALTED_UNVERIFIED_EXIT_ROUTE')
            c.route_verified=True;b.fill_fraction=.5
            r=self.tick(c,b,1900);self.assertFalse(r['settled']);self.assertEqual(b.ledger.quantity,50)
            r=self.tick(c,b,1901);self.assertEqual(r['state'],'WAIT_RECONCILIATION')
            self.assertFalse(r['entries_allowed']);self.assertEqual(b.ledger.quantity,50);j.close()

    def test_dust_liquidity_and_late_exit_do_not_report_realized(self):
        with tempfile.TemporaryDirectory() as d:
            c,b,j=self.setup_controller(d)
            self.assertFalse(self.tick(c,b,1900,capacity=0)['settled'])
            r=self.tick(c,b,2000);self.assertEqual(r['state'],'HALTED_UNSETTLED_AT_DEADLINE')
            self.assertEqual(b.ledger.quantity,100);self.assertEqual(b.ledger.trade_count,1);j.close()


class RuntimeTests(unittest.TestCase):
    def test_offline_verification_never_overwrites_real_inference_evidence(self):
        from wallex_agent.cli import main
        previous=Path.cwd()
        with tempfile.TemporaryDirectory() as d:
            try:
                os.chdir(d);Path('reports').mkdir()
                p=Path('reports/boxapi_verification.json');p.write_text('{"status":"PRIOR_REAL_INFERENCE"}')
                with patch('wallex_agent.cli.load_env'),patch.dict(os.environ,{'LLM_PROVIDER':'boxapi','BOXAPI_API_KEY':'YOUR_KEY'},clear=True),contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(main(['verify-boxapi']),0)
                self.assertEqual(json.loads(p.read_text())['status'],'PRIOR_REAL_INFERENCE')
                offline=json.loads(Path('reports/boxapi_offline_verification.json').read_text())
                self.assertEqual(offline['network_calls'],0);self.assertFalse(offline['real_inference_verified'])
            finally:os.chdir(previous)

    def test_lock_contention_and_restart(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'agent.lock'
            with ProcessLock(path):
                with self.assertRaises(PermissionError):
                    with ProcessLock(path):pass
            with ProcessLock(path):pass

    def test_clock_uncertainty_and_depth(self):
        self.assertTrue(clock_observation('Thu, 01 Jan 1970 00:01:40 GMT',99,101)['accepted'])
        for date,a,b in [('bad',99,101),('Thu, 01 Jan 1970 00:01:40 GMT',90,92),('Thu, 01 Jan 1970 00:01:40 GMT',95,105)]:
            self.assertFalse(clock_observation(date,a,b)['accepted'])
        self.assertAlmostEqual(depth_capacity([{'price':100,'quantity':50},{'price':120,'quantity':5000}],100,10),.5)
        with self.assertRaises(ValueError):depth_capacity([{'price':'NaN','quantity':2}],100,10)
