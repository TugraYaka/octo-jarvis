import httpx
from rich.markup import escape
from google.genai import errors, types

from core import assistant, config
from core.assistant import get_thinking_level
from core.browser import browser_screenshot_live
from core.client import get_client
from core.search_mode import get_modes

TRANSIENT_ERRORS = (errors.ServerError, httpx.ReadTimeout, httpx.ConnectError)


def _model() -> str:
    return config.provider_model("gemini")


def _declaration(spec: dict) -> types.FunctionDeclaration:
    params = spec["parameters"]
    return types.FunctionDeclaration(
        name=spec["name"],
        description=spec["description"],
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                key: types.Schema(type=types.Type.STRING, description=value["description"])
                for key, value in params["properties"].items()
            },
            required=params["required"] or None,
        ),
    )


_WEB_SEARCH_TOOL = types.Tool(function_declarations=[_declaration(spec) for spec in assistant.TOOLS])


def _thinking_config() -> types.ThinkingConfig:
    if get_thinking_level() == "low":
        return types.ThinkingConfig(thinking_level="minimal")
    return types.ThinkingConfig(thinking_level="high")


def _build_config(
    prompt: str, google_on: bool, duck_on: bool, on_status=None
) -> types.GenerateContentConfig:
    kwargs = dict(
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        thinking_config=_thinking_config(),
        max_output_tokens=4000 if get_thinking_level() == "low" else 16000,
    )
    if google_on:
        kwargs["tools"] = [types.Tool(google_search=types.GoogleSearch())]
    elif duck_on:
        kwargs["tools"] = [_WEB_SEARCH_TOOL]
    kwargs["system_instruction"] = assistant.build_system_instruction(
        "gemini", prompt, _model(), google_on, duck_on, on_status=on_status
    )
    return types.GenerateContentConfig(**kwargs)


def _to_contents(history: list) -> list:
    return [
        types.Content(
            role="user" if turn["role"] == "user" else "model",
            parts=[types.Part(text=turn["text"])],
        )
        for turn in history
    ]


def _run_turn(contents: list, config, state: dict, on_status=None) -> str:
    """Run one model turn and return its full display text, collecting calls/facts into state."""
    response = get_client().models.generate_content(
        model=_model(), contents=contents, config=config
    )
    text = ""
    for candidate in response.candidates or []:
        metadata = candidate.grounding_metadata
        if metadata and metadata.web_search_queries:
            state["queries"] = list(metadata.web_search_queries)
            if on_status:
                on_status(f"Searching about [bold]{escape(state['queries'][0])}[/bold]")
        parts = candidate.content.parts if candidate.content else None
        for part in parts or []:
            if part.function_call:
                state["calls"].append(part)
            if part.text:
                text += part.text
    return assistant.collect_text(text, state)


def _run_screenshot_call(call) -> list:
    """Screenshot returns image bytes, not text - build its response parts separately."""
    assistant.mark_web()
    try:
        png_bytes = browser_screenshot_live()
    except Exception as e:
        assistant.log(f"[browser_screenshot_live] failed: {e}")
        return [types.Part.from_function_response(
            name=call.name, response={"results": f"Error taking screenshot: {e}"}
        )]
    return [
        types.Part.from_function_response(
            name=call.name, response={"results": assistant.SCREENSHOT_NOTE}
        ),
        types.Part.from_bytes(data=png_bytes, mime_type="image/png"),
    ]


def _run_web_search(call_parts: list, contents: list, on_status=None) -> None:
    """Answer every pending function call from this turn, not just the first."""
    contents.append(types.Content(role="model", parts=list(call_parts)))
    response_parts = []
    for call_part in call_parts:
        call = call_part.function_call
        assistant.search_status(call.name, call.args or {}, on_status)
        if call.name == assistant.SCREENSHOT_TOOL:
            response_parts.extend(_run_screenshot_call(call))
            continue
        body = assistant.run_tool_call(call.name, call.args)
        response_parts.append(types.Part.from_function_response(
            name=call.name, response={"results": assistant.wrap_untrusted(body)}
        ))
    contents.append(types.Content(role="user", parts=response_parts))


def _deny_further_search(call_parts: list, contents: list) -> None:
    """Reject pending calls with a real function_response so the model must answer in text.

    Simply omitting `tools` from the next request does not reliably stop Gemini from
    still emitting a function_call once a conversation has used tool calling — so the
    denial has to travel as actual function_response content, not as a removed tool.
    """
    contents.append(types.Content(role="model", parts=list(call_parts)))
    response_parts = [
        types.Part.from_function_response(
            name=call_part.function_call.name,
            response={"error": assistant.TOOL_BUDGET_ERROR},
        )
        for call_part in call_parts
    ]
    contents.append(types.Content(role="user", parts=response_parts))


def ask_once(prompt: str, history: list, on_status=None) -> tuple[str, list]:
    """Return (display-ready reply, updated history), stripping <remember> tags."""
    google_on, duck_on = get_modes()
    error = assistant.search_mode_error("gemini", google_on, duck_on)
    if error:
        return error, history

    config = _build_config(prompt, google_on, duck_on, on_status=on_status)
    contents = _to_contents(history) + [types.Content(role="user", parts=[types.Part(text=prompt)])]
    state = assistant.new_state()
    reply = ""

    for hop in range(assistant.MAX_SEARCH_HOPS + 1):
        state["calls"] = []
        reply += _run_turn(contents, config, state, on_status=on_status)
        if not state["calls"]:
            break
        if hop == assistant.MAX_SEARCH_HOPS:
            _deny_further_search(state["calls"], contents)
            state["calls"] = []
            reply += _run_turn(contents, config, state, on_status=on_status)
            break
        _run_web_search(state["calls"], contents, on_status=on_status)

    assistant.finish_turn(state)
    if not state["emitted"]:
        return assistant.Notice("[yellow]I couldn't generate a response, please try again.[/yellow]"), history
    return reply, assistant.append_exchange(history, prompt, reply)


def validate_key() -> None:
    next(iter(get_client().models.list()), None)

