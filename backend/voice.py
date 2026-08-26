import os
import re
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Optional

_OBS_DATA_ENV = os.environ.get("OBS_DATA_DIR", "").strip()
if _OBS_DATA_ENV:
    DATA_DIR = Path(_OBS_DATA_ENV)
    MODELS_DIR = DATA_DIR / "models"
else:
    DATA_DIR = Path(__file__).parent.parent / "data"
    MODELS_DIR = Path(__file__).parent / "models"

STT_DIR = MODELS_DIR / "whisper"
TTS_DIR = MODELS_DIR / "piper"

VOICE_ENABLED = os.environ.get("OBS_VOICE_ENABLED", "1").strip() == "1"
STT_MODEL = os.environ.get("OBS_STT_MODEL", "small").strip()
STT_MAX_BYTES = int(os.environ.get("OBS_STT_MAX_BYTES", str(25 * 1024 * 1024)))
TTS_MAX_CHARS = int(os.environ.get("OBS_TTS_MAX_CHARS", "4000"))
TTS_DEFAULT_LANG = os.environ.get("OBS_TTS_DEFAULT_LANG", "en").strip().lower()[:2]

_lock = threading.Lock()
_stt_model = None
_stt_engine = ""
_say_cache = None

SUPPORTED_LANGS = ("it", "en", "fr", "es", "de", "pt")

_LANG_MARKERS = {
    "it": ("il","lo","la","i","gli","le","un","uno","una","di","del","dello",
           "della","dei","degli","delle","al","allo","alla","ai","agli","alle",
           "da","dal","dalla","dai","nel","nella","nei","negli","nelle","con",
           "su","sul","sulla","per","tra","fra","ed","che","chi","cui","non",
           "come","dove","quando","perche","quale","quali","quanto","cosa",
           "sono","ha","hanno","era","erano","essere","questo","questa",
           "questi","queste","anche","piu","molto","tutti","tutte","ma","si",
           "ci","mi","ne","viene","vengono","stato","stata","fare","puo"),
    "en": ("the","of","to","on","at","for","with","by","from","and","or","but",
           "is","are","was","were","be","been","being","has","have","had",
           "does","did","this","that","these","those","it","its","which","who",
           "what","when","where","why","how","not","all","any","some","more",
           "most","can","could","should","would","will","there","their","they",
           "we","you","about","into","than","then","also","such","only"),
    "fr": ("le","les","des","une","dans","pour","que","est","sur","avec","cette",
           "sont","plus","aux","par","ce","ces","nous","vous","ils","elle",
           "mais","comme","tout","leur","cet","aussi","entre"),
    "es": ("los","las","una","para","que","con","por","este","son","esta",
           "pero","sobre","como","sus","han","desde","entre","cuando","donde",
           "todo","tambien","mas"),
    "de": ("der","die","das","und","nicht","mit","auch","eine","sind","wird",
           "einen","diese","den","dem","von","zu","fur","auf","ist","als",
           "aus","bei","nach","wenn","oder"),
    "pt": ("nao","que","para","com","uma","dos","das","mais","esta","pelo",
           "sao","isso","como","seu","sua","pela","entre","quando","onde"),
}


def normalize_lang(value: str) -> str:
    clean = (value or "").strip().lower().replace("_", "-")
    if not clean:
        return ""
    head = clean.split("-")[0][:2]
    return head if head in SUPPORTED_LANGS else ""


def detect_lang(text: str, hint: str = "") -> str:
    fallback = normalize_lang(hint) or TTS_DEFAULT_LANG
    words = re.findall(r"[a-zàèéìòùáíóúâêôãõäöüçñß]+", (text or "").lower())
    if len(words) < 2:
        return fallback
    scores = {}
    for lang, markers in _LANG_MARKERS.items():
        scores[lang] = sum(1 for w in words if w in markers) / float(len(words))
    ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    best, top = ordered[0]
    second = ordered[1][1] if len(ordered) > 1 else 0.0
    if top >= 0.06 and (second == 0.0 or top >= second * 1.25):
        return best
    return fallback


def ffmpeg_present() -> bool:
    return shutil.which("ffmpeg") is not None


def _piper_binary() -> Optional[str]:
    explicit = os.environ.get("OBS_PIPER_BIN", "").strip()
    if explicit and Path(explicit).exists():
        return explicit
    found = shutil.which("piper")
    if found:
        return found
    local = TTS_DIR / "piper"
    if local.exists():
        return str(local)
    return None


PIPER_QUALITY_RANK = {"high": 4, "medium": 3, "low": 2, "x_low": 1}


def _piper_quality(name: str) -> int:
    stem = name[:-5] if name.endswith(".onnx") else name
    parts = stem.split("-")
    if len(parts) < 3:
        return 0
    return PIPER_QUALITY_RANK.get(parts[-1].lower(), 0)


def _piper_voices() -> dict:
    voices = {}
    if TTS_DIR.is_dir():
        best = {}
        for candidate in sorted(TTS_DIR.glob("*.onnx")):
            lang = normalize_lang(candidate.name.split("-")[0])
            if not lang:
                continue
            rank = _piper_quality(candidate.name)
            if lang not in best or rank > best[lang][0]:
                best[lang] = (rank, str(candidate))
        for lang in best:
            voices[lang] = best[lang][1]
    for lang in SUPPORTED_LANGS:
        override = os.environ.get("OBS_TTS_VOICE_" + lang.upper(), "").strip()
        if override and Path(override).exists():
            voices[lang] = override
    legacy = os.environ.get("OBS_TTS_VOICE", "").strip()
    if legacy and Path(legacy).exists():
        lang = normalize_lang(Path(legacy).name.split("-")[0]) or TTS_DEFAULT_LANG
        voices.setdefault(lang, legacy)
    return voices


def _say_binary() -> Optional[str]:
    return shutil.which("say")


def _say_voices() -> dict:
    global _say_cache
    if _say_cache is not None:
        return _say_cache
    binary = _say_binary()
    if not binary:
        _say_cache = {}
        return _say_cache
    try:
        listing = subprocess.run([binary, "-v", "?"], capture_output=True,
                                 timeout=15).stdout.decode("utf-8", "replace")
    except Exception:
        _say_cache = {}
        return _say_cache
    voices = {}
    for line in listing.splitlines():
        match = re.match(r"^(.+?)\s{2,}([a-z]{2})[_-]([A-Z]{2})", line)
        if not match:
            continue
        lang = normalize_lang(match.group(2))
        if lang and lang not in voices:
            voices[lang] = match.group(1).strip()
    _say_cache = voices
    return voices


def _espeak_binary() -> Optional[str]:
    for name in ("espeak-ng", "espeak"):
        found = shutil.which(name)
        if found:
            return found
    return None


def _pyttsx3_voices() -> dict:
    try:
        import pyttsx3
        engine = pyttsx3.init()
        voices = {}
        for item in engine.getProperty("voices"):
            tags = []
            for attr in ("languages", "id", "name"):
                value = getattr(item, attr, None)
                if isinstance(value, (list, tuple)):
                    tags.extend(str(v) for v in value)
                elif value:
                    tags.append(str(value))
            for tag in tags:
                lang = normalize_lang(tag[-5:]) or normalize_lang(tag[:2])
                if lang and lang not in voices:
                    voices[lang] = item.id
                    break
        return voices
    except Exception:
        return {}


def stt_engine_available() -> str:
    try:
        import faster_whisper
        return "faster-whisper"
    except Exception:
        pass
    try:
        import whisper
        return "whisper"
    except Exception:
        pass
    try:
        import transformers
        return "transformers"
    except Exception:
        return ""


def tts_engine_available() -> str:
    if _piper_binary() and _piper_voices():
        return "piper"
    if _say_binary():
        return "say"
    if _espeak_binary():
        return "espeak"
    if _pyttsx3_voices():
        return "pyttsx3"
    return ""


def available_voices() -> dict:
    engine = tts_engine_available()
    if engine == "piper":
        return {lang: Path(path).name for lang, path in _piper_voices().items()}
    if engine == "say":
        return dict(_say_voices())
    if engine == "espeak":
        return {lang: lang for lang in SUPPORTED_LANGS}
    if engine == "pyttsx3":
        return {lang: str(value) for lang, value in _pyttsx3_voices().items()}
    return {}


def status() -> dict:
    stt = stt_engine_available() if VOICE_ENABLED else ""
    tts = tts_engine_available() if VOICE_ENABLED else ""
    voices = available_voices() if tts else {}
    return {
        "enabled": VOICE_ENABLED,
        "ffmpeg": ffmpeg_present(),
        "stt_engine": stt,
        "stt_available": bool(stt),
        "stt_model": STT_MODEL,
        "stt_loaded": _stt_model is not None,
        "stt_reason": "" if stt else
                      "No local transcription engine installed. Install faster-whisper.",
        "tts_engine": tts,
        "tts_available": bool(tts),
        "tts_languages": sorted(voices.keys()),
        "tts_voices": voices,
        "tts_default_lang": TTS_DEFAULT_LANG,
        "offline": True,
        "max_audio_bytes": STT_MAX_BYTES,
        "max_text_chars": TTS_MAX_CHARS,
    }


def _load_stt():
    global _stt_model, _stt_engine
    with _lock:
        if _stt_model is not None:
            return _stt_model, _stt_engine
        engine = stt_engine_available()
        if not engine:
            raise RuntimeError(
                "Nessun motore di trascrizione locale installato. "
                "Installa faster-whisper oppure openai-whisper."
            )
        STT_DIR.mkdir(parents=True, exist_ok=True)
        if engine == "faster-whisper":
            from faster_whisper import WhisperModel
            _stt_model = WhisperModel(
                STT_MODEL, device="cpu", compute_type="int8",
                download_root=str(STT_DIR),
            )
        elif engine == "whisper":
            import whisper
            _stt_model = whisper.load_model(STT_MODEL, download_root=str(STT_DIR))
        else:
            from transformers import pipeline
            _stt_model = pipeline(
                "automatic-speech-recognition",
                model="openai/whisper-" + STT_MODEL,
            )
        _stt_engine = engine
        return _stt_model, _stt_engine


def transcribe(audio_bytes: bytes, filename: str = "audio.webm",
               language: str = "") -> dict:
    if not VOICE_ENABLED:
        raise RuntimeError("La voce e' disattivata (OBS_VOICE_ENABLED=0).")
    if not audio_bytes:
        raise ValueError("Audio vuoto.")
    if len(audio_bytes) > STT_MAX_BYTES:
        raise ValueError("Audio troppo lungo: limite " + str(STT_MAX_BYTES) + " byte.")
    if stt_engine_available() == "whisper" and not ffmpeg_present():
        raise RuntimeError(
            "openai-whisper richiede il binario ffmpeg nel PATH. "
            "Installa ffmpeg oppure passa a faster-whisper."
        )

    model, engine = _load_stt()
    suffix = Path(filename).suffix or ".webm"
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        handle.write(audio_bytes)
        handle.close()
        lang = normalize_lang(language) or None

        if engine == "faster-whisper":
            segments, info = model.transcribe(handle.name, language=lang, vad_filter=True)
            parts = [s.text for s in segments]
            return {
                "text": "".join(parts).strip(),
                "language": getattr(info, "language", lang or ""),
                "engine": engine,
                "bytes": len(audio_bytes),
            }
        if engine == "whisper":
            result = model.transcribe(handle.name, language=lang)
            return {
                "text": str(result.get("text", "")).strip(),
                "language": str(result.get("language", lang or "")),
                "engine": engine,
                "bytes": len(audio_bytes),
            }
        result = model(handle.name)
        return {
            "text": str(result.get("text", "")).strip(),
            "language": lang or "",
            "engine": engine,
            "bytes": len(audio_bytes),
        }
    finally:
        try:
            os.unlink(handle.name)
        except Exception:
            pass


def _run(command, stdin_bytes=None):
    return subprocess.run(command, input=stdin_bytes, capture_output=True, timeout=180)


def synthesize(text: str, voice: str = "", lang: str = "") -> dict:
    if not VOICE_ENABLED:
        raise RuntimeError("La voce e' disattivata (OBS_VOICE_ENABLED=0).")
    clean = (text or "").strip()
    if not clean:
        raise ValueError("Testo vuoto.")
    if len(clean) > TTS_MAX_CHARS:
        clean = clean[:TTS_MAX_CHARS]

    engine = tts_engine_available()
    if not engine:
        raise RuntimeError(
            "Nessun motore di sintesi vocale locale disponibile. "
            "Installa piper, espeak-ng oppure pyttsx3."
        )

    chosen = detect_lang(clean, lang)
    voices = available_voices()
    used = chosen if chosen in voices else (
        TTS_DEFAULT_LANG if TTS_DEFAULT_LANG in voices else
        (sorted(voices.keys())[0] if voices else "")
    )

    if engine == "piper":
        catalog = _piper_voices()
        model = voice if voice and Path(voice).exists() else catalog.get(used)
        if not model:
            raise RuntimeError("Nessuna voce piper disponibile.")
        result = _run([_piper_binary(), "--model", model, "--output_file", "-"],
                      clean.encode("utf-8"))
        if result.returncode != 0:
            raise RuntimeError(
                "piper ha fallito: " + result.stderr.decode("utf-8", "replace")[:300]
            )
        return {"audio": result.stdout, "engine": engine, "lang": used,
                "voice": Path(model).name, "detected": chosen}

    handle = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
    handle.close()
    try:
        if engine == "say":
            name = voice or _say_voices().get(used, "")
            command = [_say_binary(), "-o", handle.name,
                       "--data-format=LEI16@22050"]
            if name:
                command += ["-v", name]
            command.append(clean)
            result = _run(command)
            if result.returncode != 0:
                raise RuntimeError(
                    "say ha fallito: " + result.stderr.decode("utf-8", "replace")[:300]
                )
            label = name or "default"
        elif engine == "espeak":
            command = [_espeak_binary(), "-w", handle.name]
            if used:
                command += ["-v", used]
            command.append(clean)
            result = _run(command)
            if result.returncode != 0:
                raise RuntimeError(
                    "espeak ha fallito: " + result.stderr.decode("utf-8", "replace")[:300]
                )
            label = used
        else:
            import pyttsx3
            speaker = pyttsx3.init()
            target = voice or _pyttsx3_voices().get(used, "")
            if target:
                try:
                    speaker.setProperty("voice", target)
                except Exception:
                    target = ""
            speaker.save_to_file(clean, handle.name)
            speaker.runAndWait()
            label = target or "default"
        return {"audio": Path(handle.name).read_bytes(), "engine": engine,
                "lang": used, "voice": label, "detected": chosen}
    finally:
        try:
            os.unlink(handle.name)
        except Exception:
            pass
