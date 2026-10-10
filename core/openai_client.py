import base64
import json

from core import assistant, config
from core.browser import browser_screenshot_live
from core.client import MissingKeyError, ProviderHTTPError, rest_get, rest_post
from core.search_mode import get_modes

_OFFICIAL_URL = "https://api.openai.com/v1"


def _settings(provider: str) -> tuple[str, str, str]:
    base_url = config.provider_base_url(provider)
    model = config.provider_model(provider)
    if not base_url or not model:
        raise MissingKeyError(f"{provider} provider needs a base URL and a model.")
    problem = config.base_url_problem(base_url)
    if problem:
        raise MissingKeyError(problem)
    return base_url, model, config.PROVIDERS[provider]["label"]


def _headers(provider: str) -> dict:
    key = config.provider_api_key(provider)
    if not key and provider == "openai":
        raise MissingKeyError("No OpenAI API key set.")
    headers = {"content-type": "application/json"}
    if key:
        headers["authorization"] = f"Bearer {key}"
    return headers


def _tools() -> list:
    return [{"type": "function", "function": spec} for spec in assistant.TOOLS]


def _official(base_url: str) -> bool:
    return base_url == _OFFICIAL_URL


def _post(provider: str, base_url: str, payload: dict, path: str = "chat/completions") -> dict:
    url = f"{base_url}/{path}"
    while True:
        try:
            return rest_post(provider, url, _headers(provider), payload, 300)
        except ProviderHTTPError as e:
            if e.status != 400:
                raise
            # Non-reasoning models reject a reasoning effort, and many local or
            # third-party models reject function calling; retry without them
            # instead of failing the whole message.
            reasoning_key = next((k for k in ("reasoning_effort", "reasoning") if k in payload), None)
            if reasoning_key and "reasoning" in e.body.lower():
                dropped = (reasoning_key,)
            elif "tools" in payload and not _official(base_url):
                dropped = ("tools", "tool_choice")
            else:
                raise
            assistant.log(f"[{provider}] {dropped[0]} rejected, retrying without it: {e}")
            for key in dropped:
                payload.pop(key, None)


def _tool_messages(provider: str, base_url: str, calls: list, on_status=None) -> list:
    messages, images = [], []
    for call in calls:
        name = call["function"]["name"]
        try:
            args = json.loads(call["function"].get("arguments") or "{}")
        except json.JSONDecodeError:
            args = {}
        assistant.search_status(name, args, on_status)
        if name == assistant.SCREENSHOT_TOOL:
            content = "Screenshots are not supported with this model."
            if _official(base_url):
                try:
                    images.append(base64.b64encode(browser_screenshot_live()).decode())
                    content = "Screenshot attached in the next message."
                except Exception as e:
                    assistant.log(f"[browser_screenshot_live] failed: {e}")
                    content = f"Error taking screenshot: {e}"
        else:
            content = assistant.wrap_untrusted(assistant.run_tool_call(name, args))
        messages.append({"role": "tool", "tool_call_id": call["id"], "content": content})
    for data in images:
        messages.append({"role": "user", "content": [
            {"type": "text", "text": assistant.SCREENSHOT_NOTE},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{data}"}},
        ]})
    return messages


def _message(response: dict) -> dict:
    choices = response.get("choices") or [{}]
    return choices[0].get("message") or {}


def _effort() -> str:
    return "high" if assistant.get_thinking_level() == "high" else "low"


def _ask_native_search(provider: str, base_url: str, model: str, system: str, history: list,
                       prompt: str, budget: int, on_status=None) -> str:
    """ChatGPT's own web search only exists on the Responses API."""
    response = _post(provider, base_url, {
        "model": model,
        "instructions": system,
        "input": [
            {"role": turn["role"], "content": turn["text"]} for turn in history
        ] + [{"role": "user", "content": prompt}],
        "tools": [{"type": "web_search"}],
        "reasoning": {"effort": _effort()},
        "max_output_tokens": budget,
    }, path="responses")
    text = ""
    for item in response.get("output") or []:
        if item.get("type") == "web_search_call":
            query = (item.get("action") or {}).get("query") or ""
            assistant.log(f"[openai web_search] {query!r}")
            assistant.search_status("web_search", {"query": query}, on_status)
        if item.get("type") == "message":
            text += "".join(c.get("text", "") for c in item.get("content") or [] if c.get("type") == "output_text")
    return text


def ask_once(prompt: str, history: list, on_status=None, provider: str = "openai") -> tuple[str, list]:
    native_on, duck_on = get_modes()
    error = assistant.search_mode_error(provider, native_on, duck_on)
    if error:
        return error, history

    base_url, model, _ = _settings(provider)
    official = _official(base_url)
    system = assistant.build_system_instruction(provider, prompt, model, native_on, duck_on, on_status=on_status)
    budget = 16000 if assistant.get_thinking_level() == "high" else 4000

    if native_on and official:
        state = assistant.new_state()
        text = _ask_native_search(provider, base_url, model, system, history, prompt, budget, on_status)
        reply = assistant.collect_text(text, state)
        assistant.finish_turn(state)
        if not state["emitted"]:
            return assistant.Notice("[yellow]I couldn't generate a response, please try again.[/yellow]"), history
        return reply, assistant.append_exchange(history, prompt, reply)

    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system}] + [
            {"role": turn["role"], "content": turn["text"]} for turn in history
        ] + [{"role": "user", "content": prompt}],
        "max_completion_tokens" if official else "max_tokens": budget,
    }
    if official:
        payload["reasoning_effort"] = _effort()
    if duck_on:
        payload["tools"] = _tools()
    state = assistant.new_state()
    reply = ""

    for hop in range(assistant.MAX_SEARCH_HOPS + 1):
        message = _message(_post(provider, base_url, payload))
        reply += assistant.collect_text(message.get("content") or "", state)
        calls = message.get("tool_calls") or []
        if not calls or "tools" not in payload:
            break
        payload["messages"].append({"role": "assistant", "content": message.get("content"), "tool_calls": calls})
        if hop == assistant.MAX_SEARCH_HOPS:
            payload["messages"] += [
                {"role": "tool", "tool_call_id": call["id"], "content": assistant.TOOL_BUDGET_ERROR}
                for call in calls
            ]
            if _official(base_url):
                payload["tool_choice"] = "none"
            message = _message(_post(provider, base_url, payload))
            reply += assistant.collect_text(message.get("content") or "", state)
            break
        payload["messages"] += _tool_messages(provider, base_url, calls, on_status)

    assistant.finish_turn(state)
    if not state["emitted"]:
        return assistant.Notice("[yellow]I couldn't generate a response, please try again.[/yellow]"), history
    return reply, assistant.append_exchange(history, prompt, reply)


def validate_key(provider: str = "openai") -> None:
    base_url, _, _ = _settings(provider)
    rest_get(provider, f"{base_url}/models", _headers(provider))


def list_model_ids(provider: str) -> list[str]:
    base_url = config.provider_base_url(provider)
    if not base_url:
        return []
    data = rest_get(provider, f"{base_url}/models", _headers(provider))
    return [m["id"] for m in data.get("data") or [] if isinstance(m, dict) and m.get("id")]
