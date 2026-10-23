"""Shared causal replay for historical testing and public shadow trading."""
from __future__ import annotations

import hashlib
import json
import math
import statistics
from dataclasses import asdict, dataclass
from decimal import Decimal, ROUND_DOWN

from .data import Candle, validate
from .model import OnlineModel, Prediction, WARMUP

STRATEGIES = ("cash", "buy_hold", "momentum", "mean_reversion", "regime", "ai")


@dataclass(frozen=True)
class Config:
    initial_cash: float = 5_000_000
    quote_asset: str = "TMN"
    interval: int = 3600
    fee_bps: float = 30  # ASSUMPTION per side, not verified contest fee
    spread_bps: float = 10  # full spread
    slippage_bps: float = 10  # per side
    max_allocation: float = 0.20
    max_order_allocation: float = 0.20
    risk_per_trade: float = 0.005
    max_drawdown: float = 0.04
    daily_loss: float = 0.025
    stop_loss: float = 0.025
    take_profit: float = 0.05
    participation: float = 0.01
    min_notional: float = 50_000
    qty_step: str = "0.00000001"
    rebalance_band: float = 0.05
    cooldown_bars: int = 6
    min_ai_samples: int = 150
    ai_probability: float = 0.57
    edge_buffer: float = 0.002
    deadline: int | None = None  # verified trading cutoff only, UTC
    close_buffer: int = 1800

    def __post_init__(self):
        for key, value in asdict(self).items():
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError(f"nonfinite config: {key}")
        if self.quote_asset != "TMN":
            raise ValueError("TMN only: USDT/IRR conversion not proven")
        if self.initial_cash <= 0 or self.interval <= 0 or self.min_notional < 0:
            raise ValueError("invalid capital, interval or minimum")
        for key in ("fee_bps", "spread_bps", "slippage_bps"):
            if not 0 <= getattr(self, key) <= 1000:
                raise ValueError("invalid costs")
        for key in ("max_allocation", "max_order_allocation", "risk_per_trade", "max_drawdown", "daily_loss",
                    "stop_loss", "take_profit", "participation", "rebalance_band"):
            if not 0 < getattr(self, key) <= 1:
                raise ValueError(f"invalid bound: {key}")
        if not Decimal(self.qty_step).is_finite() or Decimal(self.qty_step) <= 0:
            raise ValueError("invalid step")
        if self.cooldown_bars < 0 or self.min_ai_samples < 1 or self.close_buffer < 0:
            raise ValueError("invalid count/buffer")
        if not 0.5 <= self.ai_probability <= 1 or self.edge_buffer < 0:
            raise ValueError("invalid AI gate")

    @property
    def roundtrip_cost(self) -> float:
        return (2*self.fee_bps+self.spread_bps+2*self.slippage_bps)/10_000


def floor_quantity(value: float, step: str) -> float:
    d = Decimal(str(value))
    s = Decimal(step)
    if not d.is_finite() or d < 0 or not s.is_finite() or s <= 0:
        raise ValueError("invalid quantity/step")
    return float((d/s).to_integral_value(rounding=ROUND_DOWN)*s)


@dataclass
class Ledger:
    cash: float
    quantity: float = 0
    cost_basis: float = 0  # total remaining purchase cost, including fees
    realized_pnl: float = 0
    fees: float = 0
    impact: float = 0
    turnover: float = 0
    trade_count: int = 0

    def equity(self, price: float) -> float:
        return self.cash + self.quantity*price

    def fill(self, signed_quantity: float, reference: float, cfg: Config) -> dict | None:
        if not math.isfinite(signed_quantity) or reference <= 0 or not math.isfinite(reference):
            raise ValueError("invalid fill")
        q = abs(signed_quantity)
        if q == 0:
            return None
        buy = signed_quantity > 0
        impact_rate = (cfg.spread_bps/2+cfg.slippage_bps)/10_000
        price = reference*(1+impact_rate if buy else 1-impact_rate)
        notional = q*price
        fee = notional*cfg.fee_bps/10_000
        if buy:
            if notional+fee > self.cash + 1e-7:
                raise ValueError("insufficient virtual cash")
            self.cash -= notional+fee
            self.quantity = float(Decimal(str(self.quantity))+Decimal(str(q)))
            self.cost_basis += notional+fee
        else:
            if q > self.quantity + 1e-14:
                raise ValueError("oversell")
            basis = self.cost_basis*q/self.quantity
            self.realized_pnl += notional-fee-basis
            self.cost_basis -= basis
            self.quantity = float(max(Decimal(0), Decimal(str(self.quantity))-Decimal(str(q))))
            if self.quantity == 0:
                self.cost_basis = 0
            self.cash += notional-fee
        self.fees += fee
        self.impact += q*abs(price-reference)
        self.turnover += notional
        self.trade_count += 1
        return {"side": "BUY" if buy else "SELL", "quantity": q, "price": price,
                "reference": reference, "notional": notional, "fee": fee,
                "realized_pnl_total": self.realized_pnl, "simulation": True}


@dataclass(frozen=True)
class Proposal:
    target: float
    reason: str
    edge: float


def propose(strategy: str, bars: list[Candle], i: int, p: Prediction, cfg: Config,
            current_allocation: float) -> Proposal:
    c = bars[i]
    closes = [x.close for x in bars[i-23:i+1]]
    mean = statistics.mean(closes)
    sigma = max(statistics.pstdev(closes), c.close*0.001)
    trend = c.close/bars[i-24].close-1
    if strategy == 'regime':
        # Prespecified causal regime gate; no test-period parameter fitting.
        threshold = max(.005, 2*p.volatility*math.sqrt(24))
        selected = 'momentum' if trend > threshold else 'mean_reversion' if abs(trend) <= threshold else 'cash'
        result = propose(selected, bars, i, p, cfg, current_allocation)
        return Proposal(result.target, 'regime '+selected+': '+result.reason, result.edge)
    if strategy == "cash":
        return Proposal(0, "cash benchmark", 0)
    if strategy == "buy_hold":
        return Proposal(cfg.max_allocation, "risk-capped buy and hold benchmark", 1)
    if strategy == "momentum":
        breakout = c.close > max(x.high for x in bars[i-24:i])
        edge = max(0, trend)
        enter = breakout and edge > cfg.roundtrip_cost+cfg.edge_buffer
        retain = current_allocation > 0 and c.close > mean and trend > 0
        return Proposal(cfg.max_allocation if enter or retain else 0,
                        "momentum breakout/retention" if enter or retain else "no momentum edge", edge)
    if strategy == "mean_reversion":
        edge = max(0, mean/c.close-1)
        enter = c.close < mean-1.5*sigma and trend > -0.04 and edge > cfg.roundtrip_cost+cfg.edge_buffer
        retain = current_allocation > 0 and c.close < mean and trend > -0.04
        return Proposal(cfg.max_allocation if enter or retain else 0,
                        "bounded reversion/retention" if enter or retain else "no reversion edge", edge)
    if strategy == "ai":
        ready = p.samples >= cfg.min_ai_samples
        enter = ready and p.probability >= cfg.ai_probability and p.expected_return > cfg.roundtrip_cost+cfg.edge_buffer
        retain = ready and current_allocation > 0 and p.probability > 0.50 and p.expected_return > 0
        return Proposal(cfg.max_allocation if enter or retain else 0,
                        "learned positive edge" if enter else "learned retention" if retain else
                        "AI abstain: training/confidence/cost gate", p.expected_return)
    raise ValueError("unknown strategy")


def run(bars: list[Candle], cfg: Config, strategy: str, *, start: int = WARMUP,
        end: int | None = None, killed: bool = False, agent=None) -> dict:
    validate(bars, cfg.interval)
    end = len(bars) if end is None else end
    if strategy not in STRATEGIES or not WARMUP <= start < end <= len(bars):
        raise ValueError("invalid strategy or replay range")
    model = OnlineModel()
    ledger = Ledger(cfg.initial_cash)
    peak = cfg.initial_cash
    daily_start = cfg.initial_cash
    last_day = None
    halted = False
    daily_halt = False
    pending = 0.0
    pending_reason = "initial virtual cash"
    trailing = 0.0
    cooldown_until = 0
    events = []
    equities = [cfg.initial_cash]
    exposure = []
    previous_equity = cfg.initial_cash
    for i in range(WARMUP, end):
        c = bars[i]
        prediction = model.predict(bars, i)
        if i < start:
            continue
        open_equity = ledger.equity(c.open)
        day = c.timestamp//86400  # UTC risk days, documented separately from Tehran deadline
        if day != last_day:
            daily_start = previous_equity
            daily_halt = False
            last_day = day
        peak = max(peak, open_equity)
        halted = halted or killed or open_equity <= peak*(1-cfg.max_drawdown)
        daily_halt = daily_halt or open_equity <= daily_start*(1-cfg.daily_loss)
        closing = cfg.deadline is not None and c.timestamp >= cfg.deadline-cfg.close_buffer
        reasons = []
        if halted: reasons.append("kill/total drawdown latch")
        if daily_halt: reasons.append("daily loss latch")
        if closing: reasons.append("deadline flatten")
        desired = 0.0 if halted or daily_halt or closing else pending
        desired = min(desired, cfg.max_allocation)
        delta = desired*open_equity/c.open-ledger.quantity
        # Historical execution capacity uses ONLY prior closed volume, not future bar volume.
        capacity = bars[i-1].volume*cfg.participation
        q = min(abs(delta), capacity)
        # A scheduled exit can take several orders; never evade the per-order cap.
        q = min(q, open_equity*cfg.max_order_allocation/c.open)
        buy_price = c.open*(1+(cfg.spread_bps/2+cfg.slippage_bps)/10_000)
        if delta > 0:
            q = min(q, ledger.cash/(buy_price*(1+cfg.fee_bps/10_000)))
            q = min(q, open_equity*cfg.max_order_allocation/buy_price)
        else:
            q = min(q, ledger.quantity)
        q = floor_quantity(q, cfg.qty_step)
        target_change = abs(delta*c.open)/max(open_equity, 1e-12)
        fill = None
        if q*c.open >= cfg.min_notional and (desired == 0 or target_change >= cfg.rebalance_band):
            fill = ledger.fill(q if delta > 0 else -q, c.open, cfg)
            fill["decision_reason"] = "; ".join(reasons) if reasons else pending_reason
            fill["order_id"] = hashlib.sha256(f"{strategy}:{c.timestamp}:{delta > 0}".encode()).hexdigest()[:24]
            if fill["side"] == "BUY" and trailing == 0:
                trailing = c.open
            if ledger.quantity < float(cfg.qty_step):
                trailing = 0
        elif abs(delta)*c.open >= cfg.min_notional:
            reasons.append("unfilled: liquidity/size/rebalance")
        equity = ledger.equity(c.close)
        peak = max(peak, equity)
        halted = halted or equity <= peak*(1-cfg.max_drawdown)
        daily_halt = daily_halt or equity <= daily_start*(1-cfg.daily_loss)
        current = ledger.quantity*c.close/max(equity, 1e-12)
        proposal = propose(strategy, bars, i, prediction, cfg, current)
        agent_trace = None
        if agent is not None and (proposal.target > 0 or current > 0):
            context = {"features": list(prediction.features), "probability": prediction.probability,
                       "expected_return": prediction.expected_return, "volatility": prediction.volatility,
                       "roundtrip_cost": cfg.roundtrip_cost, "risk_cap": cfg.max_allocation,
                       "current_allocation": current, "candidate": asdict(proposal)}
            decision, agent_trace = agent.decide(context)
            target = (min(decision.allocation, proposal.target) if decision.action == "ENTER" else
                      0 if decision.action == "EXIT" else min(current, proposal.target))
            proposal = Proposal(target, "LLM "+decision.action+": "+decision.reason, proposal.edge)
        # Independent risk veto. AI never controls these limits.
        stop_distance = max(cfg.stop_loss, prediction.volatility*3)
        cap = min(cfg.max_allocation, cfg.risk_per_trade/stop_distance)
        pending = min(proposal.target, cap)
        trailing = max(trailing, c.close) if ledger.quantity else 0
        basis_price = ledger.cost_basis/ledger.quantity if ledger.quantity else 0
        stop = bool(ledger.quantity and c.close <= trailing*(1-cfg.stop_loss))
        take = bool(basis_price and c.close >= basis_price*(1+cfg.take_profit))
        if stop or take:
            cooldown_until = i+cfg.cooldown_bars
            reasons.append("close-based trailing stop" if stop else "take profit")
        if halted or daily_halt or closing or stop or take or i < cooldown_until:
            pending = 0
            reasons.append("risk veto / cooldown")
        pending_reason = proposal.reason + ("; " + "; ".join(reasons) if reasons else "")
        event = {"bar_open": c.timestamp, "decision_at": c.timestamp+cfg.interval,
                 "strategy": strategy, "candle": asdict(c), "prediction": asdict(prediction),
                 "proposal": asdict(proposal), "target_next_open": pending,
                 "agent": agent_trace,
                 "reasons": reasons, "fill": fill, "ledger": asdict(ledger),
                 "equity": equity, "drawdown": 1-equity/peak,
                 "halted": halted, "daily_halt": daily_halt}
        events.append(event)
        equities.append(equity)
        exposure.append(current)
        previous_equity = equity
    peak_seen = equities[0]
    max_dd = 0.0
    for eq in equities:
        peak_seen = max(peak_seen, eq)
        max_dd = max(max_dd, 1-eq/peak_seen)
    rets = [b/a-1 for a, b in zip(equities, equities[1:])]
    std = statistics.pstdev(rets) if len(rets)>1 else 0
    # Net liquidation estimate is not a fill or realized return.
    liquidation_cost = ledger.quantity*bars[end-1].close*(cfg.fee_bps+cfg.spread_bps/2+cfg.slippage_bps)/10_000
    sell_pnls = []
    last_realized = 0.0
    for event in events:
        fill = event['fill']
        if fill and fill['side'] == 'SELL':
            sell_pnls.append(fill['realized_pnl_total']-last_realized)
            last_realized = fill['realized_pnl_total']
    metrics = {"net_return": equities[-1]/cfg.initial_cash-1,
               "liquidation_estimate_return": (equities[-1]-liquidation_cost)/cfg.initial_cash-1,
               "realized_pnl_TMN": ledger.realized_pnl, "max_drawdown": max_dd,
               "fees_TMN": ledger.fees, "spread_slippage_TMN": ledger.impact,
               "trade_count": ledger.trade_count, "turnover_TMN": ledger.turnover,
               "sell_fill_win_rate": sum(p > 0 for p in sell_pnls)/len(sell_pnls) if sell_pnls else None,
               "closed_sell_fills": len(sell_pnls),
               "avg_trade_TMN": ledger.turnover/max(1, ledger.trade_count),
               "mean_exposure": statistics.mean(exposure),
               "sharpe_descriptive": statistics.mean(rets)/std*math.sqrt(365*86400/cfg.interval) if std else 0,
               "final_cash_TMN": ledger.cash, "remaining_quantity": ledger.quantity,
               "flat": ledger.quantity < float(cfg.qty_step),
               "prequential_brier": model.brier_sum/max(model.samples, 1),
               "model_samples": model.samples, "bars": len(events)}
    return {"metrics": metrics, "events": events}
