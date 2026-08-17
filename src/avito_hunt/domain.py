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
