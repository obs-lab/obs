# Sections to append to COMMAND_GUIDE.md

These sections are additive. Paste them at the end of `COMMAND_GUIDE.md`,
after the last existing section, without removing or editing anything already
in the file. The numbering continues from the current last section.

---

## 14. Agents (from v2.6.0)

OBS lets each user register agents that run against the archive. There are three
kinds and they are deliberately different from each other.

| Kind | What it is | Needs a language model | Network |
|------|-----------|------------------------|---------|
| Script | Your own code, run in a disposable container | No | Container to OBS only |
| Assisted | A step loop where the model calls declared tools | Yes | None |
| External | An HTTP call to an agent you built elsewhere | No | Only to allowed hosts |

### Where to find it

Toolbar tab **Agents**, or menu **View > Agents**.

### Script agents

The same sandbox as the Code panel: disposable container, memory and CPU caps,
no access to the host. If you tick "Give the sandbox an OBS access token", the
container receives `OBS_TOKEN` and `OBS_URL` and the OBS client library for the
chosen language is injected, exactly as in the Code panel. The token lives for
120 seconds, carries only your own permissions and is revoked when the run ends.

### Assisted agents

At each step the language model answers with a single JSON object: either a tool
call or a final answer. The tools are the ones registered on the backend, listed
in the panel. If a step names a tool you did not tick, the call is refused and
the refusal appears in the trace.

Two limits worth knowing before you rely on it. First, the loop is capped: when
the step budget runs out the run is recorded as failed and no answer is
produced. Second, small local models frequently break the JSON format, which
burns steps without progress. Read the trace of a failed run before blaming the
objective.

### External agents

OBS sends `POST` with a JSON body containing the agent name, your input and your
organisation, and displays whatever comes back. If the reply is JSON with an
`answer`, `output`, `result`, `text` or `content` field, that field is shown;
otherwise the raw body is shown.

Addresses on loopback (`127.0.0.1`, `localhost`, `host.docker.internal`) and on
private networks work with no configuration. Public hosts are refused unless you
opt in:

```bash
OBS_AGENTS_EXTERNAL=1
OBS_AGENTS_EXTERNAL_HOSTS=agents.example.com,tools.example.org
```

### Periodic triggers

Off by default. To enable:

```bash
OBS_AGENTS_SCHEDULER=1
OBS_AGENTS_SCHEDULER_TICK=30
```

Once enabled, an agent can be set to run every N seconds, with N no smaller than
`OBS_AGENT_MIN_INTERVAL` (60 by default). Periodic runs appear in the history
with trigger `interval`.

### Environment variables

| Variable | Default | Effect |
|----------|---------|--------|
| `OBS_AGENT_TIMEOUT` | `180` | wall clock cap for one run, in seconds |
| `OBS_AGENT_MAX_STEPS` | `8` | default step budget for assisted agents |
| `OBS_AGENT_CONCURRENCY` | `2` | simultaneous runs allowed |
| `OBS_AGENT_MIN_INTERVAL` | `60` | smallest periodic interval |
| `OBS_AGENT_RUN_KEEP` | `500` | runs kept in history |
| `OBS_AGENTS_EXTERNAL` | `0` | allow non-local targets |
| `OBS_AGENTS_EXTERNAL_HOSTS` | empty | comma separated allow list |
| `OBS_AGENTS_EXTERNAL_TIMEOUT` | `60` | cap on the declarable timeout |
| `OBS_AGENTS_SCHEDULER` | `0` | enable periodic triggers |
| `OBS_AGENTS_SCHEDULER_TICK` | `30` | scheduler poll interval |

### Quick endpoint tests

```bash
# what the backend offers
curl -b cookies.txt http://localhost:8000/api/agents/status

# list your agents
curl -b cookies.txt http://localhost:8000/api/agents

# check whether a target address is allowed
curl -b cookies.txt -X POST http://localhost:8000/api/agents/probe \
  -H "Content-Type: application/json" \
  -d '{"url":"http://127.0.0.1:5001/run"}'

# run an agent
curl -b cookies.txt -X POST http://localhost:8000/api/agents/AGENT_ID/run \
  -H "Content-Type: application/json" \
  -d '{"input":"suppliers mentioned in 2024"}'
```

### Troubleshooting

**"Nessun motore linguistico attivo"** on an assisted agent. There is no cloud or
local model configured. Check `/api/llm/status` and section 7 of this guide.

**"Gli agenti verso host esterni sono disattivati"**. The target resolves to a
public address and `OBS_AGENTS_EXTERNAL` is not `1`. Either point the agent at a
local address or add the host to the allow list.

**"Lo scheduler e' disattivato"** when saving a periodic agent. Set
`OBS_AGENTS_SCHEDULER=1` and restart the backend.

**"Troppe esecuzioni contemporanee"**. More runs than `OBS_AGENT_CONCURRENCY`
were requested at once. Wait, or raise the value on a machine that can take it.

**A script agent fails immediately with a Docker error.** The language image is
missing. Pull it from the Code panel, section 11 of `CODE_GUIDE.md`.

---

## 15. Local files panel (from v2.6.0)

This panel reads files that are already on the machine. It does not upload them,
does not copy them, does not index them and never writes to disk.

### Where to find it

Toolbar tab **Local files**, or menu **View > Local files**.

### How it works

Nothing is readable until you register a folder as a root. Registering a root is
what grants access; removing it takes the access away immediately, and because
nothing was indexed, nothing is left behind.

Every path you open is resolved to its canonical form first, so symbolic links
and relative components cannot be used to step outside a root.

### What is always refused

Regardless of which roots you register:

- system directories (`/etc`, `/proc`, `/sys`, `/boot`, `C:\Windows`, and similar)
- the OBS data directory, and any folder that contains it
- credential folders: `.ssh`, `.gnupg`, `.aws`, `.azure`, `.kube`
- `.env` files and key material (`*.pem`, `*.key`, `*.pfx`, `*.p12`)
- the OBS databases themselves
- noise folders: `.git`, `node_modules`, `__pycache__`, `venv`

### Reading and analysing

Text formats are read directly. PDF, DOCX, XLSX and XLS are text-extracted with
the same libraries the archive ingestion uses. Everything else is listed but not
opened.

The **Analyse** button sends the extracted text and your question to whichever
language model is configured. With no model configured the file is still read and
shown, and the panel says so instead of pretending.

### Single machine versus server

By default each user manages their own roots. On a server this matters: the disk
being read is the server disk, not the user's laptop. Server mode is off by
default. To turn it on:

```bash
OBS_FS_SERVER_MODE=1
```

With server mode on, an admin can assign roots to users of their own
organisation and a developer to anyone. To switch the panel off entirely, which
is the recommended setting for `start_prod.sh` and `start_prod.bat` unless you
decided otherwise:

```bash
OBS_FS_ENABLED=0
```

### Environment variables

| Variable | Default | Effect |
|----------|---------|--------|
| `OBS_FS_ENABLED` | `1` | enable the panel |
| `OBS_FS_SERVER_MODE` | `0` | allow admins and developers to assign roots |
| `OBS_FS_MAX_READ_BYTES` | `4194304` | largest readable file |
| `OBS_FS_MAX_TEXT_CHARS` | `200000` | characters extracted per file |
| `OBS_FS_MAX_ENTRIES` | `2000` | entries returned per folder |
| `OBS_FS_MAX_SCAN` | `20000` | files examined by one search |
| `OBS_FS_MAX_DEPTH` | `12` | deepest level a search descends |
| `OBS_FS_SCAN_TIMEOUT` | `20` | seconds before a search stops |

### Quick endpoint tests

```bash
curl -b cookies.txt http://localhost:8000/api/fs/status

curl -b cookies.txt -X POST http://localhost:8000/api/fs/roots \
  -H "Content-Type: application/json" \
  -d '{"path":"/Users/me/Documents/cases","label":"Cases"}'

curl -b cookies.txt "http://localhost:8000/api/fs/browse?path=/Users/me/Documents/cases"

curl -b cookies.txt -X POST http://localhost:8000/api/fs/search \
  -H "Content-Type: application/json" \
  -d '{"path":"/Users/me/Documents/cases","pattern":"*.pdf","contains":"clause"}'
```

### Troubleshooting

**"Percorso fuori dalle radici consentite"**. The path is not inside any root you
registered, or a symbolic link pointed outside one. Register the folder that
actually contains the file.

**"La radice non puo' contenere o essere dentro i dati di OBS"**. You tried to
register a folder that overlaps the OBS data directory. Pick a narrower folder.

**"File troppo grande"**. Above `OBS_FS_MAX_READ_BYTES`. Raise the variable only
if the machine can hold the file in memory.

**A search returns few results and reports that it stopped.** It hit
`OBS_FS_MAX_SCAN` or `OBS_FS_SCAN_TIMEOUT`. Narrow the starting folder rather
than raising the limits.

---

## 16. Voice: dictation and read aloud (from v2.6.0)

Both directions run locally. Nothing is sent anywhere. The browser speech API is
deliberately not used, because on some browsers it ships the audio to a remote
service.

### Where to find it

Two small buttons in the query bar, next to the filters. They only appear when a
local engine is installed. If you see no buttons, no engine is present.

### Installing an engine

Transcription, pick one:

```bash
pip install faster-whisper==1.0.3
# or
pip install openai-whisper
```

The model downloads on first use into `data/models/whisper`. Size is set by
`OBS_STT_MODEL` (`tiny`, `base`, `small`, `medium`, `large-v3`). `small` is the
default and a reasonable balance on CPU.

Speech, in order of preference:

1. **piper**, best quality. Install the binary, put a `.onnx` voice into
   `models/piper`, or point `OBS_TTS_VOICE` at one.
2. **say**, already present on macOS, nothing to install.
3. **espeak-ng**, `sudo apt install espeak-ng` on Linux.
4. **pyttsx3**, `pip install pyttsx3`, as a fallback.

### Checking what is active

```bash
curl -b cookies.txt http://localhost:8000/api/voice/status
```

The reply names the engine actually in use for each direction, or an empty string
if none is available.

### Environment variables

| Variable | Default | Effect |
|----------|---------|--------|
| `OBS_VOICE_ENABLED` | `1` | enable both directions |
| `OBS_STT_MODEL` | `small` | Whisper model size |
| `OBS_STT_MAX_BYTES` | `26214400` | largest audio accepted |
| `OBS_TTS_MAX_CHARS` | `4000` | characters synthesised per request |
| `OBS_TTS_VOICE` | empty | path to a piper `.onnx` voice |
| `OBS_PIPER_BIN` | empty | path to the piper binary |

### Troubleshooting

**The microphone button does not appear.** No transcription engine is installed,
or `OBS_VOICE_ENABLED=0`. Check `/api/voice/status`.

**"Microphone access denied".** The browser blocked the request. In the desktop
shell, allow microphone access for the local origin; in a browser, check the site
permissions. Note that some browsers only grant microphone access over HTTPS or
on `localhost`.

**Transcription is slow.** The first call loads the model, which on CPU can take
tens of seconds. Later calls are much faster. Dropping `OBS_STT_MODEL` to `base`
roughly halves the time and costs accuracy.

**The text comes out wrong.** Expected on noisy input, strong accents or
domain-specific vocabulary. The transcription lands in the query box precisely so
you can correct it before searching, rather than silently searching for something
you did not say.

**No sound on read aloud.** Either no speech engine is installed, or the browser
blocked autoplay. Click once anywhere in the window and try again.
