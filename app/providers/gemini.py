"""Gemini vision extraction over the REST API (standard library only, no SDK dependency).

The API key is read from the GEMINI_API_KEY environment variable and sent only in the
x-goog-api-key header; it never appears in URLs, errors, logs or the audit trail.
Confidence values are the model's own estimate and are not calibrated probabilities.
"""

import base64
import json
import os
import urllib.error
import urllib.request
from typing import Any, Callable, Optional

from app.extraction import ExtractionRequest, ProviderError, ProviderField

DEFAULT_MODEL = "gemini-3.8-flash"   # override with GEMINI_MODEL
API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
TIMEOUT_SECONDS = 60

Post = Callable[[str, dict, dict, float], dict]

PROMPT = """You are reading a scanned {doc_type} for a government case file.
Extract only these fields: {fields}.
Rules:
- Copy each value exactly as printed. Do not correct spelling or expand abbreviations.
- Write dates as YYYY-MM-DD.
- For an area, put the number in "area" and the unit exactly as printed in "area_unit".
- If a field is missing, unreadable or you are unsure what it says, leave it out. Never guess.
- confidence is your estimate (0 to 1) that the value is exactly what is printed.
- page is the 1-based page number where you read the value."""

OCR_PROMPT = """The text below is OCR output from a scanned {doc_type}; it may contain OCR errors.
Extract only these fields: {fields}.
Copy values as they appear. Write dates as YYYY-MM-DD. Leave out anything unreadable. Never guess.
confidence is your estimate (0 to 1) that the value is exactly what the original document says."""


def _urllib_post(url: str, headers: dict, body: dict, timeout: float) -> dict:
    request = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _schema(fields: list[str]) -> dict:
    item = {"type": "OBJECT",
            "properties": {"name": {"type": "STRING", "enum": fields}, "value": {"type": "STRING"},
                           "confidence": {"type": "NUMBER"}, "page": {"type": "INTEGER"}},
            "required": ["name", "value", "confidence"]}
    return {"type": "OBJECT", "properties": {"fields": {"type": "ARRAY", "items": item}}, "required": ["fields"]}


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None, post: Post = _urllib_post):
        self._key = api_key or os.environ.get("GEMINI_API_KEY")
        if not self._key:
            raise ProviderError("GEMINI_API_KEY is not set")
        self.model = model or os.environ.get("GEMINI_MODEL") or DEFAULT_MODEL
        self._post = post

    def _parts(self, request: ExtractionRequest) -> list[dict[str, Any]]:
        fields = ", ".join(request.fields)
        if request.mode == "ocr_text":
            text = "\n\n".join(f"--- page {p.number} ---\n{p.text or ''}" for p in request.pages)
            return [{"text": OCR_PROMPT.format(doc_type=request.doc_type, fields=fields)}, {"text": text}]
        parts: list[dict[str, Any]] = [{"text": PROMPT.format(doc_type=request.doc_type, fields=fields)}]
        for page in request.pages:
            if page.image_bytes is not None:
                parts.append({"inline_data": {"mime_type": page.media_type or "image/png",
                                              "data": base64.b64encode(page.image_bytes).decode("ascii")}})
            else:
                parts.append({"text": f"--- page {page.number} ---\n{page.text or ''}"})
        return parts

    def _scrub(self, message: str) -> str:
        return message.replace(self._key, "***")

    def extract(self, request: ExtractionRequest) -> list[ProviderField]:
        body = {"contents": [{"parts": self._parts(request)}],
                "generationConfig": {"temperature": 0, "responseMimeType": "application/json",
                                     "responseSchema": _schema(request.fields)}}
        url = f"{API_BASE}/{self.model}:generateContent"
        headers = {"Content-Type": "application/json", "x-goog-api-key": self._key}
        try:
            response = self._post(url, headers, body, TIMEOUT_SECONDS)
        except urllib.error.HTTPError as exc:
            raise ProviderError(f"Gemini HTTP {exc.code}: {self._scrub(exc.read().decode('utf-8', 'replace'))[:300]}")
        except Exception as exc:   # network, timeout, JSON decode: all route to human review
            raise ProviderError(self._scrub(f"Gemini request failed: {exc}")) from None
        return self._parse(response)

    def _parse(self, response: dict) -> list[ProviderField]:
        try:
            text = "".join(p.get("text", "") for p in response["candidates"][0]["content"]["parts"])
            items = json.loads(text)["fields"]
            return [ProviderField(name=i["name"], value=i["value"], confidence=float(i["confidence"]),
                                  page=i.get("page")) for i in items]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            reason = response.get("promptFeedback", {}).get("blockReason") if isinstance(response, dict) else None
            raise ProviderError(f"Gemini response unusable ({reason or type(exc).__name__})") from None
