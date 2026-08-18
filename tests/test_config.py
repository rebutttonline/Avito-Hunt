from avito_hunt.config import Settings


def test_empty_scraper_expiration_is_optional() -> None:
    settings = Settings(avito_scraper_expires_at="")  # type: ignore[arg-type]
    assert settings.avito_scraper_expires_at is None
