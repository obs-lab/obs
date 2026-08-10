PYTHON_CLIENT = '''import os
import json
import urllib.request
import urllib.error

OBS_URL = os.environ.get("OBS_URL", "http://localhost:8000")
OBS_TOKEN = os.environ.get("OBS_TOKEN", "")


class ObsError(Exception):
    pass


def _call(method, path, payload=None):
    url = OBS_URL.rstrip("/") + path
    data = None
    headers = {"Authorization": "Bearer " + OBS_TOKEN}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        raise ObsError("%d %s" % (e.code, e.read().decode("utf-8", "replace")))
    except urllib.error.URLError as e:
        raise ObsError("connessione fallita: %s" % e.reason)
    if not body:
        return None
    try:
        return json.loads(body)
    except ValueError:
        return body


def query(question, top_k=6):
    return _call("POST", "/api/query", {"question": question, "top_k": top_k})


def documents(folder_id=None):
    path = "/api/documents"
    if folder_id:
        path += "?folder_id=" + str(folder_id)
    return _call("GET", path)


def document_meta(doc_id):
    return _call("GET", "/api/documents/" + str(doc_id) + "/meta")


def entities(**kwargs):
    return _call("POST", "/api/entities/graph", kwargs)


def cluster(**kwargs):
    return _call("POST", "/api/cluster", kwargs)


def analyze(**kwargs):
    return _call("POST", "/api/analyze", kwargs)


def images():
    return _call("GET", "/api/images")


def status():
    return _call("GET", "/api/status")


def get(path):
    return _call("GET", path)


def post(path, payload=None):
    return _call("POST", path, payload or {})


def plot(kind="line", x=None, y=None, labels=None, title="",
         xlabel="", ylabel="", name="plot.json", **extra):
    spec = {
        "kind": kind,
        "x": list(x) if x is not None else [],
        "y": list(y) if y is not None else [],
        "labels": list(labels) if labels is not None else [],
        "title": title,
        "xlabel": xlabel,
        "ylabel": ylabel,
    }
    spec.update(extra)
    with open(name, "w", encoding="utf-8") as f:
        json.dump({"obs_plot": spec}, f)
    return name
'''

JAVASCRIPT_CLIENT = '''const OBS_URL = process.env.OBS_URL || "http://localhost:8000";
const OBS_TOKEN = process.env.OBS_TOKEN || "";

async function call(method, path, payload) {
  const headers = { Authorization: "Bearer " + OBS_TOKEN };
  const init = { method, headers };
  if (payload !== undefined && payload !== null) {
    headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(payload);
  }
  const res = await fetch(OBS_URL.replace(/\\/$/, "") + path, init);
  const text = await res.text();
  if (!res.ok) {
    throw new Error(res.status + " " + text);
  }
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch (e) {
    return text;
  }
}

const obs = {
  query: (question, topK = 6) => call("POST", "/api/query", { question, top_k: topK }),
  documents: (folderId) =>
    call("GET", "/api/documents" + (folderId ? "?folder_id=" + folderId : "")),
  documentMeta: (docId) => call("GET", "/api/documents/" + docId + "/meta"),
  entities: (opts = {}) => call("POST", "/api/entities/graph", opts),
  cluster: (opts = {}) => call("POST", "/api/cluster", opts),
  analyze: (opts = {}) => call("POST", "/api/analyze", opts),
  images: () => call("GET", "/api/images"),
  status: () => call("GET", "/api/status"),
  get: (path) => call("GET", path),
  post: (path, payload) => call("POST", path, payload || {}),
};

module.exports = obs;
'''

R_CLIENT = '''obs_url <- Sys.getenv("OBS_URL", "http://localhost:8000")
obs_token <- Sys.getenv("OBS_TOKEN", "")

obs_call <- function(method, path, payload = NULL) {
  url <- paste0(sub("/$", "", obs_url), path)
  tmp <- tempfile()
  headers <- c(paste0("Authorization: Bearer ", obs_token))
  args <- c("-s", "-S", "-X", method, "-o", tmp, "-w", "%{http_code}")
  for (h in headers) args <- c(args, "-H", h)
  if (!is.null(payload)) {
    body <- jsonlite::toJSON(payload, auto_unbox = TRUE)
    args <- c(args, "-H", "Content-Type: application/json", "-d", body)
  }
  args <- c(args, url)
  code <- system2("curl", args, stdout = TRUE)
  body <- if (file.exists(tmp)) paste(readLines(tmp, warn = FALSE), collapse = "\\n") else ""
  unlink(tmp)
  if (!grepl("^2", code)) stop(paste("OBS", code, body))
  if (nchar(body) == 0) return(NULL)
  jsonlite::fromJSON(body)
}

obs_query <- function(question, top_k = 6) {
  obs_call("POST", "/api/query", list(question = question, top_k = top_k))
}

obs_documents <- function(folder_id = NULL) {
  path <- "/api/documents"
  if (!is.null(folder_id)) path <- paste0(path, "?folder_id=", folder_id)
  obs_call("GET", path)
}

obs_entities <- function(...) obs_call("POST", "/api/entities/graph", list(...))
obs_cluster <- function(...) obs_call("POST", "/api/cluster", list(...))
obs_analyze <- function(...) obs_call("POST", "/api/analyze", list(...))
obs_images <- function() obs_call("GET", "/api/images")
obs_status <- function() obs_call("GET", "/api/status")
obs_get <- function(path) obs_call("GET", path)
obs_post <- function(path, payload = list()) obs_call("POST", path, payload)
'''

OCTAVE_CLIENT = '''1;

function result = obs_query(varargin)
  if nargin < 2
    error("obs_query: servono metodo e percorso");
  end
  method = varargin{1};
  path = varargin{2};
  payload = "";
  if nargin >= 3
    payload = varargin{3};
  end

  url = getenv("OBS_URL");
  if isempty(url)
    url = "http://localhost:8000";
  end
  token = getenv("OBS_TOKEN");

  cmd = sprintf('curl -s -S -X %s -H "Authorization: Bearer %s"', method, token);
  if !isempty(payload)
    cmd = sprintf('%s -H "Content-Type: application/json" -d %s', ...
                  cmd, ["'" payload "'"]);
  end
  cmd = sprintf('%s "%s%s"', cmd, url, path);

  [status, out] = system(cmd);
  if status != 0
    error("obs_query: chiamata fallita (%d)", status);
  end
  result = out;
end

function docs = obs_documents()
  raw = obs_query("GET", "/api/documents");
  docs = obs_json(raw);
end

function s = obs_status()
  s = obs_json(obs_query("GET", "/api/status"));
end

function r = obs_ask(question, top_k)
  if nargin < 2
    top_k = 6;
  end
  q = strrep(question, '"', '\\"');
  payload = sprintf('{"question": "%s", "top_k": %d}', q, top_k);
  r = obs_json(obs_query("POST", "/api/query", payload));
end

function value = obs_json(text)
  if exist("jsondecode", "builtin") || exist("jsondecode", "file")
    value = jsondecode(text);
  else
    error("obs_json: jsondecode non disponibile in questa versione di Octave");
  end
end

function M = obs_matrix(docs, fields)
  if nargin < 2
    fields = {"chunks"};
  end
  if ischar(fields)
    fields = {fields};
  end

  n = numel(docs);
  p = numel(fields);
  M = zeros(n, p);

  for i = 1:n
    if iscell(docs)
      d = docs{i};
    else
      d = docs(i);
    end
    for j = 1:p
      f = fields{j};
      if isfield(d, f)
        v = d.(f);
        if ischar(v)
          v = str2double(v);
        end
        if isempty(v) || !isnumeric(v)
          v = NaN;
        end
        M(i, j) = v;
      else
        M(i, j) = NaN;
      end
    end
  end
end

function tf = obs_has_stats()
  tf = (exist("ismissing") > 0) && (exist("mad") > 0);
end
'''

JAVA_CLIENT = '''import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;

public class Obs {

    private static final String URL =
        System.getenv().getOrDefault("OBS_URL", "http://localhost:8000");
    private static final String TOKEN =
        System.getenv().getOrDefault("OBS_TOKEN", "");

    private static final HttpClient CLIENT = HttpClient.newBuilder()
        .connectTimeout(Duration.ofSeconds(15))
        .build();

    public static String call(String method, String path, String jsonPayload)
            throws IOException, InterruptedException {
        HttpRequest.Builder b = HttpRequest.newBuilder()
            .uri(URI.create(URL.replaceAll("/$", "") + path))
            .header("Authorization", "Bearer " + TOKEN)
            .timeout(Duration.ofSeconds(60));

        if (jsonPayload == null) {
            b = b.method(method, HttpRequest.BodyPublishers.noBody());
        } else {
            b = b.header("Content-Type", "application/json")
                 .method(method, HttpRequest.BodyPublishers.ofString(jsonPayload));
        }

        HttpResponse<String> res =
            CLIENT.send(b.build(), HttpResponse.BodyHandlers.ofString());

        if (res.statusCode() >= 300) {
            throw new IOException("OBS " + res.statusCode() + " " + res.body());
        }
        return res.body();
    }

    public static String query(String question, int topK)
            throws IOException, InterruptedException {
        String payload = String.format(
            "{\\"question\\": \\"%s\\", \\"top_k\\": %d}",
            question.replace("\\"", "\\\\\\""), topK);
        return call("POST", "/api/query", payload);
    }

    public static String documents() throws IOException, InterruptedException {
        return call("GET", "/api/documents", null);
    }

    public static String status() throws IOException, InterruptedException {
        return call("GET", "/api/status", null);
    }

    public static String get(String path) throws IOException, InterruptedException {
        return call("GET", path, null);
    }

    public static String post(String path, String jsonPayload)
            throws IOException, InterruptedException {
        return call("POST", path, jsonPayload == null ? "{}" : jsonPayload);
    }
}
'''

C_CLIENT = '''#ifndef OBS_H
#define OBS_H

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static char *obs_call(const char *method, const char *path, const char *payload) {
    const char *url = getenv("OBS_URL");
    const char *token = getenv("OBS_TOKEN");
    if (!url) url = "http://localhost:8000";
    if (!token) token = "";

    char cmd[8192];
    if (payload) {
        snprintf(cmd, sizeof(cmd),
                 "curl -s -S -X %s -H \\"Authorization: Bearer %s\\" "
                 "-H \\"Content-Type: application/json\\" -d '%s' \\"%s%s\\"",
                 method, token, payload, url, path);
    } else {
        snprintf(cmd, sizeof(cmd),
                 "curl -s -S -X %s -H \\"Authorization: Bearer %s\\" \\"%s%s\\"",
                 method, token, url, path);
    }

    FILE *fp = popen(cmd, "r");
    if (!fp) return NULL;

    size_t cap = 8192, len = 0;
    char *buf = malloc(cap);
    if (!buf) { pclose(fp); return NULL; }

    size_t n;
    while ((n = fread(buf + len, 1, cap - len - 1, fp)) > 0) {
        len += n;
        if (len + 1 >= cap) {
            cap *= 2;
            char *tmp = realloc(buf, cap);
            if (!tmp) { free(buf); pclose(fp); return NULL; }
            buf = tmp;
        }
    }
    buf[len] = '\\0';
    pclose(fp);
    return buf;
}

static char *obs_query(const char *question, int top_k) {
    char payload[4096];
    snprintf(payload, sizeof(payload),
             "{\\"question\\": \\"%s\\", \\"top_k\\": %d}", question, top_k);
    return obs_call("POST", "/api/query", payload);
}

static char *obs_documents(void) {
    return obs_call("GET", "/api/documents", NULL);
}

static char *obs_status(void) {
    return obs_call("GET", "/api/status", NULL);
}

static char *obs_get(const char *path) {
    return obs_call("GET", path, NULL);
}

static char *obs_post(const char *path, const char *payload) {
    return obs_call("POST", path, payload ? payload : "{}");
}

#endif
'''

CPP_CLIENT = '''#ifndef OBS_HPP
#define OBS_HPP

#include <cstdio>
#include <cstdlib>
#include <string>
#include <memory>
#include <stdexcept>

namespace obs {

inline std::string call(const std::string &method,
                        const std::string &path,
                        const std::string &payload = "") {
    const char *env_url = std::getenv("OBS_URL");
    const char *env_token = std::getenv("OBS_TOKEN");
    std::string url = env_url ? env_url : "http://localhost:8000";
    std::string token = env_token ? env_token : "";

    std::string cmd = "curl -s -S -X " + method +
                      " -H \\"Authorization: Bearer " + token + "\\"";
    if (!payload.empty()) {
        cmd += " -H \\"Content-Type: application/json\\" -d '" + payload + "'";
    }
    cmd += " \\"" + url + path + "\\"";

    std::unique_ptr<FILE, decltype(&pclose)> pipe(popen(cmd.c_str(), "r"), pclose);
    if (!pipe) throw std::runtime_error("obs: popen fallita");

    std::string out;
    char buffer[4096];
    while (std::fgets(buffer, sizeof(buffer), pipe.get()) != nullptr) {
        out += buffer;
    }
    return out;
}

inline std::string query(const std::string &question, int top_k = 6) {
    std::string payload = "{\\"question\\": \\"" + question +
                          "\\", \\"top_k\\": " + std::to_string(top_k) + "}";
    return call("POST", "/api/query", payload);
}

inline std::string documents() { return call("GET", "/api/documents"); }
inline std::string status() { return call("GET", "/api/status"); }
inline std::string get(const std::string &path) { return call("GET", path); }
inline std::string post(const std::string &path, const std::string &payload = "{}") {
    return call("POST", path, payload);
}

}

#endif
'''

CLIENTS = {
    "python": PYTHON_CLIENT,
    "javascript": JAVASCRIPT_CLIENT,
    "java": JAVA_CLIENT,
    "c": C_CLIENT,
    "cpp": CPP_CLIENT,
    "octave": OCTAVE_CLIENT,
    "r": R_CLIENT,
}

TEMPLATES = {
    "python": '''import obs
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from collections import Counter

docs = obs.documents()
print("Documenti visibili:", len(docs))

conteggio = Counter(d["azienda"] for d in docs)
aziende = list(conteggio.keys())
valori = list(conteggio.values())

fig, ax = plt.subplots(figsize=(9, 5))
ax.bar(aziende, valori, color="#3d5a80")
ax.set_title("Documenti per organizzazione")
ax.set_ylabel("documenti")
ax.tick_params(axis="x", rotation=45)
fig.tight_layout()
fig.savefig("grafico.png", dpi=140)

print("Grafico prodotto.")
''',
    "javascript": '''const obs = require("./obs");

(async () => {
  const docs = await obs.documents();
  console.log("Documenti visibili:", docs.length);

  docs.slice(0, 5).forEach(function (d) {
    console.log("-", d.titolo, "|", d.azienda, "|", d.chunks, "chunk");
  });

  const res = await obs.query("di cosa parlano i documenti?", 5);
  console.log();
  console.log(res.answer);
})();
''',
    "java": '''public class Main {
    public static void main(String[] args) throws Exception {
        String docs = Obs.documents();
        System.out.println("Documenti: " + docs);

        String res = Obs.query("di cosa parlano i documenti?", 5);
        System.out.println(res);
    }
}
''',
    "c": '''#include "obs.h"

int main(void) {
    char *docs = obs_documents();
    if (docs) {
        printf("Documenti: %s\\n", docs);
        free(docs);
    }
    return 0;
}
''',
    "cpp": '''#include "obs.hpp"
#include <iostream>

int main() {
    std::cout << "Documenti: " << obs::documents() << std::endl;
    return 0;
}
''',
    "octave": '''source("obs.m");
pkg load statistics;

docs = obs_documents();
printf("Documenti visibili: %d\\n", numel(docs));

x = linspace(0, 4 * pi, 200);
y = sin(x) .* exp(-x / 8);

figure("visible", "off");
plot(x, y, "linewidth", 2, "color", [0.24 0.35 0.50]);
title("Oscillazione smorzata");
xlabel("x");
ylabel("y");
grid on;
print("grafico.png", "-dpng", "-r140");

printf("Grafico prodotto.\\n");
''',
    "r": '''library(jsonlite)
library(ggplot2)
library(dplyr)
source("obs.R")

docs <- obs_documents()
cat("Documenti visibili:", nrow(docs), "\\n")

conteggio <- docs %>%
  count(azienda, name = "documenti")

p <- ggplot(conteggio, aes(x = reorder(azienda, -documenti), y = documenti)) +
  geom_col(fill = "#3d5a80") +
  labs(title = "Documenti per organizzazione", x = NULL, y = "documenti") +
  theme_minimal() +
  theme(axis.text.x = element_text(angle = 45, hjust = 1))

ggsave("grafico.png", p, width = 9, height = 5, dpi = 140)

cat("Grafico prodotto.\\n")
''',
}
