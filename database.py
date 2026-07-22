import aiosqlite
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "dokkaebi.db")


async def get_db():
    return await aiosqlite.connect(DB_PATH)


async def setup_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS stock (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                category TEXT NOT NULL,
                content TEXT NOT NULL,
                used INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS drop_stock (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                content TEXT NOT NULL,
                used INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS config (
                guild_id TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT,
                PRIMARY KEY (guild_id, key)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                user_id TEXT NOT NULL,
                guild_id TEXT NOT NULL,
                tier TEXT NOT NULL,
                PRIMARY KEY (user_id, guild_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS vouches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                vouched_by TEXT NOT NULL,
                message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS invites (
                code TEXT NOT NULL,
                guild_id TEXT NOT NULL,
                inviter_id TEXT NOT NULL,
                uses INTEGER DEFAULT 0,
                PRIMARY KEY (code, guild_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS message_counts (
                user_id TEXT NOT NULL,
                guild_id TEXT NOT NULL,
                count INTEGER DEFAULT 0,
                PRIMARY KEY (user_id, guild_id)
            )
        """)
        await db.commit()


# ── Config ────────────────────────────────────────────────────────────────────

async def get_config(guild_id: str, key: str) -> str | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT value FROM config WHERE guild_id=? AND key=?",
            (guild_id, key)
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else None


async def set_config(guild_id: str, key: str, value: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO config (guild_id, key, value) VALUES (?,?,?)",
            (guild_id, key, value)
        )
        await db.commit()


# ── Stock ─────────────────────────────────────────────────────────────────────

async def get_stock_count(guild_id: str, category: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM stock WHERE guild_id=? AND category=? AND used=0",
            (guild_id, category)
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0


async def get_all_stock_counts(guild_id: str) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT category, COUNT(*) FROM stock WHERE guild_id=? AND used=0 GROUP BY category",
            (guild_id,)
        ) as cur:
            rows = await cur.fetchall()
            return {row[0]: row[1] for row in rows}


async def add_stock(guild_id: str, category: str, lines: list[str]):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executemany(
            "INSERT INTO stock (guild_id, category, content) VALUES (?,?,?)",
            [(guild_id, category, line) for line in lines]
        )
        await db.commit()


async def pop_stock(guild_id: str, category: str) -> str | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, content FROM stock WHERE guild_id=? AND category=? AND used=0 ORDER BY id LIMIT 1",
            (guild_id, category)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        await db.execute("UPDATE stock SET used=1 WHERE id=?", (row[0],))
        await db.commit()
        return row[1]


async def clear_stock(guild_id: str, category: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM stock WHERE guild_id=? AND category=?",
            (guild_id, category)
        )
        await db.commit()


async def get_stock_list(guild_id: str, category: str) -> list[tuple]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, content FROM stock WHERE guild_id=? AND category=? AND used=0 ORDER BY id",
            (guild_id, category)
        ) as cur:
            return await cur.fetchall()


async def edit_stock_item(item_id: int, new_content: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE stock SET content=? WHERE id=?", (new_content, item_id))
        await db.commit()


# ── Drop Stock ────────────────────────────────────────────────────────────────

async def get_drop_stock_count(guild_id: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM drop_stock WHERE guild_id=? AND used=0",
            (guild_id,)
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0


async def add_drop_stock(guild_id: str, lines: list[str]):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executemany(
            "INSERT INTO drop_stock (guild_id, content) VALUES (?,?)",
            [(guild_id, line) for line in lines]
        )
        await db.commit()


async def pop_drop_stock(guild_id: str) -> str | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, content FROM drop_stock WHERE guild_id=? AND used=0 ORDER BY id LIMIT 1",
            (guild_id,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        await db.execute("UPDATE drop_stock SET used=1 WHERE id=?", (row[0],))
        await db.commit()
        return row[1]


# ── Subscriptions ─────────────────────────────────────────────────────────────

async def set_subscription(guild_id: str, user_id: str, tier: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO subscriptions (user_id, guild_id, tier) VALUES (?,?,?)",
            (user_id, guild_id, tier)
        )
        await db.commit()


async def get_subscription(guild_id: str, user_id: str) -> str | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT tier FROM subscriptions WHERE user_id=? AND guild_id=?",
            (user_id, guild_id)
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else None


async def remove_subscription(guild_id: str, user_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM subscriptions WHERE user_id=? AND guild_id=?",
            (user_id, guild_id)
        )
        await db.commit()


# ── Vouches ───────────────────────────────────────────────────────────────────

async def add_vouch(guild_id: str, user_id: str, vouched_by: str, message: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO vouches (guild_id, user_id, vouched_by, message) VALUES (?,?,?,?)",
            (guild_id, user_id, vouched_by, message)
        )
        await db.commit()


async def get_vouch_count(guild_id: str, user_id: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM vouches WHERE guild_id=? AND user_id=?",
            (guild_id, user_id)
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0


async def get_vouches(guild_id: str, user_id: str) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT vouched_by, message, created_at FROM vouches WHERE guild_id=? AND user_id=? ORDER BY created_at DESC LIMIT 10",
            (guild_id, user_id)
        ) as cur:
            return await cur.fetchall()


# ── Invites ───────────────────────────────────────────────────────────────────

async def upsert_invite(guild_id: str, code: str, inviter_id: str, uses: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO invites (code, guild_id, inviter_id, uses) VALUES (?,?,?,?)",
            (code, guild_id, inviter_id, uses)
        )
        await db.commit()


async def get_invite_count(guild_id: str, user_id: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT SUM(uses) FROM invites WHERE guild_id=? AND inviter_id=?",
            (guild_id, user_id)
        ) as cur:
            row = await cur.fetchone()
            return row[0] or 0


async def get_invite_leaderboard(guild_id: str, limit: int = 10) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """SELECT inviter_id, SUM(uses) as total
               FROM invites WHERE guild_id=?
               GROUP BY inviter_id ORDER BY total DESC LIMIT ?""",
            (guild_id, limit)
        ) as cur:
            return await cur.fetchall()


# ── Message Counts ────────────────────────────────────────────────────────────

async def increment_message_count(guild_id: str, user_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO message_counts (user_id, guild_id, count) VALUES (?,?,1)
               ON CONFLICT(user_id, guild_id) DO UPDATE SET count = count + 1""",
            (user_id, guild_id)
        )
        await db.commit()


async def get_message_count(guild_id: str, user_id: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT count FROM message_counts WHERE guild_id=? AND user_id=?",
            (guild_id, user_id)
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0
