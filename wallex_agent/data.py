"""Strict OHLCV ingestion and public-only Wallex transport."""
from __future__ import annotations

import csv
import hashlib
import json
import math
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class Candle:
    timestamp: int  # UTC Unix seconds, bar OPEN time
    open: float
    high: float
    low: float
    close: float
    volume: float  # base asset units


def validate(candles: list[Candle], interval: int, *, now: int | None = None) -> None:
    if interval <= 0 or not candles:
        raise ValueError("positive interval and nonempty candles required")
    previous = None
    for c in candles:
        if type(c.timestamp) is not int or c.timestamp < 0:
            raise ValueError("invalid timestamp")
        if not all(math.isfinite(x) for x in (c.open, c.high, c.low, c.close, c.volume)):
            raise ValueError("non-finite OHLCV")
        if min(c.open, c.high, c.low, c.close) <= 0 or c.volume < 0:
            raise ValueError("invalid price or volume")
        if not c.low <= min(c.open, c.close) <= max(c.open, c.close) <= c.high:
            raise ValueError("inconsistent OHLC")
        if previous is not None and c.timestamp - previous != interval:
            raise ValueError("duplicate, unsorted or missing bars; never silently fill gaps")
        if now is not None and c.timestamp + interval > now:
            raise ValueError("unclosed or future candle")
        previous = c.timestamp


def digest(candles: list[Candle]) -> str:
    return hashlib.sha256(json.dumps([asdict(c) for c in candles], sort_keys=True,
                                     allow_nan=False).encode()).hexdigest()


def read_csv(path: str | Path, interval: int) -> list[Candle]:
    with Path(path).open(newline="", encoding="utf-8") as f:
        result = [Candle(int(r["timestamp"]), *(float(r[k]) for k in
                  ("open", "high", "low", "close", "volume"))) for r in csv.DictReader(f)]
    validate(result, interval)
    return result


def write_csv(path: str | Path, candles: list[Candle]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(asdict(candles[0])))
        writer.writeheader()
        writer.writerows(asdict(c) for c in candles)


class PublicWallex:
    """GET allowlist only. TLS stays enabled; credentials never accepted."""
    base = "https://api.wallex.ir"

    def __init__(self, ca_file: str | None = None, archive_dir: str | None = None):
        self.context = ssl.create_default_context(cafile=ca_file)
        self.archive_dir = Path(archive_dir) if archive_dir else None
        self.last_observation = None

    def get(self, path: str, params: dict | None = None) -> dict:
        if path not in {"/v1/markets", "/v1/udf/history"}:
            raise ValueError("endpoint not in public read allowlist")
        url = self.base + path + ("?" + urllib.parse.urlencode(params) if params else "")
        request = urllib.request.Request(url, headers={"Accept": "application/json",
                                                      "User-Agent": "wallex-research/0.1"})
        for attempt in range(3):
            try:
                sent = time.time()
                with urllib.request.urlopen(request, timeout=25, context=self.context) as response:
                    if "json" not in response.headers.get("Content-Type", ""):
                        raise ValueError("expected JSON content type")
                    body = response.read(20_000_001)
                    if len(body) > 20_000_000:
                        raise ValueError("response exceeds bounded size")
                    data = json.loads(body)
                    from .runtime import clock_observation
                    received = time.time()
                    self.last_observation = {'sent_at':sent, 'received_at':received,
                        'clock':clock_observation(response.headers.get('Date'),sent,received)}
                    if self.archive_dir:
                        self.archive_dir.mkdir(parents=True, exist_ok=True)
                        key = hashlib.sha256((url+hashlib.sha256(body).hexdigest()).encode()).hexdigest()
                        dest = self.archive_dir / (key+".json")
                        if not dest.exists():
                            dest.write_text(json.dumps({"url": url, "fetched_at": int(time.time()),
                                                       "response": data}, sort_keys=True))
                    return data
            except urllib.error.HTTPError as e:
                if e.code not in {429, 500, 502, 503, 504} or attempt == 2:
                    raise
                time.sleep(min(10, 2 ** attempt))
        raise RuntimeError("unreachable")

    def history(self, symbol: str, start: int, end: int, interval: int = 3600,
                *, split_gaps: bool = False) -> list[Candle]:
        resolutions = {60: "1", 3600: "60", 86400: "1D"}
        if interval not in resolutions or end <= start or not symbol.isalnum():
            raise ValueError("invalid research request")
        result: dict[int, Candle] = {}
        cursor = start
        # Bounded windows, verify actual cadence rather than trusting a resolution label.
        while cursor < end:
            # Live evidence: large hourly ranges silently return only the latest ~697 bars.
            # Small windows avoid dropping the leading portion of each response.
            until = min(end, cursor + 500 * interval)
            data = self.get("/v1/udf/history", {"symbol": symbol, "resolution": resolutions[interval],
                                              "from": cursor, "to": until})
            if data.get("s") != "ok":
                raise ValueError(f"history status: {data.get('s')}")
            keys = ("t", "o", "h", "l", "c", "v")
            if len({len(data[k]) for k in keys}) != 1:
                raise ValueError("unequal history arrays")
            for row in zip(*(data[k] for k in keys)):
                c = Candle(int(row[0]), *(float(x) for x in row[1:]))
                if start <= c.timestamp and c.timestamp + interval <= end:
                    if c.timestamp in result and result[c.timestamp] != c:
                        raise ValueError("conflicting overlap")
                    result[c.timestamp] = c
            cursor = until
            if cursor < end:
                time.sleep(0.15)
        candles = sorted(result.values(), key=lambda c: c.timestamp)
        if split_gaps:
            for segment in contiguous_segments(candles, interval):
                validate(segment, interval, now=end)
        else:
            validate(candles, interval, now=end)
        return candles


def contiguous_segments(candles: list[Candle], interval: int) -> list[list[Candle]]:
    """Explicit segmentation. No gap filling and no carrying positions across outages."""
    result: list[list[Candle]] = []
    for c in candles:
        if not result or c.timestamp-result[-1][-1].timestamp != interval:
            result.append([])
        result[-1].append(c)
    return result
