"""Deterministic online logistic learning; labels mature after the holding horizon."""
from __future__ import annotations

import hashlib
import json
import math
import statistics
from dataclasses import dataclass

from .data import Candle

FEATURE_VERSION = "bounded-causal-v1"
HORIZON = 6
WARMUP = 48


def features(bars: list[Candle], i: int) -> list[float]:
    if i < WARMUP:
        raise ValueError("insufficient warmup")
    c = bars[i]
    returns = [math.log(bars[j].close / bars[j-1].close) for j in range(i-23, i+1)]
    vol = max(0.001, statistics.pstdev(returns))
    recent = bars[i-23:i+1]
    mean = statistics.mean(x.close for x in recent)
    volume_mean = statistics.mean(x.volume for x in recent)
    raw = [1.0, math.log(c.close/bars[i-1].close)/vol,
           math.log(c.close/bars[i-6].close)/(vol*math.sqrt(6)),
           math.log(c.close/bars[i-24].close)/(vol*math.sqrt(24)),
           (c.close/mean-1)/(vol*math.sqrt(24)),
           (c.high-c.low)/c.close/vol, (c.close-c.open)/c.open/vol,
           c.volume/max(volume_mean, 1e-12)-1]
    return [max(-4.0, min(4.0, x)) for x in raw]


@dataclass(frozen=True)
class Prediction:
    probability: float
    expected_return: float
    volatility: float
    samples: int
    model_hash: str
    features: tuple[float, ...]


class OnlineModel:
    def __init__(self):
        self.weights = [0.0]*8
        self.samples = 0
        self.gain = 0.0
        self.loss = 0.0
        self.positives = 0
        self.negatives = 0
        self.last_label_origin = WARMUP-1
        self.brier_sum = 0.0

    def probability(self, x: list[float]) -> float:
        z = max(-30.0, min(30.0, sum(a*b for a, b in zip(self.weights, x))))
        return 1/(1+math.exp(-z))

    def update_until(self, bars: list[Candle], i: int) -> None:
        # Label is next OPEN -> OPEN after six bars, all observed by decision close i.
        while self.last_label_origin + 1 + HORIZON + 1 <= i:
            origin = self.last_label_origin + 1
            x = features(bars, origin)
            r = bars[origin+1+HORIZON].open / bars[origin+1].open - 1
            y = float(r > 0)
            p = self.probability(x)
            rate = 0.03 / math.sqrt(1 + self.samples/500)
            self.weights = [w + rate*((y-p)*v - 0.002*w) for w, v in zip(self.weights, x)]
            self.samples += 1
            self.brier_sum += (p-y)**2
            if y:
                self.positives += 1
                self.gain += r
            else:
                self.negatives += 1
                self.loss += r
            self.last_label_origin = origin

    def predict(self, bars: list[Candle], i: int) -> Prediction:
        self.update_until(bars, i)
        x = features(bars, i)
        p = self.probability(x)
        gain = self.gain/max(self.positives, 1)
        loss = self.loss/max(self.negatives, 1)
        vol = statistics.pstdev(math.log(bars[j].close/bars[j-1].close)
                                for j in range(i-23, i+1))
        fingerprint = hashlib.sha256(json.dumps({"weights": self.weights, "n": self.samples,
            "gain": self.gain, "loss": self.loss, "version": FEATURE_VERSION},
            sort_keys=True).encode()).hexdigest()
        return Prediction(p, p*gain+(1-p)*loss, vol, self.samples, fingerprint, tuple(x))
