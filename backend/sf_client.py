"""Salesforce account loader — reads from sf_accounts.json pre-pulled via the SF MCP."""

import json
from pathlib import Path
from typing import List, Optional

SF_DATA_FILE = Path(__file__).parent.parent / "sf_accounts.json"

_CACHE: Optional[List[dict]] = None


def load_sf_accounts() -> List[dict]:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    if not SF_DATA_FILE.exists():
        return []
    with open(SF_DATA_FILE, encoding="utf-8") as f:
        _CACHE = json.load(f)
    return _CACHE


def search_sf_accounts(q: str) -> List[dict]:
    """Return accounts whose name or domain contains q (case-insensitive)."""
    if not q or len(q) < 1:
        return load_sf_accounts()
    q_lower = q.lower()
    return [
        a for a in load_sf_accounts()
        if q_lower in a["name"].lower() or q_lower in a["domain"].lower()
    ]
