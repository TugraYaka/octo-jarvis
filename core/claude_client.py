import base64

from core import assistant, config
from core.browser import browser_screenshot_live
from core.client import MissingKeyError, ProviderHTTPError, rest_get, rest_post
from core.search_mode import get_modes

_API_VERSION = "2023-06-01"


def _headers() -> dict:
    key = config.provider_api_key("claude")
    if not key:
        raise MissingKeyError("No Claude API key set.")
    return {"x-api-key": key, "anthropic-version": _API_VERSION, "content-type": "application/json"}


def _url(path: str) -> str:
    base_url = config.provider_base_url("claude")
    problem = config.base_url_problem(base_url or "")
    if problem:
        raise MissingKeyError(problem)
    return f"{base_url}/{path}"


def _tools() -> list:
    return [
        {"name": spec["name"], "description": spec["description"], "input_schema": spec["parameters"]}
        for spec in assistant.TOOLS
    ]


def _tool_result(block: dict, on_status=None) -> dict:
    name, args = block["name"], block.get("input") or {}
    assistant.search_status(name, args, on_status)
    if name == assistant.SCREENSHOT_TOOL:
        try:
            png = browser_screenshot_live()
        except Exception as e:
            assistant.log(f"[browser_screenshot_live] failed: {e}")
            content = f"Error taking screenshot: {e}"
        else:
            content = [{"type": "text", "text": assistant.SCREENSHOT_NOTE}, {
                "type": "image",
                "source": {"type": "base64", "media_type": "image/png", "data": base64.b64encode(png).decode()},
            }]
    else:
        content = assistant.wrap_untrusted(assistant.run_tool_call(name, args))
    return {"type": "tool_result", "tool_use_id": block["id"], "content": content}


# Models that take the dynamic-filtering web search tool; older ones get the basic variant.
_DYNAMIC_SEARCH_MODELS = (
    "claude-opus-5", "claude-sonnet-5", "claude-fable", "claude-mythos",
    "claude-opus-4-6", "claude-opus-4-7", "claude-opus-4-8", "claude-sonnet-4-6",
)
# Opus 5 and 5.5 manage their own thinking; /think does not apply to them.
_SELF_THINKING_MODELS = ("claude-opus-5",)
_no_effort_models: set[str] = set()


def thinking_supported(model: str) -> bool:
    return not model.startswith(_SELF_THINKING_MODELS)


def _native_search_tool(model: str) -> dict:
    kind = "web_search_20260209" if model.startswith(_DYNAMIC_SEARCH_MODELS) else "web_search_20250305"
    return {"type": kind, "name": "web_search", "max_uses": assistant.MAX_SEARCH_HOPS}


def _text(blocks: list) -> str:
    return "".join(b.get("text", "") for b in blocks if b.get("type") == "text")


def _report_native_searches(blocks: list, on_status=None) -> None:
    for block in blocks:
        if block.get("type") == "server_tool_use":
            query = (block.get("input") or {}).get("query") or ""
            assistant.log(f"[claude web_search] {query!r}")
            assistant.search_status("web_search", {"query": query}, on_status)


def ask_once(prompt: str, history: list, on_status=None) -> tuple[str, list]:
    native_on, duck_on = get_modes()
    error = assistant.search_mode_error("claude", native_on, duck_on)
    if error:
        return error, history

    model = config.provider_model("claude")
    high = assistant.get_thinking_level() == "high" or not thinking_supported(model)
    payload = {
        "model": model,
        "max_tokens": 16000 if high else 4000,
        "system": assistant.build_system_instruction(
            "claude", prompt, model, native_on, duck_on, on_status=on_status
        ),
        "messages": [
            {"role": turn["role"], "content": turn["text"]} for turn in history
        ] + [{"role": "user", "content": prompt}],
    }
    if thinking_supported(model) and model not in _no_effort_models:
        payload["output_config"] = {"effort": "high" if high else "low"}
    if native_on:
        payload["tools"] = [_native_search_tool(model)]
    elif duck_on:
        payload["tools"] = _tools()
    state = assistant.new_state()
    reply = ""

    for hop in range(assistant.MAX_SEARCH_HOPS + 1):
        response = _post(payload)
        blocks = response.get("content") or []
        _report_native_searches(blocks, on_status)
        reply += assistant.collect_text(_text(blocks), state)
        calls = [b for b in blocks if b.get("type") == "tool_use"]
        paused = response.get("stop_reason") == "pause_turn"
        if not calls and not paused:
            break
        payload["messages"].append({"role": "assistant", "content": blocks})
        if paused:
            continue
        if hop == assistant.MAX_SEARCH_HOPS:
            payload["messages"].append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": b["id"], "content": assistant.TOOL_BUDGET_ERROR, "is_error": True}
                for b in calls
            ]})
            payload["tool_choice"] = {"type": "none"}
            reply += assistant.collect_text(_text(_post(payload).get("content") or []), state)
            break
        payload["messages"].append({"role": "user", "content": [_tool_result(b, on_status) for b in calls]})

    assistant.finish_turn(state)
    if not state["emitted"]:
        return assistant.Notice("[yellow]I couldn't generate a response, please try again.[/yellow]"), history
    return reply, assistant.append_exchange(history, prompt, reply)


def _post(payload: dict) -> dict:
    try:
        return rest_post("Claude", _url("messages"), _headers(), payload, read_timeout=300)
    except ProviderHTTPError as e:
        # Older models (e.g. Haiku 4.5, Sonnet 4.5) reject the effort setting;
        # remember that and answer without it.
        if e.status != 400 or "output_config" not in payload or "effort" not in e.body.lower():
            raise
        assistant.log(f"[claude] effort rejected by {payload['model']}, retrying without it")
        _no_effort_models.add(payload["model"])
        payload.pop("output_config")
        return rest_post("Claude", _url("messages"), _headers(), payload, read_timeout=300)


def validate_key() -> None:
    rest_get("Claude", _url("models?limit=1"), _headers())

