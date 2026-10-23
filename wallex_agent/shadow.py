"""Forward-only public shadow decisions at observed bid/ask; never historical fills."""
from dataclasses import asdict, replace
import hashlib

from .data import digest, validate
from .engine import Config, Ledger, propose, floor_quantity
from .evaluation import provenance
from .journal import Journal, canonical
from .model import OnlineModel, WARMUP


class Shadow:
    def __init__(self, journal: Journal, cfg: Config, symbol: str, strategy: str = 'ai', agent=None, *, review_flat=False):
        if not symbol.endswith('TMN') or not symbol.isalnum():
            raise ValueError('only explicit TMN research symbols supported')
        self.journal,self.cfg,self.symbol,self.strategy,self.agent=journal,cfg,symbol,strategy,agent
        self.review_flat=review_flat
        journal.append('shadow-config',{'config':asdict(cfg),'symbol':symbol,'strategy':strategy,
                                        'source':provenance(),'mode':'PUBLIC_SHADOW_ONLY','review_flat':review_flat})

    def step(self, bars, bid: float, ask: float, now: int, *, depth=None, observation=None) -> dict:
        import time
        started=time.monotonic()
        cfg=self.cfg
        validate(bars,cfg.interval,now=now)
        if len(bars)<=WARMUP or now-(bars[-1].timestamp+cfg.interval)>cfg.interval:
            raise ValueError('stale or insufficient closed history')
        if not 0<bid<=ask or ask/bid-1>.005:
            raise ValueError('invalid or excessive spread')
        c=bars[-1]
        key=f'shadow:{self.symbol}:{c.timestamp}'
        old=self.journal.db.execute('SELECT body FROM events WHERE event_key=?',(key,)).fetchone()
        if old:
            return {'status':'already_processed','new_decision':False}
        previous=self.journal.db.execute("SELECT body FROM events WHERE event_key LIKE 'shadow:%' ORDER BY seq DESC LIMIT 1").fetchone()
        import json
        state=json.loads(previous[0]) if previous else None
        if state and c.timestamp<=state['bar_open']:
            raise ValueError('nonmonotonic shadow candle')
        ledger=Ledger(**state['ledger']) if state else Ledger(cfg.initial_cash)
        model=OnlineModel()
        p=model.predict(bars,len(bars)-1)
        mark=(bid+ask)/2
        equity=ledger.equity(mark)
        peak=max(state['peak'] if state else cfg.initial_cash,equity)
        day=now//86400
        daily_start=state['daily_start'] if state and state['day']==day else (state['equity'] if state else equity)
        halted=(state['halted'] if state else False) or equity<=peak*(1-cfg.max_drawdown)
        daily_halt=(state['daily_halt'] if state and state['day']==day else False) or equity<=daily_start*(1-cfg.daily_loss)
        current=ledger.quantity*mark/equity
        candidate=propose(self.strategy,bars,len(bars)-1,p,cfg,current)
        target=min(candidate.target,cfg.risk_per_trade/max(cfg.stop_loss,p.volatility*3))
        reason=candidate.reason
        ai_trace=None
        if self.agent and (candidate.target>0 or current>0 or self.review_flat):
            decision,ai_trace=self.agent.decide({'features':list(p.features),'probability':p.probability,
                'expected_return':p.expected_return,'volatility':p.volatility,'roundtrip_cost':cfg.roundtrip_cost,
                'current_allocation':current,'candidate':asdict(candidate),'risk_cap':cfg.max_allocation})
            target=min(target,decision.allocation) if decision.action=='ENTER' else 0 if decision.action=='EXIT' else min(target,current)
            reason='LLM '+decision.action+': '+decision.reason
        target=min(target,cfg.max_allocation,cfg.risk_per_trade/max(cfg.stop_loss,p.volatility*3))
        if target>current and candidate.edge<=cfg.roundtrip_cost+cfg.edge_buffer:
            target=current
            reason+='; deterministic net-edge veto'
        trailing=max(state['trailing'] if state else 0,mark) if ledger.quantity else 0
        stop=bool(trailing and bid<=trailing*(1-cfg.stop_loss))
        take=bool(ledger.quantity and bid>=ledger.cost_basis/ledger.quantity*(1+cfg.take_profit))
        cooldown=state['cooldown_until'] if state else 0
        if stop or take: cooldown=now+cfg.cooldown_bars*cfg.interval
        closing=cfg.deadline is not None and now>=cfg.deadline-cfg.close_buffer
        if halted or daily_halt or stop or take or closing or now<cooldown:
            target=0
            reason+='; independent risk/closing veto'
        delta=target*equity/mark-ledger.quantity
        price=ask if delta>0 else bid
        # Explicit observed spread already in bid/ask; add slippage once, no double spread.
        execution_cfg=replace(cfg,spread_bps=0)
        affordable=ledger.cash/(ask*(1+cfg.slippage_bps/10000)*(1+cfg.fee_bps/10000))
        q=floor_quantity(min(abs(delta),c.volume*cfg.participation,
                             affordable if delta>0 else ledger.quantity),cfg.qty_step)
        q=min(q,floor_quantity(equity*cfg.max_order_allocation/(price*(1+cfg.slippage_bps/10000)),cfg.qty_step))
        depth_verified=False
        if depth is not None:
            from .runtime import depth_capacity
            q=min(q,floor_quantity(depth_capacity(depth['ask' if delta>0 else 'bid'],price,cfg.slippage_bps),cfg.qty_step))
            depth_verified=True
        fill=None
        if q*price>=cfg.min_notional and (target==0 or abs(delta)*mark/equity>=cfg.rebalance_band):
            # Intent committed before virtual fill; no external side effect can occur.
            self.journal.append('shadow-intent:'+key,{'target':target,'quantity':q,'reason':reason,
                'observed_at':now,'bid':bid,'ask':ask,'simulation':True})
            fill=ledger.fill(q if delta>0 else -q,price,execution_cfg)
            if delta>0 and trailing==0: trailing=mark
        equity=ledger.equity(mark)
        event={'status':'public_shadow','new_decision':True,'observed_at':now,'bar_open':c.timestamp,
               'decision_latency_ms':round((time.monotonic()-started)*1000),
               'symbol':self.symbol,'prediction':asdict(p),'candidate':asdict(candidate),
               'target':target,'reason':reason,'agent':ai_trace,'bid':bid,'ask':ask,
               'quote_exchange_timestamp':None,'quote_freshness':'HTTP observation only; exchange timestamp unavailable',
               'dataset_hash':digest(bars),'ledger':asdict(ledger),'fill':fill,'equity':equity,
               'market_snapshot':{'closed_candle':asdict(c),'bid':bid,'ask':ask,
                                  'depth':depth,'observation':observation},
               'depth_verified':depth_verified,'simulation_liquidity_model':'visible depth and closed volume' if depth_verified else 'closed-volume proxy only; depth unverified',
               'risk_outcome':{'target_after_veto':target,'halted':halted,'daily_halt':daily_halt,'closing':closing,'stop':stop,'take':take},
               'peak':peak,'day':day,'daily_start':daily_start,'halted':halted,'daily_halt':daily_halt,
               'trailing':trailing,'cooldown_until':cooldown,'competition_eligible':False}
        self.journal.append(key,event)
        return event
