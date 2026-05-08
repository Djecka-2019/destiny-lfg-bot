import json
import os
import aiosqlite

DB_FILE = os.path.join(os.getenv("DATA_DIR", "."), "lfg_sessions.db")
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
                reminder_sent INTEGER NOT NULL DEFAULT 0,
                member_data   TEXT NOT NULL DEFAULT '{}',
                votes               TEXT NOT NULL DEFAULT '{}',
                options             TEXT NOT NULL DEFAULT '[]',
                mention             TEXT,
                leader_bungie_name  TEXT
            )
        """)
        for col, typedef in [
            ("guild_id",            "TEXT"),
            ("channel_id",          "TEXT"),
            ("scheduled_at",        "TEXT"),
            ("reminder_sent",       "INTEGER NOT NULL DEFAULT 0"),
            ("reserves",            "TEXT NOT NULL DEFAULT '[]'"),
            ("member_data",         "TEXT NOT NULL DEFAULT '{}'"),
            ("votes",               "TEXT NOT NULL DEFAULT '{}'"),
            ("options",             "TEXT NOT NULL DEFAULT '[]'"),
            ("mention",             "TEXT"),
            ("leader_bungie_name",  "TEXT"),
        ]:
            try:
                await db.execute(f"ALTER TABLE sessions ADD COLUMN {col} {typedef}")
            except aiosqlite.OperationalError:
                pass
        await db.execute("""
            CREATE TABLE IF NOT EXISTS profiles (
                discord_id      TEXT PRIMARY KEY,
                membership_type INTEGER NOT NULL,
                membership_id   TEXT NOT NULL,
                bungie_name     TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS guild_settings (
                guild_id   TEXT PRIMARY KEY,
                ping_roles TEXT NOT NULL DEFAULT '[]'
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS commendations (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id   TEXT NOT NULL,
                from_id      TEXT NOT NULL,
                to_id        TEXT NOT NULL,
                commendation TEXT NOT NULL,
                given_at     TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS oauth_states (
                state       TEXT PRIMARY KEY,
                discord_id  TEXT NOT NULL,
                created_at  TEXT NOT NULL
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
                    "member_data":   json.loads(row["member_data"] if row["member_data"] else "{}"),
                    "votes":               json.loads(row["votes"] if row["votes"] else "{}"),
                    "options":             json.loads(row["options"] if row["options"] else "[]"),
                    "mention":             row["mention"],
                    "leader_bungie_name":  row["leader_bungie_name"],
                }

async def upsert_session(message_id: str, session: dict) -> None:
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(
            """
            INSERT INTO sessions
                (message_id, activity, activity_type, time_str, description,
                 leader_id, leader_name, capacity, thread_id, members, reserves,
                 guild_id, channel_id, scheduled_at, reminder_sent,
                 member_data, votes, options, mention, leader_bungie_name)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(message_id) DO UPDATE SET
                thread_id          = excluded.thread_id,
                members            = excluded.members,
                reserves           = excluded.reserves,
                reminder_sent      = excluded.reminder_sent,
                member_data        = excluded.member_data,
                votes              = excluded.votes,
                options            = excluded.options,
                mention            = excluded.mention,
                leader_bungie_name = excluded.leader_bungie_name
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
                json.dumps(session.get("member_data", {})),
                json.dumps(session.get("votes", {})),
                json.dumps(session.get("options", [])),
                session.get("mention"),
                session.get("leader_bungie_name"),
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

async def get_ping_roles(guild_id: str) -> list[str]:
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute(
            "SELECT ping_roles FROM guild_settings WHERE guild_id = ?", (guild_id,)
        ) as cursor:
            row = await cursor.fetchone()
    return json.loads(row[0]) if row else []

async def add_ping_role(guild_id: str, role_id: str) -> None:
    roles = await get_ping_roles(guild_id)
    if role_id not in roles:
        roles.append(role_id)
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(
            """
            INSERT INTO guild_settings (guild_id, ping_roles) VALUES (?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET ping_roles = excluded.ping_roles
            """,
            (guild_id, json.dumps(roles)),
        )
        await db.commit()

async def remove_ping_role(guild_id: str, role_id: str) -> bool:
    roles = await get_ping_roles(guild_id)
    if role_id not in roles:
        return False
    roles.remove(role_id)
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(
            """
            INSERT INTO guild_settings (guild_id, ping_roles) VALUES (?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET ping_roles = excluded.ping_roles
            """,
            (guild_id, json.dumps(roles)),
        )
        await db.commit()
    return True

async def save_commendation(session_id: str, from_id: str, to_id: str, commendation: str) -> None:
    from datetime import datetime, timezone
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(
            "INSERT INTO commendations (session_id, from_id, to_id, commendation, given_at) VALUES (?, ?, ?, ?, ?)",
            (session_id, from_id, to_id, commendation, datetime.now(timezone.utc).isoformat()),
        )
        await db.commit()


async def get_commendation_stats(discord_id: str) -> dict[str, int]:
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute(
            "SELECT commendation, COUNT(*) FROM commendations WHERE to_id = ? GROUP BY commendation",
            (discord_id,),
        ) as cursor:
            rows = await cursor.fetchall()
    return {row[0]: row[1] for row in rows}


async def get_commendations_given_count(discord_id: str) -> int:
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM commendations WHERE from_id = ?",
            (discord_id,),
        ) as cursor:
            row = await cursor.fetchone()
    return row[0] if row else 0


async def save_oauth_state(state: str, discord_id: str) -> None:
    from datetime import datetime, timezone
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(
            "INSERT OR REPLACE INTO oauth_states (state, discord_id, created_at) VALUES (?, ?, ?)",
            (state, discord_id, datetime.now(timezone.utc).isoformat()),
        )
        await db.commit()


async def get_and_delete_oauth_state(state: str) -> str | None:
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute(
            "SELECT discord_id FROM oauth_states WHERE state = ?", (state,)
        ) as cursor:
            row = await cursor.fetchone()
        if row:
            await db.execute("DELETE FROM oauth_states WHERE state = ?", (state,))
            await db.commit()
    return row[0] if row else None


async def get_discord_profile(discord_id: str) -> tuple[int, str, str] | None:
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT membership_type, membership_id, bungie_name FROM profiles WHERE discord_id = ?",
            (discord_id,),
        ) as cursor:
            row = await cursor.fetchone()
    return (row["membership_type"], row["membership_id"], row["bungie_name"]) if row else None
