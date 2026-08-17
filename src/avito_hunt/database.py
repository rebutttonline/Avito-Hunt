import json
from collections.abc import Sequence
from datetime import timedelta

import asyncpg

from avito_hunt.domain import Listing

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    chat_id BIGINT PRIMARY KEY,
    username TEXT,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS listings (
    external_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    price INTEGER NOT NULL CHECK (price > 0),
    model TEXT NOT NULL,
    storage_gb INTEGER,
    condition TEXT NOT NULL,
    region TEXT NOT NULL,
    published_at TIMESTAMPTZ NOT NULL,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    raw JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS listings_comparable_idx
ON listings (model, storage_gb, condition, region, published_at DESC);

CREATE TABLE IF NOT EXISTS notifications (
    chat_id BIGINT NOT NULL REFERENCES users(chat_id) ON DELETE CASCADE,
    external_id TEXT NOT NULL REFERENCES listings(external_id) ON DELETE CASCADE,
    sent_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (chat_id, external_id)
);
"""


class Database:
    def __init__(self, url: str) -> None:
        self.url = url
        self.pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        self.pool = await asyncpg.create_pool(self.url, min_size=1, max_size=5)

    async def close(self) -> None:
        if self.pool:
            await self.pool.close()

    async def ensure_schema(self) -> None:
        assert self.pool
        async with self.pool.acquire() as connection:
            await connection.execute(SCHEMA_SQL)

    async def register_user(self, chat_id: int, username: str | None) -> None:
        assert self.pool
        await self.pool.execute(
            """
            INSERT INTO users (chat_id, username, enabled)
            VALUES ($1, $2, TRUE)
            ON CONFLICT (chat_id) DO UPDATE
            SET username = EXCLUDED.username, enabled = TRUE, updated_at = NOW()
            """,
            chat_id,
            username,
        )

    async def disable_user(self, chat_id: int) -> None:
        assert self.pool
        await self.pool.execute(
            "UPDATE users SET enabled = FALSE, updated_at = NOW() WHERE chat_id = $1",
            chat_id,
        )

    async def user_enabled(self, chat_id: int) -> bool:
        assert self.pool
        value = await self.pool.fetchval(
            "SELECT enabled FROM users WHERE chat_id = $1",
            chat_id,
        )
        return bool(value)

    async def enabled_chat_ids(self) -> list[int]:
        assert self.pool
        rows = await self.pool.fetch("SELECT chat_id FROM users WHERE enabled = TRUE")
        return [row["chat_id"] for row in rows]

    async def insert_listing(self, listing: Listing) -> bool:
        assert self.pool
        result = await self.pool.execute(
            """
            INSERT INTO listings (
                external_id, title, url, price, model, storage_gb,
                condition, region, published_at, raw
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb)
            ON CONFLICT (external_id) DO NOTHING
            """,
            listing.external_id,
            listing.title,
            listing.url,
            listing.price,
            listing.model,
            listing.storage_gb,
            listing.condition,
            listing.region,
            listing.published_at,
            json.dumps(listing.raw, ensure_ascii=False),
        )
        return result == "INSERT 0 1"

    async def comparable_prices(
        self,
        listing: Listing,
        *,
        max_age: timedelta,
    ) -> list[int]:
        assert self.pool
        rows: Sequence[asyncpg.Record] = await self.pool.fetch(
            """
            SELECT price FROM listings
            WHERE external_id <> $1
              AND model = $2
              AND storage_gb IS NOT DISTINCT FROM $3
              AND condition = $4
              AND region = $5
              AND published_at >= NOW() - $6::interval
            """,
            listing.external_id,
            listing.model,
            listing.storage_gb,
            listing.condition,
            listing.region,
            max_age,
        )
        return [row["price"] for row in rows]

    async def mark_notification(self, chat_id: int, external_id: str) -> bool:
        assert self.pool
        result = await self.pool.execute(
            """
            INSERT INTO notifications (chat_id, external_id)
            VALUES ($1, $2)
            ON CONFLICT DO NOTHING
            """,
            chat_id,
            external_id,
        )
        return result == "INSERT 0 1"

    async def notification_exists(self, chat_id: int, external_id: str) -> bool:
        assert self.pool
        value = await self.pool.fetchval(
            """
            SELECT EXISTS(
                SELECT 1 FROM notifications WHERE chat_id = $1 AND external_id = $2
            )
            """,
            chat_id,
            external_id,
        )
        return bool(value)
