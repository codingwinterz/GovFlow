import base64
import json

import pytest

from app.extraction import ExtractionRequest, Page, ProviderError
from app.providers.gemini import DEFAULT_MODEL, GeminiProvider

KEY = "test-key-not-real"


def _request(mode="document", pages=None):
    pages = pages or [Page(number=1, image_bytes=b"\x89PNGfake", media_type="image/png")]
    return ExtractionRequest(document_id="D-1", doc_type="ownership_record", fields=["name", "area"],
                             pages=pages, mode=mode)


def _reply(fields):
    return {"candidates": [{"content": {"parts": [{"text": json.dumps({"fields": fields})}]}}]}


class Recorder:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.calls = response, error, []

    def __call__(self, url, headers, body, timeout):
        self.calls.append((url, headers, body))
        if self.error:
            raise self.error
        return self.response


def test_missing_key_raises_provider_error(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(ProviderError, match="GEMINI_API_KEY"):
        GeminiProvider()


def test_reads_key_from_environment_and_sends_it_only_in_header(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", KEY)
    post = Recorder(_reply([]))
    GeminiProvider(post=post).extract(_request())
    url, headers, _ = post.calls[0]
    assert headers["x-goog-api-key"] == KEY
    assert KEY not in url
    assert url.endswith(f"/models/{DEFAULT_MODEL}:generateContent")


def test_model_can_be_overridden_by_environment(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", KEY)
    monkeypatch.setenv("GEMINI_MODEL", "some-other-model")
    post = Recorder(_reply([]))
    GeminiProvider(post=post).extract(_request())
    assert "/models/some-other-model:generateContent" in post.calls[0][0]


def test_sends_image_inline_with_schema_restricted_to_requested_fields():
    post = Recorder(_reply([]))
    GeminiProvider(api_key=KEY, post=post).extract(_request())
    body = post.calls[0][2]
    parts = body["contents"][0]["parts"]
    inline = next(p["inline_data"] for p in parts if "inline_data" in p)
    assert inline == {"mime_type": "image/png", "data": base64.b64encode(b"\x89PNGfake").decode()}
    cfg = body["generationConfig"]
    assert cfg["responseMimeType"] == "application/json" and cfg["temperature"] == 0
    item = cfg["responseSchema"]["properties"]["fields"]["items"]
    assert item["properties"]["name"]["enum"] == ["name", "area"]


def test_prompt_forbids_guessing_and_asks_for_iso_dates():
    post = Recorder(_reply([]))
    GeminiProvider(api_key=KEY, post=post).extract(_request())
    prompt = " ".join(p.get("text", "") for p in post.calls[0][2]["contents"][0]["parts"])
    assert "YYYY-MM-DD" in prompt and "never guess" in prompt.lower()


def test_ocr_text_mode_sends_text_not_images():
    post = Recorder(_reply([]))
    GeminiProvider(api_key=KEY, post=post).extract(_request(mode="ocr_text", pages=[Page(number=1, text="Area: 900")]))
    parts = post.calls[0][2]["contents"][0]["parts"]
    assert not any("inline_data" in p for p in parts)
    assert any("Area: 900" in p.get("text", "") for p in parts)


def test_parses_fields_from_response():
    post = Recorder(_reply([{"name": "name", "value": "Lata Shirodkar", "confidence": 0.91, "page": 1},
                            {"name": "area", "value": "900", "confidence": 0.88, "page": 1}]))
    fields = GeminiProvider(api_key=KEY, post=post).extract(_request())
    assert [(f.name, f.value, f.confidence, f.page) for f in fields] == [
        ("name", "Lata Shirodkar", 0.91, 1), ("area", "900", 0.88, 1)]


@pytest.mark.parametrize("response", [
    {},                                                                   # no candidates (e.g. blocked)
    {"candidates": [{"content": {"parts": [{"text": "not json"}]}}]},
    {"candidates": [{"content": {"parts": [{"text": "{\"other\": 1}"}]}}]},
])
def test_malformed_response_raises_provider_error(response):
    with pytest.raises(ProviderError):
        GeminiProvider(api_key=KEY, post=Recorder(response)).extract(_request())


def test_transport_error_raises_provider_error_without_leaking_key():
    post = Recorder(error=OSError(f"connection failed for key {KEY}"))
    with pytest.raises(ProviderError) as exc:
        GeminiProvider(api_key=KEY, post=post).extract(_request())
    assert KEY not in str(exc.value)


def test_default_model_is_the_one_verified_live(monkeypatch):
    """gemini-3.5-flash-lite is the only model evaluated live (docs/EVAL_RESULTS.md); it must be the default."""
    from app.providers.gemini_agent import GeminiAgentLLM
    monkeypatch.setenv("GEMINI_API_KEY", KEY)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    post = Recorder(_reply([]))
    GeminiProvider(post=post).extract(_request())
    assert post.calls[0][0].endswith("/models/gemini-3.5-flash-lite:generateContent")
    assert GeminiAgentLLM(post=post).model == "gemini-3.5-flash-lite"


def test_agent_model_can_be_overridden_by_environment(monkeypatch):
    from app.providers.gemini_agent import GeminiAgentLLM
    monkeypatch.setenv("GEMINI_API_KEY", KEY)
    monkeypatch.setenv("GEMINI_MODEL", "some-other-model")
    assert GeminiAgentLLM(post=Recorder(_reply([]))).model == "some-other-model"
