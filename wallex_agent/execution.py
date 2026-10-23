"""Durable order lifecycle against an injected, verified broker contract.

No network adapter is provided. In particular, a public spot route is never used
as a fallback for an unidentified competition credit account.
"""
from dataclasses import asdict,dataclass
from decimal import Decimal
import hashlib
import json
from typing import Protocol

from .journal import Journal,canonical


@dataclass(frozen=True)
class Intent:
    symbol: str
    side: str
    quantity: str
    limit_price: str
    decision_id: str
    reason: str

    def validate(self):
        if self.side not in {'BUY','SELL'} or not self.symbol.isalnum() or not self.reason:
            raise ValueError('invalid intent')
        for value in (self.quantity,self.limit_price):
            if not Decimal(value).is_finite() or Decimal(value)<=0:
                raise ValueError('invalid decimal intent')


@dataclass(frozen=True)
class OrderState:
    status: str  # UNKNOWN, OPEN, PARTIAL, FILLED, REJECTED, CANCELED
    cumulative_quantity: str = '0'
    cumulative_fee: str = '0'


class Broker(Protocol):
    simulation: bool
    def submit(self, client_id: str, intent: Intent) -> OrderState: ...
    def lookup(self, client_id: str) -> OrderState | None: ...


class Executor:
    def __init__(self,broker: Broker,journal: Journal):
        if broker.simulation is not True:
            raise PermissionError('production broker unavailable until challenge contract verified')
        self.broker,self.journal=broker,journal

    def latest(self,client_id):
        row=self.journal.db.execute("SELECT body FROM events WHERE event_key LIKE ? ORDER BY seq DESC LIMIT 1",
                                    ('order-state:'+client_id+':%',)).fetchone()
        return OrderState(**json.loads(row[0])) if row else None

    def record(self,client_id,intent,state):
        q,fee=Decimal(state.cumulative_quantity),Decimal(state.cumulative_fee)
        if state.status not in {'UNKNOWN','OPEN','PARTIAL','FILLED','REJECTED','CANCELED'}:
            raise ValueError('invalid order state')
        if not q.is_finite() or not fee.is_finite() or not 0<=q<=Decimal(intent.quantity) or fee<0:
            raise ValueError('invalid cumulative fills/fees')
        prior=self.latest(client_id)
        if prior and (q<Decimal(prior.cumulative_quantity) or fee<Decimal(prior.cumulative_fee)):
            raise ValueError('reconciliation regression')
        if prior and prior.status in {'FILLED','REJECTED','CANCELED'} and prior!=state:
            raise ValueError('terminal order changed')
        if state.status=='FILLED' and q!=Decimal(intent.quantity):
            raise ValueError('incomplete FILLED')
        if state.status=='REJECTED' and q!=0:
            raise ValueError('rejected order has fill')
        body=asdict(state)
        self.journal.append('order-state:'+client_id+':'+hashlib.sha256(canonical(body).encode()).hexdigest(),body)
        return state

    def execute(self,intent: Intent):
        intent.validate()
        client_id=hashlib.sha256(canonical(asdict(intent)).encode()).hexdigest()[:32]
        first=self.journal.append('order-intent:'+client_id,asdict(intent))
        if not first:
            prior=self.latest(client_id)
            if prior and prior.status in {'FILLED','REJECTED','CANCELED'}:return client_id,prior
            observed=self.broker.lookup(client_id)
            # Missing lookup is NOT proof of no order, never resubmit blindly.
            return client_id,self.record(client_id,intent,observed or prior or OrderState('UNKNOWN'))
        try:
            state=self.broker.submit(client_id,intent)
        except Exception:
            # Transport may have accepted the order; persist ambiguity, reconcile later.
            state=OrderState('UNKNOWN')
        return client_id,self.record(client_id,intent,state)
