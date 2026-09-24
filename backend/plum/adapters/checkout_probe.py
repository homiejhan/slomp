"""Checkout probes: try codes on a real cart and report what the store actually did.

Two implementations:
  * SimulatedProbe   - deterministic outcomes from coupon stats; used by tests and the demo.
  * PlaywrightProbe  - headless browser flow driven by a per-store CheckoutRecipe (selectors + total parser).

Operational notes for the real one:
  - Run it server-side against a throwaway cart, never inside a shopper's session, and never
    swap attribution cookies. Probing checks validity; it does not "click".
  - Respect each retailer's terms and robots rules; many partners prefer you validate codes via
    their offer feed. Keep concurrency per store to 1 and cadence low (a code changes state slowly).
  - Every result, pass or fail, goes back through coupons.record_outcome so the crowd stats and
    the probe stats are one ledger.
"""
from __future__ import annotations

import asyncio
import hashlib
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable, Optional

from ..coupons import applies, discount_of, record_outcome
from ..models import Coupon, Listing, ProbeResult, ProbeStep, Product


def parse_money(text: str) -> float:
    """The last dollar amount in a cart-total element: "Total: $1,234.56 (2 items)" -> 1234.56."""
    s = text or ""
    amounts = re.findall(r"\$\s*(\d[\d,]*(?:\.\d{2})?)", s) or re.findall(r"\d[\d,]*\.\d{2}", s) or re.findall(r"\d[\d,]*", s)
    return float(amounts[-1].replace(",", "")) if amounts else 0.0


class CheckoutProbe(ABC):
    @abstractmethod
    async def try_codes(self, listing: Listing, product: Product, coupons: list[Coupon]) -> ProbeResult: ...


class SimulatedProbe(CheckoutProbe):
    """Outcome = hash(code, listing) < observed success rate. Same cart, same answer."""

    async def try_codes(self, listing: Listing, product: Product, coupons: list[Coupon]) -> ProbeResult:
        steps: list[ProbeStep] = []
        for c in coupons:
            ok, why = applies(c, listing, product)
            if not ok:
                steps.append(ProbeStep(c.code, False, 0.0, why))
                continue
            truth = c.successes / c.attempts if c.attempts else 0.5
            roll = int(hashlib.sha1(f"{c.code}|{listing.id}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
            worked = roll < truth
            disc = discount_of(c, listing.price, listing.shipping or 0.0) if worked else 0.0
            steps.append(ProbeStep(c.code, worked, round(disc, 2), "" if worked else "store rejected it"))
            record_outcome(c, worked)
        winner = max((s for s in steps if s.ok), key=lambda s: s.discount, default=None)
        return ProbeResult(listing.id, steps, winner.code if winner else None, winner.discount if winner else 0.0)


@dataclass
class CheckoutRecipe:
    """What a store's cart page looks like. Keep these in config, not code, so they survive redesigns."""
    cart_url: str
    add_to_cart: Optional[str]           # selector or None if cart_url already contains the item
    promo_input: str
    promo_submit: str
    total_selector: str
    error_selector: str
    parse_total: Callable[[str], float] = parse_money
    settle_ms: int = 800
    extra_steps: list[str] = field(default_factory=list)


class PlaywrightProbe(CheckoutProbe):
    def __init__(self, recipes: dict[str, CheckoutRecipe], headless: bool = True, per_store_concurrency: int = 1):
        self.recipes = recipes
        self.headless = headless
        self._sem: dict[str, asyncio.Semaphore] = {r: asyncio.Semaphore(per_store_concurrency) for r in recipes}

    async def try_codes(self, listing: Listing, product: Product, coupons: list[Coupon]) -> ProbeResult:
        recipe = self.recipes.get(listing.retailer)
        if recipe is None:
            raise RuntimeError(f"no checkout recipe for {listing.retailer}")
        try:
            from playwright.async_api import async_playwright  # type: ignore
        except Exception as e:  # noqa: BLE001
            raise RuntimeError("pip install 'plum[probe]' && playwright install chromium") from e
        steps: list[ProbeStep] = []
        async with self._sem[listing.retailer]:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=self.headless)
                page = await browser.new_page()
                await page.goto(recipe.cart_url.format(url=listing.url, id=listing.id))
                if recipe.add_to_cart:
                    await page.click(recipe.add_to_cart)
                await page.wait_for_timeout(recipe.settle_ms)
                base = recipe.parse_total(await page.inner_text(recipe.total_selector))
                for c in coupons:
                    ok, why = applies(c, listing, product)
                    if not ok:
                        steps.append(ProbeStep(c.code, False, 0.0, why))
                        continue
                    await page.fill(recipe.promo_input, c.code)
                    await page.click(recipe.promo_submit)
                    await page.wait_for_timeout(recipe.settle_ms)
                    err = await page.query_selector(recipe.error_selector)
                    total = recipe.parse_total(await page.inner_text(recipe.total_selector))
                    worked = err is None and total < base - 0.005
                    steps.append(ProbeStep(c.code, worked, round(base - total, 2) if worked else 0.0, "" if worked else "store rejected it"))
                    record_outcome(c, worked)
                    if worked:  # remove it so the next code is tested on a clean cart
                        await page.reload()
                        await page.wait_for_timeout(recipe.settle_ms)
                await browser.close()
        winner = max((s for s in steps if s.ok), key=lambda s: s.discount, default=None)
        return ProbeResult(listing.id, steps, winner.code if winner else None, winner.discount if winner else 0.0)
