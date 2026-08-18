import json
import secrets
from collections.abc import Sequence
from datetime import datetime, timedelta
from decimal import Decimal

import asyncpg

from avito_hunt.deduplication import (
    canonical_url,
    feedback_key,
    is_specific_listing_url,
    relist_fingerprint,
)
from avito_hunt.domain import (
    ComparableCohorts,
    Listing,
    ListingChange,
    ListingRecordResult,
    UserPreferences,
)
from avito_hunt.learning import (
    InterestModel,
    LearningResult,
    features_from_context,
    model_from_json,
    update_interest_model,
)
from avito_hunt.regions import nearby_regions

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
ALTER TABLE users ADD COLUMN IF NOT EXISTS quiet_start_hour INTEGER;
ALTER TABLE users ADD COLUMN IF NOT EXISTS quiet_end_hour INTEGER;
ALTER TABLE users ADD COLUMN IF NOT EXISTS daily_alert_limit INTEGER NOT NULL DEFAULT 20;
ALTER TABLE users ADD COLUMN IF NOT EXISTS onboarding_completed BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS invite_code TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS invited_by BIGINT;

CREATE UNIQUE INDEX IF NOT EXISTS users_invite_code_idx
ON users (invite_code) WHERE invite_code IS NOT NULL;

CREATE TABLE IF NOT EXISTS listings (
    external_id TEXT PRIMARY KEY,
    source_provider TEXT NOT NULL DEFAULT 'unknown',
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
ALTER TABLE listings ADD COLUMN IF NOT EXISTS feedback_key TEXT;
ALTER TABLE listings ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE listings ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE listings ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active';
ALTER TABLE listings ADD COLUMN IF NOT EXISTS source_provider TEXT NOT NULL DEFAULT 'unknown';

UPDATE listings
SET source_provider = 'demo'
WHERE source_provider = 'unknown'
  AND (external_id LIKE 'demo-%' OR raw @> '{"demo": true}'::jsonb);

CREATE UNIQUE INDEX IF NOT EXISTS listings_feedback_key_idx
ON listings (feedback_key) WHERE feedback_key IS NOT NULL;

UPDATE listings SET canonical_url = url WHERE canonical_url IS NULL;

CREATE INDEX IF NOT EXISTS listings_canonical_url_idx
ON listings (canonical_url);

CREATE INDEX IF NOT EXISTS listings_relist_fingerprint_idx
ON listings (relist_fingerprint, first_seen_at DESC)
WHERE relist_fingerprint IS NOT NULL;

CREATE INDEX IF NOT EXISTS listings_comparable_idx
ON listings (model, storage_gb, condition, region, published_at DESC);

CREATE INDEX IF NOT EXISTS listings_provider_comparable_idx
ON listings (source_provider, model, storage_gb, condition, region, published_at DESC);

CREATE TABLE IF NOT EXISTS notifications (
    chat_id BIGINT NOT NULL REFERENCES users(chat_id) ON DELETE CASCADE,
    external_id TEXT NOT NULL REFERENCES listings(external_id) ON DELETE CASCADE,
    sent_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (chat_id, external_id)
);

CREATE TABLE IF NOT EXISTS notification_events (
    chat_id BIGINT NOT NULL REFERENCES users(chat_id) ON DELETE CASCADE,
    external_id TEXT NOT NULL REFERENCES listings(external_id) ON DELETE CASCADE,
    price INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    decision_context JSONB NOT NULL DEFAULT '{}'::jsonb,
    sent_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (chat_id, external_id, price, event_type)
);

ALTER TABLE notification_events ADD COLUMN IF NOT EXISTS decision_context JSONB
    NOT NULL DEFAULT '{}'::jsonb;

CREATE TABLE IF NOT EXISTS price_history (
    external_id TEXT NOT NULL REFERENCES listings(external_id) ON DELETE CASCADE,
    price INTEGER NOT NULL CHECK (price > 0),
    observed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (external_id, observed_at)
);

CREATE INDEX IF NOT EXISTS price_history_lookup_idx
ON price_history (external_id, observed_at DESC);

CREATE TABLE IF NOT EXISTS listing_feedback (
    chat_id BIGINT NOT NULL REFERENCES users(chat_id) ON DELETE CASCADE,
    external_id TEXT NOT NULL REFERENCES listings(external_id) ON DELETE CASCADE,
    verdict TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (chat_id, external_id)
);

CREATE TABLE IF NOT EXISTS reviewer_models (
    chat_id BIGINT PRIMARY KEY REFERENCES users(chat_id) ON DELETE CASCADE,
    weights JSONB NOT NULL,
    samples INTEGER NOT NULL DEFAULT 0,
    positives INTEGER NOT NULL DEFAULT 0,
    negatives INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS system_state (
    key TEXT PRIMARY KEY,
    value JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
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

    async def register_user(
        self,
        chat_id: int,
        username: str | None,
        referral_code: str | None = None,
    ) -> None:
        assert self.pool
        async with self.pool.acquire() as connection, connection.transaction():
            invited_by = None
            if referral_code:
                invited_by = await connection.fetchval(
                    "SELECT chat_id FROM users WHERE invite_code = $1",
                    referral_code,
                )
            await connection.execute(
                """
                INSERT INTO users (
                    chat_id, username, enabled, onboarding_completed,
                    invite_code, invited_by
                )
                VALUES ($1, $2, TRUE, FALSE, $3, $4)
                ON CONFLICT (chat_id) DO UPDATE
                SET username = EXCLUDED.username,
                    enabled = TRUE,
                    invite_code = COALESCE(users.invite_code, EXCLUDED.invite_code),
                    invited_by = COALESCE(users.invited_by, EXCLUDED.invited_by),
                    updated_at = NOW()
                """,
                chat_id,
                username,
                secrets.token_urlsafe(6),
                invited_by,
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
                   min_discount_percent, quiet_start_hour, quiet_end_hour,
                   daily_alert_limit, onboarding_completed, is_admin
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
                   min_discount_percent, quiet_start_hour, quiet_end_hour,
                   daily_alert_limit, onboarding_completed, is_admin
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

    async def set_quiet_hours(
        self,
        chat_id: int,
        start_hour: int | None,
        end_hour: int | None,
    ) -> None:
        assert self.pool
        await self.pool.execute(
            """
            UPDATE users
            SET quiet_start_hour = $2, quiet_end_hour = $3, updated_at = NOW()
            WHERE chat_id = $1
            """,
            chat_id,
            start_hour,
            end_hour,
        )

    async def set_daily_alert_limit(self, chat_id: int, value: int) -> None:
        assert self.pool
        await self.pool.execute(
            """
            UPDATE users SET daily_alert_limit = $2, updated_at = NOW()
            WHERE chat_id = $1
            """,
            chat_id,
            value,
        )

    async def complete_onboarding(self, chat_id: int) -> None:
        assert self.pool
        await self.pool.execute(
            "UPDATE users SET onboarding_completed = TRUE WHERE chat_id = $1",
            chat_id,
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
            quiet_start_hour=row["quiet_start_hour"],
            quiet_end_hour=row["quiet_end_hour"],
            daily_alert_limit=row["daily_alert_limit"],
            onboarding_completed=row["onboarding_completed"],
            is_admin=row["is_admin"],
        )

    async def insert_listing(self, listing: Listing, source_provider: str = "unknown") -> bool:
        result = await self.record_listing(listing, source_provider)
        return result.change is ListingChange.NEW

    async def record_listing(
        self,
        listing: Listing,
        source_provider: str = "unknown",
    ) -> ListingRecordResult:
        assert self.pool
        canonical = canonical_url(listing.url)
        fingerprint = relist_fingerprint(listing)
        async with self.pool.acquire() as connection, connection.transaction():
            existing = await connection.fetchrow(
                "SELECT price FROM listings WHERE external_id = $1 FOR UPDATE",
                listing.external_id,
            )
            if existing:
                previous_price = existing["price"]
                change = ListingChange.UNCHANGED
                if listing.price < previous_price:
                    change = ListingChange.PRICE_DROPPED
                elif listing.price > previous_price:
                    change = ListingChange.PRICE_INCREASED
                await connection.execute(
                    """
                    UPDATE listings
                    SET title = $2, url = $3, price = $4, model = $5,
                        storage_gb = $6, condition = $7, region = $8,
                        published_at = LEAST(published_at, $9),
                        last_seen_at = NOW(), updated_at = NOW(),
                        status = $10, raw = $11::jsonb, source_provider = $12
                    WHERE external_id = $1
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
                    listing.status,
                    json.dumps(listing.raw, ensure_ascii=False),
                    source_provider,
                )
                if change is not ListingChange.UNCHANGED:
                    await connection.execute(
                        "INSERT INTO price_history (external_id, price) VALUES ($1, $2)",
                        listing.external_id,
                        listing.price,
                    )
                return ListingRecordResult(change=change, previous_price=previous_price)

            if is_specific_listing_url(canonical) and await connection.fetchval(
                "SELECT EXISTS(SELECT 1 FROM listings WHERE canonical_url = $1)",
                canonical,
            ):
                return ListingRecordResult(change=ListingChange.DUPLICATE)
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
                return ListingRecordResult(change=ListingChange.DUPLICATE)
            result = await connection.execute(
                """
                INSERT INTO listings (
                    external_id, source_provider, title, url, price, model, storage_gb,
                    condition, region, published_at, canonical_url,
                    relist_fingerprint, feedback_key, status, raw
                ) VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14,
                    $15::jsonb
                )
                ON CONFLICT DO NOTHING
                """,
                listing.external_id,
                source_provider,
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
                feedback_key(listing.external_id),
                listing.status,
                json.dumps(listing.raw, ensure_ascii=False),
            )
            if result != "INSERT 0 1":
                return ListingRecordResult(change=ListingChange.DUPLICATE)
            await connection.execute(
                "INSERT INTO price_history (external_id, price) VALUES ($1, $2)",
                listing.external_id,
                listing.price,
            )
            return ListingRecordResult(change=ListingChange.NEW)

    async def comparable_prices(
        self,
        listing: Listing,
        *,
        max_age: timedelta,
        source_provider: str = "unknown",
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
              AND status = 'active'
              AND published_at >= NOW() - $6::interval
              AND source_provider = $7
            """,
            listing.external_id,
            listing.model,
            listing.storage_gb,
            listing.condition,
            listing.region,
            max_age,
            source_provider,
        )
        return [row["price"] for row in rows]

    async def comparable_price_cohorts(
        self,
        listing: Listing,
        *,
        max_age: timedelta,
        source_provider: str = "unknown",
    ) -> ComparableCohorts:
        assert self.pool
        rows = await self.pool.fetch(
            """
            SELECT price, region FROM listings
            WHERE external_id <> $1
              AND model = $2
              AND storage_gb IS NOT DISTINCT FROM $3
              AND condition = $4
              AND status = 'active'
              AND published_at >= NOW() - $5::interval
              AND source_provider = $6
            """,
            listing.external_id,
            listing.model,
            listing.storage_gb,
            listing.condition,
            max_age,
            source_provider,
        )
        neighbors = set(nearby_regions(listing.region))
        national = tuple(row["price"] for row in rows)
        nearby = tuple(row["price"] for row in rows if row["region"] in neighbors)
        exact = tuple(row["price"] for row in rows if row["region"] == listing.region)
        return ComparableCohorts(exact_region=exact, nearby_regions=nearby, national=national)

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

    async def notification_event_exists(
        self,
        chat_id: int,
        external_id: str,
        price: int,
        event_type: str,
    ) -> bool:
        assert self.pool
        value = await self.pool.fetchval(
            """
            SELECT EXISTS(
                SELECT 1 FROM notification_events
                WHERE chat_id = $1 AND external_id = $2
                  AND price = $3 AND event_type = $4
            )
            """,
            chat_id,
            external_id,
            price,
            event_type,
        )
        return bool(value)

    async def listing_notification_exists(self, chat_id: int, external_id: str) -> bool:
        assert self.pool
        value = await self.pool.fetchval(
            """
            SELECT EXISTS(
                SELECT 1 FROM notification_events
                WHERE chat_id = $1 AND external_id = $2
            )
            """,
            chat_id,
            external_id,
        )
        return bool(value)

    async def mark_notification_event(
        self,
        chat_id: int,
        external_id: str,
        price: int,
        event_type: str,
        decision_context: dict[str, object] | None = None,
    ) -> bool:
        assert self.pool
        result = await self.pool.execute(
            """
            INSERT INTO notification_events (
                chat_id, external_id, price, event_type, decision_context
            )
            VALUES ($1, $2, $3, $4, $5::jsonb)
            ON CONFLICT DO NOTHING
            """,
            chat_id,
            external_id,
            price,
            event_type,
            json.dumps(decision_context or {}, ensure_ascii=False),
        )
        return result == "INSERT 0 1"

    async def notifications_today(self, chat_id: int) -> int:
        assert self.pool
        return int(
            await self.pool.fetchval(
                """
                SELECT COUNT(*) FROM notification_events
                WHERE chat_id = $1
                  AND sent_at >= date_trunc('day', NOW() AT TIME ZONE 'Europe/Moscow')
                      AT TIME ZONE 'Europe/Moscow'
                """,
                chat_id,
            )
        )

    async def add_feedback(self, chat_id: int, key: str, verdict: str) -> bool:
        assert self.pool
        result = await self.pool.execute(
            """
            INSERT INTO listing_feedback (chat_id, external_id, verdict)
            SELECT $1, external_id, $3 FROM listings WHERE feedback_key = $2
            ON CONFLICT (chat_id, external_id) DO UPDATE
            SET verdict = EXCLUDED.verdict, created_at = NOW()
            """,
            chat_id,
            key,
            verdict,
        )
        return result in {"INSERT 0 1", "UPDATE 1"}

    async def learn_from_feedback(
        self,
        chat_id: int,
        key: str,
        verdict: str,
    ) -> LearningResult:
        assert self.pool
        if verdict not in {"good", "bad"}:
            return LearningResult(saved=False)
        async with self.pool.acquire() as connection, connection.transaction():
            external_id = await connection.fetchval(
                "SELECT external_id FROM listings WHERE feedback_key = $1",
                key,
            )
            if not external_id:
                return LearningResult(saved=False)
            existing_verdict = await connection.fetchval(
                """
                SELECT verdict FROM listing_feedback
                WHERE chat_id = $1 AND external_id = $2
                """,
                chat_id,
                external_id,
            )
            if existing_verdict:
                row = await connection.fetchrow(
                    """
                    SELECT weights, samples, positives, negatives FROM reviewer_models
                    WHERE chat_id = $1
                    """,
                    chat_id,
                )
                model = self._model_from_row(row)
                return LearningResult(
                    saved=True,
                    duplicate=True,
                    samples=model.samples,
                    positives=model.positives,
                    negatives=model.negatives,
                )
            await connection.execute(
                """
                INSERT INTO listing_feedback (chat_id, external_id, verdict)
                VALUES ($1, $2, $3)
                ON CONFLICT (chat_id, external_id) DO UPDATE
                SET verdict = EXCLUDED.verdict, created_at = NOW()
                """,
                chat_id,
                external_id,
                verdict,
            )
            raw_context = await connection.fetchval(
                """
                SELECT decision_context FROM notification_events
                WHERE chat_id = $1 AND external_id = $2
                ORDER BY sent_at DESC LIMIT 1
                """,
                chat_id,
                external_id,
            )
            context = self.decode_json_object(raw_context) if raw_context else None
            features = features_from_context(context or {})
            if not features:
                return LearningResult(saved=True)
            row = await connection.fetchrow(
                """
                SELECT weights, samples, positives, negatives FROM reviewer_models
                WHERE chat_id = $1 FOR UPDATE
                """,
                chat_id,
            )
            model = self._model_from_row(row)
            updated, before, after = update_interest_model(
                model,
                features,
                interested=verdict == "good",
            )
            await connection.execute(
                """
                INSERT INTO reviewer_models (
                    chat_id, weights, samples, positives, negatives
                ) VALUES ($1, $2::jsonb, $3, $4, $5)
                ON CONFLICT (chat_id) DO UPDATE
                SET weights = EXCLUDED.weights,
                    samples = EXCLUDED.samples,
                    positives = EXCLUDED.positives,
                    negatives = EXCLUDED.negatives,
                    updated_at = NOW()
                """,
                chat_id,
                json.dumps(updated.weights),
                updated.samples,
                updated.positives,
                updated.negatives,
            )
            return LearningResult(
                saved=True,
                learned=True,
                samples=updated.samples,
                positives=updated.positives,
                negatives=updated.negatives,
                prediction_before=before,
                prediction_after=after,
            )

    @staticmethod
    def _model_from_row(row: asyncpg.Record | None) -> InterestModel:
        if not row:
            return InterestModel()
        raw_weights = row["weights"]
        weights = json.loads(raw_weights) if isinstance(raw_weights, str) else raw_weights
        return model_from_json(
            weights,
            samples=row["samples"],
            positives=row["positives"],
            negatives=row["negatives"],
        )

    async def set_system_state(self, key: str, value: dict[str, object]) -> None:
        assert self.pool
        await self.pool.execute(
            """
            INSERT INTO system_state (key, value) VALUES ($1, $2::jsonb)
            ON CONFLICT (key) DO UPDATE
            SET value = EXCLUDED.value, updated_at = NOW()
            """,
            key,
            json.dumps(value, ensure_ascii=False),
        )

    async def get_system_state(self, key: str) -> dict[str, object] | None:
        assert self.pool
        value = await self.pool.fetchval("SELECT value FROM system_state WHERE key = $1", key)
        return self.decode_json_object(value)

    @staticmethod
    def decode_json_object(value: object) -> dict[str, object] | None:
        if value is None:
            return None
        decoded = json.loads(value) if isinstance(value, str) else value
        if not isinstance(decoded, dict):
            raise ValueError("System state must be a JSON object")
        return decoded

    async def admin_chat_ids(self) -> list[int]:
        assert self.pool
        rows = await self.pool.fetch("SELECT chat_id FROM users WHERE is_admin = TRUE")
        return [row["chat_id"] for row in rows]

    async def admin_stats(self) -> dict[str, object]:
        assert self.pool
        row = await self.pool.fetchrow(
            """
            SELECT
                (SELECT COUNT(*) FROM users) AS users,
                (SELECT COUNT(*) FROM users WHERE enabled = TRUE) AS enabled_users,
                (SELECT COUNT(*) FROM listings) AS listings,
                (SELECT COUNT(*) FROM notification_events) AS notifications,
                (SELECT COUNT(*) FROM listing_feedback) AS feedback,
                (SELECT COALESCE(SUM(samples), 0) FROM reviewer_models) AS model_samples,
                (SELECT COALESCE(SUM(positives), 0) FROM reviewer_models) AS model_positives,
                (SELECT COALESCE(SUM(negatives), 0) FROM reviewer_models) AS model_negatives
            """
        )
        source = await self.get_system_state("source")
        return {
            "users": row["users"],
            "enabled_users": row["enabled_users"],
            "listings": row["listings"],
            "notifications": row["notifications"],
            "feedback": row["feedback"],
            "model_samples": row["model_samples"],
            "model_positives": row["model_positives"],
            "model_negatives": row["model_negatives"],
            "source": source or {"status": "unknown"},
        }

    async def invite_code(self, chat_id: int) -> str | None:
        assert self.pool
        return await self.pool.fetchval("SELECT invite_code FROM users WHERE chat_id = $1", chat_id)

    async def delete_user(self, chat_id: int) -> None:
        assert self.pool
        await self.pool.execute("DELETE FROM users WHERE chat_id = $1", chat_id)

    async def mark_listing_status(self, external_id: str, status: str) -> None:
        assert self.pool
        await self.pool.execute(
            """
            UPDATE listings SET status = $2, updated_at = NOW()
            WHERE external_id = $1
            """,
            external_id,
            status,
        )

    async def price_history(self, external_id: str) -> list[tuple[datetime, int]]:
        assert self.pool
        rows = await self.pool.fetch(
            """
            SELECT observed_at, price FROM price_history
            WHERE external_id = $1 ORDER BY observed_at
            """,
            external_id,
        )
        return [(row["observed_at"], row["price"]) for row in rows]

    async def cleanup_expired_data(self, *, retention_days: int = 180) -> dict[str, int]:
        """Remove expired per-user events while retaining aggregate listing knowledge."""
        assert self.pool
        if retention_days < 30:
            raise ValueError("retention_days must be at least 30")
        deleted: dict[str, int] = {}
        interval = timedelta(days=retention_days)
        async with self.pool.acquire() as connection, connection.transaction():
            for table, timestamp in (
                ("notification_events", "sent_at"),
                ("listing_feedback", "created_at"),
                ("price_history", "observed_at"),
            ):
                result = await connection.execute(
                    f"DELETE FROM {table} WHERE {timestamp} < NOW() - $1::interval",
                    interval,
                )
                deleted[table] = int(result.rsplit(" ", 1)[-1])
        return deleted
