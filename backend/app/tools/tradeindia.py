# ============================================================
# VendorScout - TradeIndia supplier source (multi-marketplace)
# ============================================================
# A second REAL B2B source alongside IndiaMART, so the agent can combine results
# across marketplaces and surface the best picks overall.
#
# TradeIndia is a Next.js app: its search page embeds the full product list as
# JSON in <script id="__NEXT_DATA__">. We fetch the search page with a browser
# User-Agent and parse that JSON — reliable, no anti-bot skeleton, no headless
# browser needed. Each record maps to the same vendor shape the scout flow uses
# (name/company/product/price/location/url/specs) tagged source_site="TradeIndia".
# ============================================================

from __future__ import annotations

import json
import logging
import re
from typing import Optional
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
_NEXT = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_NUM = re.compile(r"([\d,]+(?:\.\d+)?)")


def _inr(n: float) -> str:
    """Format a number with Indian digit grouping → ₹3,00,800."""
    s = str(int(round(n)))
    if len(s) <= 3:
        return "₹" + s
    last3, rest = s[-3:], s[:-3]
    rest = re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", rest)
    return "₹" + rest + "," + last3


def _fmt_price(p) -> Optional[str]:
    if not p:
        return None
    m = _NUM.search(str(p))
    if not m:
        return None
    try:
        n = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    # TradeIndia sellers often list ₹1/₹3 placeholders meaning "price on request" —
    # treat implausibly-low values as no price so they don't win "Cheapest".
    return _inr(n) if n >= 10 else None


def _collect(node, seen: set, out: list) -> None:
    """Recursively gather every product dict in the __NEXT_DATA__ tree."""
    if isinstance(node, dict):
        if node.get("product_name") and (node.get("price") or node.get("amount")):
            key = node.get("prod_url") or node.get("product_id") or node.get("product_name")
            if key not in seen:
                seen.add(key)
                out.append(node)
        for v in node.values():
            _collect(v, seen, out)
    elif isinstance(node, list):
        for v in node:
            _collect(v, seen, out)


def _map(p: dict) -> dict:
    url = str(p.get("prod_url") or "")
    if url.startswith("/"):
        url = "https://www.tradeindia.com" + url
    company = (p.get("co_name") or p.get("initial_co_name") or "").strip()
    product = (p.get("product_name") or "").strip()
    specs = {}
    if p.get("moq"):
        specs["MOQ"] = str(p["moq"])
    if p.get("made_in_india"):
        specs["Origin"] = "Made in India"
    if p.get("price_range"):
        specs["Price range"] = str(p["price_range"])
    return {
        "name": company or product,
        "company": company or None,
        "product": product,
        "price": _fmt_price(p.get("price") or p.get("amount")),
        "location": (p.get("city") or "").strip() or None,
        "url": url or None,
        "specs": specs,
        "source_site": "TradeIndia",
        # light reputation/authenticity signals TradeIndia exposes
        "_trust": bool(p.get("has_trust_stamp")),
        "_premium": bool(p.get("super_seller") or p.get("premium_seller") or p.get("super_premium_seller")),
    }


async def fetch_tradeindia_suppliers(query: str, max_n: int = 6, timeout: int = 18) -> list[dict]:
    """Fetch REAL suppliers for `query` from TradeIndia's search JSON. [] on failure."""
    url = "https://www.tradeindia.com/search.html?keyword=" + quote(query)
    headers = {"User-Agent": _UA, "Accept-Language": "en-US,en;q=0.9",
               "Accept": "text/html,application/xhtml+xml"}
    try:
        async with httpx.AsyncClient(headers=headers, timeout=timeout,
                                     follow_redirects=True) as cl:
            r = await cl.get(url)
    except Exception as e:  # noqa: BLE001
        logger.warning("tradeindia fetch failed: %s", e)
        return []
    if r.status_code != 200:
        logger.info("tradeindia: HTTP %s for %r", r.status_code, query)
        return []
    m = _NEXT.search(r.text)
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
    except Exception:  # noqa: BLE001
        return []
    prods: list[dict] = []
    _collect(data, set(), prods)
    recs = [_map(p) for p in prods]
    recs = [x for x in recs if x["product"]]
    if recs:
        logger.info("tradeindia: %d real suppliers for %r", len(recs), query)
    return recs[:max_n]
