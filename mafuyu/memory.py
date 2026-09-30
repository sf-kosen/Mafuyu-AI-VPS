"""Per-user long-term notes, stored in SQLite.

Each user has a short free-text note (what Mafuyu remembers about them) plus a
rolling log of recent exchanges that is periodically folded into the note.
"""

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

NOTES_MAX_CHARS = 800
LOG_KEEP_PER_USER = 30


class MemoryStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock, self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS user_notes (
                    user_id INTEGER PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    notes TEXT NOT NULL DEFAULT '',
                    since_update INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS exchanges (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    user_text TEXT NOT NULL,
                    bot_text TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS exchanges_user ON exchanges(user_id, id);
                """
            )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def get_notes(self, user_ids: list[int]) -> dict[int, tuple[str, str]]:
        """Return {user_id: (display_name, notes)} for users that have non-empty notes."""
        if not user_ids:
            return {}
        marks = ",".join("?" * len(user_ids))
        with self._lock:
            rows = self._conn.execute(
                f"SELECT user_id, display_name, notes FROM user_notes "
                f"WHERE user_id IN ({marks}) AND notes != ''",
                user_ids,
            ).fetchall()
        return {uid: (name, notes) for uid, name, notes in rows}

    def record_exchange(self, user_id: int, display_name: str, user_text: str, bot_text: str) -> int:
        """Log one exchange and return how many exchanges happened since the last note update."""
        now = self._now()
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO exchanges (user_id, user_text, bot_text, created_at) VALUES (?, ?, ?, ?)",
                (user_id, user_text[:1000], bot_text[:1000], now),
            )
            self._conn.execute(
                "DELETE FROM exchanges WHERE user_id = ? AND id NOT IN "
                "(SELECT id FROM exchanges WHERE user_id = ? ORDER BY id DESC LIMIT ?)",
                (user_id, user_id, LOG_KEEP_PER_USER),
            )
            self._conn.execute(
                "INSERT INTO user_notes (user_id, display_name, since_update, updated_at) "
                "VALUES (?, ?, 1, ?) ON CONFLICT(user_id) DO UPDATE SET "
                "display_name = excluded.display_name, since_update = since_update + 1",
                (user_id, display_name, now),
            )
            (count,) = self._conn.execute(
                "SELECT since_update FROM user_notes WHERE user_id = ?", (user_id,)
            ).fetchone()
        return count

    def recent_exchanges(self, user_id: int, limit: int) -> list[tuple[str, str, str]]:
        """Return the user's last `limit` exchanges as (created_at, user_text, bot_text), oldest first."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT created_at, user_text, bot_text FROM exchanges WHERE user_id = ? "
                "ORDER BY id DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        return list(reversed(rows))

    def pending_exchanges(self, user_id: int) -> tuple[str, list[tuple[str, str]]]:
        """Return (current notes, exchanges not yet folded into the notes), oldest first."""
        with self._lock:
            row = self._conn.execute(
                "SELECT notes, since_update FROM user_notes WHERE user_id = ?", (user_id,)
            ).fetchone()
            if not row:
                return "", []
            notes, since = row
            rows = self._conn.execute(
                "SELECT user_text, bot_text FROM exchanges WHERE user_id = ? ORDER BY id DESC LIMIT ?",
                (user_id, since),
            ).fetchall()
        return notes, list(reversed(rows))

    def set_notes(self, user_id: int, notes: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE user_notes SET notes = ?, since_update = 0, updated_at = ? WHERE user_id = ?",
                (notes.strip()[:NOTES_MAX_CHARS], self._now(), user_id),
            )

    def forget(self, user_id: int) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM user_notes WHERE user_id = ?", (user_id,))
            self._conn.execute("DELETE FROM exchanges WHERE user_id = ?", (user_id,))
