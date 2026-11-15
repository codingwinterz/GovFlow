"""Deterministic stand-ins for the LLM and OCR, so tests and evals need no network.

FakeProvider replays recorded responses; it does not read the document.
Any accuracy measured with it reflects the recorded responses, not a model.
"""

from app.extraction import ExtractionRequest, OcrResult, Page, ProviderError, ProviderField


class FakeProvider:
    name = "fake"

    def __init__(self, responses: dict[tuple[str, str], list[ProviderField]]):
        self.responses = responses
        self.requests: list[ExtractionRequest] = []

    def extract(self, request: ExtractionRequest) -> list[ProviderField]:
        self.requests.append(request)
        return list(self.responses.get((request.document_id, request.mode), []))


class FailingProvider:
    name = "failing"

    def __init__(self, kind: str = "unavailable", message: str = "provider unavailable"):
        self.kind, self.message = kind, message

    def extract(self, request: ExtractionRequest) -> list[ProviderField]:
        raise ProviderError(self.message, kind=self.kind,
                            retryable=self.kind in ("rate_limited", "unavailable", "timeout"))


class FakeOcr:
    name = "fake_ocr"

    def __init__(self, pages: dict[str, tuple[str, float]]):
        self.pages = pages
        self.calls = 0

    def ocr(self, document_id: str, page: Page) -> OcrResult:
        self.calls += 1
        text, confidence = self.pages.get(document_id, ("", 0.0))
        return OcrResult(text=text, confidence=confidence)


class ScriptedAgentLLM:
    """Agent LLM stand-in: returns scripted replies in order (an exception in the script is raised)."""
    name, model = "scripted", None

    def __init__(self, script: list):
        self.script = list(script)
        self.calls: list[dict] = []

    def complete(self, system, messages, tools):
        self.calls.append({"system": system, "messages": list(messages), "tools": list(tools)})
        from app.agent import AgentReply
        if not self.script:
            return AgentReply(text="(script ended)")
        step = self.script.pop(0)
        if isinstance(step, BaseException):
            raise step
        return step
