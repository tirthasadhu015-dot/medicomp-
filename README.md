# MEDICOMP+

MEDICOMP+ is a FastAPI + Vanilla JavaScript e-pharmacy comparison app that searches Apollo Pharmacy, Tata 1mg, and PharmEasy, then uses Gemini to normalize results and suggest cheaper substitutes.

## Run locally

1. Create and activate a virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
playwright install chromium
```

3. Set environment variables from `.env.example`.
4. Start the server:

```bash
uvicorn backend.main:app --reload
```

5. Open `http://127.0.0.1:8000`.

## Notes

- Live scraping can break when pharmacy websites change their markup or apply bot protection.
- If `GEMINI_API_KEY` is missing, the app falls back to heuristic normalization.
