from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    medicine_name: str = Field(..., min_length=2, max_length=200)


class PharmacyOffer(BaseModel):
    platform: str
    product_name: str
    quantity: str
    price: float | None = None
    manufacturer: str | None = None
    purchase_url: str | None = None
    salt_composition: str | None = None
    scraped_at: str
    status: str = "ok"
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SubstituteSuggestion(BaseModel):
    brand_name: str
    salt_composition: str
    strength: str
    reason: str
    estimated_price: float | None = None


class AIInsights(BaseModel):
    unified_salt: str | None = None
    analysis: str
    substitutes: list[SubstituteSuggestion] = Field(default_factory=list)
    source: str = "fallback"


class SearchResponse(BaseModel):
    medicine_name: str
    offers: list[PharmacyOffer]
    ai_insights: AIInsights
    lowest_price: float | None = None
    warnings: list[str] = Field(default_factory=list)
