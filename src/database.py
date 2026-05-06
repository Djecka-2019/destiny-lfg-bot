import json
import os

import aiosqlite

DB_FILE = os.path.join(os.getenv("DATA_DIR", "."), "lfg_sessions.db")

# In-memory cache: message_id → session dict.
# Populated from DB at startup; DB is the source of truth on disk.
lfg_sessions: dict[str, dict] = {}


async def init_db() -> None:
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                message_id    TEXT PRIMARY KEY,
                activity      TEXT NOT NULL,
                activity_type TEXT NOT NULL,
                time_str      TEXT NOT NULL,
                description   TEXT NOT NULL DEFAULT '',
                leader_id     TEXT NOT NULL,
                leader_name   TEXT NOT NULL,
                capacity      INTEGER NOT NULL,
                thread_id     TEXT,
                members       TEXT NOT NULL DEFAULT '[]',
                reserves      TEXT NOT NULL DEFAULT '[]',
                guild_id      TEXT,
                channel_id    TEXT,
                scheduled_at  TEXT,
                reminder_sent INTEGER NOT NULL DEFAULT 0
            )
        """)
        for col, typedef in [
            ("guild_id",      "TEXT"),
            ("channel_id",    "TEXT"),
            ("scheduled_at",  "TEXT"),
            ("reminder_sent", "INTEGER NOT NULL DEFAULT 0"),
            ("reserves",      "TEXT NOT NULL DEFAULT '[]'"),
        ]:
            try:
                await db.execute(f"ALTER TABLE sessions ADD COLUMN {col} {typedef}")
            except aiosqlite.OperationalError:
                pass  # Column already exists
        await db.execute("""
            CREATE TABLE IF NOT EXISTS profiles (
                discord_id      TEXT PRIMARY KEY,
                membership_type INTEGER NOT NULL,
                membership_id   TEXT NOT NULL,
                bungie_name     TEXT NOT NULL
            )
        """)
        await db.commit()


async def load_sessions_from_db() -> None:
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM sessions") as cursor:
            async for row in cursor:
                lfg_sessions[row["message_id"]] = {
                    "activity":      row["activity"],
                    "activity_type": row["activity_type"],
                    "time":          row["time_str"],
                    "description":   row["description"],
                    "leader_id":     row["leader_id"],
                    "leader_name":   row["leader_name"],
                    "capacity":      row["capacity"],
                    "thread_id":     row["thread_id"],
                    "members":       json.loads(row["members"]),
                    "reserves":      json.loads(row["reserves"] if row["reserves"] else "[]"),
                    "guild_id":      row["guild_id"],
                    "channel_id":    row["channel_id"],
                    "scheduled_at":  row["scheduled_at"],
                    "reminder_sent": bool(row["reminder_sent"]),
                }


async def upsert_session(message_id: str, session: dict) -> None:
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(
            """
            INSERT INTO sessions
                (message_id, activity, activity_type, time_str, description,
                 leader_id, leader_name, capacity, thread_id, members, reserves,
                 guild_id, channel_id, scheduled_at, reminder_sent)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(message_id) DO UPDATE SET
                thread_id     = excluded.thread_id,
                members       = excluded.members,
                reserves      = excluded.reserves,
                reminder_sent = excluded.reminder_sent
            """,
            (
                message_id,
                session["activity"],
                session["activity_type"],
                session["time"],
                session.get("description", ""),
                session["leader_id"],
                session["leader_name"],
                session["capacity"],
                session.get("thread_id"),
                json.dumps(session["members"]),
                json.dumps(session.get("reserves", [])),
                session.get("guild_id"),
                session.get("channel_id"),
                session.get("scheduled_at"),
                int(session.get("reminder_sent", False)),
            ),
        )
        await db.commit()


async def delete_session(message_id: str) -> None:
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("DELETE FROM sessions WHERE message_id = ?", (message_id,))
        await db.commit()


async def save_profile(
    discord_id: str, membership_type: int, membership_id: str, bungie_name: str
) -> None:
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(
            """
            INSERT INTO profiles (discord_id, membership_type, membership_id, bungie_name)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(discord_id) DO UPDATE SET
                membership_type = excluded.membership_type,
                membership_id   = excluded.membership_id,
                bungie_name     = excluded.bungie_name
            """,
            (discord_id, membership_type, membership_id, bungie_name),
        )
        await db.commit()


async def get_discord_profile(discord_id: str) -> tuple[int, str, str] | None:
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT membership_type, membership_id, bungie_name FROM profiles WHERE discord_id = ?",
            (discord_id,),
        ) as cursor:
            row = await cursor.fetchone()
    return (row["membership_type"], row["membership_id"], row["bungie_name"]) if row else None
