from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any


@dataclass(frozen=True, slots=True)
class Listing:
    external_id: str
    title: str
    url: str
    price: int
    model: str
    storage_gb: int | None
    condition: str
    region: str
    published_at: datetime
    status: str = "active"
    raw: dict[str, Any] = field(default_factory=dict, compare=False)


class PriceLevel(StrEnum):
    NORMAL = "normal"
    DEAL = "deal"
    GREAT_DEAL = "great_deal"
    SUSPICIOUSLY_CHEAP = "suspiciously_cheap"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True, slots=True)
class RiskAssessment:
    level: RiskLevel
    score: int
    issues: tuple[str, ...] = ()


class ListingChange(StrEnum):
    NEW = "new"
    PRICE_DROPPED = "price_dropped"
    PRICE_INCREASED = "price_increased"
    UNCHANGED = "unchanged"
    DUPLICATE = "duplicate"


@dataclass(frozen=True, slots=True)
class ListingRecordResult:
    change: ListingChange
    previous_price: int | None = None


@dataclass(frozen=True, slots=True)
class MarketEstimate:
    market_price: int
    discount_amount: int
    discount_percent: Decimal
    comparable_count: int
    confidence: str
    range_low: int | None = None
    range_high: int | None = None
    cheaper_than_percent: int | None = None
    market_scope: str = "exact_region"

    @property
    def is_discounted(self) -> bool:
        return self.discount_amount > 0


@dataclass(frozen=True, slots=True)
class UserPreferences:
    chat_id: int
    enabled: bool = True
    model_generations: tuple[str, ...] = ()
    storage_options: tuple[int, ...] = ()
    region: str | None = None
    min_discount_percent: Decimal = Decimal("15.0")
    quiet_start_hour: int | None = None
    quiet_end_hour: int | None = None
    daily_alert_limit: int = 20
    onboarding_completed: bool = True
    is_admin: bool = False

    @property
    def tracks_all_models(self) -> bool:
        return not self.model_generations

    @property
    def tracks_all_storage(self) -> bool:
        return not self.storage_options


@dataclass(frozen=True, slots=True)
class ComparableCohorts:
    exact_region: tuple[int, ...]
    nearby_regions: tuple[int, ...]
    national: tuple[int, ...]
