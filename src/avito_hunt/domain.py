from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
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
    raw: dict[str, Any] = field(default_factory=dict, compare=False)


@dataclass(frozen=True, slots=True)
class MarketEstimate:
    market_price: int
    discount_amount: int
    discount_percent: Decimal
    comparable_count: int
    confidence: str

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

    @property
    def tracks_all_models(self) -> bool:
        return not self.model_generations

    @property
    def tracks_all_storage(self) -> bool:
        return not self.storage_options
