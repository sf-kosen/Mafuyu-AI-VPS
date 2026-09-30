"""Spending guard: estimates API cost from token usage and enforces daily/monthly caps.

Costs are estimated with peak-hour prices (the higher rate), so the real bill is at
most what is recorded here. Days and months roll over in JST.
"""

import logging
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)

JST = ZoneInfo("Asia/Tokyo")


def _get(obj, name: str):
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def cache_hit_tokens(usage) -> int:
    """DeepSeek reports cache hits either at the top level or under prompt_tokens_details."""
    for value in (
        _get(usage, "prompt_cache_hit_tokens"),
        _get(_get(usage, "prompt_tokens_details"), "prompt_cache_hit_tokens"),
        _get(_get(usage, "prompt_tokens_details"), "cached_tokens"),
    ):
        if isinstance(value, int):
            return value
    return 0


class Budget:
    def __init__(
        self,
        path: Path,
        daily_usd: float,
        monthly_usd: float,
        price_input_miss: float,
        price_input_hit: float,
        price_output: float,
    ):
        """Prices are USD per 1M tokens. A cap of 0 or less disables that cap."""
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        self.daily_usd = daily_usd
        self.monthly_usd = monthly_usd
        self._prices = (price_input_miss, price_input_hit, price_output)
        with self._lock, self._conn:
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS spend (day TEXT PRIMARY KEY, usd REAL NOT NULL)"
            )

    @staticmethod
    def _today() -> str:
        return datetime.now(JST).strftime("%Y-%m-%d")

    def cost_of(self, usage) -> float:
        miss_price, hit_price, out_price = self._prices
        prompt = _get(usage, "prompt_tokens") or 0
        completion = _get(usage, "completion_tokens") or 0
        hit = min(cache_hit_tokens(usage), prompt)
        return ((prompt - hit) * miss_price + hit * hit_price + completion * out_price) / 1_000_000

    def record(self, usage) -> float:
        cost = self.cost_of(usage)
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO spend (day, usd) VALUES (?, ?) "
                "ON CONFLICT(day) DO UPDATE SET usd = usd + excluded.usd",
                (self._today(), cost),
            )
        return cost

    def spent(self) -> tuple[float, float]:
        """Return (today's spend, this month's spend) in USD."""
        today = self._today()
        with self._lock:
            (day,) = self._conn.execute(
                "SELECT COALESCE(SUM(usd), 0) FROM spend WHERE day = ?", (today,)
            ).fetchone()
            (month,) = self._conn.execute(
                "SELECT COALESCE(SUM(usd), 0) FROM spend WHERE day LIKE ?", (today[:7] + "-%",)
            ).fetchone()
        return day, month

    def exceeded(self) -> bool:
        day, month = self.spent()
        return (0 < self.daily_usd <= day) or (0 < self.monthly_usd <= month)
