import math
from dataclasses import dataclass
from typing import Any

from avito_hunt.domain import Listing, MarketEstimate
from avito_hunt.risk import assess_listing_risk

FEATURE_VERSION = 1
FEATURE_NAMES = (
    "bias",
    "discount",
    "low_risk",
    "confidence",
    "condition_new",
    "storage_known",
    "sample_size",
    "price_percentile",
    "local_scope",
)


@dataclass(frozen=True, slots=True)
class InterestModel:
    weights: tuple[float, ...] = (0.0,) * len(FEATURE_NAMES)
    samples: int = 0
    positives: int = 0
    negatives: int = 0


@dataclass(frozen=True, slots=True)
class LearningResult:
    saved: bool
    learned: bool = False
    duplicate: bool = False
    samples: int = 0
    positives: int = 0
    negatives: int = 0
    prediction_before: float | None = None
    prediction_after: float | None = None


def decision_context(listing: Listing, estimate: MarketEstimate) -> dict[str, Any]:
    risk = assess_listing_risk(listing)
    confidence = {"low": 0.0, "medium": 0.5, "high": 1.0}.get(estimate.confidence, 0.0)
    local_scope = {"national": 0.0, "nearby_regions": 0.5, "exact_region": 1.0}.get(
        estimate.market_scope, 0.0
    )
    features = (
        1.0,
        _clamp(float(estimate.discount_percent) / 50.0, -1.0, 2.0),
        1.0 - risk.score / 100.0,
        confidence,
        1.0 if listing.condition == "new" else 0.0,
        1.0 if listing.storage_gb is not None else 0.0,
        _clamp(estimate.comparable_count / 30.0, 0.0, 1.0),
        _clamp((estimate.cheaper_than_percent or 0) / 100.0, 0.0, 1.0),
        local_scope,
    )
    return {
        "feature_version": FEATURE_VERSION,
        "feature_names": FEATURE_NAMES,
        "features": features,
    }


def model_from_json(
    weights: object,
    *,
    samples: int = 0,
    positives: int = 0,
    negatives: int = 0,
) -> InterestModel:
    if not isinstance(weights, (list, tuple)) or len(weights) != len(FEATURE_NAMES):
        return InterestModel()
    return InterestModel(
        weights=tuple(float(value) for value in weights),
        samples=samples,
        positives=positives,
        negatives=negatives,
    )


def predict_interest(model: InterestModel, features: tuple[float, ...]) -> float:
    if len(features) != len(model.weights):
        raise ValueError("Feature vector does not match the interest model")
    score = sum(weight * feature for weight, feature in zip(model.weights, features, strict=True))
    return 1.0 / (1.0 + math.exp(-_clamp(score, -30.0, 30.0)))


def update_interest_model(
    model: InterestModel,
    features: tuple[float, ...],
    *,
    interested: bool,
) -> tuple[InterestModel, float, float]:
    prediction_before = predict_interest(model, features)
    target = 1.0 if interested else 0.0
    learning_rate = 0.35 / math.sqrt(model.samples + 1)
    regularization = 0.001
    weights = tuple(
        weight + learning_rate * ((target - prediction_before) * feature - regularization * weight)
        for weight, feature in zip(model.weights, features, strict=True)
    )
    updated = InterestModel(
        weights=weights,
        samples=model.samples + 1,
        positives=model.positives + int(interested),
        negatives=model.negatives + int(not interested),
    )
    return updated, prediction_before, predict_interest(updated, features)


def features_from_context(context: dict[str, Any]) -> tuple[float, ...] | None:
    if context.get("feature_version") != FEATURE_VERSION:
        return None
    values = context.get("features")
    if not isinstance(values, (list, tuple)) or len(values) != len(FEATURE_NAMES):
        return None
    try:
        return tuple(float(value) for value in values)
    except (TypeError, ValueError):
        return None


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(value, maximum))
