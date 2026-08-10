import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

CODE_RUNNER = os.environ.get("CODE_RUNNER", "docker").lower()
CODE_TIMEOUT = int(os.environ.get("CODE_TIMEOUT", "30"))
CODE_MEMORY_MB = int(os.environ.get("CODE_MEMORY_MB", "512"))
CODE_CPUS = os.environ.get("CODE_CPUS", "1.0")
CODE_MAX_OUTPUT = int(os.environ.get("CODE_MAX_OUTPUT", "100000"))
CODE_NETWORK = os.environ.get("CODE_NETWORK", "obs_code_net")
CODE_HOST_ALIAS = os.environ.get("CODE_HOST_ALIAS", "host.docker.internal")
CODE_OBS_PORT = os.environ.get("OBS_PORT", "8000")

def _resolve_docker_bin():
    env_value = os.environ.get("DOCKER_BIN", "").strip()
    if env_value:
        return env_value
    found = shutil.which("docker")
    if found:
        return found
    candidates = [
        "/usr/local/bin/docker",
        "/opt/homebrew/bin/docker",
        "/Applications/Docker.app/Contents/Resources/bin/docker",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return "docker"


DOCKER_BIN = _resolve_docker_bin()


if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    DOCKER_DIR = Path(sys._MEIPASS) / "docker"
else:
    DOCKER_DIR = Path(__file__).parent.parent / "docker"

PLOT_EXTENSIONS = {".png", ".jpg", ".jpeg", ".svg"}
PLOT_MAX_FILES = 12
PLOT_MAX_BYTES = 8 * 1024 * 1024


@dataclass
class Language:
    key: str
    label: str
    extension: str
    image: str
    run_cmd: list
    build_cmd: Optional[list] = None
    local_cmd: Optional[list] = None
    local_build_cmd: Optional[list] = None
    client_file: Optional[str] = None
    entry_name: str = "main"
    dockerfile: Optional[str] = None
    plotting: bool = False
    extras: tuple = ()

    @property
    def source_name(self) -> str:
        return f"{self.entry_name}{self.extension}"

    @property
    def built(self) -> bool:
        return self.dockerfile is not None


LANGUAGES = {
    "python": Language(
        key="python",
        label="Python",
        extension=".py",
        image="obs-code-python:2.6.0",
        run_cmd=["python", "main.py"],
        local_cmd=["python3", "main.py"],
        client_file="obs.py",
        dockerfile="python.Dockerfile",
        plotting=True,
        extras=("robust stats",),
    ),
    "javascript": Language(
        key="javascript",
        label="JavaScript (Node)",
        extension=".js",
        image="node:20-slim",
        run_cmd=["node", "main.js"],
        local_cmd=["node", "main.js"],
        client_file="obs.js",
    ),
    "java": Language(
        key="java",
        label="Java",
        extension=".java",
        image="eclipse-temurin:21-jdk",
        build_cmd=["javac", "Main.java", "Obs.java"],
        run_cmd=["java", "Main"],
        local_build_cmd=["javac", "Main.java", "Obs.java"],
        local_cmd=["java", "Main"],
        client_file="Obs.java",
        entry_name="Main",
    ),
    "c": Language(
        key="c",
        label="C",
        extension=".c",
        image="gcc:13",
        build_cmd=["gcc", "main.c", "-o", "main", "-lm"],
        run_cmd=["./main"],
        local_build_cmd=["gcc", "main.c", "-o", "main", "-lm"],
        local_cmd=["./main"],
        client_file="obs.h",
    ),
    "cpp": Language(
        key="cpp",
        label="C++",
        extension=".cpp",
        image="gcc:13",
        build_cmd=["g++", "main.cpp", "-o", "main", "-std=c++17"],
        run_cmd=["./main"],
        local_build_cmd=["g++", "main.cpp", "-o", "main", "-std=c++17"],
        local_cmd=["./main"],
        client_file="obs.hpp",
    ),
    "octave": Language(
        key="octave",
        label="Octave (MATLAB)",
        extension=".m",
        image="obs-code-octave:2.6.0",
        run_cmd=["octave", "--no-gui", "--quiet", "main.m"],
        local_cmd=["octave", "--no-gui", "--quiet", "main.m"],
        client_file="obs.m",
        dockerfile="octave.Dockerfile",
        plotting=True,
    ),
    "r": Language(
        key="r",
        label="R",
        extension=".R",
        image="obs-code-r:2.6.0",
        run_cmd=["Rscript", "main.R"],
        local_cmd=["Rscript", "main.R"],
        client_file="obs.R",
        dockerfile="r.Dockerfile",
        plotting=True,
    ),
}

BROWSER_LANGUAGES = {"html", "css", "web"}


@dataclass
class ExecutionResult:
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    duration: float = 0.0
    timed_out: bool = False
    stage: str = "run"
    artifacts: list = field(default_factory=list)
    plots: list = field(default_factory=list)
    specs: list = field(default_factory=list)


def _truncate(text: str) -> str:
    if len(text) <= CODE_MAX_OUTPUT:
        return text
    return text[:CODE_MAX_OUTPUT] + "\n[output troncato]"


class CodeRunner:
    name = "base"

    def available(self) -> tuple:
        raise NotImplementedError

    def run(self, language: Language, source: str, workdir: Path,
            token: str, stdin: str = "") -> ExecutionResult:
        raise NotImplementedError


class SubprocessRunner(CodeRunner):
    name = "subprocess"

    def available(self) -> tuple:
        return True, "esecuzione locale senza isolamento"

    def _limits(self):
        try:
            import resource
        except ImportError:
            return None

        def _apply():
            mem = CODE_MEMORY_MB * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
            resource.setrlimit(resource.RLIMIT_CPU, (CODE_TIMEOUT, CODE_TIMEOUT))
            resource.setrlimit(resource.RLIMIT_NPROC, (64, 64))
            resource.setrlimit(resource.RLIMIT_FSIZE, (32 * 1024 * 1024, 32 * 1024 * 1024))

        return _apply

    def _exec(self, cmd, workdir, env, stdin, remaining):
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(workdir),
                env=env,
                input=stdin,
                capture_output=True,
                text=True,
                timeout=remaining,
                preexec_fn=self._limits(),
            )
            return proc.returncode, proc.stdout, proc.stderr, False
        except subprocess.TimeoutExpired as e:
            out = e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
            err = e.stderr.decode() if isinstance(e.stderr, bytes) else (e.stderr or "")
            return 124, out, err, True
        except FileNotFoundError:
            return 127, "", f"comando non trovato: {cmd[0]}", False

    def run(self, language, source, workdir, token, stdin=""):
        env = dict(os.environ)
        env["OBS_TOKEN"] = token
        env["OBS_URL"] = f"http://127.0.0.1:{CODE_OBS_PORT}"
        env["HOME"] = str(workdir)

        started = time.time()

        if language.local_build_cmd:
            code, out, err, to = self._exec(
                language.local_build_cmd, workdir, env, "", CODE_TIMEOUT
            )
            if code != 0 or to:
                return ExecutionResult(
                    stdout=_truncate(out),
                    stderr=_truncate(err),
                    exit_code=code,
                    duration=time.time() - started,
                    timed_out=to,
                    stage="build",
                )

        remaining = max(1, CODE_TIMEOUT - int(time.time() - started))
        code, out, err, to = self._exec(
            language.local_cmd, workdir, env, stdin, remaining
        )
        return ExecutionResult(
            stdout=_truncate(out),
            stderr=_truncate(err),
            exit_code=code,
            duration=time.time() - started,
            timed_out=to,
            stage="run",
        )


class DockerRunner(CodeRunner):
    name = "docker"

    def available(self) -> tuple:
        if not (shutil.which(DOCKER_BIN) or os.path.exists(DOCKER_BIN)):
            return False, "Docker was not found. Install Docker Desktop and make sure it is running."
        try:
            proc = subprocess.run(
                [DOCKER_BIN, "info"],
                capture_output=True, text=True, timeout=10,
            )
        except Exception as e:
            return False, f"Docker is not responding: {e}"
        if proc.returncode != 0:
            return False, "Docker is not running"
        return True, "docker pronto"

    def image_present(self, language: Language) -> bool:
        proc = subprocess.run(
            [DOCKER_BIN, "image", "inspect", language.image],
            capture_output=True, text=True,
        )
        return proc.returncode == 0

    def ensure_network(self) -> None:
        proc = subprocess.run(
            [DOCKER_BIN, "network", "inspect", CODE_NETWORK],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            subprocess.run(
                [DOCKER_BIN, "network", "create", CODE_NETWORK],
                capture_output=True, text=True,
            )

    def _base_cmd(self, workdir: Path, token: str, name: str) -> list:
        host_gateway = f"{CODE_HOST_ALIAS}:host-gateway"
        return [
            DOCKER_BIN, "run", "--rm",
            "--name", name,
            "--network", CODE_NETWORK,
            "--add-host", host_gateway,
            "--memory", f"{CODE_MEMORY_MB}m",
            "--memory-swap", f"{CODE_MEMORY_MB}m",
            "--cpus", str(CODE_CPUS),
            "--pids-limit", "128",
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--user", "1000:1000",
            "-e", f"OBS_TOKEN={token}",
            "-e", f"OBS_URL=http://{CODE_HOST_ALIAS}:{CODE_OBS_PORT}",
            "-e", "HOME=/work",
            "-v", f"{workdir}:/work",
            "-w", "/work",
            "-i",
        ]

    def _exec(self, language, cmd, workdir, token, stdin, remaining, name):
        full = self._base_cmd(workdir, token, name) + [language.image] + cmd
        try:
            proc = subprocess.run(
                full,
                input=stdin,
                capture_output=True,
                text=True,
                timeout=remaining,
            )
            return proc.returncode, proc.stdout, proc.stderr, False
        except subprocess.TimeoutExpired as e:
            subprocess.run([DOCKER_BIN, "kill", name], capture_output=True)
            out = e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
            err = e.stderr.decode() if isinstance(e.stderr, bytes) else (e.stderr or "")
            return 124, out, err, True

    def run(self, language, source, workdir, token, stdin=""):
        ok, detail = self.available()
        if not ok:
            return ExecutionResult(
                stderr=f"Docker non disponibile: {detail}",
                exit_code=126,
                stage="setup",
            )

        if not self.image_present(language):
            return ExecutionResult(
                stderr=(
                    f"Immagine mancante: {language.image}\n"
                    f"Scaricala con: docker pull {language.image}"
                ),
                exit_code=125,
                stage="setup",
            )

        self.ensure_network()
        os.chmod(str(workdir), 0o777)

        started = time.time()
        name = f"obs-code-{uuid.uuid4().hex[:12]}"

        if language.build_cmd:
            code, out, err, to = self._exec(
                language, language.build_cmd, workdir, token, "",
                CODE_TIMEOUT, name + "-b",
            )
            if code != 0 or to:
                return ExecutionResult(
                    stdout=_truncate(out),
                    stderr=_truncate(err),
                    exit_code=code,
                    duration=time.time() - started,
                    timed_out=to,
                    stage="build",
                )

        remaining = max(1, CODE_TIMEOUT - int(time.time() - started))
        code, out, err, to = self._exec(
            language, language.run_cmd, workdir, token, stdin, remaining, name
        )
        return ExecutionResult(
            stdout=_truncate(out),
            stderr=_truncate(err),
            exit_code=code,
            duration=time.time() - started,
            timed_out=to,
            stage="run",
        )


_PULL_JOBS = {}
_PULL_LOCK = threading.Lock()


def image_size(language: Language) -> int:
    proc = subprocess.run(
        [DOCKER_BIN, "image", "inspect", language.image,
         "--format", "{{.Size}}"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        return 0
    try:
        return int(proc.stdout.strip())
    except ValueError:
        return 0


def _prepare_cmd(language: Language) -> list:
    if language.built:
        dockerfile = DOCKER_DIR / language.dockerfile
        return [
            DOCKER_BIN, "build",
            "-t", language.image,
            "-f", str(dockerfile),
            str(DOCKER_DIR),
        ]
    return [DOCKER_BIN, "pull", language.image]


def _pull_worker(language_key: str, image: str) -> None:
    language = LANGUAGES[language_key]
    proc = subprocess.Popen(
        _prepare_cmd(language),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    for line in proc.stdout:
        line = line.strip()
        if not line:
            continue
        with _PULL_LOCK:
            job = _PULL_JOBS.get(language_key)
            if job is None:
                break
            job["message"] = line[:200]
    proc.wait()

    with _PULL_LOCK:
        job = _PULL_JOBS.get(language_key)
        if job is None:
            return
        job["running"] = False
        job["exit_code"] = proc.returncode
        if proc.returncode == 0:
            job["status"] = "done"
            job["message"] = "immagine pronta"
        else:
            job["status"] = "error"


def pull_image(language_key: str) -> dict:
    language = LANGUAGES.get(language_key)
    if language is None:
        return {"started": False, "error": "linguaggio non supportato"}

    runner = DockerRunner()
    ok, detail = runner.available()
    if not ok:
        return {"started": False, "error": detail}

    if language.built:
        dockerfile = DOCKER_DIR / language.dockerfile
        if not dockerfile.exists():
            return {
                "started": False,
                "error": f"Dockerfile mancante: {dockerfile}",
            }

    with _PULL_LOCK:
        job = _PULL_JOBS.get(language_key)
        if job and job.get("running"):
            return {"started": False, "error": "operazione gia in corso"}
        _PULL_JOBS[language_key] = {
            "language": language_key,
            "image": language.image,
            "running": True,
            "status": "building" if language.built else "pulling",
            "message": "avvio",
            "exit_code": None,
            "started_at": time.time(),
        }

    thread = threading.Thread(
        target=_pull_worker, args=(language_key, language.image), daemon=True
    )
    thread.start()
    return {"started": True, "language": language_key, "image": language.image}


def pull_status(language_key: str = "") -> dict:
    with _PULL_LOCK:
        if language_key:
            return dict(_PULL_JOBS.get(language_key, {}))
        return {k: dict(v) for k, v in _PULL_JOBS.items()}


def remove_image(language_key: str) -> dict:
    language = LANGUAGES.get(language_key)
    if language is None:
        return {"removed": False, "error": "linguaggio non supportato"}

    runner = DockerRunner()
    ok, detail = runner.available()
    if not ok:
        return {"removed": False, "error": detail}

    with _PULL_LOCK:
        job = _PULL_JOBS.get(language_key)
        if job and job.get("running"):
            return {"removed": False, "error": "scaricamento in corso"}
        _PULL_JOBS.pop(language_key, None)

    shared = [
        k for k, l in LANGUAGES.items()
        if l.image == language.image and k != language_key
    ]

    proc = subprocess.run(
        [DOCKER_BIN, "image", "rm", language.image],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        return {"removed": False, "error": proc.stderr.strip()[:200]}

    return {
        "removed": True,
        "language": language_key,
        "image": language.image,
        "also_affects": shared,
    }


def cleanup() -> dict:
    runner = DockerRunner()
    ok, detail = runner.available()
    if not ok:
        return {"cleaned": False, "error": detail}

    proc = subprocess.run(
        [DOCKER_BIN, "ps", "-a", "-q", "--filter", "name=obs-code-"],
        capture_output=True, text=True,
    )
    ids = [i for i in proc.stdout.split() if i]
    for cid in ids:
        subprocess.run([DOCKER_BIN, "rm", "-f", cid], capture_output=True)

    return {"cleaned": True, "containers_removed": len(ids)}


def remove_network() -> dict:
    proc = subprocess.run(
        [DOCKER_BIN, "network", "rm", CODE_NETWORK],
        capture_output=True, text=True,
    )
    return {"removed": proc.returncode == 0}


_RUNNERS = {
    "subprocess": SubprocessRunner,
    "docker": DockerRunner,
}


def get_runner() -> CodeRunner:
    cls = _RUNNERS.get(CODE_RUNNER, DockerRunner)
    return cls()


def runner_status() -> dict:
    runner = get_runner()
    ok, detail = runner.available()
    images = {}
    if isinstance(runner, DockerRunner) and ok:
        for key, lang in LANGUAGES.items():
            images[key] = runner.image_present(lang)
    else:
        for key in LANGUAGES:
            images[key] = ok
    is_docker = isinstance(runner, DockerRunner)
    jobs = pull_status() if is_docker else {}

    languages = {}
    for key, lang in LANGUAGES.items():
        ready = images.get(key, False)
        entry = {
            "label": lang.label,
            "extension": lang.extension,
            "image": lang.image,
            "ready": ready,
            "size": image_size(lang) if (is_docker and ok and ready) else 0,
            "built": lang.built,
            "plotting": lang.plotting,
            "extras": list(lang.extras),
        }
        job = jobs.get(key)
        if job:
            entry["job"] = {
                "running": job.get("running", False),
                "status": job.get("status", ""),
                "message": job.get("message", ""),
            }
        languages[key] = entry

    return {
        "runner": runner.name,
        "available": ok,
        "detail": detail,
        "timeout": CODE_TIMEOUT,
        "memory_mb": CODE_MEMORY_MB,
        "cpus": CODE_CPUS,
        "managed": is_docker,
        "languages": languages,
    }


def collect_specs(workdir: Path) -> list:
    specs = []
    for f in sorted(workdir.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(data, dict) and "obs_plot" in data:
            specs.append(data["obs_plot"])
        if len(specs) >= PLOT_MAX_FILES:
            break
    return specs


def collect_plots(workdir: Path, source_name: str, client_file: Optional[str],
                  preesistenti: Optional[set] = None) -> list:
    skip = {source_name}
    if client_file:
        skip.add(client_file)
    if preesistenti:
        skip |= preesistenti

    found = []
    for f in sorted(workdir.rglob("*")):
        if not f.is_file():
            continue
        if f.name in skip:
            continue
        if f.suffix.lower() not in PLOT_EXTENSIONS:
            continue
        try:
            size = f.stat().st_size
        except OSError:
            continue
        if size == 0 or size > PLOT_MAX_BYTES:
            continue
        found.append((f, size))
        if len(found) >= PLOT_MAX_FILES:
            break

    plots = []
    for f, size in found:
        try:
            raw = f.read_bytes()
        except OSError:
            continue
        if f.suffix.lower() == ".svg":
            mime = "image/svg+xml"
        elif f.suffix.lower() == ".png":
            mime = "image/png"
        else:
            mime = "image/jpeg"
        plots.append({
            "name": f.name,
            "mime": mime,
            "size": size,
            "data": base64.b64encode(raw).decode("ascii"),
        })
    return plots


def execute(language_key: str, source: str, token: str,
            stdin: str = "", client_source: str = "",
            user_id: Optional[int] = None) -> ExecutionResult:
    language = LANGUAGES.get(language_key)
    if language is None:
        return ExecutionResult(
            stderr=f"Linguaggio non supportato: {language_key}",
            exit_code=2,
            stage="setup",
        )

    runner = get_runner()
    tmp = Path(tempfile.mkdtemp(prefix="obs_code_"))
    try:
        (tmp / language.source_name).write_text(source, encoding="utf-8")
        if client_source and language.client_file:
            (tmp / language.client_file).write_text(client_source, encoding="utf-8")

        prima = set()
        if user_id is not None:
            try:
                import code_files
                riservati = {language.source_name}
                if language.client_file:
                    riservati.add(language.client_file)
                code_files.copy_into(user_id, tmp, skip=riservati)
                prima = {f.name for f in tmp.iterdir() if f.is_file()}
            except Exception:
                prima = set()

        result = runner.run(language, source, tmp, token, stdin)

        try:
            result.plots = collect_plots(
                tmp, language.source_name, language.client_file, prima
            )
        except Exception:
            result.plots = []

        try:
            result.specs = collect_specs(tmp)
        except Exception:
            result.specs = []

        return result
    finally:
        shutil.rmtree(str(tmp), ignore_errors=True)
