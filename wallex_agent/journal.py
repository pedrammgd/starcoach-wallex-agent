"""Transactional append-only event chain with idempotent restart/replay checks."""
import hashlib
import json
import sqlite3
from pathlib import Path


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


class Journal:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=10)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS events (
            seq INTEGER PRIMARY KEY, event_key TEXT UNIQUE NOT NULL,
            body TEXT NOT NULL, previous_hash TEXT NOT NULL, hash TEXT NOT NULL);
          CREATE TRIGGER IF NOT EXISTS no_update BEFORE UPDATE ON events
          BEGIN SELECT RAISE(ABORT, 'append-only'); END;
          CREATE TRIGGER IF NOT EXISTS no_delete BEFORE DELETE ON events
          BEGIN SELECT RAISE(ABORT, 'append-only'); END;
        """)
        self.verify()

    def append(self, key: str, body: dict) -> bool:
        serialized = canonical(body)
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            old = self.db.execute("SELECT body FROM events WHERE event_key=?", (key,)).fetchone()
            if old:
                if old[0] != serialized:
                    raise ValueError("replay divergence: config, code or historical data changed")
                return False
            last = self.db.execute("SELECT hash FROM events ORDER BY seq DESC LIMIT 1").fetchone()
            previous = last[0] if last else "0"*64
            hash_ = hashlib.sha256((previous+key+serialized).encode()).hexdigest()
            self.db.execute("INSERT INTO events(event_key,body,previous_hash,hash) VALUES (?,?,?,?)",
                            (key, serialized, previous, hash_))
        return True

    def verify(self) -> int:
        previous = "0"*64
        count = 0
        for key, body, prev, hash_ in self.db.execute(
                "SELECT event_key,body,previous_hash,hash FROM events ORDER BY seq"):
            expected = hashlib.sha256((previous+key+body).encode()).hexdigest()
            if prev != previous or expected != hash_:
                raise ValueError("journal chain integrity failure")
            previous = hash_
            count += 1
        return count

    def export(self, path: str) -> None:
        self.verify()
        with Path(path).open("w", encoding="utf-8") as f:
            for seq, key, body, previous, hash_ in self.db.execute("SELECT * FROM events ORDER BY seq"):
                f.write(canonical({"seq": seq, "key": key, "event": json.loads(body),
                                   "previous_hash": previous, "hash": hash_})+"\n")

    def close(self):
        self.db.close()
