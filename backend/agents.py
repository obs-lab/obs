import ipaddress
import json
import logging
import os
import socket
import threading
import time
import urllib.parse
import urllib.request

import agents_store
import code_clients
import code_store
import llm_bridge
import runners

logger = logging.getLogger("OBS.agents")

KIND_SCRIPT = "script"
KIND_ASSISTED = "assisted"
KIND_EXTERNAL = "external"
VALID_KINDS = (KIND_SCRIPT, KIND_ASSISTED, KIND_EXTERNAL)

TRIGGER_MANUAL = "manual"
TRIGGER_INTERVAL = "interval"
VALID_TRIGGERS = (TRIGGER_MANUAL, TRIGGER_INTERVAL)

AGENT_TIMEOUT = int(os.environ.get("OBS_AGENT_TIMEOUT", "180"))
AGENT_MAX_STEPS = int(os.environ.get("OBS_AGENT_MAX_STEPS", "8"))
AGENT_STEPS_CAP = 16
AGENT_MIN_INTERVAL = int(os.environ.get("OBS_AGENT_MIN_INTERVAL", "60"))

EXTERNAL_ENABLED = os.environ.get("OBS_AGENTS_EXTERNAL", "0").strip() == "1"
EXTERNAL_HOSTS = [
    h.strip().lower()
    for h in os.environ.get("OBS_AGENTS_EXTERNAL_HOSTS", "").split(",")
    if h.strip()
]
EXTERNAL_TIMEOUT_CAP = int(os.environ.get("OBS_AGENTS_EXTERNAL_TIMEOUT", "60"))

SCHEDULER_ENABLED = os.environ.get("OBS_AGENTS_SCHEDULER", "0").strip() == "1"
SCHEDULER_TICK = max(15, int(os.environ.get("OBS_AGENTS_SCHEDULER_TICK", "30")))

_scheduler_thread = None
_scheduler_stop = threading.Event()
_run_lock = threading.Semaphore(int(os.environ.get("OBS_AGENT_CONCURRENCY", "2")))


def _clean(value, limit: int = 400) -> str:
    text = "" if value is None else str(value)
    return text.strip()[:limit]


def _is_private_target(host: str) -> bool:
    if not host:
        return False
    lowered = host.lower()
    if lowered in ("localhost", "host.docker.internal"):
        return True
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:
        return False
    for info in infos:
        raw = info[4][0]
        try:
            addr = ipaddress.ip_address(raw)
        except ValueError:
            continue
        if not (addr.is_loopback or addr.is_private or addr.is_link_local):
            return False
    return bool(infos)


def external_target_allowed(url: str) -> tuple:
    parsed = urllib.parse.urlparse(url or "")
    if parsed.scheme not in ("http", "https"):
        return False, "L'indirizzo deve iniziare con http:// o https://."
    host = (parsed.hostname or "").lower()
    if not host:
        return False, "Indirizzo senza host."
    if host in EXTERNAL_HOSTS:
        return True, ""
    if _is_private_target(host):
        return True, ""
    if not EXTERNAL_ENABLED:
        return False, (
            "Gli agenti verso host esterni sono disattivati. "
            "Imposta OBS_AGENTS_EXTERNAL=1 e aggiungi l'host a OBS_AGENTS_EXTERNAL_HOSTS."
        )
    return False, "Host non presente in OBS_AGENTS_EXTERNAL_HOSTS."


def validate(name: str, kind: str, config: dict, trigger: str, interval_s: int) -> dict:
    if not _clean(name):
        raise ValueError("Il nome dell'agente e' obbligatorio.")
    if kind not in VALID_KINDS:
        raise ValueError("Tipo di agente non valido.")
    if trigger not in VALID_TRIGGERS:
        raise ValueError("Innesco non valido.")
    if trigger == TRIGGER_INTERVAL:
        if not SCHEDULER_ENABLED:
            raise ValueError(
                "Lo scheduler e' disattivato. Imposta OBS_AGENTS_SCHEDULER=1 per usare "
                "gli inneschi a intervallo."
            )
        if int(interval_s) < AGENT_MIN_INTERVAL:
            raise ValueError(
                "L'intervallo minimo e' " + str(AGENT_MIN_INTERVAL) + " secondi."
            )

    cfg = dict(config or {})

    if kind == KIND_SCRIPT:
        language = _clean(cfg.get("language"), 40)
        if language not in runners.LANGUAGES:
            raise ValueError("Linguaggio non supportato.")
        source = cfg.get("source") or ""
        if not source.strip():
            raise ValueError("Il codice dell'agente e' vuoto.")
        return {
            "language": language,
            "source": source,
            "with_obs": bool(cfg.get("with_obs", True)),
            "input_mode": "stdin" if cfg.get("input_mode", "stdin") == "stdin" else "none",
        }

    if kind == KIND_ASSISTED:
        objective = _clean(cfg.get("objective"), 2000)
        if not objective:
            raise ValueError("L'obiettivo dell'agente e' obbligatorio.")
        requested = cfg.get("tools") or []
        if not isinstance(requested, list):
            raise ValueError("L'elenco degli strumenti non e' valido.")
        tools = [t for t in (_clean(x, 60) for x in requested) if t]
        unknown = [t for t in tools if not llm_bridge.has_tool(t)]
        if unknown:
            raise ValueError("Strumenti sconosciuti: " + ", ".join(unknown))
        if not tools:
            tools = llm_bridge.tool_names()
        steps = int(cfg.get("max_steps", AGENT_MAX_STEPS) or AGENT_MAX_STEPS)
        steps = max(1, min(steps, AGENT_STEPS_CAP))
        return {
            "objective": objective,
            "tools": tools,
            "max_steps": steps,
            "lang": "it" if _clean(cfg.get("lang"), 4) != "en" else "en",
        }

    url = _clean(cfg.get("url"), 600)
    allowed, reason = external_target_allowed(url)
    if not allowed:
        raise ValueError(reason)
    headers = cfg.get("headers") or {}
    if not isinstance(headers, dict):
        raise ValueError("Le intestazioni non sono valide.")
    clean_headers = {}
    for key, value in list(headers.items())[:12]:
        clean_headers[_clean(key, 60)] = _clean(value, 400)
    timeout = int(cfg.get("timeout_s", 30) or 30)
    return {
        "url": url,
        "method": "POST" if _clean(cfg.get("method"), 8).upper() != "GET" else "GET",
        "headers": clean_headers,
        "timeout_s": max(1, min(timeout, EXTERNAL_TIMEOUT_CAP)),
    }


def _run_script(agent: dict, user: dict, payload: str) -> dict:
    cfg = agent["config"]
    code_store.purge_expired_tokens()
    token = ""
    client = ""
    if cfg.get("with_obs", True):
        token = code_store.create_ephemeral_token(user["user_id"])
        client = code_clients.CLIENTS.get(cfg["language"], "")
    stdin = payload if cfg.get("input_mode") == "stdin" else ""
    try:
        result = runners.execute(
            language_key=cfg["language"],
            source=cfg["source"],
            token=token,
            stdin=stdin,
            client_source=client,
            user_id=user["user_id"],
        )
    finally:
        if token:
            code_store.revoke_ephemeral_token(token)

    trace = [{
        "step": 1,
        "action": "script",
        "language": cfg["language"],
        "exit_code": result.exit_code,
        "duration": round(result.duration, 3),
    }]
    if result.timed_out:
        return {
            "status": agents_store.STATUS_TIMEOUT,
            "output": result.stdout,
            "error": "Esecuzione interrotta per timeout.",
            "steps": 1,
            "trace": trace,
        }
    if result.exit_code != 0:
        return {
            "status": agents_store.STATUS_ERROR,
            "output": result.stdout,
            "error": result.stderr or "Uscita con codice " + str(result.exit_code) + ".",
            "steps": 1,
            "trace": trace,
        }
    return {
        "status": agents_store.STATUS_OK,
        "output": result.stdout,
        "error": result.stderr,
        "steps": 1,
        "trace": trace,
    }


_ASSISTED_SYSTEM = {
    "it": (
        "Sei un agente operativo dentro OBS, un motore documentale locale. "
        "Lavori a passi. A ogni passo rispondi con un solo oggetto JSON, senza testo attorno "
        "e senza delimitatori di codice.\n"
        "Per usare uno strumento: {\"tool\": \"nome\", \"input\": {...}}\n"
        "Per concludere: {\"answer\": \"risposta finale\"}\n"
        "Usa solo gli strumenti elencati. Se i dati raccolti non bastano a rispondere, "
        "dichiaralo nella risposta finale invece di inventare. Cita sempre i titoli dei "
        "documenti da cui provengono le informazioni."
    ),
    "en": (
        "You are an operational agent inside OBS, a local document engine. "
        "You work in steps. At each step reply with a single JSON object, no surrounding "
        "text and no code fences.\n"
        "To use a tool: {\"tool\": \"name\", \"input\": {...}}\n"
        "To finish: {\"answer\": \"final answer\"}\n"
        "Use only the listed tools. If the gathered data is not enough, say so in the final "
        "answer instead of inventing. Always cite the document titles you used."
    ),
}


def _parse_step(raw: str) -> dict:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return {"answer": text}
    try:
        parsed = json.loads(text[start:end + 1])
    except Exception:
        return {"answer": text}
    if not isinstance(parsed, dict):
        return {"answer": text}
    return parsed


def _truncate_observation(value, limit: int = 3000) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        text = str(value)
    if len(text) > limit:
        return text[:limit] + " [troncato]"
    return text


def _run_assisted(agent: dict, user: dict, payload: str) -> dict:
    if not llm_bridge.available():
        return {
            "status": agents_store.STATUS_ERROR,
            "output": "",
            "error": "Nessun motore linguistico attivo: questo agente richiede la modalita' cloud o locale.",
            "steps": 0,
            "trace": [],
        }
    cfg = agent["config"]
    lang = cfg.get("lang", "it")
    tools = [t for t in cfg.get("tools", []) if llm_bridge.has_tool(t)]
    if not tools:
        return {
            "status": agents_store.STATUS_ERROR,
            "output": "",
            "error": "Nessuno strumento disponibile per questo agente.",
            "steps": 0,
            "trace": [],
        }

    header = "Strumenti disponibili: " + ", ".join(tools)
    conversation = [
        header,
        "Obiettivo: " + cfg["objective"],
        "Richiesta: " + (payload or "(nessuna richiesta specifica)"),
    ]
    trace = []
    deadline = time.time() + AGENT_TIMEOUT
    steps = 0

    for _ in range(int(cfg.get("max_steps", AGENT_MAX_STEPS))):
        if time.time() > deadline:
            return {
                "status": agents_store.STATUS_TIMEOUT,
                "output": "",
                "error": "Tempo massimo dell'agente superato.",
                "steps": steps,
                "trace": trace,
            }
        steps += 1
        raw = llm_bridge.complete(_ASSISTED_SYSTEM[lang], "\n\n".join(conversation), 900)
        decision = _parse_step(raw)

        if "answer" in decision and "tool" not in decision:
            trace.append({"step": steps, "action": "answer"})
            return {
                "status": agents_store.STATUS_OK,
                "output": str(decision.get("answer") or ""),
                "error": "",
                "steps": steps,
                "trace": trace,
            }

        name = _clean(decision.get("tool"), 60)
        if name not in tools:
            observation = "Strumento non consentito: " + name
            trace.append({"step": steps, "action": "rifiutato", "tool": name})
        else:
            try:
                result = llm_bridge.call_tool(name, decision.get("input") or {}, user)
                observation = _truncate_observation(result)
                trace.append({"step": steps, "action": "strumento", "tool": name})
            except Exception as exc:
                observation = "Errore dello strumento: " + str(exc)
                trace.append({"step": steps, "action": "errore", "tool": name})

        conversation.append("Azione: " + json.dumps(decision, ensure_ascii=False))
        conversation.append("Osservazione: " + observation)

    return {
        "status": agents_store.STATUS_ERROR,
        "output": "",
        "error": "Numero massimo di passi raggiunto senza una risposta finale.",
        "steps": steps,
        "trace": trace,
    }


def _run_external(agent: dict, user: dict, payload: str) -> dict:
    cfg = agent["config"]
    allowed, reason = external_target_allowed(cfg.get("url", ""))
    if not allowed:
        return {
            "status": agents_store.STATUS_ERROR,
            "output": "",
            "error": reason,
            "steps": 0,
            "trace": [],
        }

    body = json.dumps({
        "agent": agent["name"],
        "input": payload,
        "azienda": user.get("azienda", ""),
    }, ensure_ascii=False).encode("utf-8")

    headers = {"Content-Type": "application/json", "User-Agent": "OBS-LAB/2.6.0"}
    headers.update(cfg.get("headers", {}))

    url = cfg["url"]
    if cfg.get("method") == "GET":
        separator = "&" if "?" in url else "?"
        url = url + separator + urllib.parse.urlencode({"input": payload})
        request = urllib.request.Request(url, headers=headers, method="GET")
    else:
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")

    started = time.time()
    try:
        with urllib.request.urlopen(request, timeout=cfg.get("timeout_s", 30)) as response:
            raw = response.read().decode("utf-8", errors="replace")
            code = response.status
    except Exception as exc:
        return {
            "status": agents_store.STATUS_ERROR,
            "output": "",
            "error": "Chiamata all'agente esterno fallita: " + str(exc),
            "steps": 1,
            "trace": [{"step": 1, "action": "http", "url": cfg["url"]}],
        }

    trace = [{
        "step": 1,
        "action": "http",
        "url": cfg["url"],
        "http_status": code,
        "duration": round(time.time() - started, 3),
    }]

    output = raw
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            for key in ("answer", "output", "result", "text", "content"):
                if isinstance(parsed.get(key), str):
                    output = parsed[key]
                    break
    except Exception:
        pass

    if code >= 400:
        return {
            "status": agents_store.STATUS_ERROR,
            "output": output[:20000],
            "error": "L'agente esterno ha risposto con stato " + str(code) + ".",
            "steps": 1,
            "trace": trace,
        }
    return {
        "status": agents_store.STATUS_OK,
        "output": output[:20000],
        "error": "",
        "steps": 1,
        "trace": trace,
    }


_RUNNERS = {
    KIND_SCRIPT: _run_script,
    KIND_ASSISTED: _run_assisted,
    KIND_EXTERNAL: _run_external,
}


def run_agent(agent: dict, user: dict, payload: str = "",
              trigger: str = TRIGGER_MANUAL) -> dict:
    if not agent.get("enabled", True):
        raise PermissionError("Agente disattivato.")
    handler = _RUNNERS.get(agent.get("kind"))
    if handler is None:
        raise ValueError("Tipo di agente non valido.")

    run_id = agents_store.start_run(agent["agent_id"], user["user_id"], trigger, payload or "")
    acquired = _run_lock.acquire(timeout=5)
    if not acquired:
        agents_store.finish_run(run_id, agents_store.STATUS_ERROR,
                                error="Troppe esecuzioni contemporanee, riprova.")
        raise RuntimeError("Troppe esecuzioni contemporanee, riprova.")
    try:
        outcome = handler(agent, user, payload or "")
    except Exception as exc:
        agents_store.finish_run(run_id, agents_store.STATUS_ERROR, error=str(exc))
        agents_store.mark_run_time(agent["agent_id"])
        raise
    finally:
        _run_lock.release()

    agents_store.finish_run(
        run_id,
        outcome["status"],
        output=outcome.get("output", ""),
        error=outcome.get("error", ""),
        steps=outcome.get("steps", 0),
        trace=outcome.get("trace", []),
    )
    agents_store.mark_run_time(agent["agent_id"])
    result = dict(outcome)
    result["run_id"] = run_id
    result["agent_id"] = agent["agent_id"]
    return result


def _scheduler_loop(user_resolver) -> None:
    while not _scheduler_stop.wait(SCHEDULER_TICK):
        try:
            for agent in agents_store.due_agents():
                user = user_resolver(agent["owner_id"])
                if not user:
                    agents_store.mark_run_time(agent["agent_id"])
                    continue
                try:
                    run_agent(agent, user, "", TRIGGER_INTERVAL)
                except Exception as exc:
                    logger.warning("Agente %s fallito: %s", agent["agent_id"], exc)
        except Exception as exc:
            logger.warning("Ciclo scheduler fallito: %s", exc)


def start_scheduler(user_resolver) -> bool:
    global _scheduler_thread
    if not SCHEDULER_ENABLED:
        return False
    if _scheduler_thread is not None and _scheduler_thread.is_alive():
        return True
    _scheduler_stop.clear()
    _scheduler_thread = threading.Thread(
        target=_scheduler_loop, args=(user_resolver,), daemon=True
    )
    _scheduler_thread.start()
    return True


def stop_scheduler() -> None:
    _scheduler_stop.set()


def status() -> dict:
    return {
        "kinds": list(VALID_KINDS),
        "triggers": list(VALID_TRIGGERS),
        "languages": sorted(runners.LANGUAGES.keys()),
        "tools": llm_bridge.tool_names(),
        "llm_available": llm_bridge.available(),
        "llm_label": llm_bridge.label(),
        "external_enabled": EXTERNAL_ENABLED,
        "external_hosts": EXTERNAL_HOSTS,
        "scheduler_enabled": SCHEDULER_ENABLED,
        "scheduler_running": bool(_scheduler_thread and _scheduler_thread.is_alive()),
        "min_interval_s": AGENT_MIN_INTERVAL,
        "max_steps": AGENT_STEPS_CAP,
        "timeout_s": AGENT_TIMEOUT,
    }
