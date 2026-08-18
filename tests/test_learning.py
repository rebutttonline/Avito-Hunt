from datetime import UTC, datetime
from decimal import Decimal

from avito_hunt.domain import Listing, MarketEstimate
from avito_hunt.learning import (
    InterestModel,
    decision_context,
    features_from_context,
    predict_interest,
    update_interest_model,
)


def listing() -> Listing:
    return Listing(
        external_id="learn-1",
        title="iPhone 15 Pro 256 ГБ",
        url="https://example.test/learn-1",
        price=75_000,
        model="iPhone 15 Pro",
        storage_gb=256,
        condition="used",
        region="москва",
        published_at=datetime.now(UTC),
        raw={"battery_health": 90},
    )


def estimate() -> MarketEstimate:
    return MarketEstimate(
        market_price=100_000,
        discount_amount=25_000,
        discount_percent=Decimal("25"),
        comparable_count=20,
        confidence="high",
        range_low=95_000,
        range_high=105_000,
        cheaper_than_percent=95,
        market_scope="exact_region",
    )


def test_decision_context_contains_versioned_numeric_features() -> None:
    context = decision_context(listing(), estimate())
    features = features_from_context(context)
    assert features is not None
    assert len(features) == 9
    assert features[0] == 1.0


def test_online_model_learns_repeated_reviewer_signal() -> None:
    features = features_from_context(decision_context(listing(), estimate()))
    assert features is not None
    positive = InterestModel()
    negative = InterestModel()
    for _ in range(25):
        positive, _, _ = update_interest_model(positive, features, interested=True)
        negative, _, _ = update_interest_model(negative, features, interested=False)
    assert predict_interest(positive, features) > 0.8
    assert predict_interest(negative, features) < 0.2
    assert positive.samples == 25
    assert positive.positives == 25
    assert negative.negatives == 25
