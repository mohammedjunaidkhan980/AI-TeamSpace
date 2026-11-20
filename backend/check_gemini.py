"""Minimal Gemini API key check — reads config, makes one text-generation call."""
import sys
from app.core.config import get_settings

settings = get_settings()
api_key = settings.google_api_key or settings.gemini_api_key
model = settings.default_llm_model

if not api_key:
    sys.exit("No API key found (GOOGLE_API_KEY / GEMINI_API_KEY not set in .env)")

try:
    from google import genai
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model,
        contents="Say hello in one sentence.",
    )
    print(f"HTTP status : 200 OK")
    print(f"Model       : {model}")
    print(f"Response    : {response.text.strip()}")
except Exception as exc:
    print(f"FAILED: {exc}", file=sys.stderr)
    sys.exit(1)
