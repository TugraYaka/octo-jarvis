import re

from core.memory import full_memory, queue_remember, search_memory

INSTRUCTION = (
    "Memory: you have a long-term memory of facts about the user, built up across past "
    "conversations. The facts relevant to the current message, if any, are shown below "
    "under 'Relevant memory' as '[id=N] fact' — only what matched this topic is shown, "
    "not your whole memory. Use it to personalize your answer. When the user shares a "
    "new durable fact about themselves (name, preference, recurring habit, important "
    "context) that isn't already shown in memory, save it by including a tag anywhere "
    "in your reply: <remember>short fact</remember>. If the new fact instead replaces, "
    "updates, or contradicts one of the facts listed under 'Relevant memory' (e.g. the "
    "user moved, changed jobs, or reversed a preference), save it as "
    "<remember id=\"N\">short fact</remember> using that fact's id, so the old one is "
    "overwritten instead of both being kept. Only save facts worth remembering "
    "long-term, never one-off or trivial details. The tag is stripped before the user "
    "sees your reply."
)

REMEMBER_RE = re.compile(r'<remember(?:\s+id=["\'](\d+)["\'])?\s*>(.*?)</remember>', re.DOTALL)
# Broad "recall everything" style requests (list/count/search across all facts)
# aren't well served by topic-similarity search, which only surfaces facts
# close to the query's own embedding — a generic "what do you remember about
# me" query doesn't sit close to any specific fact. Detect this intent and
# hand the model the full memory list instead.
_RECALL_INTENT_RE = re.compile(
    r"\bremember\b|\bmemory\b|\blist\b|\bsort\b|how many|all of it|"
    r"list all|everything you know|what do you know about me|what do you know",
    re.IGNORECASE,
)


def context(prompt: str, on_status=None) -> str:
    if _RECALL_INTENT_RE.search(prompt):
        relevant, label = full_memory(), "Full memory (not filtered by topic)"
    else:
        relevant, label = search_memory(prompt), "Relevant memory"
    if not relevant:
        return ""
    if on_status:
        on_status("Checking memory...")
    facts = "\n".join(f"- [id={fact['id']}] {fact['text']}" for fact in relevant)
    return f"\n\n{label}:\n{facts}"


def extract(text: str) -> tuple[str, list[tuple[int | None, str]]]:
    facts = [(int(id_str) if id_str else None, fact) for id_str, fact in REMEMBER_RE.findall(text)]
    return REMEMBER_RE.sub("", text), facts


MAX_FACT_CHARS = 300
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f\u200b-\u200f\u2028-\u202e\u2060-\u2064\ufeff]")


def all_facts() -> list[dict]:
    try:
        return full_memory(limit=10_000)
    except Exception:
        return []


def clean_fact(fact: str) -> str:
    fact = _CONTROL_RE.sub(" ", fact)
    fact = re.sub(r"<[^>]{0,200}>", "", fact)
    return " ".join(fact.split())[:MAX_FACT_CHARS]


def commit(facts: list[tuple[int | None, str]], from_web: bool = False, confirm=None) -> None:
    """Save facts; facts from a turn that read web content need the user's approval."""
    for replace_id, fact in facts:
        fact = clean_fact(fact)
        if not fact:
            continue
        if from_web:
            question = f"This reply used web or pasted content. Save to long-term memory: \"{fact}\"?"
            try:
                allowed = bool(confirm and confirm(question))
            except Exception:
                allowed = False
            if not allowed:
                continue
        queue_remember(fact, replace_id)
