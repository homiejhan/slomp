"""SQLite storage: the HTTP response cache, cross-site price observations, and verification results.

One file, one process. Calls are short and synchronous; a lock makes the connection safe to share between the
event loop and worker threads.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS http_cache (
    key TEXT PRIMARY KEY, url TEXT NOT NULL, status INTEGER NOT NULL, content_type TEXT, final_url TEXT,
    body BLOB, fetched_at REAL NOT NULL, expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS price_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT, product_key TEXT NOT NULL, site TEXT NOT NULL, title TEXT, price REAL,
    regular_price REAL, url TEXT, match TEXT, in_stock INTEGER, observed_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS price_obs_key ON price_observations(product_key, observed_at);
CREATE TABLE IF NOT EXISTS verify_runs (
    run_id TEXT PRIMARY KEY, iteration INTEGER, seed INTEGER, started_at REAL, finished_at REAL, summary TEXT
);
CREATE TABLE IF NOT EXISTS verify_results (
    run_id TEXT NOT NULL, test_id TEXT NOT NULL, grp TEXT, category TEXT, subject TEXT, verdict TEXT, detail TEXT,
    PRIMARY KEY (run_id, test_id)
);
"""


@dataclass
class CachedResponse:
    url: str
    status: int
    content_type: str
    final_url: str
    body: bytes
    fetched_at: float
    expires_at: float

    @property
    def fresh(self) -> bool:
        return self.expires_at > time.time()


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(path), check_same_thread=False, timeout=30)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(SCHEMA)
        self._db.commit()

    # -- HTTP cache -----------------------------------------------------------------------------------------------
    def cache_get(self, key: str) -> Optional[CachedResponse]:
        with self._lock:
            row = self._db.execute("SELECT url, status, content_type, final_url, body, fetched_at, expires_at "
                                   "FROM http_cache WHERE key = ?", (key,)).fetchone()
        return CachedResponse(*row) if row else None

    def cache_put(self, key: str, resp: CachedResponse) -> None:
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO http_cache VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                             (key, resp.url, resp.status, resp.content_type, resp.final_url, resp.body,
                              resp.fetched_at, resp.expires_at))
            self._db.commit()

    def cache_purge(self, older_than_s: float = 30 * 86400) -> int:
        with self._lock:
            cur = self._db.execute("DELETE FROM http_cache WHERE expires_at < ?", (time.time() - older_than_s,))
            self._db.commit()
            return cur.rowcount

    # -- price observations ---------------------------------------------------------------------------------------
    def observe_prices(self, rows: Iterable[dict]) -> None:
        now = time.time()
        with self._lock:
            self._db.executemany(
                "INSERT INTO price_observations (product_key, site, title, price, regular_price, url, match, in_stock, "
                "observed_at) VALUES (:product_key, :site, :title, :price, :regular_price, :url, :match, :in_stock, :t)",
                [{**{"regular_price": None, "in_stock": None, "title": None, "match": None}, **r, "t": now}
                 for r in rows])
            self._db.commit()

    def price_history(self, product_key: str, since_s: float = 90 * 86400) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT site, price, url, observed_at FROM price_observations WHERE product_key = ? AND observed_at > ? "
                "ORDER BY observed_at", (product_key, time.time() - since_s)).fetchall()
        return [{"site": s, "price": p, "url": u, "observed_at": t} for s, p, u, t in rows]

    # -- verification ---------------------------------------------------------------------------------------------
    def verify_start(self, run_id: str, iteration: int, seed: int) -> None:
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO verify_runs VALUES (?, ?, ?, ?, NULL, NULL)",
                             (run_id, iteration, seed, time.time()))
            self._db.commit()

    def verify_record(self, run_id: str, test_id: str, grp: str, category: str, subject: str, verdict: str,
                      detail: Any) -> None:
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO verify_results VALUES (?, ?, ?, ?, ?, ?, ?)",
                             (run_id, test_id, grp, category, subject, verdict, json.dumps(detail, default=str)))
            self._db.commit()

    def verify_finish(self, run_id: str, summary: dict) -> None:
        with self._lock:
            self._db.execute("UPDATE verify_runs SET finished_at = ?, summary = ? WHERE run_id = ?",
                             (time.time(), json.dumps(summary, default=str), run_id))
            self._db.commit()

    def verify_results(self, run_id: str) -> list[dict]:
        with self._lock:
            rows = self._db.execute("SELECT test_id, grp, category, subject, verdict, detail FROM verify_results "
                                    "WHERE run_id = ? ORDER BY test_id", (run_id,)).fetchall()
        return [{"test_id": t, "group": g, "category": c, "subject": s, "verdict": v, "detail": json.loads(d)}
                for t, g, c, s, v, d in rows]

    def close(self) -> None:
        with self._lock:
            self._db.close()
