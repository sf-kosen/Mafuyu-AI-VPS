import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from mafuyu.budget import Budget, cache_hit_tokens


def usage(prompt, completion, hit=None, details_hit=None):
    details = SimpleNamespace(cached_tokens=details_hit) if details_hit is not None else None
    return SimpleNamespace(
        prompt_tokens=prompt, completion_tokens=completion,
        prompt_cache_hit_tokens=hit, prompt_tokens_details=details,
    )


class BudgetTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        # $1 per 1M miss, $0.1 per 1M hit, $2 per 1M output: easy numbers.
        self.budget = Budget(Path(self.tmp.name) / "b.sqlite3", 0.01, 0.05, 1.0, 0.1, 2.0)

    def tearDown(self):
        self.budget._conn.close()
        self.tmp.cleanup()

    def test_cache_hit_locations(self):
        self.assertEqual(cache_hit_tokens(usage(100, 0, hit=40)), 40)
        self.assertEqual(cache_hit_tokens(usage(100, 0, details_hit=30)), 30)
        self.assertEqual(cache_hit_tokens(usage(100, 0)), 0)
        self.assertEqual(cache_hit_tokens({"prompt_cache_hit_tokens": 7}), 7)

    def test_cost(self):
        # 600 miss * 1 + 400 hit * 0.1 + 1000 out * 2 = 2640 / 1M
        self.assertAlmostEqual(self.budget.cost_of(usage(1000, 1000, hit=400)), 0.00264)

    def test_daily_cap(self):
        self.assertFalse(self.budget.exceeded())
        self.budget.record(usage(0, 2000))  # $0.004
        self.budget.record(usage(0, 2000))  # $0.008 total
        self.assertFalse(self.budget.exceeded())
        self.budget.record(usage(0, 2000))  # $0.012 total, over the $0.01 daily cap
        self.assertTrue(self.budget.exceeded())
        self.assertAlmostEqual(self.budget.spent()[0], 0.012)
        self.assertAlmostEqual(self.budget.spent()[1], 0.012)

    def test_disabled_cap(self):
        self.budget.daily_usd = 0
        self.budget.monthly_usd = 0
        self.budget.record(usage(0, 10_000_000))
        self.assertFalse(self.budget.exceeded())


if __name__ == "__main__":
    unittest.main()
