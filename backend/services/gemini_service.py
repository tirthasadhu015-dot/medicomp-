from __future__ import annotations

import json
import re
from typing import Any

from backend.config import get_env
from backend.models import AIInsights, PharmacyOffer, SubstituteSuggestion

try:
    from google import genai as google_genai
except ImportError:  # pragma: no cover - optional dependency at runtime
    google_genai = None


MODEL_NAME = get_env("GEMINI_MODEL", "gemini-1.5-flash")


def build_fallback_insights(medicine_name: str, offers: list[PharmacyOffer]) -> AIInsights:
    valid_offers = [offer for offer in offers if offer.product_name and offer.status == "ok"]
    unified_salt = _infer_unified_salt(medicine_name, valid_offers)
    sorted_offers = sorted((offer for offer in valid_offers if offer.price is not None), key=lambda item: item.price or 0)

    substitutes: list[SubstituteSuggestion] = []
    for offer in sorted_offers[1:3]:
        substitutes.append(
            SubstituteSuggestion(
                brand_name=offer.product_name,
                salt_composition=offer.salt_composition or unified_salt or "Composition not confirmed",
                strength=_extract_strength(offer.product_name) or "Match strength manually",
                reason="Lower-priced listing among scraped results with a similar name/strength pattern.",
                estimated_price=offer.price,
            )
        )

    analysis = (
        f"Estimated unified salt composition: {unified_salt or 'Unable to infer confidently'}. "
        "Fallback mode is active because Gemini was unavailable, so composition mapping should be reviewed manually."
    )
    return AIInsights(
        unified_salt=unified_salt,
        analysis=analysis,
        substitutes=substitutes,
        source="fallback",
    )


async def generate_ai_insights(medicine_name: str, offers: list[PharmacyOffer]) -> AIInsights:
    api_key = get_env("GEMINI_API_KEY")
    if not api_key:
        return build_fallback_insights(medicine_name, offers)
    payload = [
        {
            "platform": offer.platform,
            "product_name": offer.product_name,
            "quantity": offer.quantity,
            "price": offer.price,
            "manufacturer": offer.manufacturer,
            "salt_composition": offer.salt_composition,
            "status": offer.status,
        }
        for offer in offers
    ]
    prompt = {
        "medicine_name": medicine_name,
        "instructions": {
            "normalize_names": True,
            "suggest_substitutes_count": 2,
            "strict_strength_match": True,
        },
        "offers": payload,
        "response_schema": {
            "unified_salt": "string",
            "analysis": "string",
            "substitutes": [
                {
                    "brand_name": "string",
                    "salt_composition": "string",
                    "strength": "string",
                    "reason": "string",
                    "estimated_price": "number|null",
                }
            ],
        },
    }

    try:
        parsed = await _generate_with_gemini(api_key, prompt)
        substitutes = [
            SubstituteSuggestion(
                brand_name=item.get("brand_name", "Unknown"),
                salt_composition=item.get("salt_composition", "Unknown"),
                strength=item.get("strength", "Unknown"),
                reason=item.get("reason", "Not provided"),
                estimated_price=item.get("estimated_price"),
            )
            for item in parsed.get("substitutes", [])[:2]
        ]
        return AIInsights(
            unified_salt=parsed.get("unified_salt"),
            analysis=parsed.get("analysis", "No analysis returned."),
            substitutes=substitutes,
            source="gemini",
        )
    except Exception:
        return build_fallback_insights(medicine_name, offers)


async def _generate_with_gemini(api_key: str, prompt: dict[str, Any]) -> dict[str, Any]:
    system_instruction = (
        "You are a pharmacy data normalizer. "
        "Given raw medicine listings from multiple Indian e-pharmacies, normalize them to a unified salt composition, "
        "identify exact strength matches, and suggest two lower-cost generic substitutes only if the chemical composition "
        "and strength are the same. Return strict JSON only."
    )
    prompt_text = json.dumps(prompt, ensure_ascii=True)

    if google_genai is not None:
        client = google_genai.Client(api_key=api_key)
        response = await client.aio.models.generate_content(
            model=MODEL_NAME,
            contents=prompt_text,
            config={
                "temperature": 0.2,
                "response_mime_type": "application/json",
                "system_instruction": system_instruction,
            },
        )
        return json.loads(response.text)

    try:
        import google.generativeai as legacy_genai
    except ImportError:  # pragma: no cover - optional dependency at runtime
        legacy_genai = None

    if legacy_genai is not None:
        legacy_genai.configure(api_key=api_key)
        model = legacy_genai.GenerativeModel(
            MODEL_NAME,
            system_instruction=system_instruction,
        )
        response = await model.generate_content_async(
            prompt_text,
            generation_config={"temperature": 0.2, "response_mime_type": "application/json"},
        )
        return json.loads(response.text)

    raise RuntimeError("No Gemini SDK is installed. Install google-genai or google-generativeai.")


def _infer_unified_salt(medicine_name: str, offers: list[PharmacyOffer]) -> str | None:
    for candidate in [medicine_name, *(offer.salt_composition or "" for offer in offers), *(offer.product_name for offer in offers)]:
        if not candidate:
            continue
        strength = _extract_strength(candidate)
        tokens = re.findall(r"[A-Za-z]{4,}", candidate)
        if tokens:
            salt = tokens[0].capitalize()
            return f"{salt} {strength}".strip() if strength else salt
    return None


def _extract_strength(text: str) -> str | None:
    match = re.search(r"(\d+\s*(?:mg|mcg|ml))", text, flags=re.IGNORECASE)
    return match.group(1) if match else None
