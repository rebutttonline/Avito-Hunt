from dataclasses import replace
from decimal import ROUND_HALF_UP, Decimal
from statistics import median

from avito_hunt.domain import ComparableCohorts, Listing, MarketEstimate, PriceLevel

DEAL_THRESHOLD = Decimal("15")
GREAT_DEAL_THRESHOLD = Decimal("25")
SUSPICIOUS_THRESHOLD = Decimal("35")


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

    ordered = sorted(filtered_prices)
    market_price = round(median(ordered))
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
        range_low=round(_percentile(ordered, Decimal("0.25"))),
        range_high=round(_percentile(ordered, Decimal("0.75"))),
        cheaper_than_percent=round(
            sum(price > listing.price for price in ordered) * 100 / len(ordered)
        ),
    )


def estimate_market_hierarchical(
    listing: Listing,
    cohorts: ComparableCohorts,
    *,
    minimum_count: int,
) -> MarketEstimate | None:
    """Use the narrowest market cohort that has enough robust observations."""
    candidates = (
        ("exact_region", cohorts.exact_region, None),
        ("nearby_regions", cohorts.nearby_regions, "medium"),
        ("national", cohorts.national, "low"),
    )
    for scope, prices, confidence_cap in candidates:
        estimate = estimate_market(listing, list(prices), minimum_count=minimum_count)
        if estimate:
            confidence = estimate.confidence
            if confidence_cap == "medium" and confidence == "high":
                confidence = "medium"
            elif confidence_cap == "low":
                confidence = "low"
            return replace(estimate, confidence=confidence, market_scope=scope)
    return None


def _percentile(ordered: list[int], percentile: Decimal) -> Decimal:
    if len(ordered) == 1:
        return Decimal(ordered[0])
    position = percentile * Decimal(len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return Decimal(ordered[lower]) + Decimal(ordered[upper] - ordered[lower]) * fraction


def is_deal(estimate: MarketEstimate | None, threshold_percent: float) -> bool:
    return bool(estimate and estimate.discount_percent >= Decimal(str(threshold_percent)))


def price_level(estimate: MarketEstimate) -> PriceLevel:
    if estimate.discount_percent >= SUSPICIOUS_THRESHOLD:
        return PriceLevel.SUSPICIOUSLY_CHEAP
    if estimate.discount_percent >= GREAT_DEAL_THRESHOLD:
        return PriceLevel.GREAT_DEAL
    if estimate.discount_percent >= DEAL_THRESHOLD:
        return PriceLevel.DEAL
    return PriceLevel.NORMAL
