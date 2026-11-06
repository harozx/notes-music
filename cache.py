"""Cache 2 lớp (hybrid) cho Notes.

    L1: RAM trong tiến trình (LRU + TTL)  -> nhanh nhất, mất khi restart
    L2: Redis (REDIS_URL)                  -> dùng chung, sống qua restart
        └─ không cấu hình / Redis chết -> tự chuyển sang SQLite (data/cache.db), Redis sống lại thì dùng lại

Đọc: L1 -> L2 (trúng L2 thì "đẩy" lên L1 với TTL còn lại). Ghi: ghi cả 2 lớp.
Giá trị phải là dữ liệu JSON (dict / list / str / số).
"""

import asyncio
import json
import logging
import sqlite3
import threading
import time
from collections import OrderedDict
from pathlib import Path

log = logging.getLogger("uvicorn.error")

try:
    import redis.asyncio as aioredis
except ImportError:  # chưa cài redis -> chỉ dùng SQLite
    aioredis = None


class _L1:
    """LRU trong RAM có hạn dùng cho từng mục."""

    def __init__(self, maxsize: int):
        self.maxsize = maxsize
        self.data: OrderedDict[str, tuple[float, object]] = OrderedDict()

    def get(self, key: str):
        hit = self.data.get(key)
        if hit is None:
            return None
        if hit[0] < time.time():
            self.data.pop(key, None)
            return None
        self.data.move_to_end(key)
        return hit[1]

    def set(self, key: str, value, ttl: float):
        self.data[key] = (time.time() + ttl, value)
        self.data.move_to_end(key)
        while len(self.data) > self.maxsize:
            self.data.popitem(last=False)

    def delete(self, key: str):
        self.data.pop(key, None)

    def delete_prefix(self, prefix: str):
        for k in [k for k in self.data if k.startswith(prefix)]:
            self.data.pop(k, None)


class _SQLite:
    """L2 dự phòng: bảng key-value có hạn dùng trong 1 file SQLite."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT NOT NULL, exp REAL NOT NULL)")
        self.db.execute("CREATE INDEX IF NOT EXISTS kv_exp ON kv(exp)")
        self.purge()

    def get(self, key: str):
        with self.lock:
            row = self.db.execute("SELECT v, exp FROM kv WHERE k=?", (key,)).fetchone()
        if not row or row[1] < time.time():
            return None
        return row[0], row[1]

    def set(self, key: str, raw: str, exp: float):
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO kv (k, v, exp) VALUES (?, ?, ?)", (key, raw, exp))

    def delete(self, key: str):
        with self.lock:
            self.db.execute("DELETE FROM kv WHERE k=?", (key,))

    def delete_prefix(self, prefix: str):
        esc = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        with self.lock:
            self.db.execute("DELETE FROM kv WHERE k LIKE ? ESCAPE '\\'", (esc + "%",))

    def purge(self):
        with self.lock:
            self.db.execute("DELETE FROM kv WHERE exp < ?", (time.time(),))

    def count(self) -> int:
        with self.lock:
            return self.db.execute("SELECT COUNT(*) FROM kv").fetchone()[0]

    def close(self):
        with self.lock:
            self.db.close()


class HybridCache:
    def __init__(self, redis_url: str, sqlite_path: Path, l1_size: int = 2000, prefix: str = "notes:"):
        self.redis_url = redis_url
        self.prefix = prefix
        self.l1 = _L1(l1_size)
        self.sqlite = _SQLite(sqlite_path)
        self.redis = None
        self._redis_down_until = 0.0
        self._janitor: asyncio.Task | None = None
        self.stats = {"l1_hit": 0, "l2_hit": 0, "miss": 0, "set": 0, "redis_errors": 0}

    # ------------------------------------------------------------ vòng đời
    async def start(self):
        if self.redis_url and aioredis:
            self.redis = aioredis.from_url(self.redis_url, socket_timeout=0.5, socket_connect_timeout=0.5,
                                           health_check_interval=30)
            try:
                await self.redis.ping()
                log.info("cache: L1 RAM + L2 Redis (%s)", self.redis_url.split("@")[-1])
            except Exception as e:
                self._mark_down(e)
        elif self.redis_url and not aioredis:
            log.warning("cache: có REDIS_URL nhưng chưa cài thư viện 'redis' (pip install redis) -> dùng SQLite")
        if not self._redis_ok():
            log.info("cache: L1 RAM + L2 SQLite (%s)", self.sqlite.db.execute("PRAGMA database_list").fetchone()[2])
        self._janitor = asyncio.create_task(self._clean_loop())

    async def close(self):
        if self._janitor:
            self._janitor.cancel()
        if self.redis:
            try:
                await self.redis.aclose()
            except Exception:
                pass
        self.sqlite.close()

    async def _clean_loop(self):
        while True:
            await asyncio.sleep(600)
            try:
                await asyncio.to_thread(self.sqlite.purge)
            except Exception as e:
                log.warning("cache: dọn SQLite lỗi: %s", e)

    # ------------------------------------------------------------ Redis khoẻ / chết
    def _redis_ok(self) -> bool:
        return self.redis is not None and time.time() >= self._redis_down_until

    def _mark_down(self, e: Exception):
        if time.time() >= self._redis_down_until:
            log.warning("cache: Redis lỗi (%s) -> tạm dùng SQLite 30 giây", e)
        self.stats["redis_errors"] += 1
        self._redis_down_until = time.time() + 30

    # ------------------------------------------------------------ L2 thô
    async def _l2_get(self, key: str):
        if self._redis_ok():
            try:
                raw = await self.redis.get(key)
                if raw is None:
                    return None
                env = json.loads(raw)
                return env["v"], env["e"]
            except Exception as e:
                self._mark_down(e)
        hit = await asyncio.to_thread(self.sqlite.get, key)
        if hit is None:
            return None
        return json.loads(hit[0]), hit[1]

    async def _l2_set(self, key: str, value, ttl: float):
        exp = time.time() + ttl
        if self._redis_ok():
            try:
                await self.redis.set(key, json.dumps({"e": exp, "v": value}, ensure_ascii=False),
                                     px=max(1, int(ttl * 1000)))
                return
            except Exception as e:
                self._mark_down(e)
        await asyncio.to_thread(self.sqlite.set, key, json.dumps(value, ensure_ascii=False), exp)

    # ------------------------------------------------------------ API
    def _k(self, ns: str, key: str) -> str:
        return f"{self.prefix}{ns}:{key}"

    async def get(self, ns: str, key: str):
        k = self._k(ns, key)
        v = self.l1.get(k)
        if v is not None:
            self.stats["l1_hit"] += 1
            return v
        hit = await self._l2_get(k)
        if hit is None:
            self.stats["miss"] += 1
            return None
        value, exp = hit
        self.stats["l2_hit"] += 1
        remain = exp - time.time()
        if remain > 0:
            self.l1.set(k, value, remain)
        return value

    async def set(self, ns: str, key: str, value, ttl: float, l1_ttl: float | None = None):
        """ttl: hạn dùng ở L2. l1_ttl: hạn dùng ở RAM (mặc định = ttl)."""
        if ttl <= 0:
            return
        k = self._k(ns, key)
        self.l1.set(k, value, min(ttl, l1_ttl or ttl))
        self.stats["set"] += 1
        try:
            await self._l2_set(k, value, ttl)
        except Exception as e:  # L2 hỏng hẳn vẫn còn L1, không làm hỏng request
            log.warning("cache: ghi L2 lỗi: %s", e)

    async def delete(self, ns: str, key: str):
        k = self._k(ns, key)
        self.l1.delete(k)
        if self._redis_ok():
            try:
                await self.redis.delete(k)
            except Exception as e:
                self._mark_down(e)
        await asyncio.to_thread(self.sqlite.delete, k)

    async def delete_prefix(self, ns: str, prefix: str = ""):
        p = self._k(ns, prefix)
        self.l1.delete_prefix(p)
        if self._redis_ok():
            try:
                keys = [k async for k in self.redis.scan_iter(match=_glob_escape(p) + "*", count=500)]
                if keys:
                    await self.redis.delete(*keys)
            except Exception as e:
                self._mark_down(e)
        await asyncio.to_thread(self.sqlite.delete_prefix, p)

    async def info(self) -> dict:
        total = self.stats["l1_hit"] + self.stats["l2_hit"] + self.stats["miss"]
        hits = self.stats["l1_hit"] + self.stats["l2_hit"]
        return {
            "l1": {"backend": "memory", "items": len(self.l1.data), "max": self.l1.maxsize},
            "l2": {"backend": "redis" if self._redis_ok() else "sqlite",
                   "redis_configured": bool(self.redis_url), "sqlite_items": self.sqlite.count()},
            "hit_rate": round(hits / total, 3) if total else None,
            **self.stats,
        }


def _glob_escape(s: str) -> str:
    return "".join("\\" + c if c in "*?[]\\" else c for c in s)
