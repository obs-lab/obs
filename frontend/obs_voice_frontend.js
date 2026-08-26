var OBS_VOICE = {
  status: null,
  stt: false,
  tts: false,
  mime: "",
  ext: "webm",
  recorder: null,
  chunks: [],
  recording: false,
  busy: false,
  player: null,
  audioEl: null,
  audioUnlocked: false,
  synthesizing: false,
  cancelled: false,
  stopPlayback: null,
  conv: {
    on: false,
    state: "idle",
    stream: null,
    ctx: null,
    analyser: null,
    buffer: null,
    timer: null,
    recorder: null,
    chunks: [],
    floor: 0,
    floorSamples: 0,
    threshold: 0.02,
    speechMs: 0,
    silenceMs: 0,
    startedAt: 0
  }
};

var OBS_VOICE_MIMES = [
  "audio/webm;codecs=opus",
  "audio/webm",
  "audio/ogg;codecs=opus",
  "audio/mp4",
  "audio/aac",
  "audio/wav"
];

var OBS_VOICE_TUNING = {
  calibrateMs: 700,
  onsetMs: 160,
  minSpeechMs: 350,
  silenceMs: 1200,
  maxUtteranceMs: 25000,
  resumeDelayMs: 350,
  tick: 50
};

function obsVoiceToast(message, type) {
  if (typeof toast === "function") toast(message, type);
}

var OBS_VOICE_SILENCE = "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAgD4AAAB9AAACABAAZGF0YQAAAAA=";

function obsVoiceUnlockAudio() {
  if (OBS_VOICE.audioUnlocked) return;
  if (!OBS_VOICE.audioEl) OBS_VOICE.audioEl = new Audio();
  OBS_VOICE.audioEl.src = OBS_VOICE_SILENCE;
  var started = OBS_VOICE.audioEl.play();
  if (started && started.then) {
    started.then(function () {
      OBS_VOICE.audioEl.pause();
      OBS_VOICE.audioUnlocked = true;
    }).catch(function () {
      OBS_VOICE.audioUnlocked = false;
    });
  } else {
    OBS_VOICE.audioUnlocked = true;
  }
}

function obsVoicePickMime() {
  if (typeof MediaRecorder === "undefined" || !MediaRecorder.isTypeSupported) return "";
  for (var i = 0; i < OBS_VOICE_MIMES.length; i++) {
    if (MediaRecorder.isTypeSupported(OBS_VOICE_MIMES[i])) return OBS_VOICE_MIMES[i];
  }
  return "";
}

function obsVoiceExtFor(mime) {
  if (mime.indexOf("mp4") !== -1) return "mp4";
  if (mime.indexOf("aac") !== -1) return "m4a";
  if (mime.indexOf("ogg") !== -1) return "ogg";
  if (mime.indexOf("wav") !== -1) return "wav";
  return "webm";
}

function obsVoiceCaptureBlocker() {
  if (typeof window.isSecureContext !== "undefined" && !window.isSecureContext) {
    return "Microphone capture needs a secure context. Open OBS on localhost, or serve it over https.";
  }
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    return "This browser or shell does not expose audio capture.";
  }
  if (typeof MediaRecorder === "undefined") {
    return "This browser does not support MediaRecorder.";
  }
  if (!obsVoicePickMime()) {
    return "No audio container supported by this browser.";
  }
  return "";
}

function obsVoiceDiag() {
  var lines = [];
  lines.push("origin: " + window.location.origin);
  lines.push("secure context: " + (window.isSecureContext ? "yes" : "no"));
  lines.push("mediaDevices: " + (navigator.mediaDevices ? "yes" : "no"));
  lines.push("MediaRecorder: " + (typeof MediaRecorder !== "undefined" ? "yes" : "no"));
  lines.push("chosen container: " + (obsVoicePickMime() || "none"));
  var blocker = obsVoiceCaptureBlocker();
  lines.push("capture blocker: " + (blocker || "none"));
  if (OBS_VOICE.status) {
    lines.push("backend stt: " + (OBS_VOICE.status.stt_engine || "none"));
    lines.push("backend tts: " + (OBS_VOICE.status.tts_engine || "none"));
    lines.push("ffmpeg on backend: " + (OBS_VOICE.status.ffmpeg ? "yes" : "no"));
  } else {
    lines.push("backend status: not loaded");
  }
  var text = lines.join("\n");
  if (window.console && console.log) console.log(text);
  return text;
}

function obsVoiceInit() {
  OBS_VOICE.mime = obsVoicePickMime();
  OBS_VOICE.ext = obsVoiceExtFor(OBS_VOICE.mime);
  fetch("/api/voice/status").then(function (r) {
    return r.json();
  }).then(function (data) {
    OBS_VOICE.status = data;
    OBS_VOICE.stt = !!(data && data.stt_available);
    OBS_VOICE.tts = !!(data && data.tts_available);
    obsVoiceApply();
  }).catch(function () {
    OBS_VOICE.stt = false;
    OBS_VOICE.tts = false;
    obsVoiceApply();
  });
}

function obsVoiceApply() {
  var blocker = obsVoiceCaptureBlocker();
  var mic = document.getElementById("voiceMicBtn");
  var speak = document.getElementById("voiceSpeakBtn");
  var conv = document.getElementById("voiceConvBtn");

  if (mic) {
    mic.style.display = "";
    mic.disabled = false;
    if (!OBS_VOICE.stt) {
      mic.className = "btn btng voice-btn off";
      mic.title = (OBS_VOICE.status && OBS_VOICE.status.stt_reason)
        ? OBS_VOICE.status.stt_reason
        : "The backend did not answer /api/voice/status.";
    } else if (blocker) {
      mic.className = "btn btng voice-btn off";
      mic.title = blocker;
    } else {
      mic.className = "btn btng voice-btn";
      mic.title = "Dictate the question (" + OBS_VOICE.status.stt_engine + ", local)";
    }
  }
  if (speak) {
    speak.style.display = OBS_VOICE.tts ? "" : "none";
    obsVoiceSpeakButton("idle");
  }
  if (mic && !OBS_VOICE.stt && OBS_VOICE.status && OBS_VOICE.status.stt_reason) {
    mic.title = OBS_VOICE.status.stt_reason;
  }
  if (conv) {
    var ready = OBS_VOICE.stt && OBS_VOICE.tts && !blocker;
    conv.style.display = "";
    conv.disabled = false;
    conv.className = "btn btng voice-btn" + (ready ? "" : " off");
    conv.title = ready
      ? "Hands free conversation: OBS listens, answers out loud and listens again"
      : (blocker || (OBS_VOICE.status && OBS_VOICE.status.stt_reason) ||
         "Conversation needs both a transcription and a speech engine.");
  }
  obsVoiceConvIndicator("");
}

function obsVoiceMicState(state, glyph) {
  var mic = document.getElementById("voiceMicBtn");
  if (!mic) return;
  mic.className = "btn btng voice-btn" + (state ? " " + state : "");
  mic.textContent = glyph;
}

function obsVoiceToggleRecord() {
  obsVoiceUnlockAudio();
  if (!OBS_VOICE.stt) {
    obsVoiceToast(
      (OBS_VOICE.status && OBS_VOICE.status.stt_reason) ||
      "Transcription is not available on this backend.", "error");
    return;
  }
  var reason = obsVoiceCaptureBlocker();
  if (reason) {
    obsVoiceToast(reason, "error");
    return;
  }
  if (OBS_VOICE.busy || OBS_VOICE.conv.on) return;
  if (OBS_VOICE.recording) {
    obsVoiceStopDictation();
  } else {
    obsVoiceStartDictation();
  }
}

function obsVoiceMediaError(err) {
  var name = err && err.name ? err.name : "";
  if (name === "NotAllowedError" || name === "SecurityError") {
    return "Microphone permission denied. On the desktop app the shell must declare microphone access.";
  }
  if (name === "NotFoundError" || name === "DevicesNotFoundError") {
    return "No microphone found on this machine.";
  }
  if (name === "NotReadableError") {
    return "The microphone is busy in another application.";
  }
  return "Audio capture failed: " + (err && err.message ? err.message : name || "unknown");
}

function obsVoiceStartDictation() {
  var blocker = obsVoiceCaptureBlocker();
  if (blocker) {
    obsVoiceToast(blocker, "error");
    return;
  }
  navigator.mediaDevices.getUserMedia({ audio: true }).then(function (stream) {
    OBS_VOICE.chunks = [];
    var options = OBS_VOICE.mime ? { mimeType: OBS_VOICE.mime } : undefined;
    var recorder = new MediaRecorder(stream, options);
    OBS_VOICE.recorder = recorder;
    recorder.ondataavailable = function (event) {
      if (event.data && event.data.size) OBS_VOICE.chunks.push(event.data);
    };
    recorder.onstop = function () {
      stream.getTracks().forEach(function (track) { track.stop(); });
      obsVoiceSendDictation();
    };
    recorder.start();
    OBS_VOICE.recording = true;
    obsVoiceMicState("rec", "\u25A0");
  }).catch(function (err) {
    obsVoiceToast(obsVoiceMediaError(err), "error");
  });
}

function obsVoiceStopDictation() {
  if (OBS_VOICE.recorder && OBS_VOICE.recording) {
    OBS_VOICE.recording = false;
    OBS_VOICE.recorder.stop();
    obsVoiceMicState("busy", "\u25CF");
  }
}

function obsVoiceTranscribe(blob) {
  var form = new FormData();
  form.append("file", blob, "speech." + OBS_VOICE.ext);
  form.append("language", "");
  return fetch("/api/voice/transcribe", { method: "POST", body: form }).then(function (r) {
    return r.json().then(function (data) {
      if (!r.ok) throw new Error(data && data.detail ? data.detail : "Transcription failed");
      return data;
    });
  });
}

function obsVoiceSendDictation() {
  if (!OBS_VOICE.chunks.length) {
    obsVoiceMicState("", "\u25CF");
    return;
  }
  OBS_VOICE.busy = true;
  var blob = new Blob(OBS_VOICE.chunks, { type: OBS_VOICE.mime || "audio/webm" });
  obsVoiceTranscribe(blob).then(function (data) {
    var text = (data.text || "").trim();
    if (!text) {
      obsVoiceToast("Nothing was recognised.", "error");
      return;
    }
    var input = document.getElementById("queryInput");
    if (input) {
      input.value = input.value ? input.value + " " + text : text;
      if (typeof autoResize === "function") autoResize(input);
      input.focus();
    }
  }).catch(function (err) {
    obsVoiceToast(err.message, "error");
  }).then(function () {
    OBS_VOICE.busy = false;
    OBS_VOICE.chunks = [];
    obsVoiceMicState("", "\u25CF");
  });
}

function obsVoiceLastAnswer() {
  var bubbles = document.querySelectorAll("#chatArea .msg-o .mbub");
  if (!bubbles.length) return "";
  return bubbles[bubbles.length - 1].textContent || "";
}

function obsVoiceSpeakLast() {
  obsVoiceUnlockAudio();
  if (obsVoiceIsSpeaking()) {
    obsVoiceStopSpeaking();
    return;
  }
  var text = obsVoiceLastAnswer().trim();
  if (!text) {
    obsVoiceToast("There is no answer to read yet.", "error");
    return;
  }
  obsVoiceSpeakText(text);
}

function obsVoiceGuessLang(text) {
  var words = (text || "").toLowerCase().match(/[a-zàèéìòùáíóúâêôãõäöüçñ]+/g) || [];
  if (words.length < 8) return window.OBS_LANG || "";
  var markers = {
    it: ["che", "non", "per", "sono", "della", "come", "questo", "anche", "nel", "alla"],
    en: ["the", "and", "for", "with", "that", "this", "from", "have", "which", "been"]
  };
  var best = "";
  var bestScore = 0;
  for (var lang in markers) {
    var score = 0;
    for (var i = 0; i < words.length; i++) {
      if (markers[lang].indexOf(words[i]) !== -1) score += 1;
    }
    if (score > bestScore) {
      bestScore = score;
      best = lang;
    }
  }
  return bestScore >= 3 ? best : (window.OBS_LANG || "");
}

function obsVoiceSynthesize(text) {
  return fetch("/api/voice/speak", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text: text, lang: obsVoiceGuessLang(text) })
  }).then(function (r) {
    if (!r.ok) {
      return r.json().then(function (data) {
        throw new Error(data && data.detail ? data.detail : "Speech failed");
      });
    }
    return r.blob();
  });
}

function obsVoicePlay(blob) {
  return new Promise(function (resolve, reject) {
    var url = URL.createObjectURL(blob);
    if (!OBS_VOICE.audioEl) OBS_VOICE.audioEl = new Audio();
    var player = OBS_VOICE.audioEl;
    OBS_VOICE.player = player;
    var done = function (fn, arg) {
      URL.revokeObjectURL(url);
      OBS_VOICE.player = null;
      player.onended = null;
      player.onerror = null;
      fn(arg);
    };
    OBS_VOICE.stopPlayback = function () { done(resolve); };
    player.onended = function () { done(resolve); };
    player.onerror = function () {
      done(reject, new Error("Playback failed. The browser may have blocked autoplay."));
    };
    player.src = url;
    var started = player.play();
    if (started && started.catch) {
      started.catch(function (err) { done(reject, err); });
    }
  });
}

function obsVoiceSpeakButton(state) {
  var speak = document.getElementById("voiceSpeakBtn");
  if (!speak) return;
  if (state === "playing") {
    speak.className = "btn btng voice-btn rec";
    speak.textContent = "\u25A0";
    speak.title = "Stop reading";
  } else if (state === "busy") {
    speak.className = "btn btng voice-btn busy";
    speak.textContent = "\u25CF";
    speak.title = "Preparing the audio";
  } else {
    speak.className = "btn btng voice-btn";
    speak.textContent = "\u25B6";
    speak.title = "Read the last answer aloud";
  }
}

function obsVoiceIsSpeaking() {
  return !!OBS_VOICE.player || OBS_VOICE.synthesizing;
}

function obsVoiceStopSpeaking() {
  OBS_VOICE.cancelled = true;
  if (OBS_VOICE.player) {
    try {
      OBS_VOICE.player.pause();
      OBS_VOICE.player.currentTime = 0;
    } catch (e) {
      OBS_VOICE.player = null;
    }
  }
  if (OBS_VOICE.stopPlayback) {
    var fn = OBS_VOICE.stopPlayback;
    OBS_VOICE.stopPlayback = null;
    fn();
  }
  OBS_VOICE.player = null;
  obsVoiceSpeakButton("idle");
  if (OBS_VOICE.conv.on && OBS_VOICE.conv.state === "speaking") {
    obsVoiceConvResume();
  }
}

function obsVoiceSpeakText(text) {
  if (!OBS_VOICE.tts) {
    obsVoiceToast("No local speech engine installed.", "error");
    return Promise.resolve();
  }
  var clean = (text || "").trim();
  if (!clean) return Promise.resolve();
  if (obsVoiceIsSpeaking()) obsVoiceStopSpeaking();

  OBS_VOICE.cancelled = false;
  OBS_VOICE.synthesizing = true;
  obsVoiceSpeakButton("busy");
  return obsVoiceSynthesize(clean).then(function (blob) {
    OBS_VOICE.synthesizing = false;
    if (OBS_VOICE.cancelled) return null;
    obsVoiceSpeakButton("playing");
    return obsVoicePlay(blob);
  }).catch(function (err) {
    if (!OBS_VOICE.cancelled) obsVoiceToast(err.message, "error");
  }).then(function () {
    OBS_VOICE.synthesizing = false;
    obsVoiceSpeakButton("idle");
  });
}

function obsVoiceConvIndicator(label) {
  var el = document.getElementById("voiceConvState");
  if (el) el.textContent = label || "";
  var button = document.getElementById("voiceConvBtn");
  if (!button) return;
  button.className = "btn btng voice-btn" + (OBS_VOICE.conv.on ? " rec" : "");
  button.textContent = OBS_VOICE.conv.on ? "\u25A0" : "\u25CE";
}

function obsVoiceConvSetState(state) {
  OBS_VOICE.conv.state = state;
  var labels = {
    calibrating: "calibrating",
    listening: "listening",
    capturing: "recording",
    thinking: "thinking",
    speaking: "speaking"
  };
  obsVoiceConvIndicator(labels[state] || "");
}

function obsVoiceConvToggle() {
  obsVoiceUnlockAudio();
  if (OBS_VOICE.conv.on) {
    obsVoiceConvStop("Conversation stopped.");
  } else {
    obsVoiceConvStart();
  }
}

function obsVoiceConvStart() {
  if (!OBS_VOICE.stt || !OBS_VOICE.tts) {
    obsVoiceToast(
      (OBS_VOICE.status && OBS_VOICE.status.stt_reason) ||
      "Conversation needs both a transcription and a speech engine.", "error");
    return;
  }
  var blocker = obsVoiceCaptureBlocker();
  if (blocker) {
    obsVoiceToast(blocker, "error");
    return;
  }
  if (OBS_VOICE.recording) obsVoiceStopDictation();

  navigator.mediaDevices.getUserMedia({
    audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true }
  }).then(function (stream) {
    var conv = OBS_VOICE.conv;
    conv.on = true;
    conv.stream = stream;
    conv.floor = 0;
    conv.floorSamples = 0;
    conv.threshold = 0.02;
    conv.speechMs = 0;
    conv.silenceMs = 0;

    var AudioCtx = window.AudioContext || window.webkitAudioContext;
    conv.ctx = new AudioCtx();
    var source = conv.ctx.createMediaStreamSource(stream);
    conv.analyser = conv.ctx.createAnalyser();
    conv.analyser.fftSize = 1024;
    conv.buffer = new Float32Array(conv.analyser.fftSize);
    source.connect(conv.analyser);

    obsVoiceConvSetState("calibrating");
    conv.timer = setInterval(obsVoiceConvTick, OBS_VOICE_TUNING.tick);
  }).catch(function (err) {
    obsVoiceToast(obsVoiceMediaError(err), "error");
  });
}

function obsVoiceConvStop(message) {
  var conv = OBS_VOICE.conv;
  conv.on = false;
  if (conv.timer) {
    clearInterval(conv.timer);
    conv.timer = null;
  }
  if (conv.recorder && conv.recorder.state !== "inactive") {
    try {
      conv.recorder.stop();
    } catch (e) {
      conv.recorder = null;
    }
  }
  conv.recorder = null;
  conv.chunks = [];
  if (conv.stream) {
    conv.stream.getTracks().forEach(function (track) { track.stop(); });
    conv.stream = null;
  }
  if (conv.ctx) {
    try {
      conv.ctx.close();
    } catch (e) {
      conv.ctx = null;
    }
    conv.ctx = null;
  }
  if (OBS_VOICE.player) {
    OBS_VOICE.player.pause();
    OBS_VOICE.player = null;
  }
  conv.state = "idle";
  obsVoiceConvIndicator("");
  if (message) obsVoiceToast(message, "success");
}

function obsVoiceLevel() {
  var conv = OBS_VOICE.conv;
  if (!conv.analyser) return 0;
  conv.analyser.getFloatTimeDomainData(conv.buffer);
  var sum = 0;
  for (var i = 0; i < conv.buffer.length; i++) {
    sum += conv.buffer[i] * conv.buffer[i];
  }
  return Math.sqrt(sum / conv.buffer.length);
}

function obsVoiceConvTick() {
  var conv = OBS_VOICE.conv;
  if (!conv.on) return;
  if (conv.state === "thinking" || conv.state === "speaking") return;

  var level = obsVoiceLevel();
  var tick = OBS_VOICE_TUNING.tick;

  if (conv.state === "calibrating") {
    conv.floor += level;
    conv.floorSamples += 1;
    if (conv.floorSamples * tick >= OBS_VOICE_TUNING.calibrateMs) {
      var mean = conv.floor / conv.floorSamples;
      conv.threshold = Math.max(mean * 3.5, 0.012);
      obsVoiceConvSetState("listening");
    }
    return;
  }

  if (conv.state === "listening") {
    if (level > conv.threshold) {
      conv.speechMs += tick;
      if (conv.speechMs >= OBS_VOICE_TUNING.onsetMs) obsVoiceConvBeginCapture();
    } else {
      conv.speechMs = 0;
    }
    return;
  }

  if (conv.state === "capturing") {
    if (level > conv.threshold) {
      conv.speechMs += tick;
      conv.silenceMs = 0;
    } else {
      conv.silenceMs += tick;
    }
    var elapsed = Date.now() - conv.startedAt;
    if (conv.silenceMs >= OBS_VOICE_TUNING.silenceMs ||
        elapsed >= OBS_VOICE_TUNING.maxUtteranceMs) {
      obsVoiceConvEndCapture();
    }
  }
}

function obsVoiceConvBeginCapture() {
  var conv = OBS_VOICE.conv;
  conv.chunks = [];
  conv.silenceMs = 0;
  conv.startedAt = Date.now();
  var options = OBS_VOICE.mime ? { mimeType: OBS_VOICE.mime } : undefined;
  try {
    conv.recorder = new MediaRecorder(conv.stream, options);
  } catch (e) {
    obsVoiceConvStop("The recorder could not start.");
    return;
  }
  conv.recorder.ondataavailable = function (event) {
    if (event.data && event.data.size) conv.chunks.push(event.data);
  };
  conv.recorder.onstop = function () {
    obsVoiceConvHandleUtterance();
  };
  conv.recorder.start();
  obsVoiceConvSetState("capturing");
}

function obsVoiceConvEndCapture() {
  var conv = OBS_VOICE.conv;
  obsVoiceConvSetState("thinking");
  if (conv.recorder && conv.recorder.state !== "inactive") {
    conv.recorder.stop();
  } else {
    obsVoiceConvHandleUtterance();
  }
}

function obsVoiceConvResume() {
  var conv = OBS_VOICE.conv;
  if (!conv.on) return;
  conv.speechMs = 0;
  conv.silenceMs = 0;
  conv.chunks = [];
  conv.recorder = null;
  setTimeout(function () {
    if (OBS_VOICE.conv.on) obsVoiceConvSetState("listening");
  }, OBS_VOICE_TUNING.resumeDelayMs);
}

function obsVoiceIsStopPhrase(text) {
  var lowered = text.toLowerCase().replace(/[^a-z ]/g, " ").replace(/\s+/g, " ").trim();
  var phrases = [
    "stop conversation", "end conversation", "stop listening",
    "chiudi conversazione", "termina conversazione", "smetti di ascoltare"
  ];
  for (var i = 0; i < phrases.length; i++) {
    if (lowered.indexOf(phrases[i]) !== -1) return true;
  }
  return false;
}

function obsVoiceAsk(text) {
  var input = document.getElementById("queryInput");
  var chat = document.getElementById("chatArea");
  if (!input || !chat || typeof sendQuery !== "function") {
    return Promise.reject(new Error("The query panel is not available."));
  }
  input.value = text;
  if (typeof autoResize === "function") autoResize(input);
  sendQuery();

  var pendings = chat.querySelectorAll(".msg-o");
  var pending = pendings.length ? pendings[pendings.length - 1] : null;
  if (!pending) return Promise.resolve("");

  return new Promise(function (resolve, reject) {
    var waited = 0;
    var poll = setInterval(function () {
      if (!OBS_VOICE.conv.on) {
        clearInterval(poll);
        resolve("");
        return;
      }
      var bubble = pending.querySelector(".mbub");
      if (bubble) {
        clearInterval(poll);
        resolve(bubble.textContent || "");
        return;
      }
      waited += 300;
      if (waited > 180000) {
        clearInterval(poll);
        reject(new Error("The answer took too long."));
      }
    }, 300);
  });
}

function obsVoiceConvHandleUtterance() {
  var conv = OBS_VOICE.conv;
  if (!conv.on) return;
  if (conv.speechMs < OBS_VOICE_TUNING.minSpeechMs || !conv.chunks.length) {
    obsVoiceConvResume();
    return;
  }
  var blob = new Blob(conv.chunks, { type: OBS_VOICE.mime || "audio/webm" });
  obsVoiceTranscribe(blob).then(function (data) {
    var text = (data.text || "").trim();
    if (!text) return "";
    if (obsVoiceIsStopPhrase(text)) {
      obsVoiceConvStop("Conversation stopped.");
      return "";
    }
    return obsVoiceAsk(text);
  }).then(function (answer) {
    if (!answer || !OBS_VOICE.conv.on) return null;
    obsVoiceConvSetState("speaking");
    return obsVoiceSpeakText(answer);
  }).catch(function (err) {
    obsVoiceToast(err.message, "error");
  }).then(function () {
    obsVoiceConvResume();
  });
}

document.addEventListener("keydown", function (event) {
  if (event.key !== "Escape") return;
  if (obsVoiceIsSpeaking()) {
    obsVoiceStopSpeaking();
    return;
  }
  if (OBS_VOICE.conv.on) obsVoiceConvStop("Conversation stopped.");
});

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", obsVoiceInit);
} else {
  obsVoiceInit();
}
