from datetime import UTC, datetime, timedelta

import pytest

from avito_hunt.avito_html_source import AVITO_PRIVATE_HTML_PROVIDER
from avito_hunt.domain import (
    ComparableCohorts,
    Listing,
    ListingChange,
    ListingRecordResult,
    UserPreferences,
)
from avito_hunt.provider import BatchSource, SourceBatch
from avito_hunt.worker_service import process_once


def make_listing(external_id: str, price: int) -> Listing:
    return Listing(
        external_id=external_id,
        title=f"iPhone 15 Pro 256 ГБ · {external_id}",
        url=f"https://www.avito.ru/moskva/telefony/{external_id}",
        price=price,
        model="iPhone 15 Pro",
        storage_gb=256,
        condition="used",
        region="москва",
        published_at=datetime.now(UTC),
        raw={"source": "live-test"},
    )


class FakeDatabase:
    def __init__(
        self,
        change: ListingChange,
        *,
        already_sent: bool = False,
        similar_sent: bool = False,
    ) -> None:
        self.change = change
        self.already_sent = already_sent
        self.similar_sent = similar_sent
        self.recorded: list[str] = []
        self.providers: list[str] = []
        self.events: list[tuple[int, str, int, str]] = []

    async def set_system_state(self, key: str, value: dict[str, object]) -> None:
        return None

    async def mark_listing_status(self, external_id: str, status: str) -> None:
        return None

    async def record_listing(
        self,
        listing: Listing,
        source_provider: str,
    ) -> ListingRecordResult:
        self.recorded.append(listing.external_id)
        self.providers.append(source_provider)
        return ListingRecordResult(change=self.change)

    async def comparable_price_cohorts(
        self,
        listing: Listing,
        *,
        max_age: object,
        source_provider: str,
    ) -> ComparableCohorts:
        assert len(self.recorded) == 11
        assert source_provider == "live-test"
        prices = (100_000,) * 10
        return ComparableCohorts(prices, prices, prices)

    async def enabled_user_preferences(self) -> list[UserPreferences]:
        return [UserPreferences(chat_id=42)]

    async def notifications_today(self, chat_id: int) -> int:
        return 0

    async def listing_notification_exists(self, chat_id: int, external_id: str) -> bool:
        return self.already_sent

    async def notification_event_exists(
        self,
        chat_id: int,
        external_id: str,
        price: int,
        event_type: str,
    ) -> bool:
        return False

    async def similar_offer_notification_exists(
        self,
        chat_id: int,
        listing: Listing,
    ) -> bool:
        return self.similar_sent

    async def mark_notification_event(
        self,
        chat_id: int,
        external_id: str,
        price: int,
        event_type: str,
        decision_context: dict[str, object],
    ) -> bool:
        self.events.append((chat_id, external_id, price, event_type))
        return True


class FakeBot:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str]] = []

    async def send_message(self, chat_id: int, text: str, **kwargs: object) -> None:
        self.messages.append((chat_id, text))


def make_source() -> BatchSource:
    listings = (make_listing("deal", 75_000),) + tuple(
        make_listing(f"market-{index}", 100_000) for index in range(10)
    )
    return BatchSource(
        SourceBatch(
            provider="live-test",
            listings=listings,
            fetched_at=datetime.now(UTC),
            received_count=len(listings),
        )
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [ListingChange.NEW, ListingChange.UNCHANGED])
async def test_process_once_evaluates_after_full_batch_and_rechecks_unchanged(
    change: ListingChange,
) -> None:
    database = FakeDatabase(change)
    bot = FakeBot()

    await process_once(database, make_source(), bot)  # type: ignore[arg-type]

    assert database.recorded == ["deal", *(f"market-{index}" for index in range(10))]
    assert database.providers == ["live-test"] * 11
    assert len(bot.messages) == 1
    assert database.events == [(42, "deal", 75_000, "new_listing")]


@pytest.mark.asyncio
async def test_process_once_does_not_resend_unchanged_listing() -> None:
    database = FakeDatabase(ListingChange.UNCHANGED, already_sent=True)
    bot = FakeBot()

    await process_once(database, make_source(), bot)  # type: ignore[arg-type]

    assert bot.messages == []
    assert database.events == []


@pytest.mark.asyncio
async def test_process_once_suppresses_likely_shop_relist() -> None:
    database = FakeDatabase(ListingChange.NEW, similar_sent=True)
    bot = FakeBot()

    await process_once(database, make_source(), bot)  # type: ignore[arg-type]

    assert bot.messages == []
    assert database.events == []


@pytest.mark.asyncio
async def test_process_once_persists_but_does_not_alert_stale_private_listing() -> None:
    database = FakeDatabase(ListingChange.NEW)
    bot = FakeBot()
    stale = Listing(
        external_id="stale-private",
        title="iPhone 15 Pro 256 ГБ",
        url="https://www.avito.ru/novokuznetsk/telefony/stale-private",
        price=75_000,
        model="iPhone 15 Pro",
        storage_gb=256,
        condition="used",
        region="новокузнецк",
        published_at=datetime.now(UTC) - timedelta(hours=5),
        raw={"source": "avito-public-html-pilot", "seller_kind": "private"},
    )
    source = BatchSource(
        SourceBatch(
            provider=AVITO_PRIVATE_HTML_PROVIDER,
            listings=(stale,),
            fetched_at=datetime.now(UTC),
            received_count=1,
        )
    )

    await process_once(database, source, bot)  # type: ignore[arg-type]

    assert database.recorded == ["stale-private"]
    assert bot.messages == []
    assert database.events == []
