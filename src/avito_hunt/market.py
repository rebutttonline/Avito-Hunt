from decimal import ROUND_HALF_UP, Decimal
from statistics import median

from avito_hunt.domain import Listing, MarketEstimate


def _remove_outliers(prices: list[int]) -> list[int]:
    if len(prices) < 5:
        return prices
    center = median(prices)
    deviations = [abs(price - center) for price in prices]
    mad = median(deviations)
    if mad == 0:
        return prices
    return [price for price in prices if abs(price - center) <= 3 * mad]


def estimate_market(
    listing: Listing,
    comparable_prices: list[int],
    *,
    minimum_count: int,
) -> MarketEstimate | None:
    valid_prices = [price for price in comparable_prices if price > 0]
    filtered_prices = _remove_outliers(valid_prices)
    if len(filtered_prices) < minimum_count:
        return None

    market_price = round(median(filtered_prices))
    discount_amount = market_price - listing.price
    discount_percent = (Decimal(discount_amount * 100) / Decimal(market_price)).quantize(
        Decimal("0.1"), rounding=ROUND_HALF_UP
    )
    confidence = "high" if len(filtered_prices) >= minimum_count * 2 else "medium"
    return MarketEstimate(
        market_price=market_price,
        discount_amount=discount_amount,
        discount_percent=discount_percent,
        comparable_count=len(filtered_prices),
        confidence=confidence,
    )


def is_deal(estimate: MarketEstimate | None, threshold_percent: float) -> bool:
    return bool(estimate and estimate.discount_percent >= Decimal(str(threshold_percent)))
