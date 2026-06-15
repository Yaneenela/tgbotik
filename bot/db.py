import aiosqlite
import os
from datetime import datetime, timedelta
from typing import Optional

DB_PATH = os.getenv("DB_PATH", "data/bot.db")


class Database:
    def __init__(self, path: str = DB_PATH):
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)

    async def connect(self):
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self._migrate()

    async def close(self):
        await self.conn.close()

    async def _migrate(self):
        await self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE NOT NULL,
                username TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_admin INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                plan_name TEXT NOT NULL,
                uuid TEXT NOT NULL,
                inbound_id INTEGER NOT NULL,
                traffic_up INTEGER DEFAULT 0,
                traffic_down INTEGER DEFAULT 0,
                traffic_total INTEGER DEFAULT 0,
                expired_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active INTEGER DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                amount REAL NOT NULL,
                currency TEXT DEFAULT 'RUB',
                plan_name TEXT,
                payment_system TEXT,
                payment_id TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        await self.conn.commit()
        try:
            await self.conn.execute("ALTER TABLE subscriptions ADD COLUMN reminded_at TIMESTAMP")
            await self.conn.commit()
        except Exception:
            pass
        try:
            await self.conn.execute("ALTER TABLE subscriptions ADD COLUMN device_count INTEGER DEFAULT 3")
            await self.conn.commit()
        except Exception:
            pass

    async def get_user(self, telegram_id: int) -> Optional[dict]:
        cursor = await self.conn.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def create_user(self, telegram_id: int, username: str = None) -> dict:
        await self.conn.execute(
            "INSERT OR IGNORE INTO users (telegram_id, username) VALUES (?, ?)",
            (telegram_id, username),
        )
        await self.conn.commit()
        user = await self.get_user(telegram_id)
        return user

    async def add_subscription(
        self,
        user_id: int,
        plan_name: str,
        uuid_str: str,
        inbound_id: int,
        days: int,
        traffic_gb: int,
        device_count: int = 3,
    ) -> dict:
        expired_at = datetime.now() + timedelta(days=days)
        total_bytes = traffic_gb * 1024**3 if traffic_gb > 0 else 0
        cursor = await self.conn.execute(
            """INSERT INTO subscriptions
               (user_id, plan_name, uuid, inbound_id, traffic_total, expired_at, device_count)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (user_id, plan_name, uuid_str, inbound_id, total_bytes, expired_at, device_count),
        )
        await self.conn.commit()
        return await self.get_subscription(cursor.lastrowid)

    async def get_subscription(self, sub_id: int) -> Optional[dict]:
        cursor = await self.conn.execute(
            "SELECT * FROM subscriptions WHERE id = ?", (sub_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_user_subscriptions(self, user_id: int) -> list[dict]:
        cursor = await self.conn.execute(
            "SELECT * FROM subscriptions WHERE user_id = ? AND is_active = 1 ORDER BY created_at DESC",
            (user_id,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def add_transaction(
        self,
        user_id: int,
        amount: float,
        currency: str,
        payment_system: str,
        payment_id: str = None,
        plan_name: str = None,
        status: str = "pending",
    ):
        await self.conn.execute(
            """INSERT INTO transactions
               (user_id, amount, currency, payment_system, payment_id, plan_name, status)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (user_id, amount, currency, payment_system, payment_id, plan_name, status),
        )
        await self.conn.commit()

    async def update_transaction(self, payment_id: str, status: str):
        await self.conn.execute(
            "UPDATE transactions SET status = ? WHERE payment_id = ?",
            (status, payment_id),
        )
        await self.conn.commit()

    async def get_all_users(self) -> list[dict]:
        cursor = await self.conn.execute("SELECT * FROM users ORDER BY created_at DESC")
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_all_active_subs(self) -> list[dict]:
        cursor = await self.conn.execute(
            "SELECT s.*, u.telegram_id, u.username FROM subscriptions s "
            "JOIN users u ON s.user_id = u.id "
            "WHERE s.is_active = 1 ORDER BY s.expired_at ASC"
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def update_sub_expiry(self, sub_id: int, days: int):
        expired_at = datetime.now() + timedelta(days=days)
        await self.conn.execute(
            "UPDATE subscriptions SET expired_at = ? WHERE id = ?",
            (expired_at, sub_id),
        )
        await self.conn.commit()

    async def update_sub_device_count(self, sub_id: int, device_count: int):
        await self.conn.execute(
            "UPDATE subscriptions SET device_count = ? WHERE id = ?",
            (device_count, sub_id),
        )
        await self.conn.commit()

    async def deactivate_sub(self, sub_id: int):
        await self.conn.execute(
            "UPDATE subscriptions SET is_active = 0 WHERE id = ?",
            (sub_id,),
        )
        await self.conn.commit()

    async def get_active_sub_by_user_and_plan(self, user_id: int, plan_name: str) -> Optional[dict]:
        cursor = await self.conn.execute(
            "SELECT * FROM subscriptions WHERE user_id = ? AND plan_name = ? AND is_active = 1 LIMIT 1",
            (user_id, plan_name),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_expiring_subs(self, within_days: int) -> list[dict]:
        cursor = await self.conn.execute(
            "SELECT s.*, u.telegram_id, u.username FROM subscriptions s "
            "JOIN users u ON s.user_id = u.id "
            "WHERE s.is_active = 1 AND s.expired_at IS NOT NULL"
        )
        rows = await cursor.fetchall()
        now = datetime.now()
        result = []
        for r in rows:
            expired = datetime.fromisoformat(r["expired_at"])
            if now < expired <= now + timedelta(days=within_days):
                reminded = r.get("reminded_at")
                if reminded:
                    reminded_dt = datetime.fromisoformat(reminded)
                    if reminded_dt > now - timedelta(days=1):
                        continue
                result.append(dict(r))
        return result

    async def get_expired_subs(self) -> list[dict]:
        cursor = await self.conn.execute(
            "SELECT s.*, u.telegram_id FROM subscriptions s "
            "JOIN users u ON s.user_id = u.id "
            "WHERE s.is_active = 1 AND s.expired_at IS NOT NULL"
        )
        rows = await cursor.fetchall()
        now = datetime.now()
        return [dict(r) for r in rows if datetime.fromisoformat(r["expired_at"]) <= now]

    async def mark_reminded(self, sub_id: int):
        await self.conn.execute(
            "UPDATE subscriptions SET reminded_at = ? WHERE id = ?",
            (datetime.now(), sub_id),
        )
        await self.conn.commit()

    async def extend_expiry(self, sub_id: int, days: int):
        sub = await self.get_subscription(sub_id)
        if not sub or not sub.get("expired_at"):
            return
        current = datetime.fromisoformat(sub["expired_at"])
        new_expiry = current + timedelta(days=days)
        await self.conn.execute(
            "UPDATE subscriptions SET expired_at = ? WHERE id = ?",
            (new_expiry, sub_id),
        )
        await self.conn.commit()

    async def is_admin(self, telegram_id: int) -> bool:
        user = await self.get_user(telegram_id)
        return user and user["is_admin"] == 1
