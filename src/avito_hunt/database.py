import json
from collections.abc import Sequence
from datetime import timedelta
from decimal import Decimal

import asyncpg

from avito_hunt.deduplication import canonical_url, is_specific_listing_url, relist_fingerprint
from avito_hunt.domain import Listing, UserPreferences

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    chat_id BIGINT PRIMARY KEY,
    username TEXT,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE users ADD COLUMN IF NOT EXISTS model_generations TEXT[] NOT NULL DEFAULT '{}';
ALTER TABLE users ADD COLUMN IF NOT EXISTS storage_options INTEGER[] NOT NULL DEFAULT '{}';
ALTER TABLE users ADD COLUMN IF NOT EXISTS region TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS min_discount_percent NUMERIC(5, 1)
    NOT NULL DEFAULT 15.0;

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
    canonical_url TEXT,
    relist_fingerprint TEXT,
    raw JSONB NOT NULL DEFAULT '{}'::jsonb
);

ALTER TABLE listings ADD COLUMN IF NOT EXISTS canonical_url TEXT;
ALTER TABLE listings ADD COLUMN IF NOT EXISTS relist_fingerprint TEXT;

UPDATE listings SET canonical_url = url WHERE canonical_url IS NULL;

CREATE INDEX IF NOT EXISTS listings_canonical_url_idx
ON listings (canonical_url);

CREATE INDEX IF NOT EXISTS listings_relist_fingerprint_idx
ON listings (relist_fingerprint, first_seen_at DESC)
WHERE relist_fingerprint IS NOT NULL;

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

    async def enable_user(self, chat_id: int) -> None:
        assert self.pool
        await self.pool.execute(
            "UPDATE users SET enabled = TRUE, updated_at = NOW() WHERE chat_id = $1",
            chat_id,
        )

    async def user_enabled(self, chat_id: int) -> bool:
        assert self.pool
        value = await self.pool.fetchval(
            "SELECT enabled FROM users WHERE chat_id = $1",
            chat_id,
        )
        return bool(value)

    async def get_user_preferences(self, chat_id: int) -> UserPreferences | None:
        assert self.pool
        row = await self.pool.fetchrow(
            """
            SELECT chat_id, enabled, model_generations, storage_options, region,
                   min_discount_percent
            FROM users WHERE chat_id = $1
            """,
            chat_id,
        )
        return self._preferences_from_row(row) if row else None

    async def enabled_user_preferences(self) -> list[UserPreferences]:
        assert self.pool
        rows = await self.pool.fetch(
            """
            SELECT chat_id, enabled, model_generations, storage_options, region,
                   min_discount_percent
            FROM users WHERE enabled = TRUE
            """
        )
        return [self._preferences_from_row(row) for row in rows]

    async def set_model_generations(self, chat_id: int, values: Sequence[str]) -> None:
        await self._update_array(chat_id, "model_generations", list(values))

    async def set_storage_options(self, chat_id: int, values: Sequence[int]) -> None:
        await self._update_array(chat_id, "storage_options", list(values))

    async def set_region(self, chat_id: int, region: str | None) -> None:
        assert self.pool
        await self.pool.execute(
            "UPDATE users SET region = $2, updated_at = NOW() WHERE chat_id = $1",
            chat_id,
            region.casefold().strip() if region else None,
        )

    async def set_min_discount(self, chat_id: int, value: Decimal) -> None:
        assert self.pool
        await self.pool.execute(
            """
            UPDATE users SET min_discount_percent = $2, updated_at = NOW()
            WHERE chat_id = $1
            """,
            chat_id,
            value,
        )

    async def _update_array(self, chat_id: int, column: str, values: list[object]) -> None:
        assert self.pool
        allowed = {"model_generations", "storage_options"}
        if column not in allowed:
            raise ValueError(f"Unsupported preference column: {column}")
        await self.pool.execute(
            f"UPDATE users SET {column} = $2, updated_at = NOW() WHERE chat_id = $1",
            chat_id,
            values,
        )

    @staticmethod
    def _preferences_from_row(row: asyncpg.Record) -> UserPreferences:
        return UserPreferences(
            chat_id=row["chat_id"],
            enabled=row["enabled"],
            model_generations=tuple(row["model_generations"] or ()),
            storage_options=tuple(row["storage_options"] or ()),
            region=row["region"],
            min_discount_percent=Decimal(row["min_discount_percent"]),
        )

    async def insert_listing(self, listing: Listing) -> bool:
        assert self.pool
        canonical = canonical_url(listing.url)
        fingerprint = relist_fingerprint(listing)
        async with self.pool.acquire() as connection, connection.transaction():
            if is_specific_listing_url(canonical) and await connection.fetchval(
                "SELECT EXISTS(SELECT 1 FROM listings WHERE canonical_url = $1)",
                canonical,
            ):
                return False
            if fingerprint and await connection.fetchval(
                """
                SELECT EXISTS(
                    SELECT 1 FROM listings
                    WHERE relist_fingerprint = $1
                      AND first_seen_at >= NOW() - INTERVAL '30 days'
                )
                """,
                fingerprint,
            ):
                return False
            result = await connection.execute(
                """
                INSERT INTO listings (
                    external_id, title, url, price, model, storage_gb,
                    condition, region, published_at, canonical_url,
                    relist_fingerprint, raw
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12::jsonb)
                ON CONFLICT DO NOTHING
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
                canonical,
                fingerprint,
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
