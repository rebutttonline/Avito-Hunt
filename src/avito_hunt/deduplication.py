import hashlib
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from avito_hunt.domain import Listing

_SPACE = re.compile(r"\s+")


def canonical_url(url: str) -> str:
    parts = urlsplit(url)
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, "", ""))


def is_specific_listing_url(url: str) -> bool:
    return urlsplit(url).path.rstrip("/") not in {"", "/"}


def relist_fingerprint(listing: Listing) -> str | None:
    seller_id = _seller_identifier(listing.raw)
    if not seller_id:
        return None
    normalized_title = _SPACE.sub(" ", listing.title.casefold()).strip()
    value = "|".join(
        (
            seller_id,
            normalized_title,
            listing.model.casefold(),
            str(listing.storage_gb or ""),
            listing.condition.casefold(),
            listing.region.casefold(),
        )
    )
    return hashlib.sha256(value.encode()).hexdigest()


def feedback_key(external_id: str) -> str:
    return hashlib.blake2s(external_id.encode(), digest_size=8).hexdigest()


def _seller_identifier(raw: dict[str, Any]) -> str | None:
    for key in ("seller_id", "user_id", "owner_id", "sellerId", "userId"):
        value = str(raw.get(key) or "").strip()
        if value:
            return value
    seller = raw.get("seller")
    if isinstance(seller, dict):
        for key in ("id", "user_id", "userId"):
            value = str(seller.get(key) or "").strip()
            if value:
                return value
    return None
