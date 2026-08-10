# OBS - Complete guide to commands and troubleshooting

> A collection of every useful command to install, start, repair and maintain
> OBS, and of every real problem encountered so far with its step-by-step fix.
> Meant to be consulted when something goes wrong, even by someone who is not
> very comfortable with the terminal. Each section can be read on its own.
>
> Commands are for macOS/Linux. Where Windows differs, it is noted.

---

## 0. Golden rules (always read first)

1. **All project commands are run from the project folder.**
   Before anything else: `cd ~/Desktop/obs-lab`.
2. **The venv MUST be created with Python 3.11**, not with `python3` (which on the Mac
   now points to 3.13, incompatible with torch/scipy). Always use `python3.11`.
3. **After changes to `main.py`** -> restart the backend (Ctrl+C and relaunch).
   **After changes to the frontend** (`index.html`) -> just reload with Cmd+Shift+R.
4. **ALWAYS replace the entire `main.py` + `index.html` pair when you receive a new
   one, and delete the old versions.** Working on mismatched versions is the number
   one cause of phantom bugs (a frontend asking for something the backend cannot do,
   or vice versa).
5. **The API key and the `.env` file must NEVER go to git.** They are already in `.gitignore`.
6. **Always close OBS with `Ctrl+C`** in the window where it runs, waiting for the
   prompt. Do not close the terminal window abruptly: it leaves "zombie" processes on
   port 8000 and can corrupt the venv.
7. **Run `curl` commands from a second terminal window** while the backend runs in the first.

---

## 1. Normal startup

### With the desktop window (Tauri)
```bash
cd ~/Desktop/obs-lab
cargo tauri dev
```

### Backend only, viewed in the browser (more reliable)
```bash
cd ~/Desktop/obs-lab/backend
../venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8000
```
Wait for `OBS ready` and `Application startup complete`, then open the browser at
`http://localhost:8000`.

**Windows (backend only):**
```powershell
cd $HOME\Desktop\obs-lab\backend
..\venv\Scripts\python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

To stop: `Ctrl+C` in the window where it runs, and wait for the prompt.

> **When to use the browser instead of the Tauri window:** if `cargo tauri dev`
> shows `Waiting for your frontend dev server...` for a long time and then
> `Could not connect ... after 180s`, the backend has started anyway (you can see it
> from `Uvicorn running`). Open `http://localhost:8000` in the browser and work from
> there. The Tauri timeout on first launch is normal, because the models load from scratch.
>
> **Web-only mode (recommended on Mac Intel):** the "Load failed" of the Tauri window
> depends on the desktop environment, not on the code (from the browser everything works).
> To avoid it entirely, start only the backend (the "backend only" command above) and
> use OBS from the browser at `http://localhost:8000`.

---

## 2. Installing the venv from scratch (the CORRECT procedure)

To use the first time, or any time the venv breaks.

```bash
cd ~/Desktop/obs-lab
rm -rf venv
python3.11 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
python download_model.py
```

Check that the Python version is correct:
```bash
venv/bin/python --version        # must say 3.11.x
```

**spaCy models (for the entity graph).** `pip install -r requirements.txt` installs the
libraries but NOT the spaCy language models, which must be downloaded separately once:
```bash
source venv/bin/activate
python -m spacy download it_core_news_lg     # default, accurate
python -m spacy download it_core_news_sm     # optional, fast fallback for Mac Intel
```
If you forget them, OBS works but the Entities tab gives an error (see section 5c).

**New libraries from v2.3.0.** `pip install -r requirements.txt` also installs `statsmodels`
(behavioural forecasting with Holt-Winters) and `reportlab` (report export to PDF). Both are
pure Python and install on every platform. If you added the features to an older setup without
reinstalling, install them by hand into the active venv:
```bash
pip install statsmodels==0.14.2 reportlab==4.2.2
```

**The embedding model from v2.5.0.** From this version OBS uses the multilingual model
BAAI/bge-m3 at 1024 dimensions, prepared locally. The `python download_model.py` step above
downloads the weights and writes them to `backend/models/bge-m3` in safetensors format, about
2.3 GB, only the first time. On later runs the script detects the model is already present and
does nothing. The same step runs automatically from `start.sh` and `start.bat`. If you set up
an older project without this step, run it once by hand into the active venv:
```bash
source venv/bin/activate
python download_model.py
```
If the model folder is missing, OBS falls back to downloading the model from the network at
first load; keeping it local is preferred and avoids that dependency. See section 5g if the
download does not complete, and section 17 for the migration and re-indexing.

If `python3.11` gives "command not found":
```bash
brew install python@3.11         # macOS
# Linux: sudo apt install -y python3.11 python3.11-venv python3.11-dev
```

**Windows:**
```powershell
cd $HOME\Desktop\obs-lab
Remove-Item -Recurse -Force venv -ErrorAction SilentlyContinue
py -3.11 -m venv venv
venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install -r requirements.txt
python download_model.py
```

---

## 3. The corrupted venv problem (RECURRING)

**Symptoms:** at startup, errors like `ModuleNotFoundError: No module named 'uvicorn'`
/ `click._compat` / `click.core`, or "no RECORD file". It happens when
`cargo tauri dev` is interrupted abruptly (window closed by force).

**Cause:** the venv gets damaged.

**Fix:** recreate it (see section 2). Key point: use **python3.11**.
If by mistake you recreate it with `python3` and that is 3.13, you will instead see
`ERROR: No matching distribution found for torch==2.2.2`, because torch 2.2.2 does
not exist for Python 3.13. The cure is the same: recreate it with python3.11.

---

## 4. WARNING: deleting folders with `rm -rf` (real, serious mistake)

A command to handle with the utmost care: `rm -rf` deletes without asking and without
a trash bin. A real mistake that already happened: wanting to delete a folder called
`venv2` and typing

```bash
rm -rf venv 2        # WRONG: the space creates TWO targets, "venv" and "2"
```

The space makes `rm` delete **two** things: `venv` (the good one!) and a hypothetical
`2`. Result: the working venv is lost.

**Rules to avoid mistakes:**
- If the name has a space, it must be quoted: `rm -rf "venv 2"`.
- If the name has NO spaces, write it joined: `rm -rf venv2`.
- Before an `rm -rf`, check what is really there: `ls -d venv*`.

**If you have already deleted the venv by mistake:** no data is lost (documents and
indexes are in `data/`, not in the venv). Just recreate it with section 2. The folder
with the space is removed with `rm -rf "venv 2"`.

---

## 5. The missing hdbscan problem (RECURRING)

**Symptom:** the backend starts, but pressing "Run clustering" (documents or images)
gives `500 Internal Server Error` and in the log
`ModuleNotFoundError: No module named 'hdbscan'`.

**Cause:** `hdbscan` historically was not in `requirements.txt`.

**Immediate fix:**
```bash
cd ~/Desktop/obs-lab
source venv/bin/activate
pip install hdbscan
```
then restart the backend.

**Permanent fix:** `hdbscan` is now in `requirements.txt`, so a clean install already
includes it.

> Reminder: `umap-learn` does NOT install on Mac Intel (numba/llvmlite/CMake
> fail). OBS uses PCA, which does not require umap. Do not try to install it.
>
> From v2.3.0 UMAP is an optional switch, not a requirement. If you are on hardware
> where it installs (not Mac Intel), you may run `pip install umap-learn==0.5.6` and set
> `OBS_USE_UMAP=1` in the `.env` to use it for the clustering projection; OBS falls back to
> PCA automatically when it is absent, so nothing breaks if you leave it out.

---

## 5b. Clustering gives 500 with "force_all_finite" (scikit-learn / hdbscan conflict)

**Symptom:** the backend starts, but pressing "Run clustering" gives
`500 Internal Server Error` and in the log:
`TypeError: check_array() got an unexpected keyword argument 'force_all_finite'`.

**Cause:** it is a VERSION conflict, not a code bug. Recent versions of
scikit-learn (1.4 onward) REMOVED the `force_all_finite` parameter, which however
`hdbscan` still uses. It typically happens after recreating the venv, if a version
of scikit-learn that is too new gets pulled in (e.g. 1.9.0).

**Fix:** install compatible versions in the active venv, then restart:
```bash
cd ~/Desktop/obs-lab
source venv/bin/activate
pip install "scikit-learn==1.3.2" "scipy==1.11.4"
```

**Permanent fix:** `requirements.txt` now pins `scikit-learn==1.3.2` and
`scipy==1.11.4` (compatible with `hdbscan==0.8.40`), so a clean install does not
bring the problem back. If in the future you upgrade scikit-learn past 1.3.x, clustering
will break again until hdbscan ships a fix: in that case, go back to these versions.

---

## 5c. The entity graph gives 500/503 (spaCy, jellyfish or model missing)

**Symptom:** in the Entities tab, pressing "Build graph" gives an error. Three variants,
each with its precise cause in the log:

- `ModuleNotFoundError: No module named 'jellyfish'` -> the jellyfish library is missing
  (Jaro-Winkler for entity resolution).
- `503` with a message that spaCy is unavailable -> the LANGUAGE MODEL is missing
  (the spaCy download is separate from the library).
- `NameError: name '_cluster_project_3d' is not defined` -> the `main.py` is not the latest
  version. Replace it with the updated one (it must contain the function
  `_cluster_project_3d`); check with `grep -c "def _cluster_project_3d" main.py` -> must return 1.

**Cause:** the two libraries (`spacy`, `jellyfish`) are in `requirements.txt`, but the
spaCy MODEL is not a pip package and must be downloaded separately, once.

**Immediate fix** (venv active):
```bash
cd ~/Desktop/obs-lab
source venv/bin/activate
pip install spacy jellyfish
python -m spacy download it_core_news_lg     # default
python -m spacy download it_core_news_sm     # fast fallback for Mac Intel
```
then restart the backend.

**Mac Intel note:** `it_core_news_lg` is accurate but slow on your hardware. To go
faster, set `SPACY_MODEL=it_core_news_sm` in `backend/.env` (see section 6). The small
model catches fewer entities and is less precise on types: it is a trade-off, not a
permanent downgrade. On the powerful machine, leave `lg`.

**numpy note:** after installing spaCy, check that numpy is STILL `1.26.4`
(`pip show numpy | grep Version`). If spaCy pulled it to a newer version, put it back
with `pip install "numpy==1.26.4"`, otherwise torch/faiss/scipy can break.

**Permanent fix:** `spacy==3.8.14` and `jellyfish==1.2.1` are pinned in
`requirements.txt`; only the model download remains, which must be done by hand the first
time (there is no way to put it in pip). If the graph is slow on large archives, that is
expected on the first build: from v2.3.0 the extracted entities of each document are cached on
disk, so later builds reuse the cache and are faster; the cache of a document is cleared when
that document is deleted.

---

## 5d. Forecast or PDF export fails (statsmodels / reportlab missing)

**Symptom:** the Forecast (Holt-Winters) analysis fails with `No module named 'statsmodels'`,
or exporting a report to PDF fails with `No module named 'reportlab'`.

**Cause:** these two libraries were added in v2.3.0 and are not present in an older venv.

**Fix:** with the venv active, install them and restart the backend:
```bash
pip install statsmodels==0.14.2 reportlab==4.2.2
```
Both are in `requirements.txt`, so a clean install already includes them. LaTeX and Markdown
export need nothing extra; only PDF export uses `reportlab`.

**Update (statsmodels / pandas version incompatibility):** it can happen that statsmodels is
installed but Forecast still fails, with an error like
`deprecate_kwarg() missing 1 required positional argument` or with the message "the forecast
module (statsmodels) is installed but does not load". This is not a missing module: it is a
conflict between `statsmodels==0.14.2` and `pandas==3.0.3`. statsmodels 0.14.2 imports an
internal function from pandas that pandas 3.x changed. The fix is to use `statsmodels==0.14.6`,
which is compatible with pandas 3.0.3 and is already listed in `requirements.txt`. With the
venv active:
```bash
pip install --no-cache-dir "statsmodels==0.14.6"
```
Then verify before restarting OBS:
```bash
python -c "from statsmodels.tsa.holtwinters import ExponentialSmoothing; print('OK')"
```
If it prints `OK`, restart the backend and Forecast works. Note: the Forecast error message now
distinguishes "statsmodels missing" from "statsmodels present but failing to load", showing the
real error in the latter case instead of generically saying "not installed".

---

## 5e. Digitized charts disappeared after restart (fixed in v2.3.0)

**Symptom (old behaviour):** a chart saved from the Digitize section appeared in the
"Digitized charts" folder during the session, then vanished after closing and reopening OBS.

**Cause:** the saved dataset was kept in memory but its reference was never written to disk on
save, so a restart lost it.

**Fix:** resolved in v2.3.0. Saving a digitized dataset now writes it to disk immediately, so it
persists across restarts. Note that charts saved with an older version cannot be recovered
(their reference was never stored); re-digitize and save them again. To confirm the running
backend has the fix, from the project root run `grep -n "index.add(summary_vec)" backend/main.py`
and check it returns a line.

---

## 5f. The Investigate board shows coloured squares instead of icons (from v2.4.0)

**Symptom:** in the Investigate section the entities appear as coloured squares with a letter, not as icons.

**Cause:** this is the intended fallback when the icon files are absent. The board reads its icons from `frontend/icons`, served at the `/icons/` path, and shows the square fallback whenever a file is missing.

**Fix (optional):** create the folder and add three PNG files with these exact names, then reload:
```bash
# from the project root
mkdir -p frontend/icons
# copy obs_person.png, obs_org.png, obs_place.png into frontend/icons
```
`obs_person.png` is for people, `obs_org.png` for organisations, `obs_place.png` for places; an optional `obs_entity.png` covers other types. You can download any icons (for example from https://win98icons.alexmeub.com/) and rename them to these names. The board keeps working without the icons, so this step is purely cosmetic.

---

## 5g. The embedding model does not download or OBS will not start (from v2.5.0)

**Symptom:** at startup the log stops at the embedding model, or `python download_model.py` ends with "Download incomplete", or the server exits with an error about `model.safetensors` not found, or a `torch.load` / CVE message about torch below 2.6.

**Cause:** OBS uses BAAI/bge-m3, whose main branch on Hugging Face ships the weights only as `pytorch_model.bin`. The installed transformers refuses to load a `.bin` file with torch below 2.6, and the large file is served through Xet, which some networks cannot fetch cleanly. The `download_model.py` script handles all of this: it disables Xet, downloads the `.bin`, converts it to `model.safetensors` locally, and removes the `.bin`. The conversion reads the weights with `torch.load(weights_only=True)`, which works on torch 2.2.2.

**Fix:** remove any partial model folder and run the script again from the project root, with the venv active:
```bash
rm -rf backend/models/bge-m3
source venv/bin/activate
python download_model.py
```
Windows:
```powershell
Remove-Item -Recurse -Force backend\models\bge-m3 -ErrorAction SilentlyContinue
venv\Scripts\Activate.ps1
python download_model.py
```
A correct run shows the config files, then `Downloading the weights (pytorch_model.bin)`, then `Converting the weights to safetensors format`, and finally `Model BGE-M3 ready`. The download is a few minutes and about 2.3 GB. If it stops midway, run the same command again: it resumes the missing files without re-downloading those already present. Once `backend/models/bge-m3/model.safetensors` exists, OBS loads the model from disk with no network access.

---

## 6. The .env file: creating it, reading it, fixing it

The `.env` lives in `backend/`, next to `main.py`. It does not exist until you create it,
and it is hidden (starts with a dot). It holds the LLM model configuration.

### Create it from scratch (overwrites, no duplicates)
```bash
cd ~/Desktop/obs-lab/backend
cat > .env << 'EOF'
LLM_BACKEND= *your model*
LOCAL_MODEL= e.g. qwen2.5:1.5b
REPORT_MAX_TOKENS=700
LLM_TIMEOUT=900
EOF
```

> Use `>` (single arrow) which **overwrites** the whole file. Do NOT use `>>` (double
> arrow) to "update" a value: that APPENDS at the end and creates duplicate lines
> (e.g. two `local_MODEL`), which cause confusion. To change existing values,
> rewrite the file from scratch as above, or open it in an editor: `open -e .env`.

> Optional variable `SPACY_MODEL` (entity graph): chooses the spaCy model.
> Default `it_core_news_lg`. On Mac Intel, to go faster, add the line
> `SPACY_MODEL=it_core_news_sm`. Requires the model to have been downloaded already (section 2).

> Optional variable `OBS_USE_UMAP` (clustering projection, from v2.3.0): when set to `1` and the
> `umap-learn` library is installed, OBS uses UMAP instead of PCA to lay out the clustering map.
> Unset or `auto` means: use UMAP if present, otherwise PCA. On Mac Intel leave it out, since
> `umap-learn` does not install there and PCA is used anyway.

### Cross-origin access: the OBS_CORS_ORIGINS variable

The backend only accepts browser requests coming from an explicit list of origins. The
list is read from `OBS_CORS_ORIGINS` (comma-separated). When the variable is absent, the
default is `http://localhost:8000,http://127.0.0.1:8000`, which is exactly how you open
OBS in local use. So in local use you do NOT need to set anything: it already works.

You only set this variable when the frontend is served from an origin DIFFERENT from the
API (a different domain or port). In that case list the trusted origins:
```bash
OBS_CORS_ORIGINS=https://obs.yourdomain.com
```
More than one origin, separated by commas, no spaces:
```bash
OBS_CORS_ORIGINS=https://obs.yourdomain.com,https://admin.yourdomain.com
```

> An origin must match EXACTLY: scheme, host and port. `https://obs.yourdomain.com` and
> `http://obs.yourdomain.com` are two different origins, and so are the versions with and
> without `www`. If in production something does not connect via CORS, nine times out of
> ten it is one of these three parts that does not match.

> Never go back to the wildcard `*` together with cookie login. With session cookies each
> origin must be listed explicitly: a wildcard plus credentials lets any site read the
> response using the victim's session. If you ever feel you need to "open to everyone",
> that is the signal to rethink the setup, not to use the wildcard.

To check what the server answers to an arbitrary origin (it must NOT echo it back):
```bash
curl -s -I -H "Origin: https://some-random-site.com" http://localhost:8000/api/status | grep -i access-control-allow-origin
```
If the `access-control-allow-origin` line is absent, or shows an origin other than the one
you sent, you are fine: the server is refusing an origin that is not in the allowlist. If
you see `https://some-random-site.com` echoed back, that origin is allowed and must be
removed from the list.

> Where to set it: put `OBS_CORS_ORIGINS` in the `.env` like the other variables, or export
> it in the service environment (systemd `Environment=`, `docker run -e`). Either way the
> `.env` is already kept out of git (see section 10), so production domains do not end up
> in the repository.

### Read it
```bash
cat .env                 # macOS/Linux
# Get-Content .env       # Windows PowerShell
```
Each variable must appear ONLY once.

### Verify it is actually read
At startup the backend prints a config line. Look for it in the log:
```
LLM config -> backend= *name*, model_name= e.g. qwen2.5:1.5b, api_key=none, timeout=900s, report_tokens=700
```
If this line shows values different from those in the `.env`, the file was not read
(or has duplicates). From OBS v2.1.0 the `.env` loading (`load_dotenv`) is included in the
code; if it is missing in an old version, update `main.py`.

### Recommended values by machine type (e.g.)
- **Mac Intel / slow CPU:** small model, short report, long timeout.
  `LOCAL_MODEL= (e.g.) qwen2.5:1.5b`, `REPORT_MAX_TOKENS=700`, `LLM_TIMEOUT=900`.
- **Powerful machine / GPU:** large model, long report, short timeout.
  `LOCAL_MODEL=(e.g.) qwen2.5:7b` (or `:14b`), `REPORT_MAX_TOKENS=2500`, `LLM_TIMEOUT=300`.
- **api (cloud):** `LLM_BACKEND=*model name*`, `API_KEY=...-...-...`,
  `REPORT_MAX_TOKENS=...`, `LLM_TIMEOUT=...`.

---

## 7. E.g. Ollama: installing and using the local model

Ollama is NOT an API with a key: it is a program that runs on your computer. The data
stays local.

```bash
# install (macOS, via Homebrew)
brew install ollama

# start the server (needed BEFORE downloading models)
brew services start ollama          # as a background service, restarts at login
# or, in a dedicated window:  ollama serve

# download a model
ollama pull qwen2.5:1.5b            # lightweight, for Mac Intel 8GB
ollama pull qwen2.5:7b             # more powerful, for machines with more RAM/GPU

# see the downloaded models (with the EXACT name to put in the .env)
ollama list

# try the model directly, without OBS
ollama run qwen2.5:1.5b "hi, who are you?"
```

**Error "could not connect to ollama server":** the server is not started. Run
`brew services start ollama` (or `ollama serve` in another window) and retry the pull.

**Direct test of the Ollama API** (useful to tell whether a problem is Ollama's or
OBS's), from a second window:
```bash
curl http://localhost:11434/api/chat -d '{"model":"qwen2.5:1.5b","messages":[{"role":"user","content":"hi"}],"stream":false}'
```
If it answers with some text, Ollama is fine and the model is there. If it says "model not found",
download the model. The name in the command must match `ollama list`.

---

## 8. REPORT troubleshooting (all cases seen)

The source-anchored report requires an active LLM (local or api, in offline it does
not work). Here are the errors encountered, in order, with cause and cure.

### "HTTP Error 404: Not Found"
**Cause:** OBS asks Ollama for a model that does not exist with that name. Typical when
the `.env` is not read and OBS uses the code default (`qwen2.5:7b`) that you have not
downloaded; or the name in the `.env` does not match `ollama list`.
**Cure:** compare `ollama list` with the `OLLAMA_MODEL` line of the `.env`; align them
exactly. Verify that the `.env` is read (the `LLM config ->` line in the log,
section 6). If the direct curl test (section 7) works but OBS does not, the problem is
almost always the `.env` not read or a `main.py` not updated.

### "timed out" (TimeoutError)
**Cause:** the model takes longer than the allowed time (`LLM_TIMEOUT`). Typical with
the small model on CPU when a long report is requested.
**Cure:** in the `.env`, lower `REPORT_MAX_TOKENS` (a shorter report to generate) and raise
`LLM_TIMEOUT` (more margin). For Mac Intel: `REPORT_MAX_TOKENS=700`, `LLM_TIMEOUT=900`.
Then restart the backend. Let it work: with the small model the report still takes
one to two minutes, that is normal, it is not stuck.

### "Load failed"
**Cause:** the frontend cannot reach the backend (backend not started, or the
window left disconnected after a pile-up of processes).
**Cure:** verify that the backend responds:
```bash
curl http://localhost:8000/api/status
```
If it responds with data, the backend is alive: close the OBS window and reopen it (or use
the browser at `http://localhost:8000`). If it does not respond, restart the backend after
freeing the port (section 9).

### The report text is rough / ungrammatical / cuts off
**Cause:** it is the limit of the small model (e.g. `qwen2.5:1.5b`) on CPU, not a bug. Imperfect
sentences, repetitions, and truncation at the end of the report (because of the `REPORT_MAX_TOKENS` cap).
**Cure:** it is expected. For a quality report to show, use a larger model
(`qwen2.5:7b` or higher) on a powerful machine, or public api. The structure, the
citations and the verification work anyway: that proves the mechanism is correct.

---

## 9. The occupied port 8000 / zombie processes problem (RECURRING)

**Symptom:** at startup `ERROR: [Errno 48] error while attempting to bind on address
('0.0.0.0', 8000): address already in use`. Or the report keeps behaving in a
strange way because an old backend instance is answering.

**Cause:** a backend from a previous launch stayed alive (not closed with Ctrl+C) and
keeps port 8000 occupied.

**Cure:** kill the zombie process and start again, waiting for the port to free up.
```bash
lsof -ti:8000 | xargs kill -9       # kills the process on port 8000
sleep 3                              # gives the system time to free the port
lsof -ti:8000                        # MUST print empty; if it prints a number, repeat the kill
cd ~/Desktop/obs-lab
cargo tauri dev                      # or backend-only startup (section 1)
```

**Windows (cmd.exe):**
```text
for /f "tokens=5" %a in ('netstat -aon ^| findstr :8000') do taskkill /F /PID %a
```

> The rule that prevents all this: ALWAYS close with `Ctrl+C` and wait for the prompt.

---

## 10. Git - commit and push (dual remote)

```bash
cd ~/Desktop/obs-lab
git status
git add .
git commit -m "clear message of what changed"
git push && git push obs main        # push to both repos (origin + obs)
```

### Safety check BEFORE pushing (IMPORTANT)
Verify that private data and the key do NOT end up on git:
```bash
git ls-files | grep -i "images/\|data/\|.env"
```
If it prints NOTHING, you are fine. If it prints something, it must be removed from tracking:
```bash
git rm -r --cached data/             # removes from git but leaves the files on disk
git commit -m "Remove private data from tracking"
```
What stays out of git (already in `.gitignore`): `.env`, `data/`, `venv/`,
`__pycache__/`, `target/`, `.DS_Store`, chat history.

### Full commit in one shot (ready block, with safety check)
This block does everything: it protects `OBS_HANDOFF.md` (keeps it out of git), STOPS by
itself if it is about to commit private files (`.env`, `data/`, `images/`), shows what it
is about to commit, creates the commit with today's date, and pushes to the two remotes.
Paste it all together in the terminal. **Before pasting, change the number in the `FIX_NUMBER=`
line** with the current fix number (otherwise you always commit "fix #1").

```bash
cd ~/Desktop/obs-lab
FIX_NUMBER=1
grep -qxF "OBS_HANDOFF.md" .gitignore || echo "OBS_HANDOFF.md" >> .gitignore
if git status --short | grep -Ei '(^|[ /])\.env|data/|images/' | grep -qv '\.gitignore'; then
  echo "STOP: private files in the commit, aborted."
  git status --short | grep -Ei '(^|[ /])\.env|data/|images/'
else
  git add .
  echo "--- Files that will be committed: ---"
  git status --short
  git commit -m "obs $(date +%d/%m/%Y) fix #${FIX_NUMBER}"
  git push && git push obs main
  echo "--- Commit finished. ---"
fi
```

> Note: do not put comments ending with characters like `<` or `>` inside the
> block: zsh interprets them as redirections and gives `parse error`. That is why here the
> comments are kept separate from the code.
>
> When the block shows "Files that will be committed", it is your last verification
> look: it must contain only `main.py`, `index.html`, the public `.md` files, the
> `.gitignore` and the test datasets. If you see `OBS_HANDOFF.md`, `.env` or `data/`,
> stop and check.

### Reset history - one clean commit (occasional, not daily)
Two scripts now live in the project folder, and you pick one depending on what you want:

- `./obs_commit.sh` - **everyday use.** Adds your changes as a new commit and pushes
  to both repos. The history grows normally, one commit on top of the others.
- `./obs_reset_history.sh` - **occasional use.** Replaces the entire history with a
  single clean commit dated today, then force-pushes to both repos. Every previous
  commit disappears from view. Use it only when you deliberately want to wipe the
  history, not for daily work.

```bash
cd ~/Desktop/obs-lab
./obs_reset_history.sh        # makes a backup, asks you to type PUBBLICA before pushing
```

> In one line: `obs_commit.sh` adds to the history, `obs_reset_history.sh` restarts it
> from zero. The reset is destructive and irreversible online, so it makes a full backup
> first and waits for an explicit `PUBBLICA` confirmation. After a reset you will find
> `obs-lab_backup_...` folders next to the project: delete the old ones when you are
> sure everything is fine.

### Wrong commit author (old profile instead of the new one)
On git, the author of a commit depends on the local configuration (`user.name` and
`user.email`), not on the account you push with. If commits show the
wrong profile:
```bash
cd ~/Desktop/obs-lab
git config user.name                 # see what is there now
git config user.email
# fix (only for this project):
git config user.name "Matteo Gandolfi"
git config user.email "292758417+matteo-gandolfi@users.noreply.github.com"
```
The email must be one of those registered on the correct GitHub profile (the "noreply"
email that GitHub provides in Settings > Emails works fine and does not expose your
real email). This fixes **future** commits; past ones stay attributed
as they were (rewriting history is more invasive and usually not worth it).

---

## 11. Quick endpoint tests (curl)

From a SECOND terminal window, with the backend running.

```bash
# system status
curl http://localhost:8000/api/status

# LLM backend status (which one is active and which are available)
curl http://localhost:8000/api/llm/status

# list documents / images / folders
curl http://localhost:8000/api/documents
curl http://localhost:8000/api/images
curl http://localhost:8000/api/folders

# create a folder
curl -X POST http://localhost:8000/api/folders \
  -H "Content-Type: application/json" -d '{"name":"Test"}'

# move a document into a folder (item_type: document|image)
curl -X POST http://localhost:8000/api/folders/assign \
  -H "Content-Type: application/json" \
  -d '{"item_type":"document","item_id":"<DOC_ID>","folder_id":"<FOLDER_ID>"}'

# take a file out of a folder (folder_id null)
curl -X POST http://localhost:8000/api/folders/assign \
  -H "Content-Type: application/json" \
  -d '{"item_type":"image","item_id":"<IMG_ID>","folder_id":null}'

# generate a report (requires an active LLM)
curl -X POST http://localhost:8000/api/report \
  -H "Content-Type: application/json" \
  -d '{"query":"What is the financial situation of the organisations?"}'

# system detail, including the reindex block (index size vs configured size)
curl http://localhost:8000/api/system/status-detail

# re-index the whole archive with the current embedding model (developer/admin)
curl -X POST http://localhost:8000/api/system/rebuild-index

# add page and box positions to PDFs already in the archive (developer/admin)
curl -X POST http://localhost:8000/api/system/reprocess-positions
```

> From v2.3.0 the report can be exported in three formats from the interface (Markdown, LaTeX,
> PDF) and can be edited in place, with the citations re-verified on save. The export endpoint is
> `POST /api/report/export` with a `format` field of `md`, `tex`, or `pdf`; re-verification of an
> edited report is `POST /api/report/reverify`.

> From v2.5.0 two administrative endpoints support the embedding migration: `POST
> /api/system/rebuild-index` re-embeds every stored chunk with the current model and rebuilds the
> FAISS index, and `POST /api/system/reprocess-positions` adds page and box positions to PDFs that
> were ingested before citation anchoring. Both are restricted to developer and admin roles. The
> `reindex` block returned by `GET /api/system/status-detail` tells you whether a rebuild is needed
> (index vectors fewer than stored chunks, or index size different from the configured one).

---

## 12. Cleanup and maintenance

```bash
# empty the compiled Python cache (harmless)
find . -name "__pycache__" -type d -exec rm -rf {} +

# see how much the data weighs
du -sh data/

# free the venv and rebuild it (see section 2)
rm -rf venv && python3.11 -m venv venv && source venv/bin/activate && \
  pip install -r requirements.txt
```

---

## 13. Diagnosis: how to read an error

- **Error in the terminal where the backend runs** (long, with "Traceback"): it is a
  server-side Python problem. The last line of the traceback says the type of error.
  E.g. `No module named 'X'` -> a library is missing (`pip install X`); `TimeoutError` ->
  the model is too slow (section 8); `404` -> Ollama model missing (section 8).
- **Error in the browser console** (right click > Inspect > Console): it is a
  frontend problem (JavaScript).
- **500 Internal Server Error** over the network: the backend raised an exception, look at
  its terminal for the traceback.
- **The page does not refresh after a frontend change:** Cmd+Shift+R (reload
  ignoring the cache).
- **In doubt whether the backend is alive:** `curl http://localhost:8000/api/status`. If
  it responds, it is up; if "connection refused", it is off.

---

## 14. Checklist: "the report does not work", in order

Follow it from top to bottom; stop as soon as one step solves it.

1. Is the local model started? `brew services start *model name (e.g. ollama)*`.
2. Is the model downloaded? `*model name* list` (must list the model from the `.env`).
3. Does the model respond on its own? curl test from section 7.
4. Does the `.env` exist and is it correct? `cat backend/.env`.
5. Is the `.env` read? The `LLM config ->` line in the log at startup (section 6).
6. Is the backend the latest version? It must have `load_dotenv` and `/api/report`.
7. Is there no zombie backend? `lsof -ti:8000` and, if needed, kill (section 9).
8. Clean startup (`Ctrl+C`, wait, relaunch).
9. If still "timed out": shorter report and longer timeout in the `.env` (section 8).

---

## 15. Authentication and users (login, roles, recovery)

OBS requires a login from v2.1.0. Login is by email and password; each user sees only
their own documents and images. Three roles: developer (owns everything), admin (one
company), user (own material only). Users and sessions live in `data/auth.db`; the
access log is in `data/access_log.jsonl`. The only new library is `bcrypt`, already in
`requirements.txt`.

### First developer account (bootstrap)
At the first startup with an empty database, OBS creates the developer account from four
lines in `backend/.env`:

```text
DEV_EMAIL=you@company.com
DEV_PASSWORD=ChangeThisPasswordNow
DEV_USERNAME=Your Name
DEV_AZIENDA=
```

The startup log confirms it the first time. After that, those lines are unused and you
may remove `DEV_PASSWORD`.

### The command-line tool (the way back in)
Run from `backend/` with the venv active. This is the recovery path when the interface
is not available or you are locked out.

```bash
cd backend

# list all users (id, email, role, company, active, locked)
python obs_admin.py list

# create a user (--temp forces a password change at first login)
python obs_admin.py create mario.rossi@acme.com "Mario Rossi" temp123 --role user --azienda ACME --temp

# create a developer (no company needed)
python obs_admin.py create you@company.com "Your Name" yourpassword --role developer

# reset a password (the user must change it at next login)
python obs_admin.py reset-password mario.rossi@acme.com newtemp123

# unlock an account locked by too many failed attempts
python obs_admin.py unlock mario.rossi@acme.com

# activate / deactivate (a deactivated user cannot log in)
python obs_admin.py activate mario.rossi@acme.com
python obs_admin.py deactivate mario.rossi@acme.com

# change role
python obs_admin.py set-role mario.rossi@acme.com admin

# restore yourself to developer, active and unlocked
python obs_admin.py promote-developer you@company.com

# delete a user (asks to type ELIMINA to confirm)
python obs_admin.py delete mario.rossi@acme.com
```

### Key-protected developer recovery

Besides `promote-developer`, which acts without protection and is meant for server-side
emergencies, there is the `recover` command, protected by a secret key. It resets the
password of a developer account only for someone who knows the key, and acts on developers
only.

The key is set once in the environment, named `OBS_RECOVERY_KEY`. While the key is not set,
the `recover` command is disabled and refuses to run.

```bash
export OBS_RECOVERY_KEY=a-long-secret-phrase-you-choose
```

To make it permanent add the same line at the end of `backend/.env`, or to the server shell
profile, so it is always present at startup. To change it, replace the value and restart the
backend; the old value stops working at once. Keep the key somewhere safe, separate from the
account passwords.

Recovery runs from `backend/` with the venv active. The key and the new password are asked on
screen, so they do not stay in the terminal history:

```bash
cd backend
python obs_admin.py recover you@company.com
```

The command asks for the recovery key, then the new temporary password twice. If the key
matches `OBS_RECOVERY_KEY` and the email belongs to a developer, the password is reset and a
permanent one is requested at first login. If the key is missing or wrong, or the email is
not a developer, the operation is refused.

### Protecting the last developer

From v2.6.0 the system prevents ending up with no active developer. The last remaining active
developer cannot be deleted, deactivated, or demoted: the operation is blocked with a message
inviting you to create another one first. The protection applies both from the interface and
from the tools, and covers every path (deletion, deactivation, role change). To truly remove a
developer, create a second one first, then act on the first. The strongest safeguard remains
keeping two developer accounts at all times, with their credentials stored separately.

### Sessions and lockout (the tunable values)
Sessions last eight hours of inactivity on a sliding timer: any action pushes the expiry
forward, so an active user is never logged out; closing the app or going idle past the
limit ends the session. Five wrong passwords lock the account for fifteen minutes, after
which it unlocks itself. The three values live at the top of `backend/auth.py`:

```python
SESSION_IDLE_HOURS  = 8
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES     = 15
```

Change the number, save, restart the backend.

### Common auth problems
- **`ModuleNotFoundError: No module named 'bcrypt'`**: wrong venv. Check `which python`
  points inside the project's `venv`, then `pip install bcrypt==4.2.1` if needed.
- **Login never succeeds / no developer exists**: the `.env` bootstrap lines were missing
  at first start. Create the account with the tool above.
- **Buttons missing in the desktop app**: confirm `frontend/obs_auth_frontend.js` exists
  and that `index.html` loads it right before `</body>`, then hard-reload.
- **Confirmation dialog never shows in the Tauri window**: native dialogs do not appear in
  Tauri; the current `obs_auth_frontend.js` uses in-app dialogs, so make sure it is the
  latest version.

---

## 16. Server deploy (Windows / Linux) and dependency portability

This section applies when OBS is moved from the development Mac to a server, typically Windows
or Linux. The goal is to avoid the compilation ordeal seen on Mac Intel.

**Why Mac Intel needed compilation (cmake / llvm) and the server does not.** The chain
`umap-learn` -> `numba` -> `llvmlite` needs precompiled binaries (wheels). For
`llvmlite==0.48.0` ready wheels exist for Windows (`win_amd64`), Linux (`manylinux x86_64`)
and Mac Apple Silicon, but NOT for Mac Intel. Only on Mac Intel does pip have to compile from
source, and that is where `cmake` and `llvm` are needed. On a Windows or Linux x86_64 server
with Python 3.11 those wheels already exist, so the install compiles nothing and needs no
system tools.

**Key requirement: exactly Python 3.11.** All versions in `requirements.txt` are tested on
Python 3.11. On other versions (3.12, 3.13) some pinned wheels may not exist and pip would try
to compile. Install Python 3.11 on the server first.

**Procedure on Linux (x86_64):**
```bash
sudo apt install -y python3.11 python3.11-venv python3.11-dev
cd /path/to/obs-lab
python3.11 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install --no-cache-dir -r requirements.txt
python -c "from statsmodels.tsa.holtwinters import ExponentialSmoothing; print('OK')"
```

**Procedure on Windows (PowerShell):**
```powershell
# first install Python 3.11 from python.org (tick "Add to PATH")
cd C:\path\to\obs-lab
py -3.11 -m venv venv
venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install --no-cache-dir -r requirements.txt
python -c "from statsmodels.tsa.holtwinters import ExponentialSmoothing; print('OK')"
```

**Verifying the install (applies on every system).** After installing, with the venv active,
check that the critical packages import without errors:
```bash
python -c "import numpy, pandas, scipy, faiss, hdbscan, statsmodels, spacy, torch; print('base import OK')"
python -c "import spacy; spacy.load('it_core_news_lg'); print('spaCy model OK')"
python -c "from statsmodels.tsa.holtwinters import ExponentialSmoothing; print('Holt-Winters OK')"
```
If all three print OK, the environment is healthy and the features (search, clustering, entity
graph, forecast) will start without the dependency errors seen in development.

**Note on cmake / llvm.** Needed ONLY on Mac Intel. On Windows and Linux do not install them:
they are not needed and are unrelated to the server deploy.
---

## 17. The embedding model and re-indexing (from v2.5.0)

This section explains the embedding migration and how to re-index the archive after it.

**What changed.** OBS moved its embedding model from the previous multilingual model at 768
dimensions to BAAI/bge-m3 at 1024 dimensions. Search, clustering and the placement of entities
all rest on these vectors, so a stronger model improves every one of them at once. The model is
prepared locally by `download_model.py` (see section 2) and loaded from `backend/models/bge-m3`
with no network access.

**Why re-indexing is needed.** Changing the model changes the vector size, from 768 to 1024. A
FAISS index has a fixed dimension, so the old index cannot hold the new vectors. On startup OBS
compares the size of the saved index with the configured one; if they differ it does not load the
old index, keeps the stored chunks in memory, and logs that a rebuild is needed. The archive text
in `chunks.json` is untouched, so re-indexing starts from the stored text and does not re-ingest
the original files. This is true for every source format, not only PDF, because the chunk text is
already plain text once ingested.

**How to re-index.** With the backend running and a developer or admin account:
```bash
# check whether a rebuild is needed
curl http://localhost:8000/api/system/status-detail

# rebuild the index with the current model
curl -X POST http://localhost:8000/api/system/rebuild-index
```
The rebuild re-embeds every stored chunk with bge-m3 and writes a fresh 1024-dimension index.
Clustering and the entity graph read their vectors from the index, so they use the new vectors
automatically once the rebuild is done, with nothing else to run. The first rebuild over a large
archive is slower than before, because bge-m3 is heavier on CPU; it is a one-time cost of the
migration, not of everyday search.

**PDF citation positions.** Documents ingested before citation anchoring have no page positions.
To add them without re-ingesting the PDFs:
```bash
curl -X POST http://localhost:8000/api/system/reprocess-positions
```
This reads the stored PDFs, computes page and box for each chunk, and saves them. It does not
touch the embeddings and is independent of the rebuild above.

**If the model itself will not load,** the problem is the download, not the index: see section 5g.

## 18. Bulk ingestion: loading a whole folder at once (from v2.6.0)

Uploading documents one at a time from the interface is fine for a handful of files. For a real
archive there is `backend/obs_bulk_ingest.py`, which ingests an entire folder tree.

**Important: this is not the same as copying the `data` folder.** Copying `data` moves an
already-processed state from one OBS installation to another. Bulk ingestion starts from raw
documents and does the whole job (extraction, chunking, embedding, indexing): the work happens
either way, you simply do not do it by hand file by file.

### How to organise the documents

The script derives the metadata from the folder structure, because nobody is going to declare an
organisation and a folder by hand for a thousand files:

```
client_archive/
  Alpha Energia/          <- 1st level folder = the "azienda" field
    Contracts/            <- subfolder = OBS folder
      contract1.pdf
      contract2.pdf
    Financials/
      report2025.pdf
  Beta Logistica/
    shipping.pdf          <- org Beta, folder "Beta Logistica"
```

Files left in the root have no organisation: the script stops and says so. Either move them into a
subfolder, or pass `--azienda "Name"`.

### Usage

Accepted formats: pdf, txt, docx, doc, md, csv, xlsx, xls.

```bash
# 1. STOP OBS (mandatory, see below)

cd ~/obs-lab
source venv/bin/activate
cd backend

# 2. dry run: shows the plan, writes nothing
python obs_bulk_ingest.py ~/Desktop/client_archive --owner your@email.com --dry-run

# 3. if the mapping looks right, run for real (asks for confirmation: type SI)
python obs_bulk_ingest.py ~/Desktop/client_archive --owner your@email.com

# 4. restart OBS
cd .. && ./start_prod.sh
```

Options:

| Option | Effect |
|---|---|
| `--dry-run` | Shows what it would do, writes nothing. Always use it the first time |
| `--owner EMAIL` | Owner of the documents. Without it, the developer account is used |
| `--azienda NAME` | Organisation for files sitting in the root |
| `--settore`, `--tipo` | Optional metadata |
| `--skip-existing` | Skips files already in the archive (useful for updates) |
| `--force` | Bypasses the running-server check. Use only if you know what you are doing |

### Why OBS must be stopped

The script writes directly to `faiss.index` and `chunks.json`. If the server is running, the two
processes overwrite each other and the archive is corrupted. That is why the script refuses to start
if it finds anything listening on port 8000. Do not bypass the check with `--force` unless you are
certain no OBS instance is running.

The script saves the index every 25 files, so an interruption halfway through does not throw away
the work already done: rerun with `--skip-existing` and it picks up where it left off.


## 19. WARNING: do not keep OBS inside iCloud, Dropbox or OneDrive

A real and serious problem. If the project folder sits on the Desktop or in Documents with iCloud
sync enabled, **iCloud syncs `data/` as well**, which is the archive itself.

Three concrete failures:

1. **iCloud can evict files from disk** to free up space, leaving only a placeholder. If it does so
   while OBS is running, the index becomes unreadable mid-operation.
2. **`faiss.index` is rewritten in full on every ingest.** iCloud re-uploads it every time, burning
   bandwidth and storage.
3. **`auth.db` and `sharing.db` are SQLite databases.** Cloud sync does not understand SQLite
   locking and can corrupt them.

### How to move the folder without losing data

The Mac warns that turning off sync may lose files. That is true only for files **not yet
downloaded** (dashed cloud icon): those live only in the cloud. **You do not need to disable
anything**: just download everything, then move.

```bash
# 1. In Finder: right-click the project folder -> "Download Now"
#    Wait until ALL cloud icons disappear.

# 2. Verify nothing is left cloud-only (this must print nothing)
find ~/Desktop/obs-lab -name "*.icloud"

# 3. Move it outside the synced folders (the home directory itself is not synced)
mv ~/Desktop/obs-lab ~/obs-lab
cd ~/obs-lab

# 4. The venv holds absolute paths and may break. If start_prod.sh errors out,
#    recreate it:
rm -rf venv
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

OBS paths are all relative to the source file, so nothing needs reconfiguring after the move.

---

## 20. The code editor and Docker (from v2.6.0)

The **Code** tab lets you write and run code inside OBS, in seven server-side
languages (Python, JavaScript, Java, C, C++, Octave, R) plus HTML and CSS
previewed in the browser. A script can read the OBS archive, and can be exported
to run outside OBS as well.

**The full guide is in `CODE_GUIDE.md`.** Only the quick commands are kept here.

### Checking that Docker works
```bash
docker --version
docker info
docker run --rm hello-world
```
Server-side code runs inside Docker containers. Without Docker running, the Code
panel says so in red and no script starts. HTML and CSS still work, because they
run in the browser.

### Downloading the languages
Done from the interface: **Code** tab, **Linguaggi** button, then **Scarica**.
Restricted to developer and admin. The terminal equivalent:
```bash
docker pull python:3.11-slim
docker pull node:20-slim
docker pull eclipse-temurin:21-jdk
docker pull gcc:13
docker pull gnuoctave/octave:9.2.0
docker pull r-base:4.4.1
```
Download them one at a time, only the ones you need: together they weigh several
gigabytes. C and C++ share `gcc:13`.

### Linux: the docker group (most common server mistake)
The Docker daemon accepts commands only from members of the `docker` group. The
user running OBS must be added to it:
```bash
sudo usermod -aG docker $USER
```
Then **log out and log back in**, otherwise the change has no effect. If
`permission denied while trying to connect to the Docker daemon socket` appears,
this is why.

To start Docker automatically when the server reboots:
```bash
sudo systemctl enable --now docker
```

### Configuration in `backend/.env`
```
CODE_RUNNER=docker
CODE_TIMEOUT=30
CODE_MEMORY_MB=512
CODE_CPUS=1.0
```

`CODE_RUNNER=subprocess` runs code **without a container**, directly on the machine
with the server's permissions: a script could read the database and every user's
data. Use it only in local development, never on a multi-user server.

### Freeing space
```bash
docker system prune -a
```
This deletes **every** Docker image on the machine, not just the OBS ones.

### Startup order
Docker first, OBS after. If OBS starts while Docker is off, just start Docker and
reload the page: no backend restart needed.

---

## 21. The worksheet panel, Sheets (from v2.6.0)

### What it is

A calculation panel with spreadsheet-style grids: you type data in, assign a role
to each column, and get charts and analyses. No documents are uploaded here.

### Isolation

Sheets does not read or write anything belonging to the OBS archive. Not the
document store, not the FAISS index, not the embeddings, not the entity graph,
not the images, not the folders, not the clusters, not the audit trail.

The isolation is structural, not a matter of discipline in each query. The data
lives in `data/obs_sheets.db`, a separate file, reached by modules that never
import `main`. The only dependency towards OBS is `auth`, used to know which
user is working, exactly as the Code panel does.

Import accepts CSV, TSV and TXT only. Documents in any format are rejected: this
is the boundary made operational, not a technical limitation.

### Required files

Backend, in `backend/`:
```
sheets_store.py     storage on the separate database
sheets_compute.py   analyses and safe formula evaluation
sheets_plots.py     server-rendered specialist charts
sheets_routes.py    the /api/sheets endpoints
```

Frontend, in `frontend/`:
```
obs_sheets_frontend.js
```

`main.py` must expose the route that serves the JavaScript file. OBS does not
use a static mount: every frontend file has its own explicit route.

### Configuration

```
OBS_SHEETS_ENABLED      1 by default. With 0 the panel is off entirely: the
                        router is not registered and the tab does not appear.
OBS_SHEETS_MAX_CELLS    100000 by default. Cell ceiling per sheet.
OBS_SHEETS_MAX_SHEETS   50 by default. Sheets per workbook.
```

### New dependency

`matplotlib==3.9.2`, needed to render the specialist charts on the server. It is
the same version already tested in `python.Dockerfile`, so it does not disturb
the torch/faiss/scipy/numpy chain. Check after installing:

```bash
python3 -m pip show numpy | grep Version      # must stay 1.26.4
python3 -m pip show matplotlib | grep Version # 3.9.2
```

### Column roles

Each column carries a free name, a role, a type and a unit. The role is a
property of the column, declared once:

```
X          abscissa
Y          ordinate, several Y columns give several series
Z          third dimension
Err X      horizontal error bars
Err Y      vertical error bars
Label      text attached to the points
Group      grouping variable
None       column ignored by charts
```

A column set to Err Y is used automatically by every chart that accepts error
bars. Units appear in the axis labels.

### Matrix charts

Surface 3D, contour and heatmap need at least two Y columns, because they build
a matrix rather than a series. Leave the Y selector on automatic and set the
role Y on all the data columns. With a single Y column the panel explains what
is missing instead of drawing an empty box.

### Formulas

Expressions reference columns by name, for example `sqrt(A**2 + B**2)`. They are
evaluated on a closed subset of the Python AST: numbers, column names,
arithmetic and comparison operators, and a fixed list of functions. Attribute
access, indexing, comprehensions, lambdas and calls to unlisted names are all
rejected. Anyone needing arbitrary code uses the Code panel, which has its own
container sandbox.

Save the sheet before applying a formula.

### Deleting a user

Workbooks belonging to a deleted user are reassigned to the developer, following
the policy already used for documents, images and scripts. Nothing is destroyed.

### Quick check that it works

1. The Sheets tab appears after Code.
2. `data/obs_sheets.db` is created on first start.
3. The log shows no `Init pannello sheets non riuscito`.
4. Import a CSV with a known relation, for instance Y = 3X + 2: the linear
   regression must return slope 3, intercept 2 and R squared 1.

### If the panel does not open

The most common cause is the MDI window manager. `OBS_MDI_PANELS` in
`obs_mdi_frontend.js` is an explicit allow list: a panel missing from it is
refused silently, with no error in the console. `sheets` must appear both there
and in `OBS_MDI_FB`.

### If the JavaScript file returns 404

The file must sit in `frontend/`, next to the other `obs_*_frontend.js`, and
`main.py` must declare its route. Copying the file alone is not enough.

## Licensing, first run and desktop packaging (v2.6.0)

### License gate

> Update for the public release. The offline license gate has been removed. OBS
> now starts and serves every request without asking for a license. The
> `license_check.py` module and the `activate.html` activation page are no longer
> part of the shipped project, and the middleware, activation endpoints and
> startup check that used them have been taken out of `main.py`. The license
> generator toolkit (`obs_license_core.py`, `obs_keygen.py`, `obs_licensegen.py`,
> `test_license.py`, the private and public keys, and `licenze_registro.json`)
> always lived outside the project and must never be committed to the public
> repository. The text below is kept as a record of how the gate worked in the
> licensed builds and no longer describes current behaviour.

OBS is protected by an offline license gate that runs before login. The gate
lives in the backend (`license_check.py`) so it covers both desktop and server
mode. On startup the backend computes the license state from `data/license.txt`
and logs it. The three states are full, readonly and none. With a full license
the app works normally. Without a valid license every request is blocked and the
user is redirected to the activation page, where the license string is pasted.

The public verification key is stored in `license_check.py` in the
`OBS_PUBLIC_KEY` field. The private signing key never lives inside OBS. The
license file is stored under the data folder, so it survives program updates.

The grace period and the pre expiry warning are configured through the
environment: `OBS_LICENSE_GRACE_DAYS` and `OBS_LICENSE_WARN_DAYS`.

### First run: administrator account

On a fresh installation there are no user accounts, and no `.env` with
`DEV_EMAIL` and `DEV_PASSWORD` is shipped. When the backend detects zero users
it redirects to `/setup`, a page where the customer creates the first
administrator (developer) account with email and password. Once created, the
account is used to sign in and to manage all other users as usual. The setup
route refuses to run a second time: if any user already exists it redirects to
login.

### First run: model download

The embedding model is about 2.2 GB and is not shipped inside the app. After the
first login, if the model is missing, the app redirects to `/models`, a page
with a one click download and a progress indicator. The download runs in the
background on the backend and the page polls `/api/models/status`. When the
model is ready OBS starts normally. The model is stored under the data folder
and only needs to be downloaded once. Startup tolerates a missing model: the
embedding load is deferred until the model has been downloaded.

### Building the desktop executable (macOS)

The desktop app is a Tauri shell that starts the Python backend as a sidecar.
For distribution the backend is frozen into a standalone executable with
PyInstaller, so the customer does not need Python installed.

The freeze is driven by `obs-backend.spec`. From the backend folder, with the
virtual environment active:

    pip install pyinstaller
    pyinstaller obs-backend.spec

This produces a `dist/obs-backend/` folder containing the frozen backend. The
resulting launcher is then wired into Tauri as the `obs-backend` sidecar, next
to the platform triple name, replacing the development wrapper.

Each operating system must be built on its own system: PyInstaller freezes a
platform specific executable, so the Windows backend must be frozen on Windows
and the macOS backend on macOS. Tauri does not cross compile these comfortably.

Freezing torch, faiss, sentence-transformers and spacy is iterative. The spec
collects their data files and hidden imports, but the first freeze on a given
machine can surface missing modules or data. Read the runtime errors and add the
missing packages to the collect list in the spec.
