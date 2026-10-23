import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
import urllib.error

from test_core import fixture
from wallex_agent.data import PublicWallex, contiguous_segments
from wallex_agent.engine import Config
from wallex_agent.journal import Journal
from wallex_agent.safety import require_live,parse_tehran_deadline
from wallex_agent.shadow import Shadow


class ShadowTests(unittest.TestCase):
    def test_forward_restart(self):
        with tempfile.TemporaryDirectory() as d:
            file=str(Path(d)/'s.db')
            cfg=Config(initial_cash=10000,min_notional=1)
            bars=fixture(200)
            now=bars[-1].timestamp+3600
            mid=bars[-1].close
            j=Journal(file);s=Shadow(j,cfg,'BTCTMN','buy_hold')
            e=s.step(bars,mid,mid*1.001,now)
            self.assertTrue(e['new_decision'])
            self.assertIsNotNone(e['fill'])
            self.assertGreaterEqual(e['fill']['reference'],mid)
            count=j.verify();j.close()
            j=Journal(file);s=Shadow(j,cfg,'BTCTMN','buy_hold')
            self.assertFalse(s.step(bars,mid,mid*1.001,now)['new_decision'])
            self.assertEqual(j.verify(),count)
            with self.assertRaises(ValueError): s.step(bars,mid,mid*1.001,now+7201)
            with self.assertRaises(ValueError): s.step(bars,mid,mid*1.1,now)
            j.close()

    def test_risk_no_entry_after_cutoff(self):
        with tempfile.TemporaryDirectory() as d:
            bars=fixture(200);now=bars[-1].timestamp+3600;mid=bars[-1].close
            cfg=Config(initial_cash=10000,min_notional=1,deadline=now+600)
            j=Journal(str(Path(d)/'s.db'));s=Shadow(j,cfg,'BTCTMN','buy_hold')
            e=s.step(bars,mid,mid*1.001,now)
            self.assertEqual(e['target'],0);self.assertIsNone(e['fill']);j.close()

    def test_live_impossible_even_with_env(self):
        with patch.dict('os.environ',{'ENABLE_LIVE_TRADING':'true','LIVE_TRADING':'true'}):
            with self.assertRaises(PermissionError): require_live()
        with self.assertRaises(ValueError):parse_tehran_deadline('2026-10-23T23:50:00')
        self.assertEqual(parse_tehran_deadline('2026-10-23T23:50:00+03:30'),1792786800)


class TransportTests(unittest.TestCase):
    def test_public_allowlist_blocks_private(self):
        c=PublicWallex()
        with self.assertRaises(ValueError):c.get('/v1/account/orders')

    def test_documented_shape_and_windows(self):
        c=PublicWallex()
        calls=[]
        def endpoint(path,params):
            calls.append(params)
            ts=list(range(params['from'],params['to'],3600))
            return {'s':'ok','t':ts,'o':['100']*len(ts),'h':['102']*len(ts),
                    'l':['99']*len(ts),'c':['101']*len(ts),'v':['1']*len(ts)}
        c.get=endpoint
        with patch('wallex_agent.data.time.sleep'):
            b=c.history('BTCTMN',0,1200*3600)
        self.assertEqual(len(b),1200)
        self.assertEqual(len(calls),3)
        self.assertLessEqual(max(p['to']-p['from'] for p in calls),500*3600)

    def test_unequal_arrays_fail(self):
        c=PublicWallex();c.get=lambda *a:{'s':'ok','t':[0],'o':[],'h':[],'l':[],'c':[],'v':[]}
        with self.assertRaises(ValueError):c.history('BTCTMN',0,3600)

    def test_429_retry_bounded_and_permissions_no_retry(self):
        c=PublicWallex()
        with patch('urllib.request.urlopen',side_effect=urllib.error.HTTPError('https://api.wallex.ir',429,'rate',{},None)) as fetch:
            with patch('wallex_agent.data.time.sleep'):
                with self.assertRaises(urllib.error.HTTPError):c.get('/v1/markets')
            self.assertEqual(fetch.call_count,3)
        with patch('urllib.request.urlopen',side_effect=urllib.error.HTTPError('https://api.wallex.ir',403,'no',{},None)) as fetch:
            with self.assertRaises(urllib.error.HTTPError):c.get('/v1/markets')
            self.assertEqual(fetch.call_count,1)

    def test_real_response_fixture(self):
        d=json.loads(Path('data/markets_public.json').read_text())
        self.assertTrue(d['success'])
        self.assertEqual(d['result']['symbols']['BTCTMN']['quoteAsset'],'TMN')
        self.assertIsInstance(d['result']['symbols']['BTCTMN']['stepSize'],int)


if __name__=='__main__':unittest.main()
