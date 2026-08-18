from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from avito_hunt.domain import Listing
from avito_hunt.normalization import listing_from_payload
from avito_hunt.provider import SourceBatch, validate_batch

AVITO_ORIGIN = "https://www.avito.ru"
BLOCKED_PATH_PREFIXES = ("/api/", "/web/", "/s/", "/search/", "/autosearch")


@dataclass(frozen=True, slots=True)
class ScrapeTarget:
    region: str
    url: str


def parse_targets(value: str) -> tuple[ScrapeTarget, ...]:
    targets: list[ScrapeTarget] = []
    for chunk in value.split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            region, url = (part.strip() for part in chunk.split("|", 1))
        except ValueError as error:
            raise ValueError(
                "Каждая цель должна иметь формат регион|https://www.avito.ru/..."
            ) from error
        validate_public_category_url(url)
        if not region:
            raise ValueError("Для цели парсера не указан регион")
        targets.append(ScrapeTarget(region=region.casefold(), url=url))
    if not targets:
        raise ValueError("Не настроено ни одной цели парсера")
    if len(targets) > 5:
        raise ValueError("Для пилота допускается не более пяти страниц")
    return tuple(targets)


def validate_public_category_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in {"avito.ru", "www.avito.ru"}:
        raise ValueError("Парсер принимает только публичные HTTPS-страницы avito.ru")
    if parsed.query or parsed.fragment:
        raise ValueError("Поисковые параметры и фрагменты URL в пилоте запрещены")
    if any(parsed.path.startswith(prefix) for prefix in BLOCKED_PATH_PREFIXES):
        raise ValueError("Этот раздел Avito запрещён для пилотного сборщика")


class AvitoHtmlSource:
    """Low-frequency reader for server-rendered cards on public category pages."""

    def __init__(self, targets: tuple[ScrapeTarget, ...], *, timeout: float = 25.0) -> None:
        self.targets = targets
        self.timeout = timeout

    async def fetch(self) -> SourceBatch:
        fetched_at = datetime.now(UTC)
        listings_by_id: dict[str, Listing] = {}
        received_count = 0
        headers = {
            "User-Agent": "AvitoHuntResearch/0.1 (+https://github.com/rebutttonline/Avito-Hunt)",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "ru-RU,ru;q=0.9",
        }
        async with httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=True,
            headers=headers,
        ) as client:
            for target in self.targets:
                response = await client.get(target.url)
                if response.status_code in {403, 429}:
                    raise RuntimeError(f"Avito ограничил запрос: HTTP {response.status_code}")
                response.raise_for_status()
                parsed = parse_avito_cards(response.text, target.region, fetched_at)
                received_count += parsed[1]
                for listing in parsed[0]:
                    listings_by_id.setdefault(listing.external_id, listing)
        batch = SourceBatch(
            provider="avito-public-html-pilot",
            listings=tuple(listings_by_id.values()),
            fetched_at=fetched_at,
            received_count=received_count,
            rejected_count=received_count - len(listings_by_id),
        )
        validate_batch(batch)
        return batch


def parse_avito_cards(
    html: str,
    region: str,
    fetched_at: datetime,
) -> tuple[list[Listing], int]:
    parser = _CardParser(region, fetched_at)
    parser.feed(html)
    parser.close()
    listings = [listing for payload in parser.items if (listing := listing_from_payload(payload))]
    return listings, len(parser.items)


class _CardParser(HTMLParser):
    def __init__(self, region: str, fetched_at: datetime) -> None:
        super().__init__(convert_charrefs=True)
        self.region = region
        self.fetched_at = fetched_at
        self.items: list[dict[str, object]] = []
        self.current: dict[str, object] | None = None
        self.item_div_depth = 0
        self.capture: str | None = None
        self.capture_tag: str | None = None

    def handle_starttag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        attrs = dict(attrs_list)
        if tag == "div" and attrs.get("data-marker") == "item" and self.current is None:
            self.current = {"id": attrs.get("data-item-id", "")}
            self.item_div_depth = 1
            return
        if self.current is None:
            return
        if tag == "div":
            self.item_div_depth += 1
        marker = attrs.get("data-marker")
        if tag == "a" and marker == "item-title":
            self.current["title"] = attrs.get("title", "")
            href = attrs.get("href", "")
            absolute = urljoin(AVITO_ORIGIN, href)
            parsed = urlsplit(absolute)
            self.current["url"] = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
            self.capture = "title_text"
            self.capture_tag = tag
        elif tag == "meta" and attrs.get("itemprop") == "price":
            self.current["price"] = attrs.get("content", "")
        elif marker in {"item-location", "item-date", "item-specific-params"}:
            self.capture = {
                "item-location": "location",
                "item-date": "date",
                "item-specific-params": "condition",
            }[marker]
            self.capture_tag = tag

    def handle_endtag(self, tag: str) -> None:
        if self.current is None:
            return
        if tag == self.capture_tag:
            self.capture = None
            self.capture_tag = None
        if tag == "div":
            self.item_div_depth -= 1
            if self.item_div_depth == 0:
                self._finish_item()

    def handle_data(self, data: str) -> None:
        if self.current is None or not self.capture:
            return
        value = str(self.current.get(self.capture, "")) + data
        self.current[self.capture] = " ".join(value.split())

    def _finish_item(self) -> None:
        assert self.current is not None
        if not self.current.get("title"):
            self.current["title"] = self.current.get("title_text", "")
        self.current.update(
            {
                "region": self.region,
                "condition": self.current.get("condition", "used"),
                "published_at": self.fetched_at.isoformat(),
                "source": "avito-public-html-pilot",
            }
        )
        self.items.append(self.current)
        self.current = None
        self.item_div_depth = 0
        self.capture = None
        self.capture_tag = None
