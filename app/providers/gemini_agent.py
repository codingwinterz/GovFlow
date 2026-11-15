"""Gemini as the agent LLM, via generateContent function calling (standard library only).

The model's own content turns are echoed back verbatim, so thought signatures survive
(Gemini 3 rejects a function-calling turn whose signature is missing). Tool results are sent
as functionResponse parts in a user turn, grouped and in call order.
VERIFY: wire format checked against the Gemini docs (generate-content/gemini-3, thought-signatures);
not yet exercised against the live API because the free-tier quota was exhausted.
"""

import time
from typing import Any, Callable, Optional

from app.agent import AgentReply, Message, ToolCall, ToolSpec
from app.extraction import ProviderError
from app.providers.gemini import GeminiClient, Post, _urllib_post

LOCAL_ID_PREFIX = "local-"   # ids we invent when the model gives none; never sent back to Gemini


def _declaration(spec: ToolSpec) -> dict[str, Any]:
    decl: dict[str, Any] = {"name": spec.name, "description": spec.description}
    if spec.parameters:
        decl["parameters"] = spec.parameters
    return decl


def _function_response(m: Message) -> dict[str, Any]:
    response: dict[str, Any] = {"name": m.name, "response": m.content or {}}
    if m.tool_call_id and not m.tool_call_id.startswith(LOCAL_ID_PREFIX):
        response["id"] = m.tool_call_id
    return {"functionResponse": response}


def _assistant_content(m: Message) -> dict[str, Any]:
    if m.raw:
        return m.raw   # verbatim: keeps thoughtSignature parts exactly where Gemini put them
    parts: list[dict[str, Any]] = [{"text": m.text}] if m.text else []
    parts += [{"functionCall": {"name": c.name, "args": c.args}} for c in m.tool_calls]
    return {"role": "model", "parts": parts}


def to_contents(messages: list[Message]) -> list[dict[str, Any]]:
    contents: list[dict[str, Any]] = []
    for m in messages:
        if m.role == "user":
            contents.append({"role": "user", "parts": [{"text": m.text}]})
        elif m.role == "assistant":
            contents.append(_assistant_content(m))
        elif contents and contents[-1].get("_tool_turn"):
            contents[-1]["parts"].append(_function_response(m))
        else:
            contents.append({"role": "user", "parts": [_function_response(m)], "_tool_turn": True})
    return [{k: v for k, v in c.items() if k != "_tool_turn"} for c in contents]


def from_response(response: dict) -> AgentReply:
    try:
        content = response["candidates"][0]["content"]
        parts = content["parts"]
    except (KeyError, IndexError, TypeError):
        reason = response.get("promptFeedback", {}).get("blockReason") if isinstance(response, dict) else None
        raise ProviderError(f"Gemini response unusable ({reason or 'no content'})", kind="bad_response") from None
    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    calls = [ToolCall(id=p["functionCall"].get("id") or f"{LOCAL_ID_PREFIX}{i}", name=p["functionCall"]["name"],
                      args=p["functionCall"].get("args") or {})
             for i, p in enumerate(parts) if "functionCall" in p]
    return AgentReply(text=text, tool_calls=calls, raw=content)


class GeminiAgentLLM:
    name = "gemini"

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None, post: Post = _urllib_post,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic,
                 pace_seconds: Optional[float] = None):
        self.client = GeminiClient(api_key, model, post, sleep, clock, pace_seconds)
        self.model = self.client.model

    def complete(self, system: str, messages: list[Message], tools: list[ToolSpec]) -> AgentReply:
        # VERIFY: Gemini 3 guidance is to keep the default temperature for agentic use, so none is set here.
        body = {"systemInstruction": {"parts": [{"text": system}]},
                "contents": to_contents(messages),
                "tools": [{"functionDeclarations": [_declaration(t) for t in tools]}]}
        return from_response(self.client.generate(body))
