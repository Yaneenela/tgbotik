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
    ) -> dict:
        expired_at = datetime.now() + timedelta(days=days)
        total_bytes = traffic_gb * 1024**3 if traffic_gb > 0 else 0
        cursor = await self.conn.execute(
            """INSERT INTO subscriptions
               (user_id, plan_name, uuid, inbound_id, traffic_total, expired_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, plan_name, uuid_str, inbound_id, total_bytes, expired_at),
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

    async def is_admin(self, telegram_id: int) -> bool:
        user = await self.get_user(telegram_id)
        return user and user["is_admin"] == 1
