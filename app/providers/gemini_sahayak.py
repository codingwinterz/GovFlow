"""Gemini for Sahayak: plain text, no tools, low temperature, the pinned model (GEMINI_MODEL overrides).
Errors surface as ProviderError from the shared client; app.sahayak then answers from the entries verbatim."""

from typing import Optional

from app.extraction import ProviderError
from app.providers.gemini import GeminiClient

TEMPERATURE = 0.1          # VERIFY: set offline only; Sahayak has not been exercised live
MAX_OUTPUT_TOKENS = 300


class GeminiSahayak:
    name = "gemini"

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None, **client_kwargs):
        self.client = GeminiClient(api_key, model, **client_kwargs)
        self.model = self.client.model

    def answer(self, system: str, prompt: str) -> str:
        body = {"systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": TEMPERATURE, "maxOutputTokens": MAX_OUTPUT_TOKENS}}
        response = self.client.generate(body)
        try:
            return "".join(p.get("text", "") for p in response["candidates"][0]["content"]["parts"])
        except (KeyError, IndexError, TypeError):
            raise ProviderError("Gemini returned no text", kind="http_error") from None
