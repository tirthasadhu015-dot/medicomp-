from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from backend import config  # noqa: F401 - ensures .env is loaded on startup
from backend.models import SearchRequest, SearchResponse
from backend.services.gemini_service import generate_ai_insights
from backend.services.scrapers import scrape_all_pharmacies


BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"

app = FastAPI(title="MediScan API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/", include_in_schema=False)
async def index() -> Response:
    if not (FRONTEND_DIR / "index.html").exists():
        return JSONResponse(
            status_code=503,
            content={"status": "error", "message": "Frontend assets are missing."},
        )
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/app.js", include_in_schema=False)
async def frontend_script() -> Response:
    if not (FRONTEND_DIR / "app.js").exists():
        return JSONResponse(
            status_code=503,
            content={"status": "error", "message": "Frontend script is missing."},
        )
    return FileResponse(FRONTEND_DIR / "app.js")


@app.post("/api/search", response_model=SearchResponse)
async def search_medicine(payload: SearchRequest) -> SearchResponse:
    medicine_name = payload.medicine_name.strip()
    if len(medicine_name) < 2:
        raise HTTPException(status_code=400, detail="Medicine name must be at least 2 characters.")

    offers, warnings = await scrape_all_pharmacies(medicine_name)
    ai_insights = await generate_ai_insights(medicine_name, offers)
    priced_offers = [offer.price for offer in offers if offer.price is not None]
    lowest_price = min(priced_offers) if priced_offers else None

    return SearchResponse(
        medicine_name=medicine_name,
        offers=offers,
        ai_insights=ai_insights,
        lowest_price=lowest_price,
        warnings=warnings,
    )


@app.get("/health")
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}
