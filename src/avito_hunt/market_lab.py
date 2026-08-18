from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from avito_hunt.domain import Listing, PriceLevel
from avito_hunt.market import estimate_market, price_level


@dataclass(frozen=True, slots=True)
class LabReport:
    cases: int
    classification_accuracy: Decimal
    mean_market_error_percent: Decimal
    false_positive_rate: Decimal


def run_market_lab() -> LabReport:
    correct = 0
    market_errors: list[Decimal] = []
    false_positives = 0
    normal_cases = 0
    cases = list(synthetic_lab_cases())
    for listing, prices, expected_level, true_market in cases:
        estimate = estimate_market(listing, prices, minimum_count=10)
        if not estimate:
            continue
        predicted = price_level(estimate)
        correct += predicted is expected_level
        error = abs(Decimal(estimate.market_price - true_market) * 100 / true_market)
        market_errors.append(error)
        if expected_level is PriceLevel.NORMAL:
            normal_cases += 1
            false_positives += predicted is not PriceLevel.NORMAL
    evaluated = len(market_errors)
    return LabReport(
        cases=evaluated,
        classification_accuracy=_percent(correct, evaluated),
        mean_market_error_percent=(
            sum(market_errors, Decimal()) / evaluated if evaluated else Decimal()
        ).quantize(Decimal("0.01")),
        false_positive_rate=_percent(false_positives, normal_cases),
    )


def synthetic_lab_cases():
    """Generate a deterministic, fictional benchmark without third-party listings."""
    models = {
        "iPhone 13": 42_000,
        "iPhone 13 Pro": 58_000,
        "iPhone 14 Pro": 72_000,
        "iPhone 14 Pro Max": 84_000,
        "iPhone 15": 69_000,
        "iPhone 15 Pro": 91_000,
        "iPhone 15 Pro Max": 105_000,
        "iPhone 16 Pro": 119_000,
    }
    regions = {
        "москва": 1.04,
        "санкт-петербург": 1.02,
        "казань": 0.99,
        "екатеринбург": 1.0,
        "новосибирск": 0.98,
    }
    discounts = (
        (Decimal("0.08"), PriceLevel.NORMAL),
        (Decimal("0.18"), PriceLevel.DEAL),
        (Decimal("0.28"), PriceLevel.GREAT_DEAL),
        (Decimal("0.40"), PriceLevel.SUSPICIOUSLY_CHEAP),
    )
    offsets = (-8, -6, -4, -3, -2, -1, 0, 0, 1, 2, 3, 4, 6, 8, 220)
    now = datetime.now(UTC)
    for model, base in models.items():
        for region, multiplier in regions.items():
            market_price = round(base * multiplier)
            prices = [round(market_price * (100 + offset) / 100) for offset in offsets]
            for discount, expected in discounts:
                candidate_price = round(Decimal(market_price) * (Decimal(1) - discount))
                external_id = f"lab-{model}-{region}-{expected.value}".replace(" ", "-")
                yield (
                    Listing(
                        external_id=external_id,
                        title=f"{model} 256 ГБ · синтетический тест",
                        url=f"https://example.test/{external_id}",
                        price=candidate_price,
                        model=model,
                        storage_gb=256,
                        condition="used",
                        region=region,
                        published_at=now,
                        raw={"synthetic": True},
                    ),
                    prices,
                    expected,
                    market_price,
                )


def format_lab_report(report: LabReport) -> str:
    return (
        "🧪 <b>Лаборатория рыночной оценки</b>\n\n"
        f"Сценариев: <b>{report.cases}</b>\n"
        f"Точность уровней: <b>{report.classification_accuracy}%</b>\n"
        f"Средняя ошибка медианы: <b>{report.mean_market_error_percent}%</b>\n"
        f"Ложные выгодные предложения: <b>{report.false_positive_rate}%</b>\n\n"
        "Набор полностью синтетический: 8 моделей, 5 регионов, выбросы и четыре "
        "ценовых уровня. Реальные данные поставщика в тесте не используются."
    )


def _percent(part: int, whole: int) -> Decimal:
    if not whole:
        return Decimal()
    return (Decimal(part * 100) / Decimal(whole)).quantize(Decimal("0.1"))
