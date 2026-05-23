from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote_plus

import httpx
from bs4 import BeautifulSoup

from backend.models import PharmacyOffer

try:
    from playwright.async_api import async_playwright
except ImportError:  # pragma: no cover - optional dependency at runtime
    async_playwright = None


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


DEFAULT_HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "accept-language": "en-US,en;q=0.9",
    "cache-control": "no-cache",
    "pragma": "no-cache",
    "user-agent": USER_AGENT,
}


@dataclass(slots=True)
class PharmacyConfig:
    name: str
    search_url: str


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean_whitespace(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = re.sub(r"\s+", " ", value).strip()
    return cleaned or None


def parse_price(raw_value: str | None) -> float | None:
    if not raw_value:
        return None
    match = re.search(r"(\d+(?:\.\d{1,2})?)", raw_value.replace(",", ""))
    return float(match.group(1)) if match else None


def infer_quantity(text: str | None) -> str | None:
    if not text:
        return None
    patterns = [
        r"(\d+\s*(?:tabs?|tablets?|capsules?|caps?|ml|mg|gm|g|sachet|sachets|bottle|strip|pack))",
        r"(strip of \d+)",
        r"(bottle of \d+\s*ml)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return clean_whitespace(match.group(1))
    return clean_whitespace(text[:80])


def infer_salt_from_name(name: str) -> str | None:
    token_match = re.findall(r"[A-Za-z][A-Za-z0-9+\-]{2,}", name)
    if not token_match:
        return None
    strength_match = re.search(r"(\d+\s*(?:mg|mcg|ml))", name, flags=re.IGNORECASE)
    first = token_match[0].capitalize()
    return f"{first} {strength_match.group(1)}".strip() if strength_match else first


async def fetch_html(
    client: httpx.AsyncClient,
    url: str,
    *,
    use_playwright_fallback: bool = True,
) -> str:
    response = await client.get(url, timeout=20.0, headers=DEFAULT_HEADERS, follow_redirects=True)
    response.raise_for_status()
    html = response.text
    if use_playwright_fallback and _looks_blocked(html):
        fallback_html = await fetch_with_playwright(url)
        if fallback_html:
            return fallback_html
    return html


def _looks_blocked(html: str) -> bool:
    lowered = html.lower()
    blocked_markers = [
        "access denied",
        "captcha",
        "bot verification",
        "temporarily unavailable",
        "please enable javascript",
    ]
    return any(marker in lowered for marker in blocked_markers)


async def fetch_with_playwright(url: str) -> str | None:
    if async_playwright is None:
        return None

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1440, "height": 900},
            locale="en-US",
        )
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(1500)
            return await page.content()
        finally:
            await context.close()
            await browser.close()


async def scrape_all_pharmacies(medicine_name: str) -> tuple[list[PharmacyOffer], list[str]]:
    async with httpx.AsyncClient() as client:
        tasks = [
            scrape_1mg(client, medicine_name),
            scrape_apollo(client, medicine_name),
            scrape_pharmeasy(client, medicine_name),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    offers: list[PharmacyOffer] = []
    warnings: list[str] = []
    for result in results:
        if isinstance(result, Exception):
            warnings.append(str(result))
            continue
        platform_offers, platform_warnings = result
        offers.extend(platform_offers)
        warnings.extend(platform_warnings)

    offers.sort(key=lambda item: (item.price is None, item.price or 0))
    return offers, warnings


async def scrape_1mg(client: httpx.AsyncClient, medicine_name: str) -> tuple[list[PharmacyOffer], list[str]]:
    url = f"https://www.1mg.com/search/all?name={quote_plus(medicine_name)}"
    warnings: list[str] = []
    try:
        html = await fetch_html(client, url)
    except Exception as exc:
        return [_error_offer("Tata 1mg", url, exc)], [f"Tata 1mg unavailable: {exc}"]

    offers = _parse_1mg_html(html, url)
    if offers:
        return offers, warnings

    embedded = _parse_1mg_embedded_json(html, url)
    if embedded:
        return embedded, warnings

    return [_empty_offer("Tata 1mg", url, "No product data found.")], ["Tata 1mg returned no matching products."]


def _parse_1mg_html(html: str, url: str) -> list[PharmacyOffer]:
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select('div[data-testid="product-card"], div.style__horizontal-card___1Zwmt')
    offers: list[PharmacyOffer] = []
    for card in cards[:6]:
        name = clean_whitespace(_extract_text(card, ["h2", "a", '[data-testid="product-title"]']))
        price = parse_price(_extract_text(card, ['[data-testid="price"]', ".style__price-tag___B2csA", ".PriceBoxPlanOption__offer-price"]))
        quantity = infer_quantity(_extract_text(card, ["div", "span"]))
        manufacturer = clean_whitespace(_extract_text(card, [".style__manufacturer___sNuVd", "span"]))
        href = _extract_href(card)
        if name:
            offers.append(
                PharmacyOffer(
                    platform="Tata 1mg",
                    product_name=name,
                    quantity=quantity or "Not listed",
                    price=price,
                    manufacturer=manufacturer,
                    purchase_url=_absolute_url("https://www.1mg.com", href or url),
                    salt_composition=infer_salt_from_name(name),
                    scraped_at=utc_now_iso(),
                )
            )
    return offers


def _parse_1mg_embedded_json(html: str, url: str) -> list[PharmacyOffer]:
    match = re.search(r"window\.__INITIAL_STATE__\s*=\s*({.*?})\s*;</script>", html, flags=re.DOTALL)
    if not match:
        return []
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return []
    products = payload.get("search", {}).get("products", [])[:6]
    offers: list[PharmacyOffer] = []
    for product in products:
        name = clean_whitespace(product.get("name"))
        if not name:
            continue
        price = product.get("discountedPrice") or product.get("price")
        quantity = clean_whitespace(product.get("packSizeLabel") or product.get("packSize"))
        manufacturer = clean_whitespace(product.get("manufacturerName"))
        slug = product.get("slug") or ""
        offers.append(
            PharmacyOffer(
                platform="Tata 1mg",
                product_name=name,
                quantity=quantity or "Not listed",
                price=float(price) if isinstance(price, (int, float)) else parse_price(str(price)),
                manufacturer=manufacturer,
                purchase_url=_absolute_url("https://www.1mg.com", slug or url),
                salt_composition=clean_whitespace(product.get("shortComposition")) or infer_salt_from_name(name),
                scraped_at=utc_now_iso(),
                metadata={"source": "embedded-json"},
            )
        )
    return offers


async def scrape_apollo(client: httpx.AsyncClient, medicine_name: str) -> tuple[list[PharmacyOffer], list[str]]:
    url = f"https://www.apollopharmacy.in/search-medicines/{quote_plus(medicine_name)}"
    try:
        html = await fetch_html(client, url)
    except Exception as exc:
        return [_error_offer("Apollo Pharmacy", url, exc)], [f"Apollo Pharmacy unavailable: {exc}"]

    offers = _parse_apollo_html(html, url)
    if offers:
        return offers, []
    return [_empty_offer("Apollo Pharmacy", url, "No product data found.")], ["Apollo Pharmacy returned no matching products."]


def _parse_apollo_html(html: str, url: str) -> list[PharmacyOffer]:
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select("div.ProductCard_productCardGrid__Q7J3q, div[class*='ProductCard_productCardGrid']")
    offers: list[PharmacyOffer] = []
    for card in cards[:6]:
        name = clean_whitespace(_extract_text(card, ["h2", "a", "div[class*='ProductCard_productName']"]))
        price = parse_price(_extract_text(card, ["div[class*='Price_price']", "span[class*='Price_price']"]))
        quantity = infer_quantity(_extract_text(card, ["div[class*='ProductCard_unit']", "span", "div"]))
        manufacturer = clean_whitespace(_extract_text(card, ["div[class*='ProductCard_sellerName']", "div[class*='ProductCard_manufacturer']"]))
        href = _extract_href(card)
        if name:
            offers.append(
                PharmacyOffer(
                    platform="Apollo Pharmacy",
                    product_name=name,
                    quantity=quantity or "Not listed",
                    price=price,
                    manufacturer=manufacturer,
                    purchase_url=_absolute_url("https://www.apollopharmacy.in", href or url),
                    salt_composition=infer_salt_from_name(name),
                    scraped_at=utc_now_iso(),
                )
            )
    return offers


async def scrape_pharmeasy(client: httpx.AsyncClient, medicine_name: str) -> tuple[list[PharmacyOffer], list[str]]:
    url = f"https://pharmeasy.in/search/all?name={quote_plus(medicine_name)}"
    try:
        html = await fetch_html(client, url)
    except Exception as exc:
        return [_error_offer("PharmEasy", url, exc)], [f"PharmEasy unavailable: {exc}"]

    offers = _parse_pharmeasy_html(html, url)
    if offers:
        return offers, []
    return [_empty_offer("PharmEasy", url, "No product data found.")], ["PharmEasy returned no matching products."]


def _parse_pharmeasy_html(html: str, url: str) -> list[PharmacyOffer]:
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select("div[data-testid='product-card'], div[class*='ProductCard_medicineUnitContainer']")
    offers: list[PharmacyOffer] = []
    for card in cards[:6]:
        name = clean_whitespace(_extract_text(card, ["h1", "h2", "a", "div[class*='ProductCard_medicineName']"]))
        price = parse_price(_extract_text(card, ["div[class*='ProductPriceContainer_ourPrice']", "span[class*='ProductPriceContainer_ourPrice']"]))
        quantity = infer_quantity(_extract_text(card, ["div[class*='ProductCard_measurementUnit']", "span", "div"]))
        manufacturer = clean_whitespace(_extract_text(card, ["div[class*='ProductCard_manufacturerName']", "div[class*='ProductCard_companyName']"]))
        href = _extract_href(card)
        if name:
            offers.append(
                PharmacyOffer(
                    platform="PharmEasy",
                    product_name=name,
                    quantity=quantity or "Not listed",
                    price=price,
                    manufacturer=manufacturer,
                    purchase_url=_absolute_url("https://pharmeasy.in", href or url),
                    salt_composition=infer_salt_from_name(name),
                    scraped_at=utc_now_iso(),
                )
            )
    return offers


def _extract_text(node: Any, selectors: list[str]) -> str | None:
    for selector in selectors:
        found = node.select_one(selector)
        if found and found.get_text(strip=True):
            return found.get_text(" ", strip=True)
    text = node.get_text(" ", strip=True)
    return text if text else None


def _extract_href(node: Any) -> str | None:
    link = node.select_one("a[href]")
    return link.get("href") if link else None


def _absolute_url(base: str, path: str) -> str:
    if path.startswith("http://") or path.startswith("https://"):
        return path
    if not path.startswith("/"):
        path = "/" + path
    return base.rstrip("/") + path


def _error_offer(platform: str, url: str, exc: Exception) -> PharmacyOffer:
    return PharmacyOffer(
        platform=platform,
        product_name="Unavailable",
        quantity="Unknown",
        price=None,
        manufacturer=None,
        purchase_url=url,
        scraped_at=utc_now_iso(),
        status="error",
        error=str(exc),
    )


def _empty_offer(platform: str, url: str, message: str) -> PharmacyOffer:
    return PharmacyOffer(
        platform=platform,
        product_name="No matching product found",
        quantity="Unknown",
        price=None,
        manufacturer=None,
        purchase_url=url,
        scraped_at=utc_now_iso(),
        status="empty",
        error=message,
    )
