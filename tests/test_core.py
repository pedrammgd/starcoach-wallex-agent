import json
import math
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from wallex_agent.ai import Agent, parse_decision
from wallex_agent.data import Candle, validate
from wallex_agent.engine import Config, Ledger, floor_quantity, run
from wallex_agent.journal import Journal
from wallex_agent.model import OnlineModel, features


def fixture(n=400):
    """Synthetic lifecycle fixture; never performance evidence."""
    result = []
    price = 100.
    for i in range(n):
        new = price*math.exp(.001+math.sin(i/10)*.003)
        result.append(Candle(1_700_002_800+i*3600, price, max(price,new)*1.002,
                             min(price,new)*.998, new, 10_000))
        price = new
    return result


class DataTests(unittest.TestCase):
    def test_reject_bad_data(self):
        b = fixture(4)
        for broken in [b+[b[-1]], b[::-1], b[:1]+b[2:], [replace(b[0], close=float('nan'))],
                       [replace(b[0], volume=-1)], [replace(b[0], high=1)]]:
            with self.subTest(broken=broken):
                with self.assertRaises(ValueError): validate(broken, 3600)

    def test_unclosed(self):
        b=fixture(1)
        with self.assertRaises(ValueError): validate(b, 3600, now=b[0].timestamp+3599)
        validate(b, 3600, now=b[0].timestamp+3600)

    def test_features_causal(self):
        b=fixture()
        changed=b[:101]+[replace(c, open=c.open*2, high=c.high*2, low=c.low*2, close=c.close*2) for c in b[101:]]
        self.assertEqual(features(b,100),features(changed,100))
        a,z=OnlineModel(),OnlineModel()
        self.assertEqual(a.predict(b,100),z.predict(changed,100))
        self.assertLessEqual(a.last_label_origin+7,100)


class LedgerTests(unittest.TestCase):
    def test_roundtrip_cost_and_realized_toman(self):
        cfg=Config(fee_bps=30,spread_bps=0,slippage_bps=0)
        book=Ledger(5_000_000)
        book.fill(100,100,cfg);book.fill(-100,100,cfg)
        self.assertEqual(book.quantity,0)
        self.assertAlmostEqual(book.cash,4_999_940)
        self.assertAlmostEqual(book.realized_pnl,-60)
        self.assertAlmostEqual(book.fees,60)

    def test_partial_cost_basis_and_oversell(self):
        cfg=Config(fee_bps=0,spread_bps=0,slippage_bps=0)
        b=Ledger(1000);b.fill(5,100,cfg);b.fill(-2,120,cfg)
        self.assertEqual((b.quantity,b.cost_basis,b.realized_pnl),(3,300,40))
        with self.assertRaises(ValueError): b.fill(-4,100,cfg)
        with self.assertRaises(ValueError): b.fill(100,100,cfg)

    def test_precision(self):
        self.assertEqual(floor_quantity(.123456789,"0.00001"),.12345)
        self.assertEqual(floor_quantity(1.24,"0.05"),1.2)
        with self.assertRaises(ValueError): floor_quantity(float('nan'),'.01')

    def test_quantity_conservation_does_not_latch_on_float_dust(self):
        b=Ledger(10000);cfg=Config(fee_bps=0,slippage_bps=0,spread_bps=0)
        b.fill(.1,100,cfg);b.fill(.2,100,cfg);b.fill(-.3,100,cfg)
        self.assertEqual(b.quantity,0);self.assertEqual(b.cost_basis,0)
        self.assertEqual(b.cash,10000)

    def test_per_order_cap_and_regime_prefix_causality(self):
        bars=fixture(240);cfg=Config(initial_cash=10000,min_notional=1,max_order_allocation=.03)
        result=run(bars,cfg,'buy_hold')
        for event in result['events']:
            if event['fill'] and event['fill']['side']=='BUY':
                # The cap is based on equity at the execution open, before costs.
                fill=event['fill'];ledger=event['ledger']
                before_equity=ledger['cash']+fill['notional']+fill['fee']+(ledger['quantity']-fill['quantity'])*event['candle']['open']
                self.assertLessEqual(fill['notional'],before_equity*.03+1e-7)
        a=run(bars[:180],cfg,'regime');b=run(bars,cfg,'regime')
        self.assertEqual(a['events'],b['events'][:len(a['events'])])

    def test_bad_config(self):
        for kw in [{"fee_bps":-1},{"max_allocation":2},{"quote_asset":"IRR"},{"qty_step":"NaN"}]:
            with self.assertRaises(ValueError): Config(**kw)


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.cfg=Config(initial_cash=10000,min_notional=1,qty_step='0.000001')
        self.bars=fixture()

    def test_causal_execution_and_prefix(self):
        a=run(self.bars[:180],self.cfg,'buy_hold')
        b=run(self.bars,self.cfg,'buy_hold')
        self.assertEqual(a['events'],b['events'][:len(a['events'])])
        self.assertIsNone(a['events'][0]['fill'])
        self.assertEqual(a['events'][1]['fill']['reference'],self.bars[49].open)

    def test_kill_and_no_short(self):
        result=run(self.bars,self.cfg,'buy_hold',killed=True)
        self.assertEqual(result['metrics']['trade_count'],0)
        for e in result['events']:
            self.assertGreaterEqual(e['ledger']['cash'],-1e-6)
            self.assertGreaterEqual(e['ledger']['quantity'],0)

    def test_liquidity_uses_previous_volume(self):
        b=[replace(c,volume=0) for c in self.bars]
        result=run(b,self.cfg,'buy_hold')
        self.assertEqual(result['metrics']['trade_count'],0)
        b[49]=replace(b[49],volume=100000)
        result=run(b,self.cfg,'buy_hold')
        self.assertIsNone(result['events'][1]['fill'])
        self.assertIsNotNone(result['events'][2]['fill'])

    def test_fee_penalty(self):
        free=run(self.bars,replace(self.cfg,fee_bps=0,slippage_bps=0,spread_bps=0),'buy_hold')
        paid=run(self.bars,self.cfg,'buy_hold')
        self.assertGreater(free['metrics']['net_return'],paid['metrics']['net_return'])

    def test_deadline_flatten(self):
        cfg=replace(self.cfg,deadline=self.bars[200].timestamp,close_buffer=3600)
        result=run(self.bars,cfg,'buy_hold')
        self.assertLess(result['metrics']['remaining_quantity'],float(cfg.qty_step))
        self.assertTrue(any(e['fill'] and e['fill']['decision_reason']=='deadline flatten' for e in result['events']))
        self.assertFalse(any(e['fill'] and e['fill']['side']=='BUY' for e in result['events'] if e['bar_open']>=self.bars[199].timestamp))

    def test_drawdown_latch(self):
        b=self.bars[:80]
        for c in self.bars[80:]:
            b.append(replace(c,open=c.open*.5,high=c.high*.5,low=c.low*.5,close=c.close*.5))
        result=run(b,self.cfg,'buy_hold')
        self.assertTrue(result['events'][-1]['halted'])
        self.assertGreater(result['metrics']['max_drawdown'],self.cfg.max_drawdown)
        self.assertFalse(any(e['fill'] and e['fill']['side']=='BUY' for e in result['events'] if e['bar_open']>=b[80].timestamp))


class JournalAndAITests(unittest.TestCase):
    def test_journal_restart_and_divergence(self):
        with tempfile.TemporaryDirectory() as d:
            p=str(Path(d)/'j.db')
            j=Journal(p);self.assertTrue(j.append('x',{'a':1}));j.close()
            j=Journal(p);self.assertFalse(j.append('x',{'a':1}))
            with self.assertRaises(ValueError): j.append('x',{'a':2})
            with self.assertRaises(Exception): j.db.execute("DELETE FROM events")
            self.assertEqual(j.verify(),1);j.close()

    def test_ai_invalid(self):
        for text in ['{}','not json','{"action":"ENTER","allocation":5,"confidence":1,"reason":"risk override"}',
                     '{"action":"ENTER","allocation":true,"confidence":1,"reason":"bad type"}']:
            with self.assertRaises((ValueError,TypeError)): parse_decision(text)

    def test_low_confidence_preserves_original_output_without_bypassing_gate(self):
        j=Journal(':memory:')
        a=Agent(lambda ctx:json.dumps({'action':'ENTER','allocation':.2,'confidence':.6,'reason':'fixture momentum candidate'}),j,model='TEST_DOUBLE')
        d,t=a.decide({'candidate':{'target':.2},'roundtrip_cost':.009})
        self.assertEqual(d.action,'HOLD');self.assertEqual(t['validated_model_output_before_confidence_gate']['action'],'ENTER')
        self.assertEqual(t['validated_model_output_before_confidence_gate']['reason'],'fixture momentum candidate')
        j.verify();j.close()

    def test_llm_causal_ablation_and_risk_veto(self):
        with tempfile.TemporaryDirectory() as d:
            j=Journal(str(Path(d)/'a.db'))
            agent=Agent(lambda ctx:json.dumps({'action':'EXIT','allocation':0,'confidence':.9,'reason':'test veto'}),j,model='TEST_DOUBLE')
            cfg=Config(initial_cash=10000,min_notional=1)
            baseline=run(fixture(),cfg,'buy_hold')
            veto=run(fixture(),cfg,'buy_hold',agent=agent)
            self.assertGreater(baseline['metrics']['trade_count'],0)
            self.assertEqual(veto['metrics']['trade_count'],0)
            self.assertTrue(any(e['agent'] for e in veto['events']))
            j.close()

    def test_failure_budget_cache_and_restart(self):
        with tempfile.TemporaryDirectory() as d:
            j=Journal(str(Path(d)/'a.db'))
            calls=[]
            def bad(ctx):
                calls.append(ctx);raise TimeoutError('never logged')
            agent=Agent(bad,j,model='TEST_DOUBLE',max_calls=1)
            self.assertEqual(agent.decide({'x':1})[0].action,'HOLD')
            self.assertEqual(agent.decide({'x':1})[0].action,'HOLD')
            self.assertEqual(agent.decide({'x':2})[1]['status'],'budget')
            self.assertEqual(len(calls),1)
            j.close()


if __name__=='__main__': unittest.main()
