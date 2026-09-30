import tempfile
import unittest
from pathlib import Path

from mafuyu.memory import MemoryStore


class MemoryStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = MemoryStore(Path(self.tmp.name) / "m.sqlite3")

    def tearDown(self):
        self.store._conn.close()
        self.tmp.cleanup()

    def test_exchange_count_and_pending(self):
        self.assertEqual(self.store.record_exchange(1, "a", "u1", "b1"), 1)
        self.assertEqual(self.store.record_exchange(1, "a", "u2", "b2"), 2)
        notes, ex = self.store.pending_exchanges(1)
        self.assertEqual(notes, "")
        self.assertEqual(ex, [("u1", "b1"), ("u2", "b2")])

        self.store.set_notes(1, "- 猫が好き")
        self.assertEqual(self.store.get_notes([1, 2]), {1: ("a", "- 猫が好き")})
        self.assertEqual(self.store.pending_exchanges(1), ("- 猫が好き", []))
        self.assertEqual(self.store.record_exchange(1, "a2", "u3", "b3"), 1)
        self.assertEqual(self.store.get_notes([1]), {1: ("a2", "- 猫が好き")})

    def test_recent_exchanges(self):
        for i in range(4):
            self.store.record_exchange(1, "a", f"u{i}", f"b{i}")
        self.store.record_exchange(2, "b", "other", "x")
        recent = self.store.recent_exchanges(1, 2)
        self.assertEqual([(u, b) for _, u, b in recent], [("u2", "b2"), ("u3", "b3")])

    def test_forget(self):
        self.store.record_exchange(1, "a", "u", "b")
        self.store.set_notes(1, "x")
        self.store.forget(1)
        self.assertEqual(self.store.get_notes([1]), {})
        self.assertEqual(self.store.pending_exchanges(1), ("", []))


if __name__ == "__main__":
    unittest.main()
