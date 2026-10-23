"""Auditable end-of-competition workflow against a simulation-only broker.

Never exports a production network adapter. Deadlines in the demo are synthetic.
"""
from dataclasses import asdict
from decimal import Decimal
import hashlib
import json

from .engine import floor_quantity
from .execution import Executor, Intent
from .journal import canonical


class ClosingController:
    def __init__(self, executor: Executor, *, symbol, deadline, buffer=1800,
                 route_verified=False, allowed_markets=()):
        if not symbol.endswith('TMN') or buffer < 0:
            raise ValueError('TMN market and nonnegative close buffer required')
        self.executor, self.journal = executor, executor.journal
        self.symbol, self.deadline, self.buffer = symbol, deadline, buffer
        self.route_verified = route_verified
        self.allowed = tuple(allowed_markets)

    def tick(self, now, *, ledger, reference, quantity_step, min_notional, capacity):
        if self.deadline is None:
            return {'state': 'HALTED_UNKNOWN_DEADLINE', 'entries_allowed': False,
                    'settled': False, 'live_orders': False}
        if now < self.deadline-self.buffer:
            return {'state': 'RUNNING', 'entries_allowed': True, 'settled': False,
                    'live_orders': False}
        if not self.route_verified or self.symbol not in self.allowed:
            return {'state': 'HALTED_UNVERIFIED_EXIT_ROUTE', 'entries_allowed': False,
                    'settled': False, 'live_orders': False}
        self.journal.append('closing-start', {'deadline': self.deadline, 'symbol': self.symbol,
                                            'mode': 'SIMULATION_ONLY'})
        # Reconcile/cancel previously recorded entries before proposing any exit.
        pending = False
        rows = self.journal.db.execute("SELECT event_key,body FROM events WHERE event_key LIKE 'order-intent:%'").fetchall()
        for key, body in rows:
            cid = key.partition(':')[2]
            intent = Intent(**json.loads(body))
            if intent.symbol != self.symbol:
                pending = True  # Do not silently settle an unrelated position.
                continue
            state = self.executor.latest(cid)
            if not state or state.status not in {'FILLED', 'REJECTED', 'CANCELED'}:
                observed = self.executor.broker.lookup(cid)
                if observed:
                    state = self.executor.record(cid, intent, observed)
                if state and state.status in {'OPEN', 'PARTIAL'} and intent.side == 'BUY':
                    # Broker's cancel result MUST carry authoritative cumulative fills.
                    state = self.executor.record(cid, intent, self.executor.broker.cancel(cid))
                self.journal.append('closing-reconcile:'+cid+':'+hashlib.sha256(canonical(asdict(state) if state else {}).encode()).hexdigest(),
                                    {'state': asdict(state) if state else None, 'simulation': True})
                if not state or state.status not in {'FILLED', 'REJECTED', 'CANCELED'}:
                    pending = True
            # Account-authoritative simulator snapshot after reconciliation, not intent quantity.
        ledger = self.executor.broker.ledger
        if pending:
            return self._report(ledger, 'WAIT_RECONCILIATION', False)
        # Refuse to fabricate a late fill after the competition's official end.
        if now >= self.deadline:
            return self._report(ledger, 'SETTLED_TMN' if ledger.quantity == 0 else 'HALTED_UNSETTLED_AT_DEADLINE', ledger.quantity == 0)
        q = floor_quantity(min(ledger.quantity, capacity), quantity_step)
        if q > 0 and q*reference >= min_notional:
            intent = Intent(self.symbol, 'SELL', str(q), str(reference),
                            f'closing:{self.deadline}:{ledger.trade_count}', 'scheduled competition exit; simulated')
            cid, state = self.executor.execute(intent)
            self.journal.append('closing-attempt:'+cid, {'order_state': asdict(state), 'simulation': True})
            ledger = self.executor.broker.ledger
        settled = ledger.quantity == 0
        return self._report(ledger, 'SETTLED_TMN' if settled else 'EXIT_PENDING_OR_DUST', settled)

    def _report(self, ledger, state, settled):
        return {'state': state, 'entries_allowed': False, 'settled': settled,
                'realized_pnl_TMN': ledger.realized_pnl, 'cash_TMN': ledger.cash,
                'fees_TMN': ledger.fees, 'remaining_assets': {self.symbol.removesuffix('TMN'): ledger.quantity},
                'remaining_cost_basis_TMN': ledger.cost_basis,
                'valuation_is_not_realized_cash': True, 'live_orders': False}


class SettlementSimulator:
    """Immediate or bounded partial virtual fills; no network operations."""
    simulation = True

    def __init__(self, ledger, cfg, *, fill_fraction=1):
        if not 0 <= fill_fraction <= 1:
            raise ValueError('invalid fraction')
        self.ledger, self.cfg = ledger, cfg
        self.fill_fraction = fill_fraction
        self.orders = {}

    def submit(self, cid, intent):
        from .execution import OrderState
        q = float(intent.quantity)*self.fill_fraction
        fill = self.ledger.fill(q if intent.side == 'BUY' else -q, float(intent.limit_price), self.cfg) if q else None
        state = OrderState('FILLED' if self.fill_fraction == 1 else 'PARTIAL', str(q), str(fill['fee'] if fill else 0))
        self.orders[cid] = state
        return state

    def lookup(self, cid):
        return self.orders.get(cid)

    def cancel(self, cid):
        from .execution import OrderState
        prior = self.orders[cid]
        self.orders[cid] = OrderState('CANCELED', prior.cumulative_quantity, prior.cumulative_fee)
        return self.orders[cid]
