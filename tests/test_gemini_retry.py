"""Retry, backoff and pacing for GeminiProvider, driven by a fake transport and a fake clock."""

import io
import json
import urllib.error

import pytest

from app.extraction import ExtractionRequest, Page, ProviderError
from app.providers.gemini import GeminiProvider, TIMEOUT_SECONDS

KEY = "test-key-not-real-0123456789"


def _request():
    return ExtractionRequest(document_id="D-1", doc_type="survey_sheet", fields=["survey_number"],
                             pages=[Page(number=1, image_bytes=b"png", media_type="image/png")], mode="document")


def _ok():
    fields = [{"name": "survey_number", "value": "154/2", "confidence": 0.95, "page": 1}]
    return {"candidates": [{"content": {"parts": [{"text": json.dumps({"fields": fields})}]}}]}


def _http(code, body=None, headers=None):
    payload = json.dumps(body or {"error": {"code": code}}).encode()
    return urllib.error.HTTPError("https://x", code, "err", headers or {}, io.BytesIO(payload))


def _retry_info(delay):
    return {"error": {"code": 429, "details": [
        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": delay}]}}


class FakeTime:
    def __init__(self):
        self.now, self.sleeps = 1000.0, []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class Script:
    """Fake transport: each call pops the next outcome (an exception to raise, or a response)."""

    def __init__(self, *outcomes):
        self.outcomes, self.timeouts = list(outcomes), []

    def __call__(self, url, headers, body, timeout):
        self.timeouts.append(timeout)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _provider(post, pace=0.0, t=None):
    t = t or FakeTime()
    return GeminiProvider(api_key=KEY, post=post, sleep=t.sleep, clock=t.clock, pace_seconds=pace), t


def test_per_call_timeout_is_30_seconds():
    post = Script(_ok())
    _provider(post)[0].extract(_request())
    assert TIMEOUT_SECONDS == 30 and post.timeouts == [30]


@pytest.mark.parametrize("failure", [
    _http(429), _http(503), TimeoutError("The read operation timed out"),
    urllib.error.URLError(TimeoutError("timed out")),
])
def test_retryable_failure_then_success(failure):
    post = Script(failure, _ok())
    provider, t = _provider(post)
    assert [f.value for f in provider.extract(_request())] == ["154/2"]
    assert len(post.timeouts) == 2 and t.sleeps == [2.0]


def test_backoff_doubles_between_attempts():
    post = Script(_http(503), _http(503), _http(503), _ok())
    provider, t = _provider(post)
    provider.extract(_request())
    assert t.sleeps == [2.0, 4.0, 8.0]


def test_gives_up_after_four_attempts_with_error_class():
    post = Script(*[_http(503)] * 5)
    provider, _ = _provider(post)
    with pytest.raises(ProviderError) as exc:
        provider.extract(_request())
    assert len(post.timeouts) == 4
    assert exc.value.kind == "unavailable" and exc.value.retryable


@pytest.mark.parametrize("failure, kind", [
    (_http(429), "rate_limited"), (TimeoutError("timed out"), "timeout"),
])
def test_exhausted_errors_are_classified(failure, kind):
    post = Script(*[failure] * 4)
    with pytest.raises(ProviderError) as exc:
        _provider(post)[0].extract(_request())
    assert exc.value.kind == kind


def test_retry_after_header_is_honoured():
    post = Script(_http(429, headers={"Retry-After": "7"}), _ok())
    provider, t = _provider(post)
    provider.extract(_request())
    assert t.sleeps == [7.0]


def test_retry_info_delay_in_body_is_honoured():
    post = Script(_http(429, body=_retry_info("13s")), _ok())
    provider, t = _provider(post)
    provider.extract(_request())
    assert t.sleeps == [13.0]


def test_hint_shorter_than_backoff_does_not_shorten_the_wait():
    post = Script(_http(503), _http(429, headers={"Retry-After": "1"}), _ok())
    provider, t = _provider(post)
    provider.extract(_request())
    assert t.sleeps == [2.0, 4.0]


def test_hint_beyond_the_cap_gives_up_instead_of_sleeping_for_hours():
    post = Script(_http(429, body=_retry_info("3600s")), _ok())
    provider, t = _provider(post)
    with pytest.raises(ProviderError) as exc:
        provider.extract(_request())
    assert exc.value.kind == "rate_limited" and t.sleeps == [] and len(post.timeouts) == 1


@pytest.mark.parametrize("code, kind", [(400, "http_error"), (403, "http_error"), (404, "http_error")])
def test_non_retryable_http_errors_fail_at_once(code, kind):
    post = Script(_http(code), _ok())
    with pytest.raises(ProviderError) as exc:
        _provider(post)[0].extract(_request())
    assert len(post.timeouts) == 1 and exc.value.kind == kind and not exc.value.retryable


def test_unusable_response_is_not_retried():
    post = Script({"candidates": []}, _ok())
    with pytest.raises(ProviderError) as exc:
        _provider(post)[0].extract(_request())
    assert len(post.timeouts) == 1 and exc.value.kind == "bad_response"


def test_key_never_appears_in_exhausted_error():
    post = Script(*[_http(503, body={"error": {"message": f"bad {KEY}"}})] * 4)
    with pytest.raises(ProviderError) as exc:
        _provider(post)[0].extract(_request())
    assert KEY not in str(exc.value) and KEY not in repr(exc.value)


# --- pacing ---------------------------------------------------------------------

def test_pace_spaces_consecutive_calls():
    post = Script(_ok(), _ok())
    provider, t = _provider(post, pace=4.0)
    provider.extract(_request())
    t.now += 1.5                      # some work happened between calls
    provider.extract(_request())
    assert t.sleeps == [pytest.approx(2.5)]


def test_first_call_is_not_delayed():
    provider, t = _provider(Script(_ok()), pace=4.0)
    provider.extract(_request())
    assert t.sleeps == []


def test_pace_defaults_to_4_seconds_and_reads_environment(monkeypatch):
    monkeypatch.delenv("GEMINI_PACE_SECONDS", raising=False)
    assert GeminiProvider(api_key=KEY).pace_seconds == 4.0
    monkeypatch.setenv("GEMINI_PACE_SECONDS", "0.5")
    assert GeminiProvider(api_key=KEY).pace_seconds == 0.5


@pytest.mark.parametrize("bad", ["fast", "-1"])
def test_invalid_pace_is_a_config_error(monkeypatch, bad):
    monkeypatch.setenv("GEMINI_PACE_SECONDS", bad)
    with pytest.raises(ProviderError) as exc:
        GeminiProvider(api_key=KEY)
    assert exc.value.kind == "not_configured"


# --- structured error details (quota id / metric / retry delay survive truncation) -------

def _quota_429(key_in_message=""):
    long_text = ("You exceeded your current quota, please check your plan and billing details. "
                 + "For more information on this error, head to the rate-limit docs. " * 6 + key_in_message
                 + "\n* Quota exceeded for metric: generate_content_free_tier_requests, limit: 20")
    return {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": long_text, "details": [
        {"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [{
            "quotaMetric": "generativelanguage.googleapis.com/generate_content_free_tier_requests",
            "quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier",
            "quotaDimensions": {"model": "gemini-3.8-flash", "location": "global"}, "quotaValue": "20"}]},
        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "41s"}]}}


def _exhaust(body):
    post = Script(*[_http(429, body=body) for _ in range(4)])   # fresh objects: an error body can be read once
    with pytest.raises(ProviderError) as exc:
        _provider(post)[0].extract(_request())
    return exc.value


def test_quota_details_are_extracted_before_truncation():
    details = _exhaust(_quota_429()).details
    assert details["http_status"] == 429 and details["status"] == "RESOURCE_EXHAUSTED"
    assert details["quota_id"] == "GenerateRequestsPerDayPerProjectPerModel-FreeTier"
    assert details["quota_metric"] == "generativelanguage.googleapis.com/generate_content_free_tier_requests"
    assert details["quota_value"] == "20" and details["retry_delay_seconds"] == 41.0
    assert details["message"].startswith("You exceeded your current quota")
    assert len(details["message"]) <= 200


def test_error_text_names_the_quota_even_when_the_message_is_long():
    text = str(_exhaust(_quota_429()))
    assert "GenerateRequestsPerDayPerProjectPerModel-FreeTier" in text and "retry in 41s" in text
    assert not text.rstrip().endswith("{")


def test_key_never_appears_in_error_details():
    exc = _exhaust(_quota_429(key_in_message=f" key={KEY} "))
    assert KEY not in json.dumps(exc.details) and KEY not in str(exc)


def test_non_json_error_body_still_gives_a_short_message():
    post = Script(urllib.error.HTTPError("https://x", 503, "err", {}, io.BytesIO(b"<html>Service down</html>")),
                  *[_http(503)] * 3)
    with pytest.raises(ProviderError) as exc:
        _provider(post)[0].extract(_request())
    assert exc.value.details["http_status"] == 503
