"""Optional causal LLM proposer. No broker tools, no account data, bounded requests."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import ssl
import urllib.request
from dataclasses import asdict, dataclass
from typing import Callable
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .journal import Journal, canonical

PROMPT = """wallex-proposal-v1: You are a cautious short-horizon trading proposal agent.
Use ONLY supplied numeric market facts; do not use remembered prices, dates, news or future knowledge.
Choose ENTER, HOLD or EXIT. ENTER proposes a target allocation, never a direct order.
HOLD keeps the current exposure; EXIT requests zero exposure. Cite input feature names in reason.
Require positive expected net edge after round-trip costs; uncertainty means HOLD.
Independent risk rules can veto you. Never request a tool, account access, leverage or shorting.
Return only the required JSON fields. Do not claim guaranteed profit."""
SCHEMA = {"type": "object", "additionalProperties": False,
          "properties": {"action": {"type": "string", "enum": ["ENTER", "HOLD", "EXIT"]},
                         "allocation": {"type": "number", "minimum": 0, "maximum": 0.2},
                         "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                         "reason": {"type": "string"}},
          "required": ["action", "allocation", "confidence", "reason"]}


@dataclass(frozen=True)
class Decision:
    action: str
    allocation: float
    confidence: float
    reason: str


class DecisionSchema(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    action: Literal['ENTER', 'HOLD', 'EXIT']
    allocation: float = Field(ge=0, le=.2)
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1, max_length=1000)


def parse_decision(text: str) -> Decision:
    d = json.loads(text)
    DecisionSchema.model_validate(d)
    if not isinstance(d, dict) or set(d) != set(SCHEMA["required"]):
        raise ValueError("invalid AI fields")
    if d["action"] not in {"ENTER", "HOLD", "EXIT"}:
        raise ValueError("invalid AI action")
    for key, upper in (("allocation", .2), ("confidence", 1)):
        value = d[key]
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= upper:
            raise ValueError("AI bounds violation")
    if not isinstance(d["reason"], str) or not 1 <= len(d["reason"]) <= 1000:
        raise ValueError("invalid AI reason")
    if d["action"] == "EXIT" and d["allocation"] != 0:
        raise ValueError("EXIT must be zero")
    return Decision(**d)


class Provider:
    def __init__(self, provider: str, model: str, ca_file: str | None = None):
        if provider not in {"openai", "gemini", "boxapi"} or not re.fullmatch(r"[A-Za-z0-9_.:/-]{1,120}", model):
            raise ValueError("invalid provider/model")
        self.provider, self.model = provider, model
        self.context = ssl.create_default_context(cafile=ca_file)
        self.last_metadata = {}
        self.boxapi = None
        self.gemini = None
        if provider == 'boxapi':
            from .boxapi import BoxAPIProvider
            self.boxapi = BoxAPIProvider(model, ca_file=ca_file)
        if provider == 'gemini':
            from .gemini import GeminiProvider
            self.gemini = GeminiProvider(model)

    def __call__(self, context: dict) -> str:
        if self.boxapi is not None:
            try:
                return self.boxapi(context)
            finally:
                self.last_metadata = self.boxapi.last_metadata
        if self.gemini is not None:
            try:
                return self.gemini(context)
            finally:
                self.last_metadata = self.gemini.last_metadata
        if self.provider == "openai":
            key = os.environ.get("OPENAI_API_KEY")
            url = "https://api.openai.com/v1/responses"
            payload = {"model": self.model, "instructions": PROMPT, "input": canonical(context),
                       "store": False, "max_output_tokens": 512,
                       "text": {"format": {"type": "json_schema", "name": "trade_proposal",
                                           "strict": True, "schema": SCHEMA}}}
            headers = {"Authorization": "Bearer "+(key or "")}
        else:
            key = os.environ.get("GEMINI_API_KEY")
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
            payload = {"systemInstruction": {"parts": [{"text": PROMPT}]},
                       "contents": [{"parts": [{"text": canonical(context)}]}],
                       "generationConfig": {"maxOutputTokens": 512, "responseMimeType": "application/json",
                                            "responseJsonSchema": SCHEMA}}
            headers = {"x-goog-api-key": key or ""}
        if not key:
            raise ValueError("LLM credential not configured")
        headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=canonical(payload).encode(), headers=headers, method="POST")
        # No automatic retries: timeouts can still incur provider billing.
        with urllib.request.urlopen(request, timeout=20, context=self.context) as response:
            raw = response.read(1_000_001)
            if len(raw) > 1_000_000:
                raise ValueError("oversized LLM response")
            data = json.loads(raw)
        if self.provider == "openai":
            if data.get("status") != "completed":
                raise ValueError("incomplete LLM output")
            return "".join(part["text"] for item in data.get("output", [])
                           for part in item.get("content", []) if part.get("type") == "output_text")
        candidate = data["candidates"][0]
        if candidate.get("finishReason") != "STOP":
            raise ValueError("incomplete LLM output")
        return "".join(p.get("text", "") for p in candidate["content"]["parts"])


class Agent:
    def __init__(self, provider: Callable[[dict], str], journal: Journal, *, model: str,
                 max_calls: int = 20, budget_usd: float = 1, reserve_per_call_usd: float = .05):
        if max_calls < 0 or not 0 < reserve_per_call_usd <= budget_usd:
            raise ValueError("invalid AI budget")
        self.provider, self.journal, self.model = provider, journal, model
        self.max_calls, self.budget, self.reserve = max_calls, budget_usd, reserve_per_call_usd
        self.prompt_hash = hashlib.sha256(PROMPT.encode()).hexdigest()

    def decide(self, context: dict) -> tuple[Decision, dict]:
        context_text = canonical(context)
        if len(context_text) > 12_000:
            return Decision("HOLD", 0, 0, "context too large"), {"status": "blocked"}
        cache_key = hashlib.sha256((self.model+self.prompt_hash+context_text).encode()).hexdigest()
        # Persistent response cache and budget reservation survive restarts.
        existing = self.journal.db.execute("SELECT body FROM events WHERE event_key=?",
                                          ("ai-result:"+cache_key,)).fetchone()
        if existing:
            body = json.loads(existing[0])
            return Decision(**body["decision"]), body
        used = self.journal.db.execute("SELECT COUNT(*) FROM events WHERE event_key LIKE 'ai-intent:%'").fetchone()[0]
        if used >= self.max_calls or (used+1)*self.reserve > self.budget+1e-12:
            return Decision("HOLD", 0, 0, "AI budget exhausted"), {"status": "budget"}
        key = "ai-intent:"+cache_key
        if not self.journal.append(key, {"model": self.model, "prompt_hash": self.prompt_hash,
                                       "context": context, "reserved_usd": self.reserve}):
            # An intent without result is an ambiguous timeout/crash: do not repeat.
            return Decision("HOLD", 0, 0, "ambiguous prior AI call"), {"status": "ambiguous"}
        status = "ok"
        original_decision = None
        try:
            decision = parse_decision(self.provider(context))
            original_decision = asdict(decision)
            if decision.confidence < .65:
                decision = Decision("HOLD", 0, decision.confidence, "low LLM confidence")
        except Exception as e:
            # Never include arbitrary provider exception text (could contain credentials).
            decision = Decision("HOLD", 0, 0, "LLM unavailable or invalid: "+type(e).__name__)
            status = "failed_closed"
        body = {"decision": asdict(decision), "status": status, "model": self.model,
                "validated_model_output_before_confidence_gate": original_decision,
                "prompt_hash": self.prompt_hash, "context_hash": cache_key,
                "provider_metadata": getattr(self.provider, 'last_metadata', {})}
        self.journal.append("ai-result:"+cache_key, body)
        return decision, body
