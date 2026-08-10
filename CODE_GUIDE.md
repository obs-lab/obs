# OBS - Code editor and Docker guide

> Complete guide to the **Code** panel in OBS: how to install Docker from scratch
> on Windows, macOS and Linux, how to download the languages, how to write and run
> code that reads OBS data, and how to export a script so it runs outside OBS too.
>
> Written for people who have never used Docker. Each section can be read on its
> own. Commands are for macOS/Linux. Where Windows differs, it is stated.

---

## 0. Golden rules (always read first)

1. **Docker must be running before OBS.** If Docker is not running, the Code panel
   says so in red and no script will start. This is not an OBS fault.
2. **A container and an image are two different things.** The image is the
   template, downloaded once (hundreds of MB). The container is the disposable
   instance created and destroyed on every run. **You never manage containers**,
   OBS creates and removes them by itself.
3. **Downloading or removing images is restricted to developer and admin.** A
   normal user sees the status of each language but has no buttons.
4. **A script sees only the documents its author can already see.** Permissions,
   ownership and sharing apply identically inside the code.
5. **Code runs isolated.** The container cannot see the database, the OBS files,
   or the machine's disk. It talks to OBS only through the HTTP API.
6. **A run has limits.** Thirty seconds and 512 MB of memory by default. A script
   exceeding them is stopped.
7. **HTML and CSS do not use Docker.** They run in the browser, previewed instantly.

---

## 1. Getting started, in short

If Docker is already installed and at least one language is downloaded:

1. Start Docker (see section 2 for your platform).
2. Start OBS as usual: `./start.sh` or `start.bat`.
3. Open `http://localhost:8000` and go to the **Code** tab.
4. Pick a language, write, press **Esegui** (or `Ctrl+Enter`).

If this is the first time, jump to section 2, then section 3.

---

## 2. Installing Docker from scratch

Docker is only needed for the languages that run on the server (Python,
JavaScript, Java, C, C++, Octave, R). HTML and CSS work without it.

### 2.1 macOS

1. Go to `https://www.docker.com/products/docker-desktop` and download
   **Docker Desktop for Mac**. Pick the right build: **Apple Silicon** for
   M1/M2/M3/M4 Macs, **Intel Chip** for Intel Macs. If unsure: Apple menu,
   "About This Mac".
2. Open the downloaded `.dmg` and drag Docker into Applications.
3. Launch Docker from Applications. The first run asks for your system password:
   this is normal, it installs the networking components.
4. Wait until the whale icon in the menu bar stops animating. When it is still,
   Docker is ready.

Check from the terminal:
```bash
docker --version
docker info
```
The first must print a version. The second, many lines with no errors.

**A note on memory.** On macOS, Docker does not run containers directly: it runs a
Linux virtual machine, which holds RAM permanently. OBS already loads heavy models
(torch, FAISS, spaCy), so on an 8 GB machine it is worth lowering the memory given
to Docker: whale icon, Settings, Resources, and reduce **Memory** to 2 GB.

### 2.2 Windows

Docker on Windows relies on WSL2, the Linux subsystem. It must be enabled first.

1. Open **PowerShell as administrator** (right-click the Start menu,
   "Windows PowerShell (admin)").
2. Install WSL2:
   ```powershell
   wsl --install
   ```
3. **Restart the computer.** This step is not optional.
4. Download **Docker Desktop for Windows** from
   `https://www.docker.com/products/docker-desktop`.
5. Run the installer, leaving **Use WSL 2 instead of Hyper-V** ticked.
6. Launch Docker Desktop and wait until the whale icon in the taskbar stops moving.

Check from PowerShell:
```powershell
docker --version
docker info
```

**If `wsl --install` fails**, virtualization is most likely disabled in the BIOS.
Restart into the BIOS (usually F2, F10 or Del at boot) and enable the setting
called **Virtualization Technology**, **Intel VT-x** or **AMD-V**, depending on the
processor.

### 2.3 Linux (Ubuntu and Debian)

On Linux, Docker runs natively, with no virtual machine: it is the lightest of the
three platforms.

```bash
sudo apt update
sudo apt install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings

curl -fsSL https://download.docker.com/linux/ubuntu/gpg | \
  sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo "deb [arch=$(dpkg --print-architecture) \
signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
```

**Mandatory step, otherwise OBS cannot talk to Docker.**
The Docker daemon accepts commands only from members of the `docker` group. The
user running OBS must be added to it:

```bash
sudo usermod -aG docker $USER
```

Then **log out and log back in** (or reboot). A group change does not affect
sessions that are already open: this is the most common mistake on servers.

Check:
```bash
docker run --rm hello-world
```
If it prints a welcome message, it works. If it says
`permission denied while trying to connect to the Docker daemon socket`, you have
not logged out and back in after `usermod`.

Finally, make sure Docker starts automatically when the server reboots:
```bash
sudo systemctl enable --now docker
```

---

## 3. Downloading the languages

Each language has its own image, downloaded once. **No command line needed**: it
is all done from the interface.

1. Open OBS, go to the **Code** tab.
2. Press the **Linguaggi** button.
3. You will see the seven languages with the status of each.
4. Press **Scarica** next to the one you need.

The download runs in the background, with visible progress. You can keep using OBS
while it downloads. When it finishes, the status becomes "installata" with the
space used.

**Download only the languages you actually use.** All seven together take several
gigabytes.

| Language | Image | Approximate size |
| --- | --- | --- |
| Python | `python:3.11-slim` | 130 MB |
| JavaScript | `node:20-slim` | 200 MB |
| Java | `eclipse-temurin:21-jdk` | 450 MB |
| C and C++ | `gcc:13` | 1.2 GB |
| Octave | `gnuoctave/octave:9.2.0` | 1.5 GB |
| R | `r-base:4.4.1` | 800 MB |

C and C++ share the same image: downloading one gives you both. Removing one loses
both, and OBS tells you so.

**If you prefer the command line**, the equivalent is:
```bash
docker pull python:3.11-slim
```

---

## 4. Writing and running code

### 4.1 The interface

The Code panel has a bar on top with the language selector and the buttons, the
list of saved scripts on the left, the editor in the middle and the output below.

| Command | What it does |
| --- | --- |
| **Esegui** (`Ctrl+Enter`) | Runs the script and shows the output |
| **Salva** (`Ctrl+S`) | Saves the script in your personal space |
| **Nuovo** | Starts again from an empty template |
| **Esporta** | Downloads a ZIP with the script, the library and instructions |
| **Linguaggi** | Opens image management |

The **accesso ai dati OBS** checkbox, when ticked, injects a library into the
script for querying the archive. Unticked, the script runs isolated and cannot
read anything from OBS.

The **stdin** field next to the output passes input data to the script, if it
reads any.

### 4.2 A script that reads the documents

Pick **Python**, tick "accesso ai dati OBS", and write:

```python
import obs

docs = obs.documents()
print("Visible documents:", len(docs))

for d in docs[:5]:
    print("-", d["titolo"], "|", d["azienda"])

res = obs.query("what are these documents about?", top_k=5)
print()
print(res.get("answer", ""))
```

Press Esegui. The script sees **only the documents you can see**: if you are a
normal user, yours and those shared with you; if you are an admin, your company's.
There is no way around this from the code, because the check is done by OBS, not
by the script.

### 4.3 The fields of a document

`obs.documents()` returns a list of documents. The field names are in Italian, as
everywhere else in OBS:

| Field | Contents |
| --- | --- |
| `doc_id` | Unique identifier |
| `titolo` | Document title |
| `azienda` | Owning organisation |
| `settore` | Sector |
| `tipo` | Document type |
| `filename` | Original file name |
| `folder_id` | Folder, or `None` if unassigned |
| `timestamp` | Ingestion date |
| `chunks` | Number of indexed fragments |

Note: the field is `titolo`, not `title`. Reading a field that does not exist
returns `None` in Python without raising, so a list of `None` almost always means
a mistyped field name.

### 4.4 Available functions

The `obs` library exposes the same operations as the interface:

| Function | What it returns |
| --- | --- |
| `obs.query(question, top_k)` | Answer and relevant passages |
| `obs.documents()` | List of visible documents |
| `obs.document_meta(doc_id)` | Metadata of one document |
| `obs.entities()` | Entity graph |
| `obs.cluster()` | Discovered themes |
| `obs.analyze()` | Statistical analysis |
| `obs.images()` | List of images |
| `obs.status()` | Archive status |
| `obs.get(path)` | Any other GET call |
| `obs.post(path, data)` | Any other POST call |

In JavaScript the functions are the same but asynchronous, so they need `await`.
In R they carry the `obs_` prefix (`obs_query`, `obs_documents`). In Java they are
static methods of the `Obs` class. In C and C++ they return raw JSON.

### 4.5 HTML and CSS

Choosing HTML or CSS turns the Esegui button into **Anteprima**, and the result
appears in a frame next to the editor, without using Docker. The page runs
sandboxed: it cannot reach OBS or the session.

---

## 5. Exporting a script

The **Esporta** button downloads a ZIP containing:

- your source file,
- the `obs` library in the right language (if data access was ticked),
- a `README.txt` with instructions to run it elsewhere.

An exported script runs on any machine. If it uses the library, it needs two
environment variables:

**macOS and Linux:**
```bash
export OBS_URL=http://localhost:8000
export OBS_TOKEN=your_token
python3 main.py
```

**Windows (PowerShell):**
```powershell
$env:OBS_URL="http://localhost:8000"
$env:OBS_TOKEN="your_token"
python main.py
```

The token is obtained by logging into OBS and reading the `obs_session` cookie, or
by calling `POST /api/auth/login`.

If you remove the library calls, the script no longer depends on OBS and runs on
its own: it is ordinary code, exportable and reusable anywhere.

---

## 6. Configuration

Settings go in `backend/.env`, like the other OBS ones.

| Variable | Default | What it does |
| --- | --- | --- |
| `CODE_RUNNER` | `docker` | `docker` or `subprocess` |
| `CODE_TIMEOUT` | `30` | Maximum seconds per run |
| `CODE_MEMORY_MB` | `512` | Maximum container memory |
| `CODE_CPUS` | `1.0` | Fraction of CPU assigned |
| `CODE_MAX_OUTPUT` | `100000` | Maximum output characters |
| `CODE_NETWORK` | `obs_code_net` | Dedicated Docker network |
| `DOCKER_BIN` | `docker` | Path to the Docker executable |

### A warning about `CODE_RUNNER=subprocess`

With this setting the code **does not run in a container**: it runs directly on the
machine, with the same permissions as the OBS server. A script could read the
database, the keys, the data of every user.

Use it **only** in development, on a local machine where you are the only user. On
a server with multiple accounts, leave it on `docker`.

---

## 7. Plots

The Code panel can produce plots and show them in a frame beside the editor, not a
pop-up: it stays open while you keep writing code.

### 7.1 Two routes

**Native library (complex plots).** The script draws with its real library, saves
to a file, and OBS collects the image. No limits: if matplotlib or ggplot can do
it, you can do it.

**`obs.plot()` (quick plot).** A single call, rendered interactively by Plotly in
the panel. Useful when a line or some bars is all you need.

The two coexist. You can use both in the same script.

### 7.2 The images with plotting libraries

Python, R and Octave use images **built by the project**, not downloaded from the
internet, because the official ones carry neither matplotlib nor ggplot. The
Dockerfiles live in the `docker/` folder and are versioned with the code, so the
build is reproducible on any machine.

In the **Languages** panel the button for these three reads **Build** instead of
**Download**, and a `(plot)` marker appears next to the name. The first build takes
a few minutes, because it downloads and installs the libraries; later ones are
immediate.

| Language | Bundled libraries |
| --- | --- |
| Python | matplotlib, numpy, pandas, seaborn, scipy, statsmodels, scikit-learn |
| R | ggplot2 and the whole tidyverse |
| Octave | native plotting functions |

Java, C, C++ and JavaScript stay as downloaded images, without plotting libraries.

### 7.3 A plot with matplotlib

Just save to a file. OBS collects any `.png`, `.jpg` or `.svg` the script produces.

```python
import obs
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from collections import Counter

docs = obs.documents()
counts = Counter(d["azienda"] for d in docs)

fig, ax = plt.subplots(figsize=(9, 5))
ax.bar(counts.keys(), counts.values(), color="#3d5a80")
ax.set_title("Documents per organisation")
fig.tight_layout()
fig.savefig("plot.png", dpi=140)
```

`matplotlib.use("Agg")` is needed because the container has no screen. The images
built by OBS already set it by default, but writing it keeps the script portable
outside as well.

### 7.4 A plot with ggplot

```r
library(ggplot2)
library(dplyr)
source("obs.R")

docs <- obs_documents()

p <- docs %>%
  count(azienda, name = "documents") %>%
  ggplot(aes(x = reorder(azienda, -documents), y = documents)) +
  geom_col(fill = "#3d5a80") +
  theme_minimal()

ggsave("plot.png", p, width = 9, height = 5, dpi = 140)
```

### 7.5 `obs.plot()`

```python
import obs

docs = obs.documents()
obs.plot(
    kind="bar",
    x=[d["titolo"] for d in docs[:5]],
    y=[d["chunks"] for d in docs[:5]],
    title="Fragments per document",
)
```

Available kinds are `line`, `bar`, `scatter`, `histogram`, `pie`. The plot comes
out interactive, with zoom and hover values.

### 7.6 Rules and limits

- OBS collects up to **12 images** per run, each under **8 MB**.
- Only `.png`, `.jpg`, `.jpeg`, `.svg` are collected. The source file and the
  client library are never mistaken for plots.
- Each plot has a **Download** button under its preview.
- The frame opens by itself when a script produces a plot, and can be opened or
  closed by hand with the **Plots** button.
- If the script produces nothing, the frame stays closed.

---

### 7.7 Robust statistics in Python

The Python image built by OBS bundles **statsmodels** and **scikit-learn**, which
together provide the robust statistics toolkit: methods that do not bend to a
handful of anomalous observations.

#### Why it matters

A few observations out of scale can badly distort an estimate that looks sound. The
example in `examples/analisi_titolo.py` shows it: over three hundred days with
**four** anomalous ones, ordinary least squares puts the beta of a stock against its
index at 0.97, when the true value is 1.30. The robust estimator recovers 1.29.

A thirty per cent error on a risk estimate, caused by 1.3% of the data. And it is
invisible to the eye, because those days look unremarkable one by one.

#### The tools

| Tool | What it does |
| --- | --- |
| `sm.RLM` with `HuberT` | Robust regression, good balance of efficiency and resistance |
| `sm.RLM` with `TukeyBiweight` | Robust regression, more aggressive towards outliers |
| `TheilSenRegressor` | Median-based regression, highly resistant |
| `RANSACRegressor` | Fits the model on the uncontaminated subset |
| `MinCovDet` | Detects multivariate outliers (robust Mahalanobis distance) |

`MinCovDet` is the Minimum Covariance Determinant: it estimates centre and scatter
using only the most compact subset of the data, so the outliers do not contaminate
the very estimate they are then judged against.

#### An example

```python
import numpy as np
import statsmodels.api as sm
from sklearn.covariance import MinCovDet
from scipy.stats import chi2

X = sm.add_constant(index_returns)

classic_beta = sm.OLS(stock_returns, X).fit().params[1]

fit = sm.RLM(stock_returns, X, M=sm.robust.norms.HuberT()).fit()
robust_beta = fit.params[1]

regression_outliers = np.where(fit.weights < 0.5)[0]

Y = np.column_stack([stock_returns, index_returns])
mcd = MinCovDet(support_fraction=0.75).fit(Y)
distances = mcd.mahalanobis(Y)
multivariate_outliers = np.where(distances > chi2.ppf(0.995, df=2))[0]
```

If `classic_beta` and `robust_beta` diverge appreciably, the outliers are driving
the ordinary estimate, and only the robust one can be trusted.

#### A note on FSDA

An earlier version of this guide announced that FSDA, the robust statistics library
from the University of Parma, was bundled with the Octave image. FSDA is written for
MATLAB and does not run on Octave without substantial changes to its own code, so it
was removed. The Python tools described here cover the same ground: MCD and robust
regression are present in both libraries.

---

## 8. Troubleshooting

### "Docker non disponibile: docker non trovato nel PATH"
Docker is not installed, or it is installed but the terminal cannot find it. Check
with `docker --version`. On macOS, if the command does not exist, Docker Desktop
was downloaded but never installed into Applications.

### "Docker non disponibile: il demone docker non e' in esecuzione"
Docker is installed but not running. Open Docker Desktop and wait for the whale
icon to stop animating. On Linux: `sudo systemctl start docker`.

### "permission denied while trying to connect to the Docker daemon socket" (Linux)
The user is not in the `docker` group, or is but has not logged out and back in
since being added:
```bash
sudo usermod -aG docker $USER
```
Then **log out and log back in**. Verify with `docker run --rm hello-world`.

### "Immagine non installata: python:3.11-slim"
The language has not been downloaded yet. Press **Linguaggi**, then **Scarica**.
If you do not see the Scarica button, your role does not allow it: ask a developer
or an admin.

### The download seems stuck
Images are downloaded from the internet and can exceed a gigabyte. On a slow
connection this takes minutes. If it does not move at all, check the connection
and retry.

### "Timeout raggiunto, esecuzione interrotta"
The script exceeded thirty seconds. Either it has an infinite loop, or it genuinely
needs more time: in that case raise `CODE_TIMEOUT` in `backend/.env` and restart OBS.

### The script does not see the documents I expect
It sees only what you see. If a document does not appear in the Documents tab, it
will not appear in the script either. This is not a bug.

### The editor stays blank
Monaco, the editor, loads from the internet on first use. Without a connection it
does not appear, and the panel says so explicitly. Reload the page with the network
up.

### "Errore di compilazione" in Java, C or C++
This is an error in your code, not in OBS. The compiler message appears in red in
the output.

---

## 9. Uninstalling and freeing space

### Removing a language
From the **Linguaggi** panel, press **Rimuovi** next to the one you do not use. It
frees the image's space, which is the heavy part.

### Cleaning residual containers
In the rare case where an interrupted run leaves traces, the **Pulisci container
residui** button in the Linguaggi panel removes them.

### Removing Docker entirely
If you decide to stop using the editor, you can uninstall Docker without touching
OBS: the rest of the software keeps working exactly as before. On macOS and Windows
uninstall Docker Desktop like any application. On Linux:
```bash
sudo apt remove docker-ce docker-ce-cli containerd.io
```

To delete the downloaded images too and reclaim all the space:
```bash
docker system prune -a
```
This command **deletes every Docker image on the machine**, not just the OBS ones.
Use it only if you are sure you do not need them.
