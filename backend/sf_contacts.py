"""SF contact lookup from pre-pulled sf_contacts.json."""

import json
from pathlib import Path
from typing import List, Optional

_CONTACTS_FILE = Path(__file__).parent.parent / "sf_contacts.json"
_CACHE: Optional[dict] = None


def _load() -> dict:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    if not _CONTACTS_FILE.exists():
        _CACHE = {}
        return _CACHE
    _CACHE = json.loads(_CONTACTS_FILE.read_text())
    return _CACHE


def _normalize_domain(d: str) -> str:
    return (d or "").lower().replace("https://", "").replace("http://", "").replace("www.", "").rstrip("/").split("/")[0]


def get_contacts_for_brand(brand_name: str, domain: str) -> List[dict]:
    """
    Return SF contacts for a brand. Looks up by domain first (exact + partial),
    then falls back to brand name substring match across all account_name fields.
    """
    data = _load()
    if not data:
        return []

    needle = _normalize_domain(domain)

    # 1. Exact domain match
    if needle in data:
        return _sorted(data[needle])

    # 2. Partial domain match (e.g. yeti.com → yeticoolers.com)
    for key, contacts in data.items():
        key_norm = _normalize_domain(key)
        if needle in key_norm or key_norm in needle:
            return _sorted(contacts)

    # 3. Brand name substring match (case-insensitive)
    brand_lower = (brand_name or "").lower()
    for contacts in data.values():
        if contacts and brand_lower in (contacts[0].get("account_name") or "").lower():
            return _sorted(contacts)

    # 4. Scan all contacts for any account_name match
    all_matching = []
    seen = set()
    for contacts in data.values():
        for c in contacts:
            acct = (c.get("account_name") or "").lower()
            if brand_lower and brand_lower in acct and c["email"] not in seen:
                all_matching.append(c)
                seen.add(c["email"])
    return _sorted(all_matching)


def _sorted(contacts: List[dict]) -> List[dict]:
    """Sort by title seniority (VP/Director/Manager first), then last name."""
    def rank(c):
        title = (c.get("title") or "").lower()
        if any(w in title for w in ("vp", "vice president", "chief", "ceo", "coo", "cto", "cmo", "president")):
            return 0
        if any(w in title for w in ("director", "head of", "svp", "evp")):
            return 1
        if "manager" in title:
            return 2
        return 3
    return sorted(contacts, key=lambda c: (rank(c), c.get("last_name", "")))
