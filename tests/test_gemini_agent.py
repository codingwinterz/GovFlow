"""GeminiAgentLLM request/response mapping, with a fake transport (no network)."""

import io
import json
import urllib.error

import pytest

from app.agent import AGENT_TOOL_NAMES, SYSTEM_PROMPT, TOOL_SPECS, Message, ToolCall
from app.extraction import ProviderError
from app.providers.gemini_agent import GeminiAgentLLM

KEY = "test-key-not-real-0123456789"


class Recorder:
    def __init__(self, *responses):
        self.responses, self.bodies, self.headers = list(responses), [], []

    def __call__(self, url, headers, body, timeout):
        self.bodies.append(body)
        self.headers.append(headers)
        r = self.responses.pop(0)
        if isinstance(r, BaseException):
            raise r
        return r


def _content(*parts):
    return {"candidates": [{"content": {"role": "model", "parts": list(parts)}}]}


SIGNED_CALL = {"functionCall": {"name": "verify_documents", "args": {}}, "thoughtSignature": "sig-A"}


def _llm(post):
    return GeminiAgentLLM(api_key=KEY, post=post, sleep=lambda s: None, clock=lambda: 0.0, pace_seconds=0)


def test_request_has_system_instruction_and_function_declarations():
    post = Recorder(_content({"text": "ok"}))
    _llm(post).complete(SYSTEM_PROMPT, [Message(role="user", text="Process case LA-01")], TOOL_SPECS)
    body = post.bodies[0]
    assert body["systemInstruction"] == {"parts": [{"text": SYSTEM_PROMPT}]}
    decls = body["tools"][0]["functionDeclarations"]
    assert [d["name"] for d in decls] == list(AGENT_TOOL_NAMES)
    by_name = {d["name"]: d for d in decls}
    assert "parameters" not in by_name["verify_documents"]
    assert by_name["extract_document"]["parameters"]["required"] == ["document_id"]
    assert body["contents"] == [{"role": "user", "parts": [{"text": "Process case LA-01"}]}]


def test_key_only_in_header():
    post = Recorder(_content({"text": "ok"}))
    _llm(post).complete("s", [Message(role="user", text="x")], TOOL_SPECS)
    assert post.headers[0]["x-goog-api-key"] == KEY and KEY not in json.dumps(post.bodies[0])


def test_function_call_is_parsed_and_raw_content_kept():
    post = Recorder(_content(SIGNED_CALL))
    reply = _llm(post).complete("s", [Message(role="user", text="x")], TOOL_SPECS)
    assert [(c.name, c.args) for c in reply.tool_calls] == [("verify_documents", {})]
    assert reply.raw["parts"][0]["thoughtSignature"] == "sig-A"


def test_history_echoes_model_turn_verbatim_and_sends_results_as_user_function_responses():
    raw = {"role": "model", "parts": [SIGNED_CALL]}
    history = [Message(role="user", text="go"),
               Message(role="assistant", tool_calls=[ToolCall(id="local-0", name="verify_documents")], raw=raw),
               Message(role="tool", tool_call_id="local-0", name="verify_documents", content={"flags": []})]
    post = Recorder(_content({"text": "done"}))
    _llm(post).complete("s", history, TOOL_SPECS)
    contents = post.bodies[0]["contents"]
    assert contents[1] == raw                                      # thought signature preserved
    assert contents[2] == {"role": "user", "parts": [
        {"functionResponse": {"name": "verify_documents", "response": {"flags": []}}}]}


def test_parallel_results_are_grouped_in_one_turn_in_order():
    raw = {"role": "model", "parts": [
        {"functionCall": {"name": "check_eligibility", "args": {}}, "thoughtSignature": "s"},
        {"functionCall": {"name": "compute_compensation", "args": {}}}]}
    history = [Message(role="user", text="go"),
               Message(role="assistant", raw=raw, tool_calls=[ToolCall(id="local-0", name="check_eligibility"),
                                                              ToolCall(id="local-1", name="compute_compensation")]),
               Message(role="tool", tool_call_id="local-0", name="check_eligibility", content={"a": 1}),
               Message(role="tool", tool_call_id="local-1", name="compute_compensation", content={"b": 2})]
    post = Recorder(_content({"text": "done"}))
    _llm(post).complete("s", history, TOOL_SPECS)
    turn = post.bodies[0]["contents"][2]
    assert [p["functionResponse"]["name"] for p in turn["parts"]] == ["check_eligibility", "compute_compensation"]
    assert len(post.bodies[0]["contents"]) == 3


def test_call_ids_from_the_model_are_echoed_in_responses():
    post = Recorder(_content({"functionCall": {"id": "fc-9", "name": "get_case_status", "args": {}}}))
    reply = _llm(post).complete("s", [Message(role="user", text="x")], TOOL_SPECS)
    assert reply.tool_calls[0].id == "fc-9"
    history = [Message(role="user", text="x"), Message(role="assistant", raw=reply.raw, tool_calls=reply.tool_calls),
               Message(role="tool", tool_call_id="fc-9", name="get_case_status", content={"s": 1})]
    post2 = Recorder(_content({"text": "ok"}))
    _llm(post2).complete("s", history, TOOL_SPECS)
    assert post2.bodies[0]["contents"][2]["parts"][0]["functionResponse"]["id"] == "fc-9"


def test_text_reply():
    reply = _llm(Recorder(_content({"text": "Recommended "}, {"text": "eligible."}))).complete(
        "s", [Message(role="user", text="x")], TOOL_SPECS)
    assert reply.text == "Recommended eligible." and reply.tool_calls == []


@pytest.mark.parametrize("response", [{}, {"candidates": []}, {"candidates": [{"content": {}}]}])
def test_unusable_response_is_provider_error(response):
    with pytest.raises(ProviderError) as exc:
        _llm(Recorder(response)).complete("s", [Message(role="user", text="x")], TOOL_SPECS)
    assert exc.value.kind == "bad_response"


def test_http_errors_use_the_shared_retrying_client():
    err = urllib.error.HTTPError("u", 400, "bad", {}, io.BytesIO(b'{"error": {"message": "bad request"}}'))
    with pytest.raises(ProviderError) as exc:
        _llm(Recorder(err)).complete("s", [Message(role="user", text="x")], TOOL_SPECS)
    assert exc.value.kind == "http_error" and exc.value.details["message"] == "bad request"
