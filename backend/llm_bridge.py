import threading

_lock = threading.Lock()

_state = {
    "llm_complete": None,
    "llm_label": None,
    "tools": {},
}


def register(llm_complete=None, llm_label=None, tools=None) -> None:
    with _lock:
        if llm_complete is not None:
            _state["llm_complete"] = llm_complete
        if llm_label is not None:
            _state["llm_label"] = llm_label
        if tools is not None:
            _state["tools"] = dict(tools)


def available() -> bool:
    with _lock:
        return _state["llm_complete"] is not None


def label() -> str:
    with _lock:
        fn = _state["llm_label"]
    if fn is None:
        return "non configurato"
    try:
        return str(fn())
    except Exception:
        return "non disponibile"


def complete(system_prompt: str, user_message: str, max_tokens: int = 1200) -> str:
    with _lock:
        fn = _state["llm_complete"]
    if fn is None:
        raise RuntimeError("Nessun motore linguistico registrato.")
    return fn(system_prompt, user_message, max_tokens)


def tool_names() -> list:
    with _lock:
        return sorted(_state["tools"].keys())


def has_tool(name: str) -> bool:
    with _lock:
        return name in _state["tools"]


def call_tool(name: str, payload: dict, user: dict):
    with _lock:
        fn = _state["tools"].get(name)
    if fn is None:
        raise ValueError("Strumento non disponibile: " + str(name))
    return fn(payload or {}, user)
