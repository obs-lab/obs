import os
import sys
import multiprocessing

if __name__ == "__main__":
    multiprocessing.freeze_support()

if "--download-models" in sys.argv:
    import model_setup
    code = model_setup.run_download_blocking()
    sys.exit(code)

if "--download-spacy" in sys.argv:
    import model_setup
    code = model_setup.run_spacy_download_blocking()
    sys.exit(code)

if "--download-clip" in sys.argv:
    import model_setup
    code = model_setup.run_clip_download_blocking()
    sys.exit(code)
    
import uuid
import time
import json
import hashlib
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import numpy as np
from fastapi import FastAPI, UploadFile, File, HTTPException, Form, Request, Depends, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel

import auth
import auth_routes
import ownership
import sharing
import sharing_routes
import code_store
import code_files
import code_routes
import sheets_store
import sheets_routes
import model_setup
from auth_routes import current_user, require_roles

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except Exception:
    pass

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("OBS")

try:
    import digitizer_core
    _DIGITIZER_OK = True
except Exception as _e:
    digitizer_core = None
    _DIGITIZER_OK = False
    logger.warning("digitizer_core non disponibile: %s", _e)


def _fig_to_json(fig):
    """Serializza un grafico Plotly con array come liste JSON semplici
    (compatibile con qualsiasi versione di plotly.js, niente base64 typed-array)."""
    import json as _json
    from plotly.utils import PlotlyJSONEncoder
    return _json.dumps(fig.to_dict(), cls=PlotlyJSONEncoder)

_OBS_DATA_ENV = os.environ.get("OBS_DATA_DIR", "").strip()
if _OBS_DATA_ENV:
    DATA_DIR    = Path(_OBS_DATA_ENV)
else:
    DATA_DIR    = Path(__file__).parent.parent / "data"
DOCS_DIR        = DATA_DIR / "documents"
VS_DIR          = DATA_DIR / "vector_store"
KG_DIR          = DATA_DIR / "knowledge_graph"
TABLES_DIR      = DATA_DIR / "tables"
ENTITIES_DIR    = DATA_DIR / "entities"
DIGITIZE_DIR    = DATA_DIR / "digitize"
UPLOAD_TMP_DIR  = DATA_DIR / "upload_tmp"
AUDIT_FILE      = DATA_DIR / "audit_trail.jsonl"
CHATS_FILE      = DATA_DIR / "chat_history.json"
import sys as _sys
if getattr(_sys, "frozen", False) and hasattr(_sys, "_MEIPASS"):
    FRONTEND_DIR = Path(_sys._MEIPASS) / "frontend"
else:
    FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
if _OBS_DATA_ENV:
    MODELS_DIR  = DATA_DIR / "models"
else:
    MODELS_DIR  = Path(__file__).parent / "models"

for d in [DATA_DIR, MODELS_DIR, DOCS_DIR, VS_DIR, KG_DIR, TABLES_DIR, ENTITIES_DIR, DIGITIZE_DIR, UPLOAD_TMP_DIR]:
    d.mkdir(parents=True, exist_ok=True)

CLOUD_API_KEY = os.environ.get("CLOUD_API_KEY", "")

LLM_BACKEND   = os.environ.get("LLM_BACKEND", "auto").lower()
CLOUD_API_URL   = os.environ.get("CLOUD_API_URL", "")
CLOUD_MODEL     = os.environ.get("CLOUD_MODEL", "")
CLOUD_API_STYLE = os.environ.get("CLOUD_API_STYLE", "messages").lower()
try:
    CLOUD_API_HEADERS = json.loads(os.environ.get("CLOUD_API_HEADERS", "{}"))
except Exception:
    CLOUD_API_HEADERS = {}
LOCAL_MODEL  = os.environ.get("LOCAL_MODEL", "")
LOCAL_API_URL = os.environ.get("LOCAL_API_URL", "http://localhost:11434")
LOCAL_NUM_CTX = int(os.environ.get("LOCAL_NUM_CTX", "8192"))

LLM_TIMEOUT     = int(os.environ.get("LLM_TIMEOUT", "600"))
REPORT_MAX_TOKENS = int(os.environ.get("REPORT_MAX_TOKENS", "1100"))

import llm_config as _llm_config


def _apply_llm_config():
    global LLM_BACKEND, CLOUD_API_URL, CLOUD_MODEL, CLOUD_API_STYLE, CLOUD_API_KEY
    global LOCAL_MODEL, LOCAL_API_URL, LOCAL_NUM_CTX, LLM_TIMEOUT, REPORT_MAX_TOKENS
    saved = _llm_config.load()
    if "backend" in saved:
        LLM_BACKEND = str(saved["backend"]).lower()
    if "cloud_api_url" in saved:
        CLOUD_API_URL = saved["cloud_api_url"]
    if "cloud_model" in saved:
        CLOUD_MODEL = saved["cloud_model"]
    if "cloud_api_style" in saved:
        CLOUD_API_STYLE = str(saved["cloud_api_style"]).lower()
    if "cloud_api_key" in saved:
        CLOUD_API_KEY = saved["cloud_api_key"]
    if "local_model" in saved:
        LOCAL_MODEL = saved["local_model"]
    if "local_api_url" in saved:
        LOCAL_API_URL = saved["local_api_url"]
    if "local_num_ctx" in saved:
        LOCAL_NUM_CTX = int(saved["local_num_ctx"])
    if "llm_timeout" in saved:
        LLM_TIMEOUT = int(saved["llm_timeout"])
    if "report_max_tokens" in saved:
        REPORT_MAX_TOKENS = int(saved["report_max_tokens"])


_apply_llm_config()

logger.info("LLM config -> backend=%s, local_model=%s, cloud_key=%s, timeout=%ds, report_tokens=%d",
            LLM_BACKEND, LOCAL_MODEL or "none", "set" if CLOUD_API_KEY else "none",
            LLM_TIMEOUT, REPORT_MAX_TOKENS)

OBS_CONFIG = {
    "embedding_model":     "BAAI/bge-m3",
    "embedding_dim":       1024,
    "top_k_retrieval":     15,
    "top_k_reranked":      6,
    "boundary_threshold":  0.68,
    "chunk_min_sentences": 1,
    "chunk_max_sentences": 4,
    "image_model":         "sentence-transformers/clip-ViT-B-32",
    "image_dim":           512,
    "ocr_enabled":         True,
    "ocr_min_chars":       12,
    "embed_batch_size":    64,
    "upload_stream_chunk": 1024 * 1024,
    "max_sentence_chars":  1200,
}

_embed_model  = None
_rerank_model = None
_faiss_index  = None
_cross_encoder  = None
_chunk_store: List[dict] = []
_kg_nodes: dict = {}
_kg_edges: List[dict] = []

def get_embed_model():
    global _embed_model
    if _embed_model is None:
        from sentence_transformers import SentenceTransformer
        logger.info("Loading embedding model")
        local_path = MODELS_DIR / "bge-m3"
        if (local_path / "model.safetensors").exists():
            _embed_model = SentenceTransformer(str(local_path), local_files_only=True)
        else:
            _embed_model = SentenceTransformer(OBS_CONFIG["embedding_model"], model_kwargs={"use_safetensors": True})
        logger.info("Embedding model ready.")
    return _embed_model


def encode_in_batches(model, texts, batch_size=None, normalize=False):
    if batch_size is None:
        batch_size = OBS_CONFIG.get("embed_batch_size", 64)
    if not texts:
        dim = OBS_CONFIG["embedding_dim"]
        return np.zeros((0, dim), dtype="float32")
    out = []
    for start in range(0, len(texts), batch_size):
        part = texts[start:start + batch_size]
        vecs = model.encode(part, show_progress_bar=False, batch_size=batch_size).astype("float32")
        if normalize:
            norms = np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-9
            vecs = vecs / norms
        out.append(vecs)
    return np.vstack(out)

def get_cross_encoder():
    global _cross_encoder
    if _cross_encoder is None:
        from sentence_transformers import CrossEncoder
        logger.info("Loading cross-encoder model")
        _cross_encoder = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
        logger.info("Cross-encoder ready.")
    return _cross_encoder

def get_faiss_index():
    global _faiss_index
    if _faiss_index is None:
        import faiss
        _faiss_index = faiss.IndexHNSWFlat(OBS_CONFIG["embedding_dim"], 32)
        _faiss_index.hnsw.efConstruction = 200
        _faiss_index.hnsw.efSearch = 64
        _load_persisted_index()
    return _faiss_index

CHUNK_STORE_FILE = VS_DIR / "chunks.json"
FAISS_INDEX_FILE = VS_DIR / "faiss.index"
KG_FILE          = KG_DIR / "knowledge_graph.json"

def _load_persisted_index():
    global _chunk_store, _kg_nodes, _kg_edges, _faiss_index
    import faiss
    if FAISS_INDEX_FILE.exists() and CHUNK_STORE_FILE.exists():
        logger.info("Loading persisted FAISS index")
        loaded = faiss.read_index(str(FAISS_INDEX_FILE))
        expected_dim = OBS_CONFIG["embedding_dim"]
        if loaded.d != expected_dim:
            logger.warning(
                "Persisted index dimension %d does not match configured dimension %d. "
                "Index not loaded. Run /api/system/rebuild-index to re-index the archive "
                "with the current embedding model.",
                loaded.d, expected_dim)
            _chunk_store = json.loads(CHUNK_STORE_FILE.read_text())
            logger.info(f"Loaded {len(_chunk_store)} chunks from disk (embeddings pending rebuild).")
        else:
            _faiss_index = loaded
            _chunk_store = json.loads(CHUNK_STORE_FILE.read_text())
            logger.info(f"Loaded {len(_chunk_store)} chunks from disk.")
    if KG_FILE.exists():
        kg_data = json.loads(KG_FILE.read_text())
        _kg_nodes = kg_data.get("nodes", {})
        _kg_edges = kg_data.get("edges", [])

def _persist_index():
    import faiss
    faiss.write_index(_faiss_index, str(FAISS_INDEX_FILE))
    CHUNK_STORE_FILE.write_text(json.dumps(_chunk_store, ensure_ascii=False, indent=2))
    KG_FILE.write_text(json.dumps({"nodes": _kg_nodes, "edges": _kg_edges}, ensure_ascii=False, indent=2))

def semantic_chunking(sentences: List[str], model) -> List[str]:
    if len(sentences) <= OBS_CONFIG["chunk_min_sentences"]:
        return [" ".join(sentences)]

    embeddings = encode_in_batches(model, sentences)
    chunks, current = [], [sentences[0]]

    for i in range(1, len(sentences)):
        a = embeddings[i-1] / (np.linalg.norm(embeddings[i-1]) + 1e-9)
        b = embeddings[i]   / (np.linalg.norm(embeddings[i])   + 1e-9)
        cosine = float(np.dot(a, b))
        boundary = cosine < OBS_CONFIG["boundary_threshold"]
        too_long = len(current) >= OBS_CONFIG["chunk_max_sentences"]

        if (boundary or too_long) and len(current) >= OBS_CONFIG["chunk_min_sentences"]:
            chunks.append(" ".join(current))
            current = [sentences[i]]
        else:
            current.append(sentences[i])

    if current:
        chunks.append(" ".join(current))
    return chunks

def extract_text(filepath: Path, filename: str) -> str:
    suffix = filename.lower().rsplit(".", 1)[-1]
    if suffix == "pdf":
        import fitz
        doc = fitz.open(str(filepath))
        return "\n".join(page.get_text() for page in doc)
    elif suffix in ("doc", "docx"):
        import docx
        d = docx.Document(str(filepath))
        return "\n".join(p.text for p in d.paragraphs if p.text.strip())
    elif suffix == "txt":
        return filepath.read_text(encoding="utf-8", errors="replace")
    elif suffix == "csv":
        import pandas as pd
        df = pd.read_csv(filepath)
        return f"Dataset: {filepath.name}\nColonne: {', '.join(df.columns.tolist())}\nRighe: {len(df)}\n\n{df.to_string(index=False, max_rows=100)}"
    elif suffix in ("xlsx", "xls"):
        import pandas as pd
        df = pd.read_excel(filepath)
        return f"Dataset: {filepath.name}\nColonne: {', '.join(df.columns.tolist())}\nRighe: {len(df)}\n\n{df.to_string(index=False, max_rows=100)}"
    else:
        return filepath.read_text(encoding="utf-8", errors="replace")

def extract_pdf_blocks(filepath: Path):
    import fitz
    doc = fitz.open(str(filepath))
    blocks = []
    for page_num, page in enumerate(doc):
        page_dict = page.get_text("dict")
        page_height = page.rect.height
        page_width = page.rect.width
        for block in page_dict.get("blocks", []):
            if block.get("type", 0) != 0:
                continue
            block_text_parts = []
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    block_text_parts.append(span.get("text", ""))
            block_text = " ".join(t for t in block_text_parts if t).strip()
            if not block_text:
                continue
            bbox = block.get("bbox", [0, 0, 0, 0])
            blocks.append({
                "page": page_num,
                "bbox": [round(float(b), 2) for b in bbox],
                "page_width": round(float(page_width), 2),
                "page_height": round(float(page_height), 2),
                "text": block_text,
            })
    return blocks


def _normalize_for_match(s: str) -> str:
    import re
    return re.sub(r'\s+', ' ', s).strip().lower()


def locate_chunk_position(chunk_text: str, blocks: List[dict]):
    if not blocks:
        return None
    target = _normalize_for_match(chunk_text)
    if not target:
        return None
    head = target[:60]
    best = None
    for blk in blocks:
        btext = _normalize_for_match(blk["text"])
        if not btext:
            continue
        if head and head in btext:
            best = blk
            break
        if target[:24] and target[:24] in btext:
            best = blk
    if best is None:
        return None
    return {
        "page": best["page"],
        "bbox": best["bbox"],
        "page_width": best["page_width"],
        "page_height": best["page_height"],
    }


def split_sentences(text: str) -> List[str]:
    import re
    text = re.sub(r'\s+', ' ', text).strip()
    sentences = re.split(r'(?<=[.!?])\s+', text)
    max_len = OBS_CONFIG.get("max_sentence_chars", 1200)
    out = []
    for s in sentences:
        s = s.strip()
        if len(s) <= 20:
            continue
        if len(s) <= max_len:
            out.append(s)
            continue
        words = s.split(" ")
        piece = ""
        for w in words:
            if piece and len(piece) + 1 + len(w) > max_len:
                out.append(piece)
                piece = w
            else:
                piece = w if not piece else piece + " " + w
        if piece:
            out.append(piece)
    return out


def _table_path(doc_id: str) -> Path:
    return TABLES_DIR / f"{doc_id}.json"


def _persist_table(doc_id: str, filepath: Path, suffix: str):
    """Se il file è tabellare, salva la struttura (colonne numeriche con valori
    e una colonna etichetta se presente). Best-effort: se fallisce, non blocca
    l'ingest (il documento resta comunque cercabile come testo)."""
    try:
        import pandas as pd
        if suffix == "csv":
            df = pd.read_csv(filepath)
        elif suffix in ("xlsx", "xls"):
            df = pd.read_excel(filepath)
        else:
            return
    except Exception as e:
        logger.warning("Lettura tabellare fallita per %s: %s", filepath.name, e)
        return

    if df is None or df.empty:
        return

    num_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    if not num_cols:
        return

    label_col = None
    for c in df.columns:
        if c not in num_cols:
            label_col = c
            break

    labels = ([str(x) for x in df[label_col].tolist()] if label_col is not None
              else [str(i + 1) for i in range(len(df))])

    columns = {}
    for c in num_cols:
        vals = []
        for x in df[c].tolist():
            try:
                if pd.isna(x):
                    continue
                vals.append(float(x))
            except Exception:
                continue
        if vals:
            columns[str(c)] = vals

    if not columns:
        return

    table = {
        "doc_id":     doc_id,
        "filename":   filepath.name,
        "label_col":  str(label_col) if label_col is not None else None,
        "labels":     labels,
        "columns":    columns,
        "n_rows":     len(df),
    }
    try:
        _table_path(doc_id).write_text(json.dumps(table, ensure_ascii=False))
        logger.info("Tabella conservata per doc %s: %d colonne numeriche.",
                    doc_id, len(columns))
    except Exception as e:
        logger.warning("Impossibile salvare la tabella: %s", e)


def _load_table(doc_id: str):
    """Carica la tabella strutturata di un documento, se esiste."""
    p = _table_path(doc_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def ingest_document(filepath: Path, filename: str, azienda: str, settore: str, tipo: str, titolo: str, folder_id: Optional[str] = None, owner_id: Optional[int] = None) -> dict:
    global _chunk_store
    import faiss

    model = get_embed_model()
    index = get_faiss_index()

    text      = extract_text(filepath, filename)
    sentences = split_sentences(text)

    if not sentences:
        return {"chunks_added": 0, "error": "No text extracted"}

    chunks    = semantic_chunking(sentences, model)
    doc_id    = hashlib.md5(text.encode()).hexdigest()[:10]
    embeddings = encode_in_batches(model, chunks, normalize=True)

    index.add(embeddings)

    pdf_blocks = None
    if filename.lower().rsplit(".", 1)[-1] == "pdf":
        try:
            pdf_blocks = extract_pdf_blocks(filepath)
        except Exception as e:
            logger.warning("Estrazione posizioni PDF fallita per %s: %s", filename, e)
            pdf_blocks = None

    for i, chunk in enumerate(chunks):
        record = {
            "chunk_id":  f"{doc_id}_{i}",
            "doc_id":    doc_id,
            "azienda":   azienda,
            "settore":   settore,
            "tipo":      tipo,
            "titolo":    titolo,
            "filename":  filename,
            "source_path": str(filepath),
            "text":      chunk,
            "folder_id": folder_id,
            "owner_id":  owner_id,
            "timestamp": datetime.utcnow().isoformat(),
        }
        if pdf_blocks:
            pos = locate_chunk_position(chunk, pdf_blocks)
            if pos:
                record["position"] = pos
        _chunk_store.append(record)

    _extract_kg_entities(text, azienda, settore, doc_id)
    _suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if _suffix in ("csv", "xlsx", "xls"):
        _persist_table(doc_id, filepath, _suffix)
    _persist_index()

    return {
        "doc_id":       doc_id,
        "chunks_added": len(chunks),
        "sentences":    len(sentences),
        "azienda":      azienda,
    }

def _extract_kg_entities(text: str, azienda: str, settore: str, doc_id: str):
    import re
    global _kg_nodes, _kg_edges

    if azienda not in _kg_nodes:
        _kg_nodes[azienda] = {"tipo": "azienda", "settore": settore}

    amounts = re.findall(r'\d+[,.]?\d*\s*(?:milioni?|mln)?\s*(?:di\s+)?euro', text, re.IGNORECASE)
    companies = re.findall(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)(?:\s+S\.r\.l\.|\s+S\.p\.A\.)?', text)

    for comp in set(companies[:10]):
        if comp != azienda and len(comp) > 4:
            if comp not in _kg_nodes:
                _kg_nodes[comp] = {"tipo": "entita_esterna"}
            edge = {"from": azienda, "to": comp, "rel": "MENZIONA", "doc_id": doc_id}
            if edge not in _kg_edges:
                _kg_edges.append(edge)

def retrieve(query: str, top_k: int = None, azienda_filter: Optional[str] = None,
             user: Optional[dict] = None, folder_id: Optional[str] = None) -> List[dict]:
    if top_k is None:
        top_k = OBS_CONFIG["top_k_retrieval"]

    model = get_embed_model()
    index = get_faiss_index()

    if index.ntotal == 0:
        return []

    q_emb = model.encode([query], show_progress_bar=False).astype("float32")
    q_emb = q_emb / (np.linalg.norm(q_emb) + 1e-9)

    k = min(top_k * 3, index.ntotal)
    distances, indices = index.search(q_emb, k)

    allowed_owner_ids = None
    extra_doc_ids = set()
    placements = {}
    if user is not None:
        allowed_owner_ids = ownership.visible_owner_ids(user)
        extra_doc_ids = shared_doc_ids_for(user)
        placements = sharing.get_placements(user["user_id"])

    results = []
    for dist, idx in zip(distances[0], indices[0]):
        if idx < 0 or idx >= len(_chunk_store):
            continue
        chunk = _chunk_store[idx]
        if azienda_filter and chunk["azienda"] != azienda_filter:
            continue
        if not _chunk_in_folder_scope(chunk, folder_id, user=user, placements=placements):
            continue
        if allowed_owner_ids is not None:
            oid = chunk.get("owner_id")
            shared_ok = chunk.get("doc_id") in extra_doc_ids
            if not ((oid is not None and oid in allowed_owner_ids) or shared_ok):
                continue
        results.append({**chunk, "score": float(dist)})
        if len(results) >= top_k:
            break
    return results

def rerank(query: str, chunks: List[dict]) -> List[dict]:
    if not chunks:
        return chunks
    try:
        cross_encoder = get_cross_encoder()
        pairs = [[query, c["text"]] for c in chunks]
        scores = cross_encoder.predict(pairs)
        for chunk, score in zip(chunks, scores):
            chunk["rerank_score"] = float(score)
        return sorted(chunks, key=lambda x: x["rerank_score"], reverse=True)
    except Exception as e:
        logger.warning(f"Cross-encoder failed, falling back to keyword rerank: {e}")
        query_words = set(query.lower().split())
        for chunk in chunks:
            text_lower = chunk["text"].lower()
            overlap = sum(1 for w in query_words if w in text_lower and len(w) > 3)
            chunk["rerank_score"] = chunk["score"] + overlap * 0.05
        return sorted(chunks, key=lambda x: x["rerank_score"], reverse=True)

def hyde_expand(query: str) -> str:
    expansions = {
        "fornitore": "fornitore contratto fornitura accordo",
        "costo":     "costo prezzo euro budget investimento",
        "sinergia":  "sinergia collaborazione condivisione cross-settoriale",
        "risultat":  "risultati performance KPI metriche report",
    }
    expanded = query
    for kw, exp in expansions.items():
        if kw in query.lower():
            expanded += " " + exp
    return expanded

def _norm_lang(lang) -> str:
    if isinstance(lang, str) and lang.strip().lower() in ("it", "en"):
        return lang.strip().lower()
    return "en"


_QA_SYSTEM_PROMPT = {
    "en": (
        "You are OBS-LAB, a document knowledge-management system. "
        "Your function is to answer the user's question using exclusively the document "
        "context provided below. Treat that context as the sole authoritative source: do "
        "not introduce information, assumptions, or external knowledge that is not present "
        "in it. When the provided context does not contain the information required to "
        "answer, state this explicitly rather than inferring or speculating. Respond in the "
        "same language as the question, with precision and a clear structure, and attribute "
        "every statement to its source by indicating the originating organisation and document."
    ),
    "it": (
        "Sei OBS-LAB, un sistema di gestione della conoscenza documentale. "
        "La tua funzione è rispondere alla domanda dell'utente utilizzando esclusivamente il "
        "contesto documentale fornito di seguito. Considera tale contesto come unica fonte "
        "autorevole: non introdurre informazioni, supposizioni o conoscenze esterne non "
        "presenti in esso. Quando il contesto fornito non contiene le informazioni necessarie "
        "per rispondere, dichiaralo esplicitamente anziché dedurre o ipotizzare. Rispondi nella "
        "stessa lingua della domanda, con precisione e una struttura chiara, e attribuisci ogni "
        "affermazione alla sua fonte indicando l'organizzazione e il documento di origine."
    ),
}


def _build_prompt(query, chunks, intent, lang="en"):
    """Costruisce system prompt e user message condivisi da tutti i backend."""
    context_parts = []
    for i, c in enumerate(chunks[:OBS_CONFIG["top_k_reranked"]], 1):
        context_parts.append(
            f"[Fonte {i}: {c['azienda']} - {c['titolo']} ({c['tipo']})]\n{c['text']}"
        )
    context = "\n\n---\n\n".join(context_parts)

    system_prompt = _QA_SYSTEM_PROMPT[_norm_lang(lang)]

    user_message = f"""CONTESTO DOCUMENTALE:
{context}

DOMANDA: {query}

TIPO DI QUERY: {intent}

Fornisci una risposta precisa basata sul contesto."""
    return system_prompt, user_message


def _local_available() -> bool:
    """Verifica se il server locale risponde (timeout breve)."""
    try:
        import urllib.request
        req = urllib.request.Request(f"{LOCAL_API_URL}/api/tags")
        with urllib.request.urlopen(req, timeout=1.5) as r:
            return r.status == 200
    except Exception:
        return False


_BACKEND_OVERRIDE: Optional[str] = None


def _available_backends() -> dict:
    """Quali backend sono utilizzabili ORA. Serve all'interruttore per accendere
    o spegnere le opzioni. 'offline' è sempre disponibile."""
    return {
        "cloud":   bool(CLOUD_API_URL and CLOUD_API_KEY),
        "local":   _local_available(),
        "offline": True,
    }


def _decide_backend() -> str:
    """Risolve il backend attivo: override runtime > LLM_BACKEND > auto."""
    choice = _BACKEND_OVERRIDE or LLM_BACKEND
    if choice in ("cloud", "local", "offline"):
        avail = _available_backends()
        if avail.get(choice):
            return choice
        if avail["cloud"]:
            return "cloud"
        if avail["local"]:
            return "local"
        return "offline"
    if CLOUD_API_URL and CLOUD_API_KEY:
        return "cloud"
    if _local_available():
        return "local"
    return "offline"


def _llm_mode_label() -> str:
    """Etichetta leggibile del backend attivo, per la UI."""
    b = _decide_backend()
    if b == "cloud":
        return f"cloud:{CLOUD_MODEL}" if CLOUD_MODEL else "cloud-api"
    if b == "local":
        return f"local:{LOCAL_MODEL}" if LOCAL_MODEL else "local"
    return "offline-template"


def _generate_offline(query, chunks, t0):
    context = "\n\n".join(f"[{c['azienda']} - {c['titolo']}]\n{c['text']}" for c in chunks[:4])
    answer = f"[Modalità offline]\n\nContesto trovato:\n{context[:2000]}"
    return {"answer": answer, "latency_ms": int((time.time()-t0)*1000), "model": "template"}


def _cloud_request(system_prompt, messages, max_tokens, timeout=LLM_TIMEOUT):
    import urllib.request
    if not (CLOUD_API_URL and CLOUD_API_KEY):
        raise RuntimeError("backend cloud non configurato (CLOUD_API_URL / CLOUD_API_KEY)")
    headers = {"Content-Type": "application/json"}
    if CLOUD_API_STYLE == "messages":
        headers["x-api-key"] = CLOUD_API_KEY
        payload = {
            "model": CLOUD_MODEL,
            "max_tokens": max_tokens,
            "system": system_prompt,
            "messages": messages,
        }
    else:
        headers["Authorization"] = f"Bearer {CLOUD_API_KEY}"
        payload = {
            "model": CLOUD_MODEL,
            "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system_prompt}] + messages,
        }
    headers.update(CLOUD_API_HEADERS)
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(CLOUD_API_URL, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = json.loads(r.read().decode("utf-8"))
    if CLOUD_API_STYLE == "messages":
        text = body["content"][0]["text"]
    else:
        text = body["choices"][0]["message"]["content"]
    return {"text": text, "model": body.get("model", CLOUD_MODEL)}


def _local_request(system_prompt, messages, num_predict, timeout):
    import urllib.request
    payload = {
        "model": LOCAL_MODEL,
        "messages": [{"role": "system", "content": system_prompt}] + messages,
        "stream": False,
        "options": {"temperature": 0.2, "num_predict": num_predict, "num_ctx": LOCAL_NUM_CTX},
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{LOCAL_API_URL}/api/chat", data=data,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = json.loads(r.read().decode("utf-8"))
    text = body.get("message", {}).get("content", "").strip()
    return {"text": text, "model": f"local:{LOCAL_MODEL}"}


def _generate_cloud(query, chunks, intent, conversation_history, t0, lang="en"):
    system_prompt, user_message = _build_prompt(query, chunks, intent, lang)

    messages = []
    if conversation_history:
        for turn in conversation_history[-4:]:
            messages.append({"role": turn.role, "content": turn.content})
    messages.append({"role": "user", "content": user_message})

    res = _cloud_request(system_prompt, messages, max_tokens=2000)
    return {"answer": res["text"], "latency_ms": int((time.time()-t0)*1000), "model": res["model"]}


def _generate_local(query, chunks, intent, conversation_history, t0, lang="en"):
    """Sintesi tramite modello locale (nessun contatto con l'esterno)."""
    system_prompt, user_message = _build_prompt(query, chunks, intent, lang)

    messages = []
    if conversation_history:
        for turn in conversation_history[-4:]:
            messages.append({"role": turn.role, "content": turn.content})
    messages.append({"role": "user", "content": user_message})

    res = _local_request(system_prompt, messages, num_predict=1024, timeout=180)
    answer = res["text"] or "[Nessuna risposta dal modello locale]"
    return {"answer": answer, "latency_ms": int((time.time()-t0)*1000), "model": res["model"]}


def _llm_complete(system_prompt: str, user_message: str, max_tokens: int = 2500) -> str:
    """Chiamata LLM generica sul backend attivo (per il report, uso non-Q&A).
    Ritorna solo il testo. Solleva RuntimeError('offline') se non c'è LLM."""
    backend = _decide_backend()
    messages = [{"role": "user", "content": user_message}]
    if backend == "cloud":
        return _cloud_request(system_prompt, messages, max_tokens=max_tokens)["text"]
    if backend == "local":
        return _local_request(system_prompt, messages, num_predict=max_tokens, timeout=LLM_TIMEOUT)["text"]
    raise RuntimeError("offline")


def generate_answer(query: str, chunks: List[dict], intent: str, conversation_history: list = [], lang: str = "en") -> dict:
    t0 = time.time()
    backend = _decide_backend()

    try:
        if backend == "cloud":
            return _generate_cloud(query, chunks, intent, conversation_history, t0, lang)
        elif backend == "local":
            return _generate_local(query, chunks, intent, conversation_history, t0, lang)
        else:
            return _generate_offline(query, chunks, t0)
    except Exception as e:
        logger.warning(f"LLM backend '{backend}' fallito: {e}. Fallback offline.")
        out = _generate_offline(query, chunks, t0)
        out["model"] = f"{backend}-failed template"
        return out

FACTUAL_KW    = {"cos'è","cos è","definizione","che cosa","descrivi","spiega","cosa sono","quale","chi è"}
RELATIONAL_KW = {"fornitore","supplier","relazione","collega","connessione","sinergia","condivide","comune"}
ANALYTICAL_KW = {"analizza","confronta","tendenza","trend","previsione","perché","strategia","opportunità"}

def classify_intent(query: str) -> str:
    q = query.lower()
    if any(kw in q for kw in ANALYTICAL_KW):
        return "ANALYTICAL"
    if any(kw in q for kw in RELATIONAL_KW):
        return "RELATIONAL"
    return "FACTUAL"

def kg_traversal(query: str) -> str:
    q = query.lower()
    relevant_edges = [
        e for e in _kg_edges
        if any(w in q for w in (e["from"].lower().split() + e["to"].lower().split()))
    ]
    if not relevant_edges:
        nodes_list = list(_kg_nodes.keys())[:10]
        return f"Entità nel Knowledge Graph: {', '.join(nodes_list)}"
    lines = [f"{e['from']} - [{e['rel']}] - {e['to']}" for e in relevant_edges[:8]]
    return "Relazioni trovate:\n" + "\n".join(lines)

def log_audit(query: str, intent: str, chunks_used: int, latency_ms: int, user_id: str = "anonymous"):
    entry = {
        "timestamp":   datetime.utcnow().isoformat(),
        "user_id":     user_id,
        "query_hash":  hashlib.md5(query.encode()).hexdigest()[:8],
        "intent":      intent,
        "chunks_used": chunks_used,
        "latency_ms":  latency_ms,
    }
    with open(AUDIT_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")

app = FastAPI(title="OBS-LAB", version="2.6.0")

_default_cors_origins = "http://localhost:8000,http://127.0.0.1:8000"
_cors_origins = [o.strip() for o in os.environ.get("OBS_CORS_ORIGINS", _default_cors_origins).split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

from fastapi.responses import JSONResponse as _JSONResponse


app.include_router(auth_routes.router)
app.include_router(sharing_routes.router)
app.include_router(code_routes.router)
if os.environ.get("OBS_SHEETS_ENABLED", "1") != "0":
    app.include_router(sheets_routes.router)

@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Errore non gestito su %s: %s", request.url.path, exc)
    return _JSONResponse(status_code=400,
                         content={"detail": "Errore durante l'elaborazione: " + str(exc)})

class ConversationTurn(BaseModel):
    role: str
    content: str

class QueryRequest(BaseModel):
    query: str
    use_hyde: bool = False
    azienda_filter: Optional[str] = None
    folder_id: Optional[str] = None
    conversation_history: Optional[List[ConversationTurn]] = []
    lang: Optional[str] = "en"

class QueryResponse(BaseModel):
    answer: str
    intent: str
    chunks: List[dict]
    kg_context: Optional[str]
    latency_ms: int
    model: str

@app.get("/api/status")
def status(user: dict = Depends(current_user), folder_id: Optional[str] = None):
    index = get_faiss_index()
    visible = _visible_chunks(user)
    if folder_id:
        _pl = sharing.get_placements(user["user_id"])
        visible = [c for c in visible
                   if _chunk_in_folder_scope(c, folder_id, user=user, placements=_pl)]
    aziende = list({c["azienda"] for c in visible})
    return {
        "status":       "online",
        "chunks":       len(visible),
        "documents":    len({c["doc_id"] for c in visible}),
        "aziende":      aziende,
        "kg_nodes":     len(_kg_nodes),
        "kg_edges":     len(_kg_edges),
        "llm_mode":     _llm_mode_label(),
        "version":      "2.6.0",
    }

@app.get("/api/llm/status")
def llm_status(user: dict = Depends(current_user)):
    """Stato dei backend LLM per l'interruttore: quale è attivo e quali disponibili."""
    avail = _available_backends()
    return {
        "active":    _decide_backend(),
        "available": avail,
        "label":     _llm_mode_label(),
        "local_model": LOCAL_MODEL,
    }


class LlmSwitchRequest(BaseModel):
    backend: str


@app.post("/api/llm/switch")
def llm_switch(req: LlmSwitchRequest,
               user: dict = Depends(require_roles(auth.ROLE_DEVELOPER, auth.ROLE_ADMIN))):
    """Cambia il backend a runtime (l'interruttore della UI). Rifiuta se non disponibile."""
    global _BACKEND_OVERRIDE
    b = req.backend
    if b not in ("cloud", "local", "offline"):
        raise HTTPException(400, "Backend non valido.")
    avail = _available_backends()
    if not avail.get(b):
        raise HTTPException(400, f"Backend '{b}' non disponibile "
                                 f"(manca la configurazione cloud o il server locale non è in esecuzione).")
    _BACKEND_OVERRIDE = b
    return {"active": _decide_backend(), "label": _llm_mode_label()}


@app.get("/api/llm/models")
def llm_models(user: dict = Depends(current_user)):
    models = []
    error = ""
    try:
        import urllib.request
        req = urllib.request.Request(f"{LOCAL_API_URL}/api/tags")
        with urllib.request.urlopen(req, timeout=2.0) as r:
            body = json.loads(r.read().decode("utf-8"))
        for m in body.get("models", []):
            name = m.get("name") or m.get("model")
            if name:
                models.append(name)
    except Exception as e:
        error = str(e)
    return {"models": models, "error": error, "local_api_url": LOCAL_API_URL}


@app.get("/api/llm/config")
def llm_config_get(user: dict = Depends(require_roles(auth.ROLE_DEVELOPER, auth.ROLE_ADMIN))):
    return {
        "backend": LLM_BACKEND,
        "cloud_api_url": CLOUD_API_URL,
        "cloud_model": CLOUD_MODEL,
        "cloud_api_style": CLOUD_API_STYLE,
        "cloud_api_key_set": bool(CLOUD_API_KEY),
        "local_model": LOCAL_MODEL,
        "local_api_url": LOCAL_API_URL,
        "local_num_ctx": LOCAL_NUM_CTX,
        "llm_timeout": LLM_TIMEOUT,
        "report_max_tokens": REPORT_MAX_TOKENS,
    }


class LlmConfigRequest(BaseModel):
    backend: Optional[str] = None
    cloud_api_url: Optional[str] = None
    cloud_model: Optional[str] = None
    cloud_api_style: Optional[str] = None
    cloud_api_key: Optional[str] = None
    local_model: Optional[str] = None
    local_api_url: Optional[str] = None
    local_num_ctx: Optional[int] = None
    llm_timeout: Optional[int] = None
    report_max_tokens: Optional[int] = None


@app.post("/api/llm/config")
def llm_config_set(req: LlmConfigRequest,
                   user: dict = Depends(require_roles(auth.ROLE_DEVELOPER, auth.ROLE_ADMIN))):
    global _BACKEND_OVERRIDE
    values = {k: v for k, v in req.dict().items() if v is not None}
    if "backend" in values and values["backend"] not in ("cloud", "local", "offline", "auto"):
        raise HTTPException(400, "Invalid backend.")
    _llm_config.save(values)
    _apply_llm_config()
    if "backend" in values:
        if values["backend"] == "auto":
            _BACKEND_OVERRIDE = None
        else:
            _BACKEND_OVERRIDE = values["backend"]
    return {"saved": True, "active": _decide_backend(), "label": _llm_mode_label()}


_ingest_jobs = {}
_ingest_jobs_lock = threading.Lock()
_ingest_work_lock = threading.Lock()


def _job_set(job_id, **fields):
    with _ingest_jobs_lock:
        job = _ingest_jobs.get(job_id, {})
        job.update(fields)
        _ingest_jobs[job_id] = job


def _job_get(job_id):
    with _ingest_jobs_lock:
        job = _ingest_jobs.get(job_id)
        return dict(job) if job else None


def _prune_ingest_jobs(max_keep=200):
    with _ingest_jobs_lock:
        if len(_ingest_jobs) <= max_keep:
            return
        done = [(jid, j) for jid, j in _ingest_jobs.items()
                if j.get("status") in ("done", "error")]
        done.sort(key=lambda kv: kv[1].get("finished_at", ""))
        for jid, _ in done[:len(_ingest_jobs) - max_keep]:
            _ingest_jobs.pop(jid, None)


def _run_ingest_job(job_id, save_path, filename, azienda, settore, tipo, titolo,
                    folder_id, owner_id):
    _job_set(job_id, status="processing", started_at=datetime.utcnow().isoformat())
    try:
        with _ingest_work_lock:
            result = ingest_document(save_path, filename, azienda, settore, tipo, titolo,
                                     folder_id=folder_id, owner_id=owner_id)
        _job_set(job_id, status="done", result=result,
                 finished_at=datetime.utcnow().isoformat())
    except Exception as e:
        logger.exception("Ingest job %s failed", job_id)
        _job_set(job_id, status="error", error=str(e),
                 finished_at=datetime.utcnow().isoformat())
    finally:
        _prune_ingest_jobs()


@app.post("/api/ingest")
async def ingest(
    background_tasks: BackgroundTasks,
    file:    UploadFile = File(...),
    azienda: str = Form(...),
    settore: str = Form(""),
    tipo:    str = Form("documento"),
    titolo:  str = Form(""),
    folder_id: str = Form(""),
    user: dict = Depends(current_user),
):
    allowed = {"pdf", "txt", "docx", "doc", "md", "csv", "xlsx", "xls"}
    suffix = file.filename.lower().rsplit(".", 1)[-1]
    if suffix not in allowed:
        raise HTTPException(400, f"Formato non supportato: {suffix}. Usa: {allowed}")

    save_path = DOCS_DIR / f"{uuid.uuid4()}_{file.filename}"
    stream_chunk = OBS_CONFIG.get("upload_stream_chunk", 1024 * 1024)
    with save_path.open("wb") as out:
        while True:
            block = await file.read(stream_chunk)
            if not block:
                break
            out.write(block)

    if not titolo:
        titolo = file.filename.rsplit(".", 1)[0].replace("_", " ").replace("-", " ")

    job_id = uuid.uuid4().hex
    _job_set(job_id, status="queued", filename=file.filename, titolo=titolo,
             azienda=azienda, created_at=datetime.utcnow().isoformat())
    background_tasks.add_task(_run_ingest_job, job_id, save_path, file.filename,
                             azienda, settore, tipo, titolo, folder_id or None,
                             user["user_id"])
    return {"success": True, "job_id": job_id, "status": "queued", "filename": file.filename}


@app.get("/api/ingest/status/{job_id}")
def ingest_status(job_id: str, user: dict = Depends(current_user)):
    job = _job_get(job_id)
    if not job:
        raise HTTPException(404, "Job non trovato.")
    out = {"job_id": job_id, "status": job.get("status"),
           "filename": job.get("filename")}
    if job.get("status") == "done":
        out["result"] = job.get("result")
    elif job.get("status") == "error":
        out["error"] = job.get("error")
    return out


_chunk_upload_lock = threading.Lock()


def _chunk_part_path(upload_id):
    safe = "".join(c for c in upload_id if c.isalnum())
    if not safe:
        raise HTTPException(400, "upload_id non valido.")
    return UPLOAD_TMP_DIR / f"{safe}.part"


@app.post("/api/ingest/chunk")
async def ingest_chunk(
    upload_id:    str = Form(...),
    chunk_index:  int = Form(...),
    total_chunks: int = Form(...),
    chunk:  UploadFile = File(...),
    user: dict = Depends(current_user),
):
    part_path = _chunk_part_path(upload_id)
    stream_chunk = OBS_CONFIG.get("upload_stream_chunk", 1024 * 1024)
    with _chunk_upload_lock:
        mode = "wb" if chunk_index == 0 else "ab"
        with part_path.open(mode) as out:
            while True:
                block = await chunk.read(stream_chunk)
                if not block:
                    break
                out.write(block)
    return {"success": True, "upload_id": upload_id,
            "chunk_index": chunk_index, "received": chunk_index + 1,
            "total_chunks": total_chunks}


@app.post("/api/ingest/finalize")
def ingest_finalize(
    background_tasks: BackgroundTasks,
    upload_id: str = Form(...),
    filename:  str = Form(...),
    azienda:   str = Form(...),
    settore:   str = Form(""),
    tipo:      str = Form("documento"),
    titolo:    str = Form(""),
    folder_id: str = Form(""),
    user: dict = Depends(current_user),
):
    allowed = {"pdf", "txt", "docx", "doc", "md", "csv", "xlsx", "xls"}
    suffix = filename.lower().rsplit(".", 1)[-1]
    if suffix not in allowed:
        raise HTTPException(400, f"Formato non supportato: {suffix}. Usa: {allowed}")

    part_path = _chunk_part_path(upload_id)
    if not part_path.exists():
        raise HTTPException(404, "Upload non trovato o gia' finalizzato.")

    save_path = DOCS_DIR / f"{uuid.uuid4()}_{filename}"
    with _chunk_upload_lock:
        part_path.replace(save_path)

    if not titolo:
        titolo = filename.rsplit(".", 1)[0].replace("_", " ").replace("-", " ")

    job_id = uuid.uuid4().hex
    _job_set(job_id, status="queued", filename=filename, titolo=titolo,
             azienda=azienda, created_at=datetime.utcnow().isoformat())
    background_tasks.add_task(_run_ingest_job, job_id, save_path, filename,
                             azienda, settore, tipo, titolo, folder_id or None,
                             user["user_id"])
    return {"success": True, "job_id": job_id, "status": "queued", "filename": filename}


@app.post("/api/query", response_model=QueryResponse)
def query(req: QueryRequest, user: dict = Depends(current_user)):
    t0 = time.time()

    if not _chunk_store:
        raise HTTPException(400, "Nessun documento nel sistema. Carica documenti prima di fare query.")

    intent = classify_intent(req.query)
    q = req.query

    if req.use_hyde:
        q = hyde_expand(req.query)

    chunks = retrieve(q, azienda_filter=req.azienda_filter, folder_id=req.folder_id)
    chunks = ownership.filter_chunks(user, chunks, extra_doc_ids=shared_doc_ids_for(user))
    chunks = rerank(req.query, chunks)
    top_chunks = chunks[:OBS_CONFIG["top_k_reranked"]]

    if not top_chunks:
        return QueryResponse(
            answer     = "Nessun documento di tua competenza contiene informazioni pertinenti alla domanda.",
            intent     = intent,
            chunks     = [],
            kg_context = None,
            latency_ms = int((time.time() - t0) * 1000),
            model      = "none",
        )

    kg_ctx = None
    if intent in ("RELATIONAL", "ANALYTICAL"):
        kg_ctx = kg_traversal(req.query)

    gen = generate_answer(req.query, top_chunks, intent, req.conversation_history or [], _norm_lang(req.lang))

    latency = int((time.time() - t0) * 1000)
    log_audit(req.query, intent, len(top_chunks), latency, user_id=str(user["user_id"]))

    return QueryResponse(
        answer     = gen["answer"],
        intent     = intent,
        chunks     = [{"text": c["text"][:600], "azienda": c["azienda"],
                       "titolo": c["titolo"], "score": round(c.get("rerank_score", c["score"]), 3)}
                      for c in top_chunks],
        kg_context = kg_ctx,
        latency_ms = latency,
        model      = gen["model"],
    )

def _doc_owner_of(doc_id):
    for c in _chunk_store:
        if c.get("doc_id") == doc_id:
            return c.get("owner_id")
    return None


def _img_owner_of(img_id):
    for im in _image_store:
        if im.get("img_id") == img_id:
            return im.get("owner_id")
    return None


def _chunk_in_folder_scope(chunk, folder_id, user=None, placements=None):
    if not folder_id:
        return True
    eff = chunk.get("folder_id")
    if user is not None and chunk.get("doc_id") is not None:
        pl = placements if placements is not None else sharing.get_placements(user["user_id"])
        eff = _effective_folder_of(chunk, user, pl)
    if folder_id == "__unfiled__":
        return not eff
    return eff == folder_id


def _docs_in_folder(folder_id):
    return {c["doc_id"] for c in _chunk_store if c.get("folder_id") == folder_id}


def _imgs_in_folder(folder_id):
    return {im["img_id"] for im in _image_store if im.get("folder_id") == folder_id}


def shared_doc_split_for(user: dict) -> dict:
    if user["role"] == auth.ROLE_DEVELOPER:
        return {"direct": set(), "via_folder": set()}
    return sharing.shared_doc_ids_split(
        user["user_id"],
        doc_owner_of=_doc_owner_of,
        docs_in_folder=_docs_in_folder,
    )


def shared_doc_ids_for(user: dict) -> set:
    if user["role"] == auth.ROLE_DEVELOPER:
        return set()
    return sharing.shared_doc_ids(
        user["user_id"],
        doc_owner_of=_doc_owner_of,
        docs_in_folder=_docs_in_folder,
    )


def _effective_folder_of(chunk_or_doc: dict, user: dict, placements: dict) -> Optional[str]:
    """La cartella in cui l'utente vede questo documento. Per il proprietario e'
    il folder_id reale. Per chi lo ha ricevuto per condivisione diretta e' la sua
    collocazione personale, se ne ha impostata una. Per chi lo ha ricevuto
    attraverso una cartella condivisa resta la cartella del proprietario."""
    if chunk_or_doc.get("owner_id") == user["user_id"]:
        return chunk_or_doc.get("folder_id")
    did = chunk_or_doc.get("doc_id")
    if did in placements:
        return placements[did]
    return chunk_or_doc.get("folder_id")


def shared_img_ids_for(user: dict) -> set:
    if user["role"] == auth.ROLE_DEVELOPER:
        return set()
    return sharing.shared_doc_ids(
        user["user_id"],
        doc_owner_of=_img_owner_of,
        docs_in_folder=_imgs_in_folder,
    )


def _visible_chunks(user: dict) -> List[dict]:
    return ownership.filter_chunks(user, _chunk_store, extra_doc_ids=shared_doc_ids_for(user))


def _visible_images(user: dict) -> List[dict]:
    return ownership.filter_images(user, _image_store, extra_doc_ids=shared_img_ids_for(user))


@app.get("/api/documents")
def list_documents(user: dict = Depends(current_user), folder_id: Optional[str] = None):
    docs = {}
    for c in _chunk_store:
        did = c["doc_id"]
        if did not in docs:
            docs[did] = {
                "doc_id":    did,
                "titolo":    c["titolo"],
                "azienda":   c["azienda"],
                "settore":   c.get("settore", ""),
                "tipo":      c.get("tipo", ""),
                "filename":  c["filename"],
                "folder_id": c.get("folder_id"),
                "owner_id":  c.get("owner_id"),
                "timestamp": c["timestamp"],
                "chunks":    0,
            }
        docs[did]["chunks"] += 1
    visible = ownership.filter_documents(user, list(docs.values()), extra_doc_ids=shared_doc_ids_for(user))
    placements = sharing.get_placements(user["user_id"])
    split = shared_doc_split_for(user)
    visible_folder_ids = {f["folder_id"] for f in _visible_folders(user)}
    for d in visible:
        eff = _effective_folder_of(d, user, placements)
        if eff not in visible_folder_ids:
            eff = None
        d["folder_id"] = eff
        is_owner = (user["role"] == auth.ROLE_DEVELOPER
                    or d.get("owner_id") == user["user_id"])
        d["is_owner"] = is_owner
        d["shared_via_folder"] = (not is_owner) and (d["doc_id"] in split["via_folder"])
        d["can_move"] = is_owner or (d["doc_id"] in split["direct"])
    if folder_id:
        if folder_id == "__unfiled__":
            visible = [d for d in visible if not d.get("folder_id")]
        else:
            visible = [d for d in visible if d.get("folder_id") == folder_id]
    return sorted(visible, key=lambda x: x["timestamp"], reverse=True)


def _doc_source_path(doc_id: str) -> Optional[Path]:
    """Ritrova il file originale su disco per un doc_id."""
    for c in _chunk_store:
        if c.get("doc_id") == doc_id:
            sp = c.get("source_path")
            if sp and Path(sp).exists():
                return Path(sp)
            fn = c.get("filename")
            if fn:
                for f in DOCS_DIR.iterdir():
                    if f.name.endswith(fn):
                        return f
            break
    return None


@app.get("/api/documents/{doc_id}/meta")
def document_meta(doc_id: str, user: dict = Depends(current_user)):
    """Metadati per il viewer: tipo di file e, per i testi, il contenuto da mostrare."""
    rec = next((c for c in _chunk_store if c.get("doc_id") == doc_id), None)
    if not rec:
        raise HTTPException(404, "Documento non trovato.")
    if not ownership.can_see_item(user, rec.get("owner_id"),
                                  extra_doc_ids=shared_doc_ids_for(user), doc_id=doc_id):
        raise HTTPException(403, "Non hai accesso a questo documento.")
    path = _doc_source_path(doc_id)
    suffix = (rec.get("filename", "").lower().rsplit(".", 1)[-1]
              if "." in rec.get("filename", "") else "")
    kind = "pdf" if suffix == "pdf" else ("text" if suffix in ("txt", "md", "csv", "docx", "xlsx", "xls") else "other")
    out = {
        "doc_id": doc_id,
        "titolo": rec.get("titolo", ""),
        "azienda": rec.get("azienda", ""),
        "filename": rec.get("filename", ""),
        "suffix": suffix,
        "kind": kind,
        "has_file": path is not None,
    }
    if kind == "text" and path is not None:
        try:
            out["content"] = extract_text(path, rec.get("filename", ""))
        except Exception:
            out["content"] = "(impossibile leggere il contenuto)"
    return out


@app.get("/api/documents/{doc_id}/file")
def document_file(doc_id: str, user: dict = Depends(current_user)):
    """Serve il file originale (per immagini incorporate e PDF nel viewer)."""
    rec = next((c for c in _chunk_store if c.get("doc_id") == doc_id), None)
    if not rec:
        raise HTTPException(404, "Documento non trovato.")
    if not ownership.can_see_item(user, rec.get("owner_id"),
                                  extra_doc_ids=shared_doc_ids_for(user), doc_id=doc_id):
        raise HTTPException(403, "Non hai accesso a questo documento.")
    path = _doc_source_path(doc_id)
    if not path:
        raise HTTPException(404, "File originale non disponibile.")
    return FileResponse(str(path), headers={"Cache-Control": "no-cache"})

@app.get("/api/system/status-detail")
def system_status_detail(user: dict = Depends(current_user)):
    import platform, sys
    index = get_faiss_index()
    return {
        "components": {
            "embedding_model": {"status": "ok", "model": OBS_CONFIG["embedding_model"], "dim": OBS_CONFIG["embedding_dim"]},
            "faiss_index":     {"status": "ok", "vectors": index.ntotal, "type": "HNSW"},
            "knowledge_graph": {"status": "ok", "nodes": len(_kg_nodes), "edges": len(_kg_edges)},
            "chunk_store":     {"status": "ok", "chunks": len(_chunk_store)},
            "llm":             {"status": _decide_backend(), "model": _llm_mode_label()},
        },
        "reindex": {
            "needed":         index.ntotal < len(_chunk_store),
            "index_dim":      index.d,
            "configured_dim": OBS_CONFIG["embedding_dim"],
            "index_vectors":  index.ntotal,
            "chunks_total":   len(_chunk_store),
        },
        "system": {
            "python":   sys.version,
            "platform": platform.platform(),
            "obs_version": "2.6.0",
        }
    }

@app.post("/api/system/rebuild-index")
def rebuild_index(user: dict = Depends(require_roles(auth.ROLE_DEVELOPER, auth.ROLE_ADMIN))):
    global _faiss_index
    import faiss
    if not _chunk_store:
        return {"success": True, "message": "Nessun chunk da ricostruire.", "vectors": 0}

    model = get_embed_model()
    new_index = faiss.IndexHNSWFlat(OBS_CONFIG["embedding_dim"], 32)
    new_index.hnsw.efConstruction = 200
    new_index.hnsw.efSearch = 64

    texts = [c["text"] for c in _chunk_store]
    embeddings = encode_in_batches(model, texts, normalize=True)
    new_index.add(embeddings)
    _faiss_index = new_index
    _persist_index()
    return {"success": True, "message": f"Indice ricostruito con {len(texts)} chunk.", "vectors": new_index.ntotal}

@app.post("/api/system/reprocess-positions")
def reprocess_positions(user: dict = Depends(require_roles(auth.ROLE_DEVELOPER, auth.ROLE_ADMIN))):
    global _chunk_store
    if not _chunk_store:
        return {"success": True, "message": "Nessun chunk da processare.", "updated": 0}

    by_doc = {}
    for c in _chunk_store:
        if c.get("filename", "").lower().rsplit(".", 1)[-1] == "pdf":
            by_doc.setdefault(c["doc_id"], []).append(c)

    updated = 0
    docs_done = 0
    for doc_id, chunks in by_doc.items():
        path = _doc_source_path(doc_id)
        if not path or not path.exists():
            continue
        try:
            blocks = extract_pdf_blocks(path)
        except Exception as e:
            logger.warning("Reprocess posizioni fallito per doc %s: %s", doc_id, e)
            continue
        if not blocks:
            continue
        for c in chunks:
            pos = locate_chunk_position(c["text"], blocks)
            if pos:
                c["position"] = pos
                updated += 1
        docs_done += 1

    _persist_index()
    return {"success": True, "message": f"Posizioni aggiornate per {docs_done} documenti PDF.",
            "updated": updated, "documents": docs_done}

@app.delete("/api/system/reset")
def reset_system(user: dict = Depends(require_roles(auth.ROLE_DEVELOPER))):
    global _chunk_store, _faiss_index, _kg_nodes, _kg_edges
    import faiss
    _chunk_store = []
    _kg_nodes = {}
    _kg_edges = []
    _faiss_index = faiss.IndexHNSWFlat(OBS_CONFIG["embedding_dim"], 32)
    _faiss_index.hnsw.efConstruction = 200
    _faiss_index.hnsw.efSearch = 64
    _persist_index()
    import shutil
    for f in DOCS_DIR.iterdir():
        f.unlink(missing_ok=True)
    return {"success": True, "message": "Sistema resettato."}

@app.get("/api/export/documents")
def export_documents(user: dict = Depends(current_user)):
    from fastapi.responses import PlainTextResponse
    visible = _visible_chunks(user)
    if not visible:
        return PlainTextResponse("Nessun documento nel sistema.", media_type="text/plain")

    docs = {}
    for c in visible:
        did = c["doc_id"]
        if did not in docs:
            docs[did] = {
                "titolo":    c["titolo"],
                "azienda":   c["azienda"],
                "settore":   c.get("settore", "-"),
                "tipo":      c.get("tipo", "-"),
                "filename":  c["filename"],
                "timestamp": c["timestamp"],
                "chunks":    0,
            }
        docs[did]["chunks"] += 1

    lines = []
    lines.append("=" * 60)
    lines.append("OBS-LAB")
    lines.append("Document Registry")
    lines.append(f"Esportato il: {datetime.utcnow().strftime('%d/%m/%Y alle %H:%M UTC')}")
    lines.append("=" * 60)
    lines.append("")

    for i, d in enumerate(sorted(docs.values(), key=lambda x: x["timestamp"]), 1):
        ts = datetime.fromisoformat(d["timestamp"])
        lines.append(f"[{i:03d}] {d['titolo']}")
        lines.append(f"      Azienda  : {d['azienda']}")
        lines.append(f"      Settore  : {d['settore']}")
        lines.append(f"      Tipo     : {d['tipo']}")
        lines.append(f"      File     : {d['filename']}")
        lines.append(f"      Chunks   : {d['chunks']}")
        lines.append(f"      Caricato : {ts.strftime('%d/%m/%Y %H:%M')} UTC")
        lines.append("")

    lines.append("-" * 60)
    lines.append(f"Totale documenti: {len(docs)}")
    lines.append(f"Totale chunks   : {sum(d['chunks'] for d in docs.values())}")
    lines.append("=" * 60)

    text = "\n".join(lines)
    from fastapi.responses import Response
    return Response(
        content=text.encode("utf-8"),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=OBS_Registro_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.txt"}
    )

@app.delete("/api/documents/{doc_id}")
def delete_document(doc_id: str, user: dict = Depends(current_user)):
    global _chunk_store, _faiss_index, _kg_edges
    import faiss

    indices_to_remove = [i for i, c in enumerate(_chunk_store) if c["doc_id"] == doc_id]
    if not indices_to_remove:
        raise HTTPException(404, "Documento non trovato")

    owner_id = _doc_owner_of(doc_id)
    if user["role"] != auth.ROLE_DEVELOPER and owner_id != user["user_id"]:
        raise HTTPException(403, "Solo il proprietario puo' eliminare questo documento.")

    sharing.purge_target(sharing.TARGET_DOCUMENT, doc_id)
    sharing.purge_placements_for_doc(doc_id)

    removed = len(indices_to_remove)
    _chunk_store = [c for c in _chunk_store if c["doc_id"] != doc_id]
    _kg_edges = [e for e in _kg_edges if e.get("doc_id") != doc_id]

    try:
        tp = _table_path(doc_id)
        if tp.exists():
            tp.unlink()
    except Exception:
        pass

    for _p in (_digitize_session_path(doc_id), _digitize_image_path(doc_id),
               _entities_path(doc_id)):
        try:
            if _p.exists():
                _p.unlink()
        except Exception:
            pass

    model = get_embed_model()
    new_index = faiss.IndexHNSWFlat(OBS_CONFIG["embedding_dim"], 32)
    new_index.hnsw.efConstruction = 200
    new_index.hnsw.efSearch = 64
    if _chunk_store:
        texts = [c["text"] for c in _chunk_store]
        embeddings = encode_in_batches(model, texts, normalize=True)
        new_index.add(embeddings)
    _faiss_index = new_index
    _persist_index()
    return {"success": True, "removed_chunks": removed}

@app.get("/api/audit")
def audit_trail(limit: int = 50, user: dict = Depends(current_user)):
    if not AUDIT_FILE.exists():
        return []
    lines = AUDIT_FILE.read_text().strip().split("\n")
    entries = [json.loads(l) for l in lines if l]
    if user["role"] == auth.ROLE_DEVELOPER:
        pass
    elif user["role"] == auth.ROLE_ADMIN:
        company_ids = {str(u["id"]) for u in auth.list_users(user["role"], user["azienda"])}
        company_ids.add(str(user["user_id"]))
        entries = [e for e in entries if str(e.get("user_id")) in company_ids]
    else:
        uid = str(user["user_id"])
        entries = [e for e in entries if str(e.get("user_id")) == uid]
    return entries[-limit:][::-1]

@app.delete("/api/audit")
def clear_audit(user: dict = Depends(require_roles(auth.ROLE_DEVELOPER))):
    if AUDIT_FILE.exists():
        AUDIT_FILE.write_text("")
    return {"success": True, "message": "Audit trail cleared."}

@app.get("/api/kg")
def knowledge_graph(user: dict = Depends(current_user)):
    if user["role"] == auth.ROLE_DEVELOPER:
        return {"nodes": _kg_nodes, "edges": _kg_edges[:200]}
    visible_doc_ids = {c.get("doc_id") for c in _visible_chunks(user)}
    visible_aziende = {c.get("azienda") for c in _visible_chunks(user)}
    edges = [e for e in _kg_edges
             if e.get("doc_id") in visible_doc_ids
             or e.get("from") in visible_aziende or e.get("to") in visible_aziende]
    node_keys = set(visible_aziende)
    for e in edges:
        node_keys.add(e.get("from"))
        node_keys.add(e.get("to"))
    nodes = {k: v for k, v in _kg_nodes.items() if k in node_keys}
    return {"nodes": nodes, "edges": edges[:200]}

def _load_chats() -> list:
    if not CHATS_FILE.exists():
        return []
    try:
        return json.loads(CHATS_FILE.read_text())
    except:
        return []

def _save_chats(chats: list):
    CHATS_FILE.write_text(json.dumps(chats, ensure_ascii=False, indent=2))

@app.get("/api/chats")
def get_chats(user: dict = Depends(current_user)):
    uid = user["user_id"]
    return [c for c in _load_chats() if c.get("owner_id") == uid]

@app.post("/api/chats")
def save_chat(chat: dict, user: dict = Depends(current_user)):
    uid = user["user_id"]
    chat["owner_id"] = uid
    chats = _load_chats()
    existing = next((i for i, c in enumerate(chats)
                     if c.get("id") == chat.get("id") and c.get("owner_id") == uid), None)
    if existing is not None:
        chats[existing] = chat
    else:
        chats.insert(0, chat)
    mine = [c for c in chats if c.get("owner_id") == uid][:100]
    others = [c for c in chats if c.get("owner_id") != uid]
    _save_chats(mine + others)
    return {"success": True}

@app.delete("/api/chats/{chat_id}")
def delete_chat(chat_id: str, user: dict = Depends(current_user)):
    uid = user["user_id"]
    chats = _load_chats()
    chats = [c for c in chats if not (c.get("id") == chat_id and c.get("owner_id") == uid)]
    _save_chats(chats)
    return {"success": True}

@app.get("/")
def serve_frontend(request: Request):
    if auth.count_users() == 0:
        return RedirectResponse(url="/setup", status_code=302)
    token = request.cookies.get(auth_routes.SESSION_COOKIE)
    if not auth.validate_session(token):
        return RedirectResponse(url="/login", status_code=302)
    if not model_setup.models_ready():
        return RedirectResponse(url="/models", status_code=302)
    index = FRONTEND_DIR / "index.html"
    if index.exists():
        return FileResponse(
            str(index),
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0"
            }
        )
    return {"message": "OBS API running. Frontend not built yet."}


@app.get("/login")
def serve_login():
    if auth.count_users() == 0:
        return RedirectResponse(url="/setup", status_code=302)
    page = FRONTEND_DIR / "login.html"
    if page.exists():
        return FileResponse(
            str(page),
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0"
            }
        )
    return {"message": "Login page not found."}


@app.get("/setup")
def serve_setup():
    if auth.count_users() > 0:
        return RedirectResponse(url="/login", status_code=302)
    page = FRONTEND_DIR / "setup.html"
    if page.exists():
        return FileResponse(
            str(page),
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0"
            }
        )
    return {"message": "Setup page not found."}


@app.get("/models")
def serve_models(request: Request):
    token = request.cookies.get(auth_routes.SESSION_COOKIE)
    if not auth.validate_session(token):
        return RedirectResponse(url="/login", status_code=302)
    if model_setup.models_ready():
        return RedirectResponse(url="/", status_code=302)
    page = FRONTEND_DIR / "models.html"
    if page.exists():
        return FileResponse(
            str(page),
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0"
            }
        )
    return {"message": "Models page not found."}


@app.get("/api/models/status")
def api_models_status(user: dict = Depends(current_user)):
    return model_setup.get_status()


@app.post("/api/models/download")
def api_models_download(user: dict = Depends(current_user)):
    return model_setup.start_download()

@app.get("/api/spacy/status")
def api_spacy_status(user: dict = Depends(current_user)):
    return model_setup.spacy_status()


@app.post("/api/spacy/download")
def api_spacy_download(user: dict = Depends(current_user)):
    return model_setup.start_spacy_download()


@app.post("/api/spacy/remove")
def api_spacy_remove(user: dict = Depends(require_roles("admin"))):
    return model_setup.remove_spacy()


@app.get("/api/clip/status")
def api_clip_status(user: dict = Depends(current_user)):
    return model_setup.clip_status()


@app.post("/api/clip/download")
def api_clip_download(user: dict = Depends(current_user)):
    return model_setup.start_clip_download()


@app.post("/api/clip/remove")
def api_clip_remove(user: dict = Depends(require_roles("admin"))):
    return model_setup.remove_clip()

@app.get("/i18n.js")
def serve_i18n():
    f = FRONTEND_DIR / "i18n.js"
    return FileResponse(str(f), headers={"Cache-Control": "no-cache, no-store, must-revalidate"})

@app.get("/obs_auth_frontend.js")
def serve_auth_frontend():
    f = FRONTEND_DIR / "obs_auth_frontend.js"
    return FileResponse(str(f), headers={"Cache-Control": "no-cache, no-store, must-revalidate"})

@app.get("/obs_sharing_frontend.js")
def serve_sharing_frontend():
    f = FRONTEND_DIR / "obs_sharing_frontend.js"
    return FileResponse(str(f), headers={"Cache-Control": "no-cache, no-store, must-revalidate"})

@app.get("/obs_code_frontend.js")
def serve_code_frontend():
    f = FRONTEND_DIR / "obs_code_frontend.js"
    return FileResponse(str(f), headers={"Cache-Control": "no-cache, no-store, must-revalidate"})

@app.get("/obs_mdi_frontend.js")
def serve_mdi_frontend():
    f = FRONTEND_DIR / "obs_mdi_frontend.js"
    return FileResponse(str(f), headers={"Cache-Control": "no-cache, no-store, must-revalidate"})

@app.get("/obs_sheets_frontend.js")
def serve_sheets_frontend():
    f = FRONTEND_DIR / "obs_sheets_frontend.js"
    return FileResponse(str(f), headers={"Cache-Control": "no-cache, no-store, must-revalidate"})


ICONS_DIR = FRONTEND_DIR / "icons"


@app.get("/favicon.ico")
def serve_favicon():
    for candidate in (FRONTEND_DIR / "favicon.ico", ICONS_DIR / "favicon.ico"):
        if candidate.exists() and candidate.is_file():
            return FileResponse(
                str(candidate),
                media_type="image/png",
                headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
            )
    raise HTTPException(404, "Favicon non trovata.")


@app.get("/icons/{name}")
def serve_icon(name: str):
    import re
    if not re.fullmatch(r"[A-Za-z0-9_.\-]+\.(png|svg|gif|ico|jpg|jpeg|webp)", name):
        raise HTTPException(404, "Icona non trovata.")
    f = ICONS_DIR / name
    if not f.exists() or not f.is_file():
        raise HTTPException(404, "Icona non trovata.")
    return FileResponse(str(f), headers={"Cache-Control": "max-age=86400"})

class ChartRequest(BaseModel):
    query: str
    chart_type: Optional[str] = "auto"
    azienda_filter: Optional[str] = None
    column: Optional[str] = None
    doc_id: Optional[str] = None

@app.post("/api/chart")
def generate_chart(req: ChartRequest, user: dict = Depends(current_user)):
    import pandas as pd
    import plotly.express as px

    if req.doc_id:
        top_chunks = _chunks_for_doc(req.doc_id, user=user)
        if not top_chunks:
            raise HTTPException(404, "Documento selezionato non trovato.")
    else:
        if not (req.query or "").strip():
            raise HTTPException(400, "Scrivi una domanda o seleziona un documento.")
        chunks = retrieve(req.query, azienda_filter=req.azienda_filter, user=user)
        chunks = rerank(req.query, chunks)
        top_chunks = chunks[:8]

    if not top_chunks:
        raise HTTPException(400, "Nessun dato trovato per generare il grafico.")

    series = _get_numeric_series(top_chunks, column=req.column)
    if series.get("need_column"):
        return {"need_column": True, "columns": series["columns"], "doc": series["doc"]}
    unique_data = series["data"][:12]
    chosen_col = series.get("column")

    if not unique_data:
        raise HTTPException(400, "Impossibile estrarre dati numerici dai documenti trovati.")

    df = pd.DataFrame(unique_data)
    chart_type = req.chart_type if req.chart_type != "auto" else "bar"
    _coltxt = (" - " + chosen_col) if chosen_col else ""
    _qtitle = (req.query[:60] if (req.query or "").strip() else (top_chunks[0].get("titolo", "")))
    _ttl = f"Analisi: {_qtitle}{_coltxt}"

    _obs_palette = ['#3d5a80', '#5c6b73', '#2f4858', '#6b7a80', '#455a64',
                    '#57708c', '#4a6670', '#7d8b96', '#38505f', '#8795a0']
    if chart_type == "bar":
        fig = px.bar(df, x="label", y="value",
                     title=_ttl,
                     labels={"label": "", "value": chosen_col or "Valore"},
                     color="value",
                     color_continuous_scale=[[0.0, '#eef1f4'], [1.0, '#2f4858']])
    elif chart_type == "pie":
        fig = px.pie(df, names="label", values="value",
                     title=_ttl, color_discrete_sequence=_obs_palette)
    elif chart_type == "line":
        fig = px.line(df, x="label", y="value",
                      title=_ttl, markers=True,
                      color_discrete_sequence=['#3d5a80'])
    else:
        fig = px.bar(df, x="label", y="value",
                     title=_ttl,
                     color_discrete_sequence=['#3d5a80'])

    fig.update_layout(
        plot_bgcolor="#fffbf0", paper_bgcolor="#ffffff",
        font=dict(family="Trebuchet MS, Arial", size=12, color="#2a0000"),
        title_font_size=14, title_font_color="#2a0000", showlegend=False,
        margin=dict(l=40, r=20, t=60, b=80),
        xaxis_tickangle=-45,
    )
    if chart_type != "pie":
        fig.update_xaxes(showgrid=True, gridcolor="#a0a0a4", gridwidth=1,
                         zeroline=True, zerolinecolor="#808080", zerolinewidth=1,
                         linecolor="#808080", ticks="outside", tickcolor="#808080")
        fig.update_yaxes(showgrid=True, gridcolor="#a0a0a4", gridwidth=1,
                         zeroline=True, zerolinecolor="#808080", zerolinewidth=1,
                         linecolor="#808080", ticks="outside", tickcolor="#808080")

    return {
        "chart": _fig_to_json(fig),
        "data_points": len(unique_data),
        "sources": [{"titolo": c["titolo"], "azienda": c["azienda"]} for c in top_chunks[:3]]
    }

class AnalysisRequest(BaseModel):
    query: str
    analysis_type: str
    azienda_filter: Optional[str] = None
    column: Optional[str] = None
    x_column: Optional[str] = None
    doc_id: Optional[str] = None
    horizon: Optional[int] = None
    seasonal_periods: Optional[int] = None

def _chunks_for_doc(doc_id: str, user: Optional[dict] = None):
    """Restituisce i chunk di un documento specifico, ordinati, nel formato
    atteso dagli endpoint (lista di dict con doc_id/titolo/azienda...).
    Serve per analizzare un documento SCELTO esplicitamente, senza query."""
    chunks = [c for c in _chunk_store if c.get("doc_id") == doc_id]
    if user is not None and chunks:
        if not ownership.can_see_item(user, chunks[0].get("owner_id"),
                                      extra_doc_ids=shared_doc_ids_for(user), doc_id=doc_id):
            return []
    def _idx(c):
        try:
            return int(c["chunk_id"].rsplit("_", 1)[1])
        except Exception:
            return 0
    chunks.sort(key=_idx)
    return chunks


def _report_verify_citations(report_text, sources):
    """Verifica meccanica: per ogni frase con citazione [N], misura quanto la frase
    è semanticamente vicina al chunk citato (cosine via embedding model già in uso).
    Ritorna lista di affermazioni con stato 'verified' (verde) / 'weak' (giallo)."""
    import re
    model = get_embed_model()

    sentences = re.split(r'(?<=[.!?])\s+', report_text)
    claims = []
    for sent in sentences:
        cites = [int(x) for x in re.findall(r'\[(\d+)\]', sent)]
        clean = re.sub(r'\s*\[\d+\]', '', sent).strip()
        if not clean:
            continue
        claims.append({"text": clean, "citations": cites, "raw": sent.strip()})

    to_check = [c for c in claims if c["citations"]]
    if to_check:
        claim_vecs = model.encode([c["text"] for c in to_check],
                                  show_progress_bar=False).astype("float32")
        claim_vecs /= (np.linalg.norm(claim_vecs, axis=1, keepdims=True) + 1e-9)
        for c, cv in zip(to_check, claim_vecs):
            best = 0.0
            for n in c["citations"]:
                if 1 <= n <= len(sources):
                    sv = sources[n - 1]["_vec"]
                    sim = float(np.dot(cv, sv))
                    best = max(best, sim)
            c["score"] = round(best, 3)
            c["status"] = "verified" if best >= 0.45 else "weak"
    for c in claims:
        c.setdefault("status", "none")
        c.setdefault("score", None)
    return claims


def generate_report(query: str, azienda_filter=None, folder_id=None, user=None, lang="en"):
    """Genera un report strutturato ancorato alle fonti, con verifica delle citazioni.
    Ritorna {title, claims[], sources[], llm_model} oppure solleva per offline."""
    import re

    chunks = retrieve(query, top_k=14, azienda_filter=azienda_filter, user=user, folder_id=folder_id)
    chunks = rerank(query, chunks)
    if folder_id:
        chunks = [c for c in chunks if _chunk_in_folder_scope(c, folder_id)]
    top = chunks[:10]
    if not top:
        raise HTTPException(400, "Nessuna fonte trovata per questa richiesta.")

    model = get_embed_model()
    src_vecs = model.encode([c["text"] for c in top],
                            show_progress_bar=False).astype("float32")
    src_vecs /= (np.linalg.norm(src_vecs, axis=1, keepdims=True) + 1e-9)
    sources = []
    for i, c in enumerate(top):
        src = {
            "n": i + 1, "doc_id": c["doc_id"], "titolo": c["titolo"],
            "azienda": c["azienda"], "text": c["text"], "_vec": src_vecs[i],
        }
        if c.get("position"):
            src["position"] = c["position"]
        sources.append(src)

    ctx = "\n\n".join(f"[{s['n']}] ({s['azienda']} - {s['titolo']})\n{s['text']}"
                      for s in sources)
    _report_system = {
        "en": (
            "You are OBS-LAB, a document knowledge-management system. "
            "Produce a concise, professional report based exclusively on the numbered sources "
            "provided. Adhere to the following requirements without exception. First, every "
            "sentence that states a fact must end with the corresponding source number in "
            "square brackets, for example: \"Revenue increased over the period [2].\" Second, "
            "do not introduce any claim that is not supported by the sources. Third, where the "
            "sources are insufficient to address the request, state this explicitly. Fourth, "
            "organise the report under section headings introduced by \"## \". Fifth, respond "
            "in the language of the request. Sixth, remain concise: few sections, short "
            "sentences, no repetition. Seventh, do not append a citations or references "
            "section: citations must appear only inline, after each sentence, in the form [n]."
        ),
        "it": (
            "Sei OBS-LAB, un sistema di gestione della conoscenza "
            "documentale. Produci un report conciso e professionale basato esclusivamente "
            "sulle fonti numerate fornite. Rispetta i seguenti requisiti senza eccezioni. "
            "Primo, ogni frase che afferma un fatto deve terminare con il numero della fonte "
            "corrispondente tra parentesi quadre, ad esempio: \"I ricavi sono cresciuti nel "
            "periodo [2].\" Secondo, non introdurre alcuna affermazione non supportata dalle "
            "fonti. Terzo, qualora le fonti siano insufficienti a soddisfare la richiesta, "
            "dichiaralo esplicitamente. Quarto, organizza il report sotto intestazioni di "
            "sezione introdotte da \"## \". Quinto, rispondi nella lingua della richiesta. "
            "Sesto, mantieni la concisione: poche sezioni, frasi brevi, nessuna ripetizione. "
            "Settimo, non aggiungere una sezione di citazioni o riferimenti: le citazioni "
            "devono comparire solo inline, dopo ogni frase, nella forma [n]."
        ),
    }
    system_prompt = _report_system[_norm_lang(lang)]
    user_message = (
        f"FONTI:\n{ctx}\n\nRICHIESTA: {query}\n\n"
        "Scrivi un report BREVE con 2-4 sezioni '## Titolo'. Ricorda: ogni frase che "
        "afferma un fatto deve finire con il numero della fonte tra parentesi quadre, "
        "es. [1] o [3]. Vai dritto al punto, niente preamboli."
    )

    raw = _llm_complete(system_prompt, user_message, max_tokens=REPORT_MAX_TOKENS)

    _cut = re.search(r'\n\s*#{0,3}\s*(Citazion|Fonti|Sources|References|Bibliografia)',
                     raw, re.IGNORECASE)
    if _cut:
        raw = raw[:_cut.start()].rstrip()

    title_m = re.search(r'^\s*#+\s*(.+)$', raw, re.MULTILINE)
    title = title_m.group(1).strip() if title_m else query[:80]
    claims = _report_verify_citations(raw, sources)

    out_sources = [{k: v for k, v in s.items() if k != "_vec"} for s in sources]
    verified = sum(1 for c in claims if c["status"] == "verified")
    weak = sum(1 for c in claims if c["status"] == "weak")
    return {
        "title": title,
        "raw": raw,
        "claims": claims,
        "sources": out_sources,
        "stats": {"verified": verified, "weak": weak,
                  "total_cited": verified + weak},
        "llm_model": _llm_mode_label(),
    }


def _get_numeric_series(top_chunks, column: Optional[str] = None):
    """Smistatore del percorso numerico.

    Ritorna un dict:
      - {"need_column": True, "columns": [...], "doc": "..."} se il foglio ha
        più colonne numeriche e l'utente non ne ha ancora scelta una;
      - {"data": [{"label","value"}, ...], "column": "..."} con i dati pronti.

    Percorso tabellare (CSV/XLSX con struttura conservata) quando disponibile,
    altrimenti percorso testuale (_extract_numeric_data, invariato)."""
    if not top_chunks:
        return {"data": []}

    target_doc = top_chunks[0]["doc_id"]
    table = _load_table(target_doc)

    if not table or not table.get("columns"):
        return {"data": _extract_numeric_data(top_chunks)}

    cols = table["columns"]
    num_col_names = list(cols.keys())

    chosen = None
    if column and column in cols:
        chosen = column
    elif len(num_col_names) == 1:
        chosen = num_col_names[0]
    else:
        return {"need_column": True, "columns": num_col_names,
                "doc": table.get("filename", "")}

    labels = table.get("labels") or [str(i + 1) for i in range(len(cols[chosen]))]
    values = cols[chosen]
    n = min(len(labels), len(values))
    data = [{"label": str(labels[i]), "value": float(values[i])} for i in range(n)]
    all_numeric = {name: [float(v) for v in vals] for name, vals in cols.items()}
    return {"data": data, "column": chosen, "all_numeric": all_numeric,
            "all_columns": num_col_names}


def _extract_numeric_data(top_chunks):
    """Estrae coppie (label, value) dal documento più rilevante, in ordine.

    Euristica robusta: per ogni segmento prende l'ULTIMO numero (il valore vero,
    non l'eventuale indice iniziale tipo 'Studente 1'), conserva i decimali e
    gestisce 'milioni/mln'. Mantiene i duplicati quando le etichette sono tutte
    uguali (serie tipo 'Studente N'), altrimenti deduplica per etichetta.
    """
    import re
    if not top_chunks:
        return []

    target_doc = top_chunks[0]["doc_id"]
    doc_chunks = [c for c in _chunk_store if c["doc_id"] == target_doc]

    def _chunk_idx(c):
        try:
            return int(c["chunk_id"].rsplit("_", 1)[1])
        except:
            return 0
    doc_chunks.sort(key=_chunk_idx)

    full_text = "\n".join(c["text"] for c in doc_chunks)
    protected = re.sub(r'(?<=\d)[.,](?=\d)', '\x00', full_text)
    segments = re.split(r'[.\n;]+', protected)

    data = []
    for seg in segments:
        seg = seg.replace('\x00', '.').strip()
        if not seg:
            continue
        nums = list(re.finditer(r'\d+\.\d+|\d+', seg))
        if not nums:
            continue
        m = nums[-1]
        try:
            val = float(m.group())
        except:
            continue
        tail = seg[m.end():m.end() + 12].lower()
        if 'milion' in tail or 'mln' in tail:
            val *= 1_000_000
        label = seg[:m.start()].strip().rstrip(':').strip()
        label = re.sub(r'\s*\d+\s*$', '', label).strip()
        if 2 < len(label) < 45 and val > 0:
            data.append({"label": label, "value": val})

    if not data:
        return []

    distinct = len(set(d["label"].lower() for d in data))
    if distinct <= 2:
        return data[:200]

    seen, unique = set(), []
    for d in data:
        key = d["label"].lower()
        if key not in seen:
            seen.add(key)
            unique.append(d)
    return unique[:200]

class DigitizeRef(BaseModel):
    pixel: float
    value: str
    px: Optional[float] = None
    py: Optional[float] = None

class DigitizeAxis(BaseModel):
    axis_type: str = "linear"
    references: List[DigitizeRef]

class DigitizeCalibrateRequest(BaseModel):
    x_axis: DigitizeAxis
    y_axis: DigitizeAxis

class DigitizePoint(BaseModel):
    label: Optional[str] = None
    px: float
    py: float

class DigitizeSaveRequest(BaseModel):
    title: str
    x_name: str = "x"
    y_name: str = "y"
    x_axis: DigitizeAxis
    y_axis: DigitizeAxis
    points: List[DigitizePoint]
    folder_id: Optional[str] = None
    image_data: Optional[str] = None
    cat_mode: Optional[str] = None
    cat_list: Optional[str] = None


def _digitize_session_path(doc_id: str) -> Path:
    return DIGITIZE_DIR / f"{doc_id}.json"


def _model_dump(model):
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def _digitize_image_path(doc_id: str) -> Path:
    return DIGITIZE_DIR / f"{doc_id}.img"


def _digitize_fit(axis: "DigitizeAxis"):
    refs = [(r.pixel, r.value) for r in axis.references]
    return digitizer_core.fit_axis(refs, axis.axis_type)


def _ensure_digitize_folder():
    name = "Digitized charts"
    existing = next((f for f in _folders if f["name"].lower() == name.lower()), None)
    if existing:
        return existing["folder_id"]
    folder = {
        "folder_id": uuid.uuid4().hex[:10],
        "name":      name,
        "created":   datetime.utcnow().isoformat(),
    }
    _folders.append(folder)
    _persist_folders()
    return folder["folder_id"]


@app.post("/api/digitize/calibrate")
def digitize_calibrate(req: DigitizeCalibrateRequest, user: dict = Depends(current_user)):
    if not _DIGITIZER_OK:
        raise HTTPException(503, "Modulo di digitalizzazione non disponibile.")
    try:
        cal_x = _digitize_fit(req.x_axis)
        cal_y = _digitize_fit(req.y_axis)
    except ValueError as e:
        raise HTTPException(400, str(e))
    warnings = digitizer_core.calibration_warnings(cal_x, cal_y)
    return {"x": cal_x, "y": cal_y, "warnings": warnings}


@app.post("/api/digitize/save")
def digitize_save(req: DigitizeSaveRequest, user: dict = Depends(current_user)):
    global _chunk_store
    if not _DIGITIZER_OK:
        raise HTTPException(503, "Modulo di digitalizzazione non disponibile.")
    if not req.points:
        raise HTTPException(400, "Nessun punto da salvare.")

    x_is_category = (req.x_axis.axis_type == "category")
    try:
        cal_x = None if x_is_category else _digitize_fit(req.x_axis)
        cal_y = _digitize_fit(req.y_axis)
    except ValueError as e:
        raise HTTPException(400, str(e))

    if x_is_category:
        for i, p in enumerate(req.points):
            if not (p.label and str(p.label).strip()):
                raise HTTPException(400, "Asse categoria: ogni punto deve avere un'etichetta.")

    labels, xvals, yvals = [], [], []
    for i, p in enumerate(req.points):
        vy = digitizer_core.pixel_to_value(p.py, cal_y)
        if x_is_category:
            labels.append(str(p.label).strip())
        elif req.x_axis.axis_type == "time":
            vx = digitizer_core.pixel_to_value(p.px, cal_x)
            labels.append(p.label if p.label else vx.strftime("%Y-%m-%d"))
            xvals.append(vx.timestamp())
        else:
            vx = digitizer_core.pixel_to_value(p.px, cal_x)
            xlabel = format(float(vx), ".6g")
            labels.append(p.label if p.label else xlabel)
            xvals.append(float(vx))
        yvals.append(float(vy))

    doc_id = "dig" + hashlib.md5((req.title + datetime.utcnow().isoformat()).encode()).hexdigest()[:9]
    x_name = req.x_name or "x"
    y_name = req.y_name or "y"
    if x_is_category or req.x_axis.axis_type == "time":
        columns = {y_name: yvals}
    else:
        columns = {x_name: xvals, y_name: yvals}

    table = {
        "doc_id":    doc_id,
        "filename":  req.title + " (digitalizzato)",
        "label_col": x_name,
        "labels":    labels,
        "columns":   columns,
        "n_rows":    len(req.points),
    }
    try:
        _table_path(doc_id).write_text(json.dumps(table, ensure_ascii=False))
    except Exception as e:
        raise HTTPException(500, "Impossibile salvare la tabella: " + str(e))

    session = {
        "doc_id":   doc_id,
        "title":    req.title,
        "x_name":   x_name,
        "y_name":   y_name,
        "x_type":   req.x_axis.axis_type,
        "y_type":   req.y_axis.axis_type,
        "cat_mode": req.cat_mode,
        "cat_list": req.cat_list,
        "refs_x":   [_model_dump(r) for r in req.x_axis.references],
        "refs_y":   [_model_dump(r) for r in req.y_axis.references],
        "points":   [_model_dump(p) for p in req.points],
        "has_image": False,
    }
    if req.image_data:
        try:
            raw = req.image_data
            if "," in raw and raw.strip().startswith("data:"):
                raw = raw.split(",", 1)[1]
            import base64
            _digitize_image_path(doc_id).write_bytes(base64.b64decode(raw))
            session["has_image"] = True
            session["image_mime"] = "image/png"
        except Exception:
            session["has_image"] = False
    try:
        _digitize_session_path(doc_id).write_text(json.dumps(session, ensure_ascii=False))
    except Exception:
        pass

    summary = "Dati digitalizzati dal grafico '" + req.title + "'. "
    summary += "Coppie (" + x_name + ", " + y_name + "): "
    summary += "; ".join(labels[i] + " " + format(yvals[i], ".6g") for i in range(len(labels)))
    target_folder = req.folder_id if req.folder_id else _ensure_digitize_folder()

    model = get_embed_model()
    index = get_faiss_index()
    summary_vec = model.encode([summary], show_progress_bar=False).astype("float32")
    summary_vec = summary_vec / (np.linalg.norm(summary_vec, axis=1, keepdims=True) + 1e-9)
    index.add(summary_vec)

    _chunk_store.append({
        "chunk_id":   doc_id + "_0",
        "doc_id":     doc_id,
        "azienda":    "Digitalizzazione",
        "settore":    "",
        "tipo":       "grafico",
        "titolo":     req.title,
        "filename":   req.title + " (digitalizzato)",
        "source_path": "",
        "text":       summary,
        "folder_id":  target_folder,
        "owner_id":   user["user_id"],
        "timestamp":  datetime.utcnow().isoformat(),
    })
    _persist_index()

    if x_is_category:
        full = digitizer_core.calibration_warnings(cal_y, cal_y)
        cal_warn = [w for w in full if w.startswith("Asse Y")]
    else:
        cal_warn = digitizer_core.calibration_warnings(cal_x, cal_y)
    return {
        "doc_id":   doc_id,
        "n_points": len(req.points),
        "columns":  list(columns.keys()),
        "warnings": cal_warn,
        "folder_id": target_folder,
        "calibration": {"x": cal_x, "y": cal_y},
    }


class DigitizeSeries(BaseModel):
    name: str
    points: List[DigitizePoint]


class DigitizeMultiSaveRequest(BaseModel):
    title: str
    x_name: str = "x"
    x_axis: DigitizeAxis
    y_axis: DigitizeAxis
    series: List[DigitizeSeries]
    folder_id: Optional[str] = None
    image_data: Optional[str] = None


class DigitizeDetectRequest(BaseModel):
    image_data: str
    target_color: List[int]
    tolerance: int = 40
    max_points: int = 60


@app.post("/api/digitize/save-multi")
def digitize_save_multi(req: DigitizeMultiSaveRequest, user: dict = Depends(current_user)):
    global _chunk_store
    if not _DIGITIZER_OK:
        raise HTTPException(503, "Modulo di digitalizzazione non disponibile.")
    if not req.series or all(not s.points for s in req.series):
        raise HTTPException(400, "Nessuna serie con punti da salvare.")

    x_is_category = (req.x_axis.axis_type == "category")
    try:
        cal_x = None if x_is_category else _digitize_fit(req.x_axis)
        cal_y = _digitize_fit(req.y_axis)
    except ValueError as e:
        raise HTTPException(400, str(e))

    reference = max(req.series, key=lambda s: len(s.points))
    labels = []
    for p in reference.points:
        if x_is_category:
            labels.append(str(p.label).strip() if p.label else "")
        elif req.x_axis.axis_type == "time":
            vx = digitizer_core.pixel_to_value(p.px, cal_x)
            labels.append(p.label if p.label else vx.strftime("%Y-%m-%d"))
        else:
            vx = digitizer_core.pixel_to_value(p.px, cal_x)
            labels.append(p.label if p.label else format(float(vx), ".6g"))

    columns = {}
    if not x_is_category and req.x_axis.axis_type not in ("time",):
        columns[req.x_name or "x"] = [
            float(digitizer_core.pixel_to_value(p.px, cal_x)) for p in reference.points
        ]

    for s in req.series:
        yvals = [float(digitizer_core.pixel_to_value(p.py, cal_y)) for p in s.points]
        columns[s.name] = yvals

    doc_id = "dig" + hashlib.md5((req.title + datetime.utcnow().isoformat()).encode()).hexdigest()[:9]
    n_rows = len(reference.points)
    table = {
        "doc_id":    doc_id,
        "filename":  req.title + " (digitalizzato)",
        "label_col": req.x_name or "x",
        "labels":    labels,
        "columns":   columns,
        "n_rows":    n_rows,
    }
    try:
        _table_path(doc_id).write_text(json.dumps(table, ensure_ascii=False))
    except Exception as e:
        raise HTTPException(500, "Impossibile salvare la tabella: " + str(e))

    session = {
        "doc_id":   doc_id,
        "title":    req.title,
        "x_name":   req.x_name or "x",
        "x_type":   req.x_axis.axis_type,
        "y_type":   req.y_axis.axis_type,
        "refs_x":   [_model_dump(r) for r in req.x_axis.references],
        "refs_y":   [_model_dump(r) for r in req.y_axis.references],
        "series":   [{"name": s.name, "points": [_model_dump(p) for p in s.points]} for s in req.series],
        "has_image": False,
        "multi":    True,
    }
    if req.image_data:
        try:
            raw = req.image_data
            if "," in raw and raw.strip().startswith("data:"):
                raw = raw.split(",", 1)[1]
            import base64
            _digitize_image_path(doc_id).write_bytes(base64.b64decode(raw))
            session["has_image"] = True
            session["image_mime"] = "image/png"
        except Exception:
            session["has_image"] = False
    try:
        _digitize_session_path(doc_id).write_text(json.dumps(session, ensure_ascii=False))
    except Exception:
        pass

    series_names = ", ".join(s.name for s in req.series)
    summary = "Dati digitalizzati dal grafico '" + req.title + "' con serie multiple: " + series_names + ". "
    summary += str(len(req.series)) + " serie, " + str(n_rows) + " punti di riferimento."
    target_folder = req.folder_id if req.folder_id else _ensure_digitize_folder()

    model = get_embed_model()
    index = get_faiss_index()
    summary_vec = model.encode([summary], show_progress_bar=False).astype("float32")
    summary_vec = summary_vec / (np.linalg.norm(summary_vec, axis=1, keepdims=True) + 1e-9)
    index.add(summary_vec)

    _chunk_store.append({
        "chunk_id":   doc_id + "_0",
        "doc_id":     doc_id,
        "azienda":    "Digitalizzazione",
        "settore":    "",
        "tipo":       "grafico",
        "titolo":     req.title,
        "filename":   req.title + " (digitalizzato)",
        "source_path": "",
        "text":       summary,
        "folder_id":  target_folder,
        "owner_id":   user["user_id"],
        "timestamp":  datetime.utcnow().isoformat(),
    })
    _persist_index()

    if x_is_category:
        full = digitizer_core.calibration_warnings(cal_y, cal_y)
        cal_warn = [w for w in full if w.startswith("Asse Y")]
    else:
        cal_warn = digitizer_core.calibration_warnings(cal_x, cal_y)
    return {
        "doc_id":   doc_id,
        "series":   [s.name for s in req.series],
        "columns":  list(columns.keys()),
        "n_points": n_rows,
        "warnings": cal_warn,
        "folder_id": target_folder,
    }


@app.post("/api/digitize/detect-points")
def digitize_detect_points(req: DigitizeDetectRequest, user: dict = Depends(current_user)):
    if not _DIGITIZER_OK:
        raise HTTPException(503, "Modulo di digitalizzazione non disponibile.")
    try:
        import base64
        from PIL import Image
        import io
        raw = req.image_data
        if "," in raw and raw.strip().startswith("data:"):
            raw = raw.split(",", 1)[1]
        img = Image.open(io.BytesIO(base64.b64decode(raw))).convert("RGB")
    except Exception as e:
        raise HTTPException(400, "Immagine non leggibile: " + str(e))

    arr = np.asarray(img, dtype=np.int16)
    tr, tg, tb = (int(req.target_color[0]), int(req.target_color[1]), int(req.target_color[2]))
    tol = max(1, int(req.tolerance))

    dist = (np.abs(arr[:, :, 0] - tr) + np.abs(arr[:, :, 1] - tg) + np.abs(arr[:, :, 2] - tb))
    mask = dist <= (tol * 3)
    height, width = mask.shape

    points = []
    for col in range(width):
        rows = np.where(mask[:, col])[0]
        if rows.size == 0:
            continue
        py = float(np.mean(rows))
        points.append({"px": float(col), "py": py})

    if not points:
        return {"points": [], "message": "Nessun pixel corrisponde al colore indicato."}

    max_pts = max(2, int(req.max_points))
    if len(points) > max_pts:
        step = len(points) / float(max_pts)
        sampled = [points[int(i * step)] for i in range(max_pts)]
        points = sampled

    return {"points": points, "detected": len(points),
            "image_width": width, "image_height": height}


@app.get("/api/digitize/session/{doc_id}")
def digitize_session(doc_id: str, user: dict = Depends(current_user)):
    if not _chunks_for_doc(doc_id, user=user):
        raise HTTPException(403, "Non hai accesso a questa digitalizzazione.")
    sp = _digitize_session_path(doc_id)
    if not sp.exists():
        raise HTTPException(404, "Sessione di digitalizzazione non trovata.")
    try:
        return json.loads(sp.read_text())
    except Exception as e:
        raise HTTPException(500, "Sessione illeggibile: " + str(e))


@app.get("/api/digitize/image/{doc_id}")
def digitize_image(doc_id: str, user: dict = Depends(current_user)):
    if not _chunks_for_doc(doc_id, user=user):
        raise HTTPException(403, "Non hai accesso a questa digitalizzazione.")
    ip = _digitize_image_path(doc_id)
    if not ip.exists():
        raise HTTPException(404, "Immagine di digitalizzazione non trovata.")
    return FileResponse(str(ip), media_type="image/png", headers={"Cache-Control": "no-cache"})


@app.post("/api/analyze")
def analyze(req: AnalysisRequest, user: dict = Depends(current_user)):
    import numpy as np
    import pandas as pd
    import plotly.graph_objects as go
    from scipy import stats as scipy_stats

    if req.doc_id:
        top_chunks = _chunks_for_doc(req.doc_id, user=user)
        if not top_chunks:
            raise HTTPException(404, "Documento selezionato non trovato.")
    else:
        if not (req.query or "").strip():
            raise HTTPException(400, "Scrivi una domanda o seleziona un documento.")
        chunks = retrieve(req.query, azienda_filter=req.azienda_filter, user=user)
        chunks = rerank(req.query, chunks)
        top_chunks = chunks[:8]
    if not top_chunks:
        raise HTTPException(400, "Nessun dato trovato.")

    at = req.analysis_type
    eff_column = req.column
    if at == "correlation" and not eff_column:
        probe = _get_numeric_series(top_chunks, column=None)
        if probe.get("need_column") and probe.get("columns"):
            eff_column = probe["columns"][0]

    series = _get_numeric_series(top_chunks, column=eff_column)
    if series.get("need_column"):
        return {"need_column": True, "columns": series["columns"], "doc": series["doc"]}
    unique = series["data"]
    if len(unique) < 2:
        raise HTTPException(400, "Dati numerici insufficienti per l'analisi.")

    labels = [d["label"] for d in unique]
    values = np.array([d["value"] for d in unique], dtype=float)
    n = len(values)
    all_numeric = series.get("all_numeric", {})
    chosen_col = series.get("column")
    stats_out, interpretation = {}, ""
    fig = go.Figure()

    if at == "regression":
        if all_numeric and len(all_numeric) >= 2:
            x_col = req.x_column
            if not x_col or x_col not in all_numeric:
                others = [c for c in all_numeric.keys() if c != chosen_col]
                return {"need_x_column": True, "x_columns": others,
                        "y_column": chosen_col, "doc": series.get("doc", "")}
            xv = np.array(all_numeric[x_col], dtype=float)
            yv = np.array(all_numeric[chosen_col], dtype=float)
            m = min(len(xv), len(yv))
            xv, yv = xv[:m], yv[:m]
            slope, intercept, r, p, se = scipy_stats.linregress(xv, yv)
            order = np.argsort(xv)
            fig.add_trace(go.Scatter(x=xv, y=yv, mode='markers', name='Data',
                                     marker=dict(size=8, color='#3d5a80')))
            fig.add_trace(go.Scatter(x=xv[order], y=(slope*xv + intercept)[order],
                                     mode='lines', name='Regression',
                                     line=dict(color='#8fa3b5', width=3)))
            fig.update_layout(title=f"Linear Regression: {chosen_col} vs {x_col}",
                              xaxis_title=x_col, yaxis_title=chosen_col)
            stats_out = {"x": x_col, "y": chosen_col,
                         "slope": round(slope, 4), "intercept": round(intercept, 4),
                         "R²": round(r**2, 4), "p-value": f"{p:.2e}", "std err": round(se, 4)}
            trend = "crescente" if slope > 0 else "decrescente"
            fit = "forte" if r**2 > 0.7 else ("moderata" if r**2 > 0.4 else "debole")
            interpretation = (f"Regressione di {chosen_col} su {x_col}. Trend {trend}, "
                              f"bonta del fit {fit} (R²={r**2:.3f}). Per ogni unita di "
                              f"{x_col}, {chosen_col} varia di {slope:.2f} in media.")
        else:
            x = np.arange(n)
            slope, intercept, r, p, se = scipy_stats.linregress(x, values)
            line = slope * x + intercept
            fig.add_trace(go.Scatter(x=x, y=values, mode='markers', name='Data',
                                     marker=dict(size=9, color='#3d5a80')))
            fig.add_trace(go.Scatter(x=x, y=line, mode='lines', name='Regression',
                                     line=dict(color='#8fa3b5', width=3)))
            fig.update_layout(title=f"Linear Regression: {req.query[:50]}",
                              xaxis_title="Index", yaxis_title="Value")
            stats_out = {"slope": round(slope, 4), "intercept": round(intercept, 4),
                         "R²": round(r**2, 4), "p-value": f"{p:.2e}", "std err": round(se, 4)}
            trend = "crescente" if slope > 0 else "decrescente"
            fit = "forte" if r**2 > 0.7 else ("moderata" if r**2 > 0.4 else "debole")
            interpretation = f"Trend {trend}. Bonta del fit {fit} (R²={r**2:.3f}). Ogni step varia il valore di {slope:.2f} in media."

    elif at == "descriptive":
        fig.add_trace(go.Bar(x=labels, y=values, marker_color='#3d5a80'))
        fig.add_hline(y=float(np.mean(values)), line_dash="dash", line_color="#8fa3b5",
                      annotation_text="Mean")
        fig.update_layout(title=f"Descriptive Statistics: {req.query[:50]}", xaxis_tickangle=-45)
        stats_out = {
            "count": n, "mean": round(float(np.mean(values)), 2),
            "median": round(float(np.median(values)), 2),
            "std": round(float(np.std(values, ddof=1)), 2),
            "min": round(float(np.min(values)), 2), "max": round(float(np.max(values)), 2),
            "Q1": round(float(np.percentile(values, 25)), 2),
            "Q3": round(float(np.percentile(values, 75)), 2),
            "skewness": round(float(scipy_stats.skew(values)), 3),
            "kurtosis": round(float(scipy_stats.kurtosis(values)), 3),
            "CV%": round(float(np.std(values, ddof=1) / np.mean(values) * 100), 1),
        }
        interpretation = f"Media {np.mean(values):.2f}, deviazione std {np.std(values, ddof=1):.2f}. Coefficiente di variazione {stats_out['CV%']}%."

    elif at == "distribution_normal":
        mu, sigma = scipy_stats.norm.fit(values)
        xr = np.linspace(values.min(), values.max(), 200)
        pdf = scipy_stats.norm.pdf(xr, mu, sigma)
        fig.add_trace(go.Histogram(x=values, histnorm='probability density', name='Data',
                                   marker_color='#3d5a80', opacity=0.6, nbinsx=min(15, n)))
        fig.add_trace(go.Scatter(x=xr, y=pdf, mode='lines', name='Normal fit',
                                 line=dict(color='#8fa3b5', width=3)))
        fig.update_layout(title=f"Normal Distribution Fit: {req.query[:40]}")
        ks_stat, ks_p = scipy_stats.kstest(values, 'norm', args=(mu, sigma))
        stats_out = {"mu (mean)": round(mu, 3), "sigma (std)": round(sigma, 3),
                     "KS statistic": round(ks_stat, 4), "KS p-value": round(ks_p, 4)}
        interpretation = ("Distribuzione compatibile con la normale (p>0.05)." if ks_p > 0.05
                          else "I dati si discostano dalla normale (p<0.05).")

    elif at == "distribution_poisson":
        from scipy import stats as _st
        lam = float(np.mean(values))
        is_count_like = np.allclose(values, np.round(values)) and values.max() < 1000
        fig.add_trace(go.Histogram(x=values, histnorm='probability density', name='Data',
                                   marker_color='#3d5a80', opacity=0.6, nbinsx=min(15, n)))
        k = np.arange(int(values.min()), int(values.max()) + 1)
        pmf = _st.poisson.pmf(k, lam)
        fig.add_trace(go.Scatter(x=k, y=pmf, mode='lines', name='Poisson fit',
                                 line=dict(color='#8fa3b5', width=3)))
        fig.update_layout(title=f"Poisson Fit (lambda={lam:.1f}): {req.query[:35]}",
                          xaxis_title="Value", yaxis_title="Probability / Density")
        var = float(np.var(values))
        stats_out = {"lambda": round(lam, 3), "variance": round(var, 3),
                     "mean/var ratio": round(lam / (var + 1e-9), 3)}
        if not is_count_like:
            interpretation = (f"lambda={lam:.1f}. ATTENZIONE: i dati non sembrano conteggi interi, "
                              f"la Poisson e poco appropriata. Per una vera Poisson serve media circa varianza "
                              f"(qui media={lam:.0f}, varianza={var:.0f}).")
        else:
            interpretation = (f"lambda stimato = {lam:.1f}. Media={lam:.0f}, varianza={var:.0f}; "
                              f"per una Poisson ideale i due valori coincidono.")

    elif at == "histogram":
        fig.add_trace(go.Histogram(x=values, histnorm='probability density', name='Histogram',
                                   marker_color='#3d5a80', opacity=0.6, nbinsx=min(15, n)))
        if n > 2:
            kde = scipy_stats.gaussian_kde(values)
            xr = np.linspace(values.min(), values.max(), 200)
            fig.add_trace(go.Scatter(x=xr, y=kde(xr), mode='lines', name='KDE',
                                     line=dict(color='#8fa3b5', width=3)))
        fig.update_layout(title=f"Histogram + KDE: {req.query[:45]}")
        stats_out = {"count": n, "mean": round(float(np.mean(values)), 2),
                     "std": round(float(np.std(values, ddof=1)), 2)}
        interpretation = "Distribuzione empirica dei valori con stima di densita kernel."

    elif at == "boxplot":
        fig.add_trace(go.Box(y=values, name=req.query[:30], marker_color='#3d5a80',
                             boxmean='sd'))
        fig.update_layout(title=f"Box Plot: {req.query[:50]}")
        q1, q3 = np.percentile(values, 25), np.percentile(values, 75)
        iqr = q3 - q1
        outliers = values[(values < q1 - 1.5*iqr) | (values > q3 + 1.5*iqr)]
        stats_out = {"Q1": round(float(q1), 2), "median": round(float(np.median(values)), 2),
                     "Q3": round(float(q3), 2), "IQR": round(float(iqr), 2),
                     "outliers": len(outliers)}
        interpretation = f"{len(outliers)} outlier rilevati (oltre 1.5xIQR dai quartili)."

    elif at == "correlation":
        if all_numeric and len(all_numeric) >= 2:
            m = min(len(v) for v in all_numeric.values())
            df = pd.DataFrame({k: v[:m] for k, v in all_numeric.items()})
            corr = df.corr()
            fig.add_trace(go.Heatmap(z=corr.values, x=corr.columns.tolist(),
                                     y=corr.columns.tolist(),
                                     colorscale=[[0.0, '#2f4858'], [0.5, '#eef1f4'], [1.0, '#5f7a6a']],
                                     zmid=0, zmin=-1, zmax=1,
                                     text=np.round(corr.values, 2), texttemplate="%{text}"))
            fig.update_layout(title="Correlation Heatmap")
            cv = corr.values.copy()
            np.fill_diagonal(cv, 0.0)
            i, j = np.unravel_index(np.argmax(np.abs(cv)), cv.shape)
            stats_out = {"variables": len(corr.columns),
                         "strongest pair": f"{corr.columns[i]} / {corr.columns[j]}",
                         "strongest corr": round(float(cv[i, j]), 3)}
            interpretation = (f"Matrice di correlazione tra le {len(corr.columns)} colonne "
                              f"numeriche. Coppia piu' correlata: {corr.columns[i]} e "
                              f"{corr.columns[j]} (r={cv[i, j]:+.2f}). Valori vicini a +1 o -1 "
                              f"indicano legame forte, vicini a 0 legame debole.")
        else:
            raise HTTPException(400, "La heatmap di correlazione richiede un foglio con "
                                     "almeno due colonne numeriche (CSV/XLSX strutturato).")

    elif at == "montecarlo":
        from scipy import stats as _st
        sims = 10000
        rng = np.random.default_rng(42)
        mu, sigma = float(np.mean(values)), float(np.std(values, ddof=1))

        candidates = {"normal": _st.norm, "t-Student": _st.t,
                      "lognormal": _st.lognorm, "gamma": _st.gamma,
                      "exponential": _st.expon, "logistic": _st.logistic}
        positive = bool(np.all(values > 0))
        best_name, best_dist, best_params, best_ks = "normal", _st.norm, (mu, sigma), np.inf
        fit_table = {}
        for name, dist in candidates.items():
            if name in ("lognormal", "gamma", "exponential") and not positive:
                continue
            try:
                params = dist.fit(values)
                ks_stat, _ = _st.kstest(values, dist.name, args=params)
                fit_table[name] = round(float(ks_stat), 4)
                if ks_stat < best_ks:
                    best_ks, best_name, best_dist, best_params = ks_stat, name, dist, params
            except Exception:
                continue

        sim = best_dist.rvs(*best_params, size=sims, random_state=rng)
        sim = sim[np.isfinite(sim)]
        if sim.size < 100:
            sim = rng.normal(mu, sigma, sims)
            best_name, best_dist, best_params = "normal", _st.norm, (mu, sigma)

        fig.add_trace(go.Histogram(x=sim, histnorm='probability density', name='MC simulation',
                                   marker_color='#3d5a80', opacity=0.55, nbinsx=60))
        xr = np.linspace(float(np.min(sim)), float(np.max(sim)), 200)
        try:
            theo = best_dist.pdf(xr, *best_params)
            fig.add_trace(go.Scatter(x=xr, y=theo, mode='lines',
                                     name=f'{best_name} fit', line=dict(color='#8fa3b5', width=2)))
        except Exception:
            pass
        fig.add_trace(go.Scatter(x=values, y=np.zeros(n), mode='markers', name='Real data',
                                 marker=dict(color='#2a0000', size=7, symbol='line-ns-open')))
        p5, p50, p95 = np.percentile(sim, [5, 50, 95])
        for val, lbl, col in [(p5, "P5", "#7d8b96"), (p50, "P50", "#3d5a80"), (p95, "P95", "#2f4858")]:
            fig.add_vline(x=val, line_dash="dash", line_color=col, annotation_text=lbl)
        fig.update_layout(title=f"Monte Carlo (10k sims, {best_name}): {req.query[:30]}",
                          xaxis_title="Simulated value", yaxis_title="Density")
        stats_out = {"simulations": sims, "best fit": best_name,
                     "KS statistic": round(float(best_ks), 4),
                     "sim mean": round(float(np.mean(sim)), 2),
                     "sim std": round(float(np.std(sim, ddof=1)), 2),
                     "P5": round(float(p5), 2), "P50": round(float(p50), 2),
                     "P95": round(float(p95), 2),
                     "VaR 95%": round(float(np.mean(sim) - p5), 2),
                     "candidates KS": ", ".join(f"{k}={v}" for k, v in
                                                sorted(fit_table.items(), key=lambda kv: kv[1]))}
        interpretation = (f"10.000 scenari simulati dalla distribuzione che meglio adatta i dati "
                          f"({best_name}, KS={best_ks:.3f}, piu basso e meglio). Intervallo di "
                          f"confidenza 90%: [{p5:.1f}, {p95:.1f}]. La distribuzione scelta puo essere "
                          f"non normale se i dati sono asimmetrici o a code spesse. Le tacche rosse "
                          f"sono i dati reali.")

    elif at == "tstudent":
        params = scipy_stats.t.fit(values)
        dfree, loc, scale = params
        xr = np.linspace(values.min(), values.max(), 200)
        t_pdf = scipy_stats.t.pdf(xr, dfree, loc, scale)
        n_pdf = scipy_stats.norm.pdf(xr, float(np.mean(values)), float(np.std(values, ddof=1)))
        fig.add_trace(go.Histogram(x=values, histnorm='probability density', name='Data',
                                   marker_color='#3d5a80', opacity=0.5, nbinsx=min(15, n)))
        fig.add_trace(go.Scatter(x=xr, y=t_pdf, mode='lines', name='t-Student',
                                 line=dict(color='#8fa3b5', width=3)))
        fig.add_trace(go.Scatter(x=xr, y=n_pdf, mode='lines', name='Normal',
                                 line=dict(color='#2a00aa', width=2, dash='dash')))
        fig.update_layout(title=f"t-Student vs Normal (fat tails): {req.query[:30]}")
        stats_out = {"df (tail param)": round(dfree, 3), "loc": round(loc, 3), "scale": round(scale, 3),
                     "kurtosis": round(float(scipy_stats.kurtosis(values)), 3)}
        interpretation = (f"Gradi di liberta={dfree:.1f}. " +
                          ("Code spesse (fat tails) marcate." if dfree < 10 else "Code vicine alla normale."))

    elif at == "qqplot":
        (osm, osr), (slope, intercept, r) = scipy_stats.probplot(values, dist="norm")
        fig.add_trace(go.Scatter(x=osm, y=osr, mode='markers', name='Data quantiles',
                                 marker=dict(size=8, color='#3d5a80')))
        fig.add_trace(go.Scatter(x=osm, y=slope*osm + intercept, mode='lines', name='Normal line',
                                 line=dict(color='#8fa3b5', width=3)))
        fig.update_layout(title=f"Q-Q Plot (normality): {req.query[:40]}",
                          xaxis_title="Theoretical quantiles", yaxis_title="Sample quantiles")
        stats_out = {"R (linearity)": round(r, 4), "slope": round(slope, 3)}
        interpretation = ("Punti allineati: dati ~ normali." if r > 0.97
                          else "Deviazioni dalla retta: non-normalita presente.")

    elif at == "cdf":
        sorted_v = np.sort(values)
        cdf_y = np.arange(1, n + 1) / n
        fig.add_trace(go.Scatter(x=sorted_v, y=cdf_y, mode='lines+markers', name='Empirical CDF',
                                 line=dict(color='#3d5a80', width=2)))
        mu, sigma = float(np.mean(values)), float(np.std(values, ddof=1))
        xr = np.linspace(values.min(), values.max(), 200)
        fig.add_trace(go.Scatter(x=xr, y=scipy_stats.norm.cdf(xr, mu, sigma), mode='lines',
                                 name='Normal CDF', line=dict(color='#8fa3b5', width=2, dash='dash')))
        fig.update_layout(title=f"Cumulative Distribution: {req.query[:40]}",
                          xaxis_title="Value", yaxis_title="Cumulative probability")
        stats_out = {"count": n, "median": round(float(np.median(values)), 2)}
        interpretation = "Distribuzione cumulativa empirica vs normale teorica."

    elif at == "forecast":
        try:
            from statsmodels.tsa.holtwinters import ExponentialSmoothing
            from statsmodels.tools.sm_exceptions import ConvergenceWarning
        except ModuleNotFoundError:
            raise HTTPException(400, "Il modulo di previsione (statsmodels) non e installato "
                                     "nell'ambiente attivo. Installa le dipendenze con "
                                     "pip install -r requirements.txt e riavvia OBS.")
        except Exception as _imp_err:
            raise HTTPException(400, "Il modulo di previsione (statsmodels) e installato ma "
                                     "non si carica, probabile incompatibilita di versione. "
                                     "Dettaglio: " + str(_imp_err))
        import warnings as _warnings

        if n < 4:
            raise HTTPException(400, "La previsione richiede almeno 4 osservazioni ordinate.")

        horizon = req.horizon if (req.horizon and req.horizon > 0) else max(3, min(n // 2, 24))

        auto_m = 0
        if req.seasonal_periods and req.seasonal_periods >= 2:
            auto_m = int(req.seasonal_periods)
        else:
            for cand in (12, 7, 4):
                if n >= 2 * cand:
                    auto_m = cand
                    break

        use_seasonal = auto_m >= 2 and n >= 2 * auto_m
        positive = bool(np.all(values > 0))
        trend_mode = "add"
        seasonal_mode = "add"

        best_fit = None
        best_aic = np.inf
        configs = []
        if use_seasonal:
            configs.append({"trend": "add", "seasonal": "add", "seasonal_periods": auto_m})
            configs.append({"trend": "add", "seasonal": "mul", "seasonal_periods": auto_m} if positive else
                           {"trend": "add", "seasonal": "add", "seasonal_periods": auto_m})
        configs.append({"trend": "add", "seasonal": None, "seasonal_periods": None})
        configs.append({"trend": None, "seasonal": None, "seasonal_periods": None})

        with _warnings.catch_warnings():
            _warnings.simplefilter("ignore", ConvergenceWarning)
            _warnings.simplefilter("ignore", RuntimeWarning)
            for cfg in configs:
                try:
                    damped = cfg["trend"] is not None
                    m = ExponentialSmoothing(
                        values,
                        trend=cfg["trend"],
                        seasonal=cfg["seasonal"],
                        seasonal_periods=cfg["seasonal_periods"],
                        damped_trend=damped,
                        initialization_method="estimated",
                    ).fit(optimized=True)
                    if np.isfinite(m.aic) and m.aic < best_aic:
                        best_aic = m.aic
                        best_fit = m
                        trend_mode = cfg["trend"] or "none"
                        seasonal_mode = cfg["seasonal"] or "none"
                except Exception:
                    continue

        if best_fit is None:
            raise HTTPException(400, "Impossibile stimare un modello di previsione su questi dati.")

        fitted = np.asarray(best_fit.fittedvalues, dtype=float)
        forecast = np.asarray(best_fit.forecast(horizon), dtype=float)
        resid = values - fitted
        sigma = float(np.std(resid, ddof=1)) if len(resid) > 1 else float(np.std(values))
        steps = np.arange(1, horizon + 1)
        band = 1.96 * sigma * np.sqrt(steps)
        lower = forecast - band
        upper = forecast + band

        hist_x = np.arange(n)
        fut_x = np.arange(n, n + horizon)

        fig.add_trace(go.Scatter(x=hist_x, y=values, mode='lines+markers', name='History',
                                 line=dict(color='#3d5a80', width=2),
                                 marker=dict(size=6, color='#3d5a80')))
        fig.add_trace(go.Scatter(x=hist_x, y=fitted, mode='lines', name='Fitted',
                                 line=dict(color='#2a00aa', width=1, dash='dot')))
        fig.add_trace(go.Scatter(x=fut_x, y=forecast, mode='lines+markers', name='Forecast',
                                 line=dict(color='#8fa3b5', width=3),
                                 marker=dict(size=6, color='#8fa3b5')))
        fig.add_trace(go.Scatter(
            x=np.concatenate([fut_x, fut_x[::-1]]),
            y=np.concatenate([upper, lower[::-1]]),
            fill='toself', fillcolor='rgba(42,0,255,0.15)',
            line=dict(color='rgba(0,0,0,0)'), name='95% interval', hoverinfo='skip'))
        fig.add_vline(x=n - 0.5, line_dash="dash", line_color="#808080")
        fig.update_layout(title=f"Forecast (Holt-Winters): {req.query[:35]}",
                          xaxis_title="Step", yaxis_title=chosen_col or "Value")

        ss_res = float(np.sum(resid ** 2))
        ss_tot = float(np.sum((values - np.mean(values)) ** 2)) + 1e-9
        r2 = 1.0 - ss_res / ss_tot
        mae = float(np.mean(np.abs(resid)))
        nz = values != 0
        mape = float(np.mean(np.abs(resid[nz] / values[nz])) * 100) if np.any(nz) else float("nan")

        stats_out = {
            "model": f"trend={trend_mode}, seasonal={seasonal_mode}" + (f" (m={auto_m})" if use_seasonal else ""),
            "horizon": horizon,
            "AIC": round(float(best_aic), 2),
            "in-sample R2": round(r2, 4),
            "MAE": round(mae, 4),
            "MAPE%": round(mape, 2) if np.isfinite(mape) else "n/a",
            "next value": round(float(forecast[0]), 4),
            "next 95% CI": f"[{lower[0]:.3g}, {upper[0]:.3g}]",
        }
        direction = "in crescita" if forecast[-1] > values[-1] else ("in calo" if forecast[-1] < values[-1] else "stabile")
        seas_txt = f" con stagionalita di periodo {auto_m}" if use_seasonal else " senza stagionalita rilevata"
        interpretation = (f"Previsione a {horizon} passi con smoothing esponenziale{seas_txt}. "
                          f"Andamento previsto {direction} (da {values[-1]:.3g} a {forecast[-1]:.3g}). "
                          f"La banda mostra l'intervallo di confidenza al 95%, che si allarga "
                          f"con l'orizzonte. Adattamento in-sample R2={r2:.3f}, MAE={mae:.3g}.")

    else:
        raise HTTPException(400, f"Tipo di analisi non riconosciuto: {at}")

    fig.update_layout(
        plot_bgcolor="#fffbf0", paper_bgcolor="#ffffff",
        font=dict(family="Trebuchet MS, Arial", size=12, color="#2a0000"),
        title_font_size=14, title_font_color="#2a0000",
        margin=dict(l=50, r=20, t=60, b=80),
        legend=dict(bgcolor="rgba(255,251,240,0.7)", bordercolor="#a0a0a4", borderwidth=1),
    )
    fig.update_xaxes(showgrid=True, gridcolor="#a0a0a4", gridwidth=1,
                     zeroline=True, zerolinecolor="#808080", zerolinewidth=1,
                     linecolor="#808080", ticks="outside", tickcolor="#808080")
    fig.update_yaxes(showgrid=True, gridcolor="#a0a0a4", gridwidth=1,
                     zeroline=True, zerolinecolor="#808080", zerolinewidth=1,
                     linecolor="#808080", ticks="outside", tickcolor="#808080")

    return {
        "chart": _fig_to_json(fig),
        "data_points": n,
        "stats": stats_out,
        "interpretation": interpretation,
        "sources": [{"titolo": c["titolo"], "azienda": c["azienda"]} for c in top_chunks[:3]],
    }


_ENTITY_TYPES = {"PER", "ORG", "LOC"}

_SPACY_NLP = None
_SPACY_TRIED = False

def _get_spacy():
    """Carica il modello spaCy italiano una sola volta. Restituisce None se
    spaCy o il modello non sono installati (il chiamante gestisce il fallback)."""
    global _SPACY_NLP, _SPACY_TRIED
    if _SPACY_TRIED:
        return _SPACY_NLP
    _SPACY_TRIED = True
    model_name = os.environ.get("SPACY_MODEL", "it_core_news_lg")
    try:
        import spacy
        spacy_path = None
        try:
            spacy_path = model_setup.spacy_model_path()
        except Exception:
            spacy_path = None
        if spacy_path:
            _SPACY_NLP = spacy.load(spacy_path)
            logger.info("spaCy NER -> loaded from %s", spacy_path)
        else:
            _SPACY_NLP = spacy.load(model_name)
            logger.info("spaCy NER -> %s caricato", model_name)
    except Exception as e:
        logger.warning("spaCy non disponibile (modello '%s': %s). NER disattivato. "
                       "Installa con: pip install spacy && "
                       "python -m spacy download %s", model_name, e, model_name)
        _SPACY_NLP = None
    return _SPACY_NLP

def _extract_entities(text: str):
    """Estrae entità nominate da un testo. Interfaccia ISOLATA: ritorna sempre
    una lista di {text, type}, indipendentemente dal motore dietro.
    type è uno di _ENTITY_TYPES. Lista vuota se il NER non è disponibile."""
    nlp = _get_spacy()
    if nlp is None or not (text or "").strip():
        return []
    out = []
    seen = set()
    for ent in nlp(text).ents:
        etype = ent.label_
        if etype not in _ENTITY_TYPES:
            continue
        name = ent.text.strip()
        if len(name) < 2:
            continue
        key = (name.lower(), etype)
        if key in seen:
            continue
        seen.add(key)
        out.append({"text": name, "type": etype})
    return out

def _entities_path(doc_id: str) -> Path:
    return ENTITIES_DIR / f"{doc_id}.json"

def _persist_entities(doc_id: str, entities: list):
    """Salva le entità di un documento (cache su disco)."""
    try:
        _entities_path(doc_id).write_text(
            json.dumps(entities, ensure_ascii=False))
    except Exception:
        logger.exception("Persistenza entità fallita per %s", doc_id)

def _load_entities(doc_id: str):
    """Carica le entità persistite di un documento, o None se assenti."""
    p = _entities_path(doc_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None

def _entities_for_doc(doc_id: str, force: bool = False):
    """Entità di un documento, con cache. Aggrega i chunk del documento,
    fa il NER una sola volta e persiste. Ogni entità riporta il conteggio
    di occorrenze nel documento e i chunk in cui appare.
    Formato: [{text, type, count, chunk_ids:[...]}]."""
    if not force:
        cached = _load_entities(doc_id)
        if cached is not None:
            return cached

    chunks = [c for c in _chunk_store if c.get("doc_id") == doc_id]
    agg = {}
    for c in chunks:
        cid = c.get("chunk_id", "")
        for e in _extract_entities(c.get("text", "")):
            key = (e["text"].lower(), e["type"])
            if key not in agg:
                agg[key] = {"text": e["text"], "type": e["type"],
                            "count": 0, "chunk_ids": []}
            agg[key]["count"] += 1
            if cid and cid not in agg[key]["chunk_ids"]:
                agg[key]["chunk_ids"].append(cid)

    entities = sorted(agg.values(), key=lambda x: x["count"], reverse=True)
    _persist_entities(doc_id, entities)
    return entities



_ER_THRESHOLD = 0.5

_ER_ORG_SUFFIXES = {
    "spa", "srl", "snc", "sas", "sapa", "scarl", "scrl", "soc", "societa",
    "gmbh", "ltd", "llc", "inc", "corp", "co", "plc", "ag", "sa", "bv", "nv",
    "sp", "sr", "sn", "sca", "scr",
}

def _er_normalize(name: str) -> str:
    """Nucleo normalizzato di un nome: minuscolo, senza punteggiatura, senza
    suffissi societari, spazi compattati. Deterministico (stadio 1).
    La punteggiatura va tolta PRIMA dello split, così 'S.p.A.' -> 'spa' e
    rientra tra i suffissi rimossi."""
    import re
    s = (name or "").lower()
    s = s.replace(".", "")
    s = re.sub(r"[\,\;\:\'\"\(\)\[\]\-]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    tokens = [t for t in s.split(" ") if t and t not in _ER_ORG_SUFFIXES]
    return " ".join(tokens)

def _er_initial_is_ambiguous(abbrev_core: str, all_cores: list) -> bool:
    """Un nucleo con un'iniziale (es. 'm rossi') è AMBIGUO se più di un nucleo
    'pieno' dello stesso insieme è compatibile con esso (stesso cognome e nome
    pieno che inizia con quella lettera). Es.: 'm rossi' è ambiguo se esistono
    sia 'mario rossi' sia 'maria rossi'. In tal caso l'iniziale non lega nessuno."""
    ta = abbrev_core.split(" ")
    init_pos = next((i for i, tok in enumerate(ta) if len(tok) == 1), None)
    if init_pos is None:
        return False
    candidates = set()
    for other in all_cores:
        if other == abbrev_core:
            continue
        tb = other.split(" ")
        if len(tb) != len(ta):
            continue
        full = tb[init_pos]
        if len(full) <= 1 or not full.startswith(ta[init_pos]):
            continue
        ok = True
        for k in range(len(ta)):
            if k == init_pos:
                continue
            if not _er_token_match(ta[k], tb[k]):
                ok = False
                break
        if ok:
            candidates.add(full)
    return len(candidates) >= 2

def _er_token_match(t1: str, t2: str) -> bool:
    """Due token (parole di un nome) corrispondono se: sono uguali; uno è
    l'iniziale dell'altro ('m' ~ 'mario'); o sono quasi identici per refusi
    (Jaro-Winkler alto sul SINGOLO token, dove una lettera diversa pesa molto
    di più che sul nome intero)."""
    if t1 == t2:
        return True
    if len(t1) == 1 and t2.startswith(t1):
        return True
    if len(t2) == 1 and t1.startswith(t2):
        return True
    import jellyfish
    return jellyfish.jaro_winkler_similarity(t1, t2) >= 0.94

def _er_similar(core_a: str, core_b: str, all_cores=None) -> float:
    """Decide se due nuclei normalizzati sono la STESSA entità, confrontando
    token per token (stadio 2). Ritorna 1.0 se coincidono, 0.0 altrimenti.

    Regola: stesso numero di token significativi, e ogni token allineato
    corrisponde via _er_token_match (uguale / iniziale / quasi-uguale).
    Distingue 'mario rossi' ~ 'm rossi' (iniziale) da 'mario rossi' !=
    'maria rossi' (due nomi pieni diversi).

    Ambiguità: se il match avviene tramite un'iniziale che è ambigua nel
    contesto (es. 'm rossi' compatibile sia con Mario sia con Maria), NON
    fonde: l'iniziale ambigua non lega nessuno. Il cognome condiviso terrà
    comunque le entità vicine nel grafo, senza affermare un'identità falsa."""
    if core_a == core_b:
        return 1.0
    ta = core_a.split(" ")
    tb = core_b.split(" ")
    if len(ta) == 1 and len(tb) == 1:
        import jellyfish
        return 1.0 if jellyfish.jaro_winkler_similarity(ta[0], tb[0]) >= 0.94 else 0.0
    if len(ta) != len(tb):
        return 0.0
    matched_via_initial = False
    for x, y in zip(ta, tb):
        if x == y:
            continue
        is_init = (len(x) == 1 and y.startswith(x)) or (len(y) == 1 and x.startswith(y))
        if is_init:
            matched_via_initial = True
            continue
        if not _er_token_match(x, y):
            return 0.0
    if matched_via_initial and all_cores is not None:
        if _er_initial_is_ambiguous(core_a, all_cores) or \
           _er_initial_is_ambiguous(core_b, all_cores):
            return 0.0
    return 1.0

def _resolve_entities(entities: list):
    """Fonde le varianti della stessa entità. Input: lista di
    {text, type, count, chunk_ids}. Output: lista di entità risolte
    {text, type, count, chunk_ids, variants:[...]}, dove `text` è la forma
    canonica scelta (la variante più frequente, a parità la più lunga).

    Algoritmo: raggruppo per tipo (vincolo, stadio 3); dentro ogni tipo unisco
    i nuclei normalizzati identici (stadio 1) e poi, tra nuclei distinti, quelli
    con Jaro-Winkler >= soglia (stadio 2). Conservativo: nel dubbio non fonde."""
    by_type = {}
    for e in entities:
        core = _er_normalize(e.get("text", ""))
        if not core:
            continue
        t = e.get("type", "?")
        by_type.setdefault(t, {})
        bucket = by_type[t]
        if core not in bucket:
            bucket[core] = {"members": [], "count": 0}
        bucket[core]["members"].append(e)
        bucket[core]["count"] += e.get("count", 1)

    resolved = []
    for t, bucket in by_type.items():
        cores = list(bucket.keys())
        parent = {c: c for c in cores}
        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x
        def union(x, y):
            rx, ry = find(x), find(y)
            if rx != ry:
                parent[ry] = rx
        for i in range(len(cores)):
            for j in range(i + 1, len(cores)):
                if _er_similar(cores[i], cores[j], cores) >= _ER_THRESHOLD:
                    union(cores[i], cores[j])
        groups = {}
        for c in cores:
            groups.setdefault(find(c), []).append(c)
        for root, core_list in groups.items():
            members = []
            for c in core_list:
                members.extend(bucket[c]["members"])
            total = sum(m.get("count", 1) for m in members)
            chunk_ids = []
            for m in members:
                for cid in m.get("chunk_ids", []):
                    if cid not in chunk_ids:
                        chunk_ids.append(cid)
            canonical = sorted(
                members,
                key=lambda m: (m.get("count", 1), len(m.get("text", ""))),
                reverse=True)[0]["text"]
            variants = sorted(set(m.get("text", "") for m in members))
            resolved.append({
                "text": canonical,
                "type": t,
                "count": total,
                "chunk_ids": chunk_ids,
                "variants": variants,
            })
    resolved.sort(key=lambda x: x["count"], reverse=True)
    return resolved


RELATION_TYPES = [
    "fornisce_a",
    "cliente_di",
    "controllata_da",
    "controlla",
    "partecipa_a",
    "collabora_con",
    "concorrente_di",
    "con_sede_in",
    "opera_in",
    "membro_di",
    "associata_a",
]

RELATION_SYNONYMS = {
    "fornitore_di": "fornisce_a",
    "fornisce": "fornisce_a",
    "supplies": "fornisce_a",
    "supplier_of": "fornisce_a",
    "vende_a": "fornisce_a",
    "customer_of": "cliente_di",
    "acquista_da": "cliente_di",
    "compra_da": "cliente_di",
    "posseduta_da": "controllata_da",
    "owned_by": "controllata_da",
    "subsidiary_of": "controllata_da",
    "controllata": "controllata_da",
    "possiede": "controlla",
    "owns": "controlla",
    "controls": "controlla",
    "detiene": "controlla",
    "partecipa": "partecipa_a",
    "partner_of": "collabora_con",
    "collabora": "collabora_con",
    "partnership_con": "collabora_con",
    "alleanza_con": "collabora_con",
    "concorrente": "concorrente_di",
    "competitor_of": "concorrente_di",
    "rivale_di": "concorrente_di",
    "sede_in": "con_sede_in",
    "con_sede_a": "con_sede_in",
    "based_in": "con_sede_in",
    "ha_sede_in": "con_sede_in",
    "situata_in": "con_sede_in",
    "opera_nel": "opera_in",
    "operates_in": "opera_in",
    "attiva_in": "opera_in",
    "membro": "membro_di",
    "member_of": "membro_di",
    "aderisce_a": "membro_di",
    "associata": "associata_a",
    "associated_with": "associata_a",
    "legata_a": "associata_a",
    "correlata_a": "associata_a",
}


def _normalize_relation_label(raw: str) -> Optional[str]:
    if not raw:
        return None
    key = raw.strip().lower().replace(" ", "_").replace("-", "_")
    while "__" in key:
        key = key.replace("__", "_")
    key = key.strip("_")
    if key in RELATION_TYPES:
        return key
    if key in RELATION_SYNONYMS:
        return RELATION_SYNONYMS[key]
    return None


def _relation_support_in_text(support: str, texts: list) -> Optional[str]:
    if not support:
        return None
    needle = " ".join(support.strip().lower().split())
    if len(needle) < 6:
        return None
    for t in texts:
        hay = " ".join((t or "").lower().split())
        if needle in hay:
            return support.strip()
    return None


def _type_single_relation(label_a: str, label_b: str, texts: list) -> Optional[dict]:
    joined = "\n\n".join("- " + " ".join((t or "").split())[:600] for t in texts[:4])
    allowed = ", ".join(RELATION_TYPES)
    system_prompt = (
        "Sei un analista che estrae relazioni tipizzate tra entita da testi aziendali. "
        "Rispondi con un solo oggetto JSON valido, senza testo aggiuntivo. "
        "Le chiavi sono: relation, direction, support, confidence. "
        "Il valore di relation deve appartenere a questo insieme chiuso: " + allowed + ". "
        "Se nessuna relazione tra le due entita e supportata dal testo, usa relation uguale a null. "
        "Il campo direction vale 'a_to_b' se la relazione va dalla prima entita alla seconda, "
        "'b_to_a' nel verso opposto. "
        "Il campo support deve essere una frase copiata alla lettera dal testo fornito. "
        "Il campo confidence e un numero tra 0 e 1."
    )
    user_message = (
        "Entita A: " + label_a + "\n"
        "Entita B: " + label_b + "\n\n"
        "Passaggi in cui compaiono insieme:\n" + joined + "\n\n"
        "Qual e la relazione tipizzata tra A e B secondo il testo?"
    )
    try:
        raw = _llm_complete(system_prompt, user_message, max_tokens=300)
    except Exception:
        return None
    if not raw:
        return None
    txt = raw.strip()
    start = txt.find("{")
    end = txt.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        obj = json.loads(txt[start:end + 1])
    except Exception:
        return None
    rel = _normalize_relation_label(obj.get("relation") or "")
    if not rel:
        return None
    support = _relation_support_in_text(str(obj.get("support") or ""), texts)
    if not support:
        return None
    direction = obj.get("direction")
    if direction not in ("a_to_b", "b_to_a"):
        direction = "a_to_b"
    try:
        conf = float(obj.get("confidence"))
    except Exception:
        conf = 0.5
    conf = max(0.0, min(1.0, conf))
    return {"relation": rel, "direction": direction,
            "support": support, "confidence": round(conf, 3)}


def _typed_relations_for_edges(entities, edges, cid_text, max_edges):
    if _decide_backend() == "offline":
        return {}
    ranked = sorted(edges, key=lambda e: e["weight"], reverse=True)
    if max_edges and max_edges > 0:
        ranked = ranked[:max_edges]
    out = {}
    for e in ranked:
        a_i, b_i = e["source"], e["target"]
        ent_a, ent_b = entities[a_i], entities[b_i]
        shared = set(ent_a.get("chunk_ids", [])) & set(ent_b.get("chunk_ids", []))
        texts = [cid_text.get(cid, "") for cid in shared if cid_text.get(cid)]
        if not texts:
            continue
        typed = _type_single_relation(ent_a["text"], ent_b["text"], texts)
        if typed:
            out[(a_i, b_i)] = typed
    return out


def _cooccurrence_edges(entities: list):
    """Archi di co-occorrenza tra entità: due entità (per indice nella lista)
    sono collegate se condividono almeno un chunk; il peso è il numero di
    chunk condivisi. Funzione PURA (niente FAISS/spaCy): testabile in isolamento.
    Ritorna lista di {source, target, weight} con source<target."""
    chunk_to_ents = {}
    for ei, ent in enumerate(entities):
        for cid in ent.get("chunk_ids", []):
            chunk_to_ents.setdefault(cid, set()).add(ei)
    edge_w = {}
    for cid, ent_set in chunk_to_ents.items():
        ents = sorted(ent_set)
        for a_i in range(len(ents)):
            for b_i in range(a_i + 1, len(ents)):
                key = (ents[a_i], ents[b_i])
                edge_w[key] = edge_w.get(key, 0) + 1
    edges = [{"source": a, "target": b, "weight": w}
             for (a, b), w in edge_w.items()]
    edges.sort(key=lambda e: e["weight"], reverse=True)
    return edges


def _build_entity_graph(azienda_filter: Optional[str] = None, doc_ids: Optional[list] = None,
                        include_themes: bool = False, min_cluster_size: int = 2,
                        pca_dims: int = 40, typed_relations: bool = False,
                        max_typed_edges: int = 30, natural_labels: bool = False,
                        user: Optional[dict] = None, folder_id: Optional[str] = None):
    source = _visible_chunks(user) if user is not None else _chunk_store
    doc_filter = set(doc_ids) if doc_ids else None
    _pl = sharing.get_placements(user["user_id"]) if user is not None else {}
    sel = [c for c in source
           if ((not azienda_filter) or c.get("azienda") == azienda_filter)
           and (doc_filter is None or c.get("doc_id") in doc_filter)
           and _chunk_in_folder_scope(c, folder_id, user=user, placements=_pl)]
    if len(sel) < 2:
        raise HTTPException(400, "Servono almeno 2 chunk per il grafo.")

    _global_pos = {c.get("chunk_id", ""): i for i, c in enumerate(_chunk_store)}
    cid_to_pos = {c.get("chunk_id", ""): _global_pos.get(c.get("chunk_id", ""))
                  for c in sel}

    visible_cids = {c.get("chunk_id", "") for c in sel}
    doc_ids = []
    seen_docs = set()
    for c in sel:
        d = c.get("doc_id")
        if d and d not in seen_docs:
            seen_docs.add(d)
            doc_ids.append(d)

    agg = {}
    for d in doc_ids:
        for e in _entities_for_doc(d):
            visible_chunk_ids = [cid for cid in e.get("chunk_ids", []) if cid in visible_cids]
            if not visible_chunk_ids:
                continue
            key = (e["text"].lower(), e["type"])
            if key not in agg:
                agg[key] = {"text": e["text"], "type": e["type"],
                            "count": 0, "chunk_ids": []}
            agg[key]["count"] += len(visible_chunk_ids)
            for cid in visible_chunk_ids:
                if cid not in agg[key]["chunk_ids"]:
                    agg[key]["chunk_ids"].append(cid)
    grezze = list(agg.values())
    entities = _resolve_entities(grezze)
    if len(entities) < 2:
        return {"nodes": [], "edges": [], "n_entities": len(entities)}

    edges_all = _cooccurrence_edges(entities)

    index = get_faiss_index()
    try:
        index.make_direct_map()
    except Exception:
        pass
    centroids = []
    valid_ent = []
    for ei, ent in enumerate(entities):
        vecs = []
        for cid in ent.get("chunk_ids", []):
            pos = cid_to_pos.get(cid)
            if pos is None:
                continue
            try:
                vecs.append(index.reconstruct(pos))
            except Exception:
                continue
        if not vecs:
            continue
        v = np.mean(np.array(vecs, dtype=np.float64), axis=0)
        v = v / (np.linalg.norm(v) + 1e-9)
        centroids.append(v)
        valid_ent.append(ei)

    if len(valid_ent) < 2:
        return {"nodes": [], "edges": [], "n_entities": len(entities)}

    X = np.array(centroids, dtype=np.float64)
    coords3 = _cluster_project_3d(X)

    node_theme = {}
    theme_label_map = {}
    theme_name_map = {}
    themes_catalog = []
    if include_themes and len(valid_ent) >= 2:
        try:
            from hdbscan import HDBSCAN
            Xc_red = _cluster_reduce_dims(X, n_components=min(pca_dims, X.shape[0] - 1))
            comm = HDBSCAN(min_cluster_size=max(2, min_cluster_size),
                           metric="euclidean").fit_predict(Xc_red)
            cid_text = {c.get("chunk_id"): c.get("text", "") for c in _chunk_store}
            per_comm = {}
            for k_idx, ei in enumerate(valid_ent):
                lab = int(comm[k_idx])
                node_theme[ei] = lab
                if lab != -1:
                    per_comm.setdefault(lab, []).append(ei)
            want_theme_labels = bool(natural_labels) and _decide_backend() != "offline"
            theme_name_map = {}
            for lab, eis in per_comm.items():
                texts = []
                for ei in eis:
                    for cid in entities[ei].get("chunk_ids", []):
                        t = cid_text.get(cid)
                        if t:
                            texts.append(t)
                tema = _cluster_keywords(texts)
                theme_label_map[lab] = tema
                entry = {"theme_id": lab, "tema": tema, "members": len(eis)}
                if want_theme_labels:
                    lbl = _cluster_llm_label(tema, texts)
                    if lbl:
                        entry["label"] = lbl
                        theme_name_map[lab] = lbl
                themes_catalog.append(entry)
            themes_catalog.sort(key=lambda x: x["members"], reverse=True)
        except Exception:
            logger.warning("Clustering tematico delle entità non disponibile")
            node_theme, theme_label_map, themes_catalog = {}, {}, []
            theme_name_map = {}

    pos_of = {ei: k for k, ei in enumerate(valid_ent)}
    cid_doc = {}
    cid_ts = {}
    for c in _chunk_store:
        cid = c.get("chunk_id")
        if cid:
            cid_doc[cid] = (c.get("doc_id"), c.get("titolo", ""))
            ts = c.get("timestamp")
            if ts:
                cid_ts[cid] = ts
    nodes = []
    for k, ei in enumerate(valid_ent):
        ent = entities[ei]
        seen_docs = []
        docs = []
        dates = []
        for cid in ent.get("chunk_ids", []):
            info = cid_doc.get(cid)
            if info and info[0] and info[0] not in seen_docs:
                seen_docs.append(info[0])
                docs.append({"doc_id": info[0], "titolo": info[1]})
            ts = cid_ts.get(cid)
            if ts:
                dates.append(ts)
        node = {
            "id": ei,
            "label": ent["text"],
            "type": ent["type"],
            "count": ent["count"],
            "variants": ent.get("variants", []),
            "chunk_ids": ent.get("chunk_ids", []),
            "documents": docs,
            "dates": dates,
            "x": float(coords3[k, 0]),
            "y": float(coords3[k, 1]),
            "z": float(coords3[k, 2]),
        }
        if include_themes:
            tid = node_theme.get(ei, -1)
            node["theme"] = tid
            node["theme_label"] = theme_label_map.get(tid, "")
            node["theme_name"] = theme_name_map.get(tid, "")
        nodes.append(node)
    edges = []
    for e in edges_all:
        a_i, b_i, w = e["source"], e["target"], e["weight"]
        if a_i in pos_of and b_i in pos_of:
            edges.append({"source": a_i, "target": b_i, "weight": w})
    edges.sort(key=lambda e: e["weight"], reverse=True)

    typed_active = bool(typed_relations) and _decide_backend() != "offline"
    n_typed = 0
    if typed_active:
        cid_text_full = {c.get("chunk_id"): c.get("text", "") for c in _chunk_store}
        typed_map = _typed_relations_for_edges(entities, edges, cid_text_full, max_typed_edges)
        for e in edges:
            info = typed_map.get((e["source"], e["target"]))
            if info:
                e["relation"] = info["relation"]
                e["direction"] = info["direction"]
                e["support"] = info["support"]
                e["confidence"] = info["confidence"]
                n_typed += 1

    return {
        "nodes": nodes,
        "edges": edges,
        "n_entities": len(nodes),
        "n_edges": len(edges),
        "themes": themes_catalog,
        "typed_relations": typed_active,
        "n_typed": n_typed,
    }


class EntityGraphRequest(BaseModel):
    azienda_filter: Optional[str] = None
    doc_ids: Optional[List[str]] = None
    folder_id: Optional[str] = None
    include_themes: bool = False
    min_cluster_size: int = 2
    pca_dims: int = 40
    typed_relations: bool = False
    max_typed_edges: int = 30
    natural_labels: bool = False


@app.post("/api/entities/graph")
def entity_graph(req: EntityGraphRequest, user: dict = Depends(current_user)):
    if _get_spacy() is None:
        raise HTTPException(503, "Il grafo di entità richiede spaCy. Installa "
                                 "con: pip install spacy && python -m spacy "
                                 "download it_core_news_lg")
    try:
        return _build_entity_graph(azienda_filter=req.azienda_filter,
                                   doc_ids=req.doc_ids, include_themes=req.include_themes,
                                   min_cluster_size=req.min_cluster_size, pca_dims=req.pca_dims,
                                   typed_relations=req.typed_relations,
                                   max_typed_edges=req.max_typed_edges,
                                   natural_labels=req.natural_labels, user=user,
                                   folder_id=req.folder_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Costruzione grafo entità fallita")
        raise HTTPException(500, f"Grafo entità fallito: {e}")



class ClusterRequest(BaseModel):
    azienda_filter: Optional[str] = None
    min_cluster_size: int = 2
    pca_dims: int = 40
    doc_ids: Optional[List[str]] = None
    folder_id: Optional[str] = None
    natural_labels: bool = False

_CLUSTER_STOPWORDS = {
    "il","lo","la","i","gli","le","un","uno","una","di","a","da","in","con",
    "su","per","tra","fra","e","ed","o","che","chi","cui","non","ha","hanno",
    "del","dei","delle","della","dello","degli","al","ai","alle","alla","allo",
    "agli","nel","nei","nelle","nella","sul","sui","sulla","sono","stato",
    "stata","stati","state","essere","viene","vengono","anche","come","più",
    "molto","questo","questa","questi","queste","loro","suo","sua","tutti",
    "tutte","tutto","ogni","è","si","se","ma","già","sia","rispetto","corso",
    "particolare","attenzione","stata","verso","presso","oltre","mediante",
}

def _cluster_reduce_dims(X, n_components=40):
    n_components = min(n_components, X.shape[0] - 1, X.shape[1])
    if n_components < 2:
        return X
    use_umap = os.environ.get("OBS_USE_UMAP", "auto").lower()
    if use_umap in ("auto", "1", "true", "yes") and X.shape[0] >= 5:
        try:
            import umap
            reducer = umap.UMAP(n_components=min(n_components, X.shape[0] - 2),
                                random_state=42, n_neighbors=min(15, X.shape[0] - 1),
                                metric="cosine")
            return reducer.fit_transform(X)
        except Exception:
            if use_umap in ("1", "true", "yes"):
                logger.warning("UMAP richiesto ma non disponibile, uso PCA")
    from sklearn.decomposition import PCA
    return PCA(n_components=n_components, random_state=42).fit_transform(X)

def _cluster_project_2d(X):
    """Proiezione 2D per la mappa (PCA a 2 componenti, deterministica)."""
    from sklearn.decomposition import PCA
    if X.shape[0] < 3 or X.shape[1] < 2:
        coords = np.zeros((X.shape[0], 2))
        if X.shape[1] >= 1:
            coords[:, 0] = X[:, 0]
        return coords
    return PCA(n_components=2, random_state=42).fit_transform(X)

def _cluster_project_3d(X):
    """Proiezione 3D per la mappa (PCA a 3 componenti, deterministica).
    Usata sia dai cluster (vista 3D) sia dal grafo di entità."""
    from sklearn.decomposition import PCA
    if X.shape[0] < 4 or X.shape[1] < 3:
        coords = np.zeros((X.shape[0], 3))
        for k in range(min(3, X.shape[1])):
            coords[:, k] = X[:, k]
        return coords
    return PCA(n_components=3, random_state=42).fit_transform(X)

def _cluster_keywords(texts, top_n=4):
    """Etichetta tematica leggibile dalle parole più frequenti del cluster."""
    import re
    from collections import Counter
    words = []
    for t in texts:
        for w in re.findall(r"[a-zà-ÿ]{4,}", t.lower()):
            if w not in _CLUSTER_STOPWORDS:
                words.append(w)
    if not words:
        return "-"
    return ", ".join(w for w, _ in Counter(words).most_common(top_n))


def _sanitize_label(raw: str) -> Optional[str]:
    if not raw:
        return None
    label = " ".join(str(raw).strip().split())
    if label and label[0] in "\"'" and label[-1] in "\"'" and len(label) >= 2:
        label = label[1:-1].strip()
    label = label.strip().strip(".")
    if len(label) < 2:
        return None
    words = label.split()
    if len(words) > 8:
        label = " ".join(words[:8])
    return label


def _cluster_llm_label(keywords: str, texts: list) -> Optional[str]:
    if _decide_backend() == "offline":
        return None
    samples = [" ".join((t or "").split())[:300] for t in texts[:4] if t]
    joined = "\n".join("- " + s for s in samples)
    system_prompt = (
        "Sei un analista che assegna titoli tematici brevi e leggibili. "
        "Ricevi le parole chiave di un tema e alcuni passaggi rappresentativi. "
        "Rispondi con un solo titolo sintetico, da due a sei parole, senza virgolette, "
        "senza punteggiatura finale, nella lingua dei passaggi. "
        "Il titolo deve descrivere il tema, non elencare le parole chiave."
    )
    user_message = (
        "Parole chiave: " + (keywords or "") + "\n\n"
        "Passaggi rappresentativi:\n" + (joined if joined else "(nessuno)") + "\n\n"
        "Titolo del tema:"
    )
    try:
        raw = _llm_complete(system_prompt, user_message, max_tokens=40)
    except Exception:
        return None
    return _sanitize_label(raw)


def _cluster_hierarchy(unique_labels, labels, X_red, meta, persistence, with_labels=False):
    if not unique_labels:
        return None

    per_texts, per_docs, per_az, per_size, per_examples, per_centroid = {}, {}, {}, {}, {}, {}
    for lab in unique_labels:
        members = [j for j in range(len(labels)) if int(labels[j]) == lab]
        texts = [meta[j]["text"] for j in members]
        per_texts[lab] = texts
        per_docs[lab] = set(meta[j].get("doc_id", "?") for j in members)
        per_az[lab] = set(meta[j].get("azienda", "?") for j in members)
        per_size[lab] = len(members)
        per_examples[lab] = [t[:140] for t in texts[:3]]
        per_centroid[lab] = np.mean(X_red[members], axis=0)

    counter = {"n": 0}

    def _nid():
        counter["n"] += 1
        return "cn" + str(counter["n"])

    def _agg(label_set):
        texts, docs, az, size = [], set(), set(), 0
        for lab in label_set:
            texts += per_texts[lab]
            docs |= per_docs[lab]
            az |= per_az[lab]
            size += per_size[lab]
        return _cluster_keywords(texts), size, len(docs), sorted(az), texts

    def _leaf(lab):
        tema, size, ndoc, az, texts = _agg({lab})
        node = {
            "node_id": _nid(),
            "type": "theme",
            "cluster_id": int(lab),
            "tema": tema,
            "size": size,
            "n_documenti": ndoc,
            "aziende": az,
            "esempi": per_examples[lab],
            "children": [],
        }
        if with_labels:
            lbl = _cluster_llm_label(tema, texts)
            if lbl:
                node["label"] = lbl
        if persistence is not None and 0 <= lab < len(persistence):
            node["stability"] = round(float(persistence[lab]), 3)
        return node, {lab}

    if len(unique_labels) == 1:
        node, _ = _leaf(unique_labels[0])
        return node

    from scipy.cluster.hierarchy import linkage, to_tree
    cent = np.array([per_centroid[lab] for lab in unique_labels], dtype=float)
    Z = linkage(cent, method="ward")
    root = to_tree(Z)

    def _build(tnode):
        if tnode.is_leaf():
            return _leaf(unique_labels[tnode.id])
        left, ll = _build(tnode.left)
        right, rl = _build(tnode.right)
        here = ll | rl
        tema, size, ndoc, az, texts = _agg(here)
        node = {
            "node_id": _nid(),
            "type": "group",
            "tema": tema,
            "size": size,
            "n_documenti": ndoc,
            "aziende": az,
            "children": [left, right],
        }
        if with_labels:
            lbl = _cluster_llm_label(tema, texts)
            if lbl:
                node["label"] = lbl
        return node, here

    tree, _ = _build(root)
    return tree

class ReportRequest(BaseModel):
    query: str
    azienda_filter: Optional[str] = None
    folder_id: Optional[str] = None
    lang: Optional[str] = "en"


@app.post("/api/report")
def make_report(req: ReportRequest, user: dict = Depends(current_user)):
    """Genera un report strutturato ancorato alle fonti, con verifica citazioni."""
    if not (req.query or "").strip():
        raise HTTPException(400, "Scrivi una richiesta per il report.")
    try:
        return generate_report(req.query, azienda_filter=req.azienda_filter,
                               folder_id=req.folder_id, user=user, lang=_norm_lang(req.lang))
    except RuntimeError:
        raise HTTPException(503, "Il report richiede un LLM attivo (cloud o locale). "
                                 "Il backend è in modalità offline.")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Report generation failed")
        raise HTTPException(500, f"Generazione report fallita: {e}")


class ReportExportRequest(BaseModel):
    title: str
    raw: str
    sources: List[dict] = []
    stats: Optional[dict] = None
    format: Optional[str] = "md"


class ReportReverifyRequest(BaseModel):
    raw: str
    sources: List[dict] = []


def _latex_escape(s: str) -> str:
    s = s or ""
    repl = {
        "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$",
        "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}",
        "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
    }
    out = []
    for ch in s:
        out.append(repl.get(ch, ch))
    return "".join(out)


def _report_to_markdown(req: "ReportExportRequest") -> str:
    lines = [f"# {req.title}", ""]
    lines.append(req.raw.strip())
    lines.append("")
    lines.append("---")
    lines.append("## Fonti")
    for s in req.sources:
        lines.append(f"- **[{s.get('n')}]** {s.get('azienda','')} - {s.get('titolo','')}")
    if req.stats:
        lines.append("")
        lines.append(f"_Citazioni verificate: {req.stats.get('verified',0)} | "
                     f"deboli: {req.stats.get('weak',0)} | "
                     f"generato da OBS._")
    return "\n".join(lines)


def _report_to_latex(req: "ReportExportRequest") -> str:
    import re
    body_lines = []
    for line in req.raw.strip().split("\n"):
        stripped = line.strip()
        if not stripped:
            body_lines.append("")
            continue
        hm = re.match(r'^(#{1,3})\s+(.*)$', stripped)
        if hm:
            level = len(hm.group(1))
            title = _latex_escape(hm.group(2))
            cmd = "section" if level <= 2 else "subsection"
            body_lines.append("\\" + cmd + "{" + title + "}")
        else:
            esc = _latex_escape(stripped)
            esc = re.sub(r'\[(\d+)\]', r'\\citemark{\1}', esc)
            body_lines.append(esc + "\n")
    body = "\n".join(body_lines)

    src_items = []
    for s in req.sources:
        label = _latex_escape(f"[{s.get('n')}] {s.get('azienda','')} - {s.get('titolo','')}")
        src_items.append("  \\item " + label)
    sources_block = "\n".join(src_items) if src_items else "  \\item (nessuna fonte)"

    stats_line = ""
    if req.stats:
        stats_line = (f"\\vspace{{1em}}\\noindent\\textit{{Citazioni verificate: "
                      f"{req.stats.get('verified',0)}, deboli: {req.stats.get('weak',0)}, "
                      f"generato da OBS.}}")

    template = (
        "\\documentclass[11pt,a4paper]{article}\n"
        "\\usepackage[utf8]{inputenc}\n"
        "\\usepackage[T1]{fontenc}\n"
        "\\usepackage[margin=2.5cm]{geometry}\n"
        "\\usepackage{parskip}\n"
        "\\usepackage{enumitem}\n"
        "\\usepackage{hyperref}\n"
        "\\newcommand{\\citemark}[1]{\\textsuperscript{[#1]}}\n"
        "\\title{" + _latex_escape(req.title) + "}\n"
        "\\author{OBS-LAB}\n"
        "\\date{\\today}\n"
        "\\begin{document}\n"
        "\\maketitle\n"
        + body + "\n"
        "\\vspace{2em}\n"
        "\\hrule\n"
        "\\section*{Fonti}\n"
        "\\begin{itemize}[leftmargin=*]\n"
        + sources_block + "\n"
        "\\end{itemize}\n"
        + stats_line + "\n"
        "\\end{document}\n"
    )
    return template


def _report_to_pdf_bytes(req: "ReportExportRequest") -> bytes:
    import re
    from io import BytesIO
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=2.2 * cm, rightMargin=2.2 * cm,
                            topMargin=2.2 * cm, bottomMargin=2.2 * cm,
                            title=req.title, author="OBS-LAB")
    styles = getSampleStyleSheet()
    h_title = ParagraphStyle("obsTitle", parent=styles["Title"], fontSize=18,
                             textColor=colors.HexColor("#3d5a80"))
    h_sec = ParagraphStyle("obsSec", parent=styles["Heading2"], fontSize=13,
                           textColor=colors.HexColor("#2a00aa"), spaceBefore=10)
    body_st = ParagraphStyle("obsBody", parent=styles["BodyText"], fontSize=10.5,
                             leading=15)
    src_st = ParagraphStyle("obsSrc", parent=styles["BodyText"], fontSize=9,
                            leading=13, textColor=colors.HexColor("#333333"))

    def _xml(s):
        return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    flow = [Paragraph(_xml(req.title), h_title), Spacer(1, 6)]
    for line in req.raw.strip().split("\n"):
        stripped = line.strip()
        if not stripped:
            flow.append(Spacer(1, 4))
            continue
        hm = re.match(r'^#{1,3}\s+(.*)$', stripped)
        if hm:
            flow.append(Paragraph(_xml(hm.group(1)), h_sec))
        else:
            txt = _xml(stripped)
            txt = re.sub(r'\[(\d+)\]', r'<super>[\1]</super>', txt)
            flow.append(Paragraph(txt, body_st))
    flow.append(Spacer(1, 10))
    flow.append(HRFlowable(width="100%", color=colors.HexColor("#8fa3b5")))
    flow.append(Paragraph("Fonti", h_sec))
    for s in req.sources:
        label = f"[{s.get('n')}] {_xml(str(s.get('azienda','')))} - {_xml(str(s.get('titolo','')))}"
        flow.append(Paragraph(label, src_st))
    if req.stats:
        flow.append(Spacer(1, 8))
        flow.append(Paragraph(
            f"Citazioni verificate: {req.stats.get('verified',0)}, "
            f"deboli: {req.stats.get('weak',0)}, generato da OBS.", src_st))
    doc.build(flow)
    return buf.getvalue()


@app.post("/api/report/export")
def export_report(req: ReportExportRequest, user: dict = Depends(current_user)):
    from fastapi.responses import PlainTextResponse, Response as _Resp
    fmt = (req.format or "md").lower()
    if fmt in ("md", "markdown"):
        return PlainTextResponse(_report_to_markdown(req), headers={
            "Content-Disposition": 'attachment; filename="OBS_report.md"'})
    if fmt in ("tex", "latex"):
        return PlainTextResponse(_report_to_latex(req), headers={
            "Content-Disposition": 'attachment; filename="OBS_report.tex"'})
    if fmt == "pdf":
        try:
            pdf_bytes = _report_to_pdf_bytes(req)
        except Exception as e:
            logger.exception("Report PDF export failed")
            raise HTTPException(500, f"Export PDF fallito: {e}")
        return _Resp(content=pdf_bytes, media_type="application/pdf", headers={
            "Content-Disposition": 'attachment; filename="OBS_report.pdf"'})
    raise HTTPException(400, "Formato non valido. Usa md, tex o pdf.")


@app.post("/api/report/reverify")
def reverify_report(req: ReportReverifyRequest, user: dict = Depends(current_user)):
    model = get_embed_model()
    src_texts = [s.get("text", "") for s in req.sources]
    if not src_texts:
        raise HTTPException(400, "Servono le fonti per riverificare le citazioni.")
    src_vecs = model.encode(src_texts, show_progress_bar=False).astype("float32")
    src_vecs /= (np.linalg.norm(src_vecs, axis=1, keepdims=True) + 1e-9)
    sources = []
    for i, s in enumerate(req.sources):
        sources.append({"n": s.get("n", i + 1), "text": s.get("text", ""), "_vec": src_vecs[i]})
    claims = _report_verify_citations(req.raw, sources)
    verified = sum(1 for c in claims if c["status"] == "verified")
    weak = sum(1 for c in claims if c["status"] == "weak")
    return {"claims": claims, "stats": {"verified": verified, "weak": weak,
                                        "total_cited": verified + weak}}


@app.post("/api/cluster")
def cluster(req: ClusterRequest, user: dict = Depends(current_user)):
    from hdbscan import HDBSCAN

    doc_filter = set(req.doc_ids) if req.doc_ids else None
    visible_cids = {c.get("chunk_id") for c in _visible_chunks(user)}
    _pl = sharing.get_placements(user["user_id"])
    idxs = [i for i, c in enumerate(_chunk_store)
            if c.get("chunk_id") in visible_cids
            and ((not req.azienda_filter) or c.get("azienda") == req.azienda_filter)
            and (doc_filter is None or c.get("doc_id") in doc_filter)
            and _chunk_in_folder_scope(c, req.folder_id, user=user, placements=_pl)]

    if len(idxs) < 2:
        raise HTTPException(400, "Servono almeno 2 chunk per il clustering.")

    index = get_faiss_index()
    try:
        index.make_direct_map()
    except Exception:
        pass
    vecs = []
    for i in idxs:
        try:
            vecs.append(index.reconstruct(i))
        except Exception:
            vecs.append(None)
    valid = [(i, v) for i, v in zip(idxs, vecs) if v is not None]
    if len(valid) < 2:
        raise HTTPException(400, "Impossibile recuperare i vettori dei chunk.")

    sel_idxs = [i for i, _ in valid]
    X = np.array([v for _, v in valid], dtype=np.float64)
    meta = [_chunk_store[i] for i in sel_idxs]
    n = len(meta)

    X = X / (np.linalg.norm(X, axis=1, keepdims=True) + 1e-9)

    X_red = _cluster_reduce_dims(X, n_components=req.pca_dims)
    clusterer = HDBSCAN(min_cluster_size=max(2, req.min_cluster_size),
                        metric="euclidean")
    labels = clusterer.fit_predict(X_red)

    coords = _cluster_project_2d(X_red)
    coords3 = _cluster_project_3d(X_red)

    persistence = getattr(clusterer, "cluster_persistence_", None)
    unique_labels = sorted(set(int(l) for l in labels) - {-1})
    want_labels = bool(req.natural_labels) and _decide_backend() != "offline"
    clusters = []
    for lab in unique_labels:
        members = [j for j in range(n) if labels[j] == lab]
        texts = [meta[j]["text"] for j in members]
        docs = sorted(set(meta[j].get("doc_id", "?") for j in members))
        aziende = sorted(set(meta[j].get("azienda", "?") for j in members))
        kw = _cluster_keywords(texts)
        entry = {
            "cluster_id": int(lab),
            "tema": kw,
            "size": len(members),
            "n_documenti": len(docs),
            "n_aziende": len(aziende),
            "aziende": aziende,
            "esempi": [t[:140] for t in texts[:3]],
        }
        if want_labels:
            lbl = _cluster_llm_label(kw, texts)
            if lbl:
                entry["label"] = lbl
        if persistence is not None and 0 <= lab < len(persistence):
            entry["stability"] = round(float(persistence[lab]), 3)
        clusters.append(entry)
    clusters.sort(key=lambda c: c["size"], reverse=True)

    tree = _cluster_hierarchy(unique_labels, labels, X_red, meta, persistence,
                              with_labels=want_labels)

    points = [{
        "x": float(coords[j, 0]),
        "y": float(coords[j, 1]),
        "z": float(coords3[j, 2]),
        "cluster": int(labels[j]),
        "azienda": meta[j].get("azienda", "?"),
        "titolo": meta[j].get("titolo", "?"),
        "snippet": meta[j]["text"][:80],
    } for j in range(n)]

    return {
        "n_clusters": len(unique_labels),
        "n_noise": int(np.sum(labels == -1)),
        "n_chunks": n,
        "clusters": clusters,
        "tree": tree,
        "points": points,
    }


IMAGES_DIR     = DATA_DIR / "images"
IMAGES_DIR.mkdir(parents=True, exist_ok=True)
IMG_VIS_INDEX_FILE = VS_DIR / "img_visual.index"
IMG_TXT_INDEX_FILE = VS_DIR / "img_textual.index"
IMG_STORE_FILE     = VS_DIR / "images.json"

_image_model     = None
_img_vis_index   = None
_img_txt_index   = None
_image_store: List[dict] = []

_IMAGE_VOCAB = [
    "documento", "fattura", "grafico", "diagramma", "tabella", "screenshot",
    "prodotto", "imballaggio", "etichetta", "magazzino", "scaffale", "veicolo",
    "macchinario", "edificio", "ufficio", "cantiere", "mappa", "logo",
    "persona al lavoro", "foto di gruppo", "paesaggio", "interno", "esterno",
    "testo scritto", "presentazione", "fotografia di oggetto",
]


def get_image_model():
    """Carica CLIP una sola volta (lazy). Stessa libreria del testo."""
    global _image_model
    if _image_model is None:
        from sentence_transformers import SentenceTransformer
        clip_local = None
        try:
            clip_local = model_setup.clip_path()
        except Exception:
            clip_local = None
        if clip_local:
            logger.info("Loading CLIP image model from %s", clip_local)
            _image_model = SentenceTransformer(clip_local)
        else:
            logger.info("Loading CLIP image model: %s", OBS_CONFIG["image_model"])
            _image_model = SentenceTransformer(OBS_CONFIG["image_model"])
    return _image_model


def get_img_vis_index():
    global _img_vis_index
    if _img_vis_index is None:
        import faiss
        _img_vis_index = faiss.IndexHNSWFlat(OBS_CONFIG["image_dim"], 32)
    return _img_vis_index


def get_img_txt_index():
    global _img_txt_index
    if _img_txt_index is None:
        import faiss
        _img_txt_index = faiss.IndexHNSWFlat(OBS_CONFIG["embedding_dim"], 32)
    return _img_txt_index


def _embed_image_files(paths):
    """Vettori CLIP per una lista di immagini. Ritorna array float32 normalizzato."""
    from PIL import Image
    model = get_image_model()
    imgs = [Image.open(p).convert("RGB") for p in paths]
    vecs = model.encode(imgs, show_progress_bar=False).astype("float32")
    vecs = vecs / (np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-9)
    return vecs


def _embed_text_query_clip(text):
    """Vettore CLIP di una frase (per ricerca testo->immagine nello spazio visivo)."""
    model = get_image_model()
    v = model.encode([text], show_progress_bar=False).astype("float32")
    v = v / (np.linalg.norm(v, axis=1, keepdims=True) + 1e-9)
    return v


def run_ocr(path):
    """OCR opzionale. Ritorna testo estratto (o '' se disattivato/non disponibile/poco testo)."""
    if not OBS_CONFIG.get("ocr_enabled"):
        return ""
    try:
        import pytesseract
        from PIL import Image
        import shutil
        tess = shutil.which("tesseract")
        if not tess:
            for c in ["/usr/local/bin/tesseract", "/opt/homebrew/bin/tesseract"]:
                if os.path.exists(c):
                    tess = c
                    break
        if tess:
            pytesseract.pytesseract.tesseract_cmd = tess
        txt = pytesseract.image_to_string(Image.open(path), lang="ita+eng")
        txt = " ".join(txt.split())
        return txt if len(txt) >= OBS_CONFIG["ocr_min_chars"] else ""
    except Exception as e:
        logger.warning("OCR not available or failed: %s", e)
        return ""


def _unique_image_id(seed_bytes: bytes = b"") -> str:
    """Id immagine univoco a 10 esadecimali. Combina il contenuto con entropia
    casuale e verifica l'assenza di collisioni con lo store, cosi' due file
    identici (una copia e il suo originale) ricevono comunque id distinti."""
    existing = {im.get("img_id") for im in _image_store}
    while True:
        raw = seed_bytes + uuid.uuid4().bytes
        candidate = hashlib.md5(raw).hexdigest()[:10]
        if candidate not in existing:
            return candidate


def ingest_image(filepath: Path, filename: str, azienda: str, titolo: str, folder_id: Optional[str] = None, owner_id: Optional[int] = None) -> dict:
    """Indicizza un'immagine: vettore visivo (sempre) + vettore testuale (se OCR trova testo)."""
    global _image_store
    img_id = _unique_image_id(filepath.read_bytes())

    vis_vec = _embed_image_files([filepath])[0]
    vis_idx = len(_image_store)
    get_img_vis_index().add(vis_vec.reshape(1, -1))

    ocr_text = run_ocr(filepath)
    txt_idx = -1
    if ocr_text:
        tmodel = get_embed_model()
        tvec = tmodel.encode([ocr_text], show_progress_bar=False).astype("float32")
        tvec = tvec / (np.linalg.norm(tvec, axis=1, keepdims=True) + 1e-9)
        txt_index = get_img_txt_index()
        txt_idx = txt_index.ntotal
        txt_index.add(tvec)

    _image_store.append({
        "img_id":    img_id,
        "filename":  filename,
        "azienda":   azienda,
        "titolo":    titolo or filename,
        "path":      str(filepath),
        "vis_idx":   vis_idx,
        "txt_idx":   txt_idx,
        "folder_id": folder_id,
        "owner_id":  owner_id,
        "ocr_text":  ocr_text[:500],
        "timestamp": datetime.utcnow().isoformat(),
    })
    _persist_images()
    return {"img_id": img_id, "has_text": bool(ocr_text)}


def _persist_images():
    import faiss
    IMG_STORE_FILE.write_text(json.dumps(_image_store, ensure_ascii=False, indent=2))
    if _img_vis_index is not None:
        faiss.write_index(_img_vis_index, str(IMG_VIS_INDEX_FILE))
    if _img_txt_index is not None:
        faiss.write_index(_img_txt_index, str(IMG_TXT_INDEX_FILE))


def _load_persisted_images():
    global _image_store, _img_vis_index, _img_txt_index
    import faiss
    if IMG_STORE_FILE.exists():
        _image_store = json.loads(IMG_STORE_FILE.read_text())
        logger.info("Loaded %d images from disk.", len(_image_store))
    if IMG_VIS_INDEX_FILE.exists():
        _img_vis_index = faiss.read_index(str(IMG_VIS_INDEX_FILE))
    if IMG_TXT_INDEX_FILE.exists():
        _img_txt_index = faiss.read_index(str(IMG_TXT_INDEX_FILE))


def _label_visual_cluster(member_vecs):
    """Etichetta un cluster visivo con CLIP zero-shot: confronta il centroide
    del cluster col vocabolario di concetti e prende i più vicini.
    Non identifica persone: solo categorie di contenuto."""
    try:
        model = get_image_model()
        centroid = np.mean(member_vecs, axis=0, keepdims=True)
        centroid = centroid / (np.linalg.norm(centroid) + 1e-9)
        vocab_vecs = model.encode(_IMAGE_VOCAB, show_progress_bar=False).astype("float32")
        vocab_vecs = vocab_vecs / (np.linalg.norm(vocab_vecs, axis=1, keepdims=True) + 1e-9)
        sims = (vocab_vecs @ centroid.T).ravel()
        top = np.argsort(-sims)[:3]
        return ", ".join(_IMAGE_VOCAB[i] for i in top)
    except Exception:
        return "-"


class ImageClusterRequest(BaseModel):
    lens: str = "visual"
    azienda_filter: Optional[str] = None
    min_cluster_size: int = 2
    pca_dims: int = 40
    folder_id: Optional[str] = None


def _reconstruct_all(index, n):
    try:
        index.make_direct_map()
    except Exception:
        pass
    out = []
    for i in range(n):
        try:
            out.append(index.reconstruct(i))
        except Exception:
            out.append(None)
    return out


@app.post("/api/images/cluster")
def cluster_images(req: ImageClusterRequest, user: dict = Depends(current_user)):
    """Clustering delle immagini su una delle due lenti. Riusa il motore esistente."""
    from hdbscan import HDBSCAN

    images = _visible_images(user)
    if not images:
        raise HTTPException(400, "Nessuna immagine indicizzata.")

    visual = (req.lens != "textual")

    sel = []
    for img in images:
        if req.azienda_filter and img.get("azienda") != req.azienda_filter:
            continue
        if not _chunk_in_folder_scope(img, req.folder_id):
            continue
        if visual:
            sel.append((img, img["vis_idx"]))
        elif img.get("txt_idx", -1) >= 0:
            sel.append((img, img["txt_idx"]))
    if len(sel) < 2:
        raise HTTPException(400, "Servono almeno 2 immagini (con testo, per la lente testuale).")

    index = get_img_vis_index() if visual else get_img_txt_index()
    recon = _reconstruct_all(index, index.ntotal)
    valid = [(img, recon[idx]) for img, idx in sel if idx < len(recon) and recon[idx] is not None]
    if len(valid) < 2:
        raise HTTPException(400, "Impossibile recuperare i vettori delle immagini.")

    metas = [m for m, _ in valid]
    X = np.array([v for _, v in valid], dtype=np.float64)
    X = X / (np.linalg.norm(X, axis=1, keepdims=True) + 1e-9)
    n = len(metas)

    X_red = _cluster_reduce_dims(X, n_components=req.pca_dims)
    labels = HDBSCAN(min_cluster_size=max(2, req.min_cluster_size),
                     metric="euclidean").fit_predict(X_red)
    coords = _cluster_project_2d(X_red)
    coords3 = _cluster_project_3d(X_red)

    unique_labels = sorted(set(int(l) for l in labels) - {-1})
    clusters = []
    for lab in unique_labels:
        members = [j for j in range(n) if labels[j] == lab]
        aziende = sorted(set(metas[j].get("azienda", "?") for j in members))
        if visual:
            tema = _label_visual_cluster(np.array([X[j] for j in members]))
        else:
            tema = _cluster_keywords([metas[j].get("ocr_text", "") for j in members])
        clusters.append({
            "cluster_id": int(lab),
            "tema": tema,
            "size": len(members),
            "n_aziende": len(aziende),
            "aziende": aziende,
            "esempi": [metas[j].get("titolo", "?") for j in members[:3]],
        })
    clusters.sort(key=lambda c: c["size"], reverse=True)

    points = [{
        "x": float(coords[j, 0]),
        "y": float(coords[j, 1]),
        "z": float(coords3[j, 2]),
        "cluster": int(labels[j]),
        "azienda": metas[j].get("azienda", "?"),
        "titolo": metas[j].get("titolo", "?"),
        "img_id": metas[j].get("img_id", ""),
    } for j in range(n)]

    return {
        "lens": "visual" if visual else "textual",
        "n_clusters": len(unique_labels),
        "n_noise": int(np.sum(labels == -1)),
        "n_images": n,
        "clusters": clusters,
        "points": points,
    }


class ImageSearchRequest(BaseModel):
    query: str
    top_k: int = 12
    folder_id: Optional[str] = None


@app.post("/api/images/search")
def search_images(req: ImageSearchRequest, user: dict = Depends(current_user)):
    """Ricerca per frase nello spazio visivo CLIP (testo->immagine). Niente persone."""
    if not _image_store:
        raise HTTPException(400, "Nessuna immagine indicizzata.")
    visible_ids = {im["img_id"] for im in _visible_images(user)
                   if _chunk_in_folder_scope(im, req.folder_id)}
    qvec = _embed_text_query_clip(req.query)
    index = get_img_vis_index()
    k = min(max(req.top_k * 3, req.top_k), index.ntotal)
    D, I = index.search(qvec, k)
    results = []
    for rank, idx in enumerate(I[0]):
        img = next((im for im in _image_store if im["vis_idx"] == int(idx)), None)
        if img and img["img_id"] in visible_ids:
            results.append({
                "img_id": img["img_id"], "titolo": img["titolo"],
                "azienda": img["azienda"], "filename": img["filename"],
                "score": float(D[0][rank]),
            })
        if len(results) >= req.top_k:
            break
    return {"query": req.query, "results": results}


@app.post("/api/images/ingest")
async def ingest_image_endpoint(
    file: UploadFile = File(...),
    azienda: str = Form("?"),
    titolo: str = Form(""),
    folder_id: str = Form(""),
    user: dict = Depends(current_user),
):
    suffix = Path(file.filename).suffix or ".img"
    dest = IMAGES_DIR / f"{uuid.uuid4().hex}{suffix}"
    dest.write_bytes(await file.read())
    if not titolo and file.filename:
        titolo = file.filename.rsplit(".", 1)[0].replace("_", " ").replace("-", " ").strip()
    try:
        return ingest_image(dest, file.filename, azienda, titolo,
                            folder_id=folder_id or None, owner_id=user["user_id"])
    except Exception as e:
        logger.exception("Image ingest failed")
        raise HTTPException(500, f"Ingest immagine fallito: {e}")


@app.get("/api/images")
def list_images(user: dict = Depends(current_user)):
    visible = ownership.filter_images(user, _image_store, extra_doc_ids=shared_img_ids_for(user))
    return {
        "count": len(visible),
        "with_text": sum(1 for i in visible if i.get("txt_idx", -1) >= 0),
        "images": [{
            "img_id": i["img_id"], "titolo": i["titolo"],
            "azienda": i["azienda"], "has_text": i.get("txt_idx", -1) >= 0,
            "folder_id": i.get("folder_id"),
        } for i in visible],
    }


class ImageRenameRequest(BaseModel):
    titolo: str


@app.patch("/api/images/{img_id}")
def rename_image(img_id: str, req: ImageRenameRequest, user: dict = Depends(current_user)):
    """Rinomina un'immagine (solo il titolo visualizzato; non tocca vettori né file)."""
    img = next((i for i in _image_store if i["img_id"] == img_id), None)
    if not img:
        raise HTTPException(404, "Immagine non trovata.")
    if user["role"] != auth.ROLE_DEVELOPER and img.get("owner_id") != user["user_id"]:
        raise HTTPException(403, "Solo il proprietario puo' rinominare questa immagine.")
    new_title = (req.titolo or "").strip()
    if not new_title:
        raise HTTPException(400, "Il titolo non può essere vuoto.")
    img["titolo"] = new_title[:200]
    _persist_images()
    return {"success": True, "titolo": img["titolo"]}


@app.get("/api/images/file/{img_id}")
def get_image_file(img_id: str, user: dict = Depends(current_user)):
    img = next((i for i in _image_store if i["img_id"] == img_id), None)
    if not img:
        raise HTTPException(404, "Immagine non trovata.")
    if not ownership.can_see_item(user, img.get("owner_id"),
                                  extra_doc_ids=shared_img_ids_for(user), doc_id=img_id):
        raise HTTPException(403, "Non hai accesso a questa immagine.")
    path = img.get("path")
    if path and Path(path).exists():
        return FileResponse(path, headers={"Cache-Control": "no-cache"})
    raise HTTPException(404, "File immagine non disponibile.")


@app.delete("/api/images/{img_id}")
def delete_image(img_id: str, user: dict = Depends(current_user)):
    """Elimina un'immagine: rimuove file, metadati e ricostruisce i due indici.
    Per non rieseguire CLIP, ricostruisce i vettori da FAISS e scarta quello rimosso."""
    global _image_store, _img_vis_index, _img_txt_index
    import faiss

    target = next((i for i in _image_store if i["img_id"] == img_id), None)
    if not target:
        raise HTTPException(404, "Immagine non trovata.")

    if user["role"] != auth.ROLE_DEVELOPER and target.get("owner_id") != user["user_id"]:
        raise HTTPException(403, "Solo il proprietario puo' eliminare questa immagine.")

    sharing.purge_target(sharing.TARGET_DOCUMENT, img_id)

    try:
        p = target.get("path")
        if p and Path(p).exists():
            Path(p).unlink()
    except Exception as e:
        logger.warning("Impossibile eliminare il file immagine: %s", e)

    vis_index = get_img_vis_index()
    txt_index = get_img_txt_index()
    vis_recon = _reconstruct_all(vis_index, vis_index.ntotal)
    txt_recon = _reconstruct_all(txt_index, txt_index.ntotal)

    survivors = [im for im in _image_store if im["img_id"] != img_id]

    new_vis = faiss.IndexHNSWFlat(OBS_CONFIG["image_dim"], 32)
    new_txt = faiss.IndexHNSWFlat(OBS_CONFIG["embedding_dim"], 32)
    for im in survivors:
        old_vis = im.get("vis_idx", -1)
        if 0 <= old_vis < len(vis_recon) and vis_recon[old_vis] is not None:
            im["vis_idx"] = new_vis.ntotal
            new_vis.add(np.asarray(vis_recon[old_vis], dtype="float32").reshape(1, -1))
        old_txt = im.get("txt_idx", -1)
        if old_txt >= 0 and old_txt < len(txt_recon) and txt_recon[old_txt] is not None:
            im["txt_idx"] = new_txt.ntotal
            new_txt.add(np.asarray(txt_recon[old_txt], dtype="float32").reshape(1, -1))
        else:
            im["txt_idx"] = -1

    _img_vis_index = new_vis
    _img_txt_index = new_txt
    _image_store = survivors
    _persist_images()
    return {"success": True, "remaining": len(_image_store)}


def _load_image_array(img: dict):
    from PIL import Image
    path = img.get("path")
    if not path or not Path(path).exists():
        raise HTTPException(404, "File immagine non disponibile.")
    pil = Image.open(path).convert("RGB")
    return np.asarray(pil, dtype=np.uint8), pil.width, pil.height


class ColorSampleRequest(BaseModel):
    x: float
    y: float
    radius: int = 2


class ColorAnalyzeRequest(BaseModel):
    k: int = 5
    region: Optional[List[float]] = None


class ColorCompareRequest(BaseModel):
    lab1: List[float]
    lab2: List[float]


@app.post("/api/images/{img_id}/sample")
def image_color_sample(img_id: str, req: ColorSampleRequest, user: dict = Depends(current_user)):
    img = next((i for i in _image_store if i["img_id"] == img_id), None)
    if not img:
        raise HTTPException(404, "Immagine non trovata.")
    if not ownership.can_see_item(user, img.get("owner_id"),
                                  extra_doc_ids=shared_img_ids_for(user), doc_id=img_id):
        raise HTTPException(403, "Non hai accesso a questa immagine.")
    import color_analysis
    arr, w, h = _load_image_array(img)
    try:
        res = color_analysis.sample_color(arr, req.x, req.y, radius=req.radius)
    except ValueError as e:
        raise HTTPException(400, str(e))
    res["image_width"] = w
    res["image_height"] = h
    return res


@app.post("/api/images/{img_id}/analyze")
def image_color_analyze(img_id: str, req: ColorAnalyzeRequest, user: dict = Depends(current_user)):
    img = next((i for i in _image_store if i["img_id"] == img_id), None)
    if not img:
        raise HTTPException(404, "Immagine non trovata.")
    if not ownership.can_see_item(user, img.get("owner_id"),
                                  extra_doc_ids=shared_img_ids_for(user), doc_id=img_id):
        raise HTTPException(403, "Non hai accesso a questa immagine.")
    import color_analysis
    arr, w, h = _load_image_array(img)
    try:
        colors = color_analysis.dominant_colors(arr, k=req.k, region=req.region)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"img_id": img_id, "colors": colors,
            "image_width": w, "image_height": h,
            "region": req.region}


@app.post("/api/images/compare")
def image_color_compare(req: ColorCompareRequest, user: dict = Depends(current_user)):
    import color_analysis
    if len(req.lab1) != 3 or len(req.lab2) != 3:
        raise HTTPException(400, "Ogni colore richiede tre coordinate CIELAB.")
    de = color_analysis.delta_e_2000(req.lab1, req.lab2)
    return {"delta_e": round(de, 3)}


class ImageCropRequest(BaseModel):
    region: List[float]


@app.post("/api/images/{img_id}/crop")
def image_crop(img_id: str, req: ImageCropRequest, user: dict = Depends(current_user)):
    """Sovrascrive l'immagine con la sola regione selezionata e la reindicizza.
    Il contenuto dei pixel cambia, quindi CLIP e OCR vengono rieseguiti e le
    posizioni FAISS rimappate in blocco per tutte le immagini."""
    global _image_store, _img_vis_index, _img_txt_index
    from PIL import Image
    import faiss

    img = next((i for i in _image_store if i["img_id"] == img_id), None)
    if not img:
        raise HTTPException(404, "Immagine non trovata.")
    if user["role"] != auth.ROLE_DEVELOPER and img.get("owner_id") != user["user_id"]:
        raise HTTPException(403, "Solo il proprietario puo' ritagliare questa immagine.")
    if len(req.region) != 4:
        raise HTTPException(400, "La regione richiede quattro valori [x0, y0, x1, y1].")

    path = img.get("path")
    if not path or not Path(path).exists():
        raise HTTPException(404, "File immagine non disponibile.")

    pil = Image.open(path).convert("RGB")
    w, h = pil.width, pil.height
    x0f, x1f = sorted((float(req.region[0]), float(req.region[2])))
    y0f, y1f = sorted((float(req.region[1]), float(req.region[3])))
    x0 = max(0, min(w - 1, int(round(x0f * w))))
    x1 = max(x0 + 1, min(w, int(round(x1f * w))))
    y0 = max(0, min(h - 1, int(round(y0f * h))))
    y1 = max(y0 + 1, min(h, int(round(y1f * h))))
    cropped = pil.crop((x0, y0, x1, y1))
    cropped.save(path)

    new_img_id = _unique_image_id(Path(path).read_bytes())

    vis_vec = _embed_image_files([Path(path)])[0]
    ocr_text = run_ocr(Path(path))
    tvec = None
    if ocr_text:
        tmodel = get_embed_model()
        tvec = tmodel.encode([ocr_text], show_progress_bar=False).astype("float32")
        tvec = tvec / (np.linalg.norm(tvec, axis=1, keepdims=True) + 1e-9)

    vis_index = get_img_vis_index()
    txt_index = get_img_txt_index()
    vis_recon = _reconstruct_all(vis_index, vis_index.ntotal)
    txt_recon = _reconstruct_all(txt_index, txt_index.ntotal)

    new_vis = faiss.IndexHNSWFlat(OBS_CONFIG["image_dim"], 32)
    new_txt = faiss.IndexHNSWFlat(OBS_CONFIG["embedding_dim"], 32)
    for im in _image_store:
        if im["img_id"] == img_id:
            im["img_id"] = new_img_id
            im["vis_idx"] = new_vis.ntotal
            new_vis.add(vis_vec.reshape(1, -1))
            if tvec is not None:
                im["txt_idx"] = new_txt.ntotal
                new_txt.add(tvec)
            else:
                im["txt_idx"] = -1
            im["ocr_text"] = ocr_text[:500]
            continue
        old_vis = im.get("vis_idx", -1)
        if 0 <= old_vis < len(vis_recon) and vis_recon[old_vis] is not None:
            im["vis_idx"] = new_vis.ntotal
            new_vis.add(np.asarray(vis_recon[old_vis], dtype="float32").reshape(1, -1))
        old_txt = im.get("txt_idx", -1)
        if 0 <= old_txt < len(txt_recon) and txt_recon[old_txt] is not None:
            im["txt_idx"] = new_txt.ntotal
            new_txt.add(np.asarray(txt_recon[old_txt], dtype="float32").reshape(1, -1))
        else:
            im["txt_idx"] = -1

    _img_vis_index = new_vis
    _img_txt_index = new_txt
    _persist_images()
    return {"success": True, "img_id": new_img_id, "has_text": bool(ocr_text),
            "width": x1 - x0, "height": y1 - y0}


@app.post("/api/images/{img_id}/duplicate")
def image_duplicate(img_id: str, user: dict = Depends(current_user)):
    """Duplica un'immagine: copia il file e riusa i vettori gia' calcolati alle
    nuove posizioni, senza rieseguire CLIP ne OCR, perche' il contenuto e' identico."""
    global _image_store
    import faiss
    import re

    src = next((i for i in _image_store if i["img_id"] == img_id), None)
    if not src:
        raise HTTPException(404, "Immagine non trovata.")
    if not ownership.can_see_item(user, src.get("owner_id"),
                                  extra_doc_ids=shared_img_ids_for(user), doc_id=img_id):
        raise HTTPException(403, "Non hai accesso a questa immagine.")

    src_path = src.get("path")
    if not src_path or not Path(src_path).exists():
        raise HTTPException(404, "File immagine non disponibile.")

    suffix = Path(src_path).suffix or ".img"
    dest = IMAGES_DIR / f"{uuid.uuid4().hex}{suffix}"
    dest.write_bytes(Path(src_path).read_bytes())
    new_img_id = _unique_image_id(dest.read_bytes())

    vis_index = get_img_vis_index()
    txt_index = get_img_txt_index()
    vis_recon = _reconstruct_all(vis_index, vis_index.ntotal)
    txt_recon = _reconstruct_all(txt_index, txt_index.ntotal)

    src_vis = src.get("vis_idx", -1)
    if not (0 <= src_vis < len(vis_recon) and vis_recon[src_vis] is not None):
        try:
            dest.unlink()
        except Exception:
            pass
        raise HTTPException(500, "Vettore visivo dell'originale non disponibile.")

    new_vis_idx = vis_index.ntotal
    vis_index.add(np.asarray(vis_recon[src_vis], dtype="float32").reshape(1, -1))

    new_txt_idx = -1
    src_txt = src.get("txt_idx", -1)
    if 0 <= src_txt < len(txt_recon) and txt_recon[src_txt] is not None:
        new_txt_idx = txt_index.ntotal
        txt_index.add(np.asarray(txt_recon[src_txt], dtype="float32").reshape(1, -1))

    raw_title = src.get("titolo") or src.get("filename") or "immagine"
    base_title = re.sub(r"\s*\(copia(?:\s+\d+)?\)\s*$", "", raw_title).strip() or "immagine"
    existing_titles = {im.get("titolo") for im in _image_store}
    candidate = f"{base_title} (copia)"
    n = 2
    while candidate in existing_titles:
        candidate = f"{base_title} (copia {n})"
        n += 1

    _image_store.append({
        "img_id":    new_img_id,
        "filename":  src.get("filename", ""),
        "azienda":   src.get("azienda", "?"),
        "titolo":    candidate[:200],
        "path":      str(dest),
        "vis_idx":   new_vis_idx,
        "txt_idx":   new_txt_idx,
        "folder_id": src.get("folder_id"),
        "owner_id":  user["user_id"],
        "ocr_text":  src.get("ocr_text", ""),
        "timestamp": datetime.utcnow().isoformat(),
    })
    _persist_images()
    return {"success": True, "img_id": new_img_id, "has_text": new_txt_idx >= 0}


FOLDERS_FILE = VS_DIR / "folders.json"
_folders: List[dict] = []


def _load_folders():
    global _folders
    if FOLDERS_FILE.exists():
        try:
            _folders = json.loads(FOLDERS_FILE.read_text())
            logger.info("Loaded %d folders from disk.", len(_folders))
        except Exception as e:
            logger.warning("Could not load folders: %s", e)
            return
    legacy = [f for f in _folders if f.get("owner_id") is None]
    if legacy:
        dev_id = auth.developer_user_id()
        if dev_id is None:
            logger.warning("Nessun account developer: %d cartelle legacy restano senza proprietario.",
                           len(legacy))
        else:
            for f in legacy:
                f["owner_id"] = dev_id
            _persist_folders()
            logger.info("Assegnate %d cartelle legacy al developer (id %s).", len(legacy), dev_id)


def _persist_folders():
    FOLDERS_FILE.write_text(json.dumps(_folders, ensure_ascii=False, indent=2))


def _folder_counts(folder_id: str, user: Optional[dict] = None, placements: Optional[dict] = None):
    """Quanti documenti e immagini stanno in una cartella, dal punto di vista dell'utente."""
    chunks = _visible_chunks(user) if user is not None else _chunk_store
    images = _visible_images(user) if user is not None else _image_store
    if user is None:
        doc_ids = {c["doc_id"] for c in chunks if c.get("folder_id") == folder_id}
    else:
        pl = placements if placements is not None else sharing.get_placements(user["user_id"])
        doc_ids = {c["doc_id"] for c in chunks
                   if _effective_folder_of(c, user, pl) == folder_id}
    n_imgs = sum(1 for im in images if im.get("folder_id") == folder_id)
    return len(doc_ids), n_imgs


def _visible_folders(user: dict) -> List[dict]:
    """Il developer vede tutte le cartelle. Gli altri vedono le proprie e quelle
    esplicitamente condivise con loro. Una cartella senza owner_id e' legacy e
    appartiene al developer."""
    if user["role"] == auth.ROLE_DEVELOPER:
        return list(_folders)
    shared = sharing.shared_folder_ids(user["user_id"])
    return [f for f in _folders
            if f.get("owner_id") == user["user_id"] or f["folder_id"] in shared]


class FolderRequest(BaseModel):
    name: str


@app.get("/api/folders")
def list_folders(user: dict = Depends(current_user)):
    visible_chunks = _visible_chunks(user)
    visible_images = _visible_images(user)
    placements = sharing.get_placements(user["user_id"])
    mine = _visible_folders(user)
    visible_ids = {f["folder_id"] for f in mine}
    out = []
    for f in mine:
        nd, ni = _folder_counts(f["folder_id"], user=user, placements=placements)
        out.append({**f,
                    "n_documents": nd,
                    "n_images": ni,
                    "is_owner": (user["role"] == auth.ROLE_DEVELOPER
                                 or f.get("owner_id") == user["user_id"])})
    out.sort(key=lambda x: x.get("name", "").lower())
    unfiled_docs = len({c["doc_id"] for c in visible_chunks
                        if _effective_folder_of(c, user, placements) not in visible_ids})
    unfiled_imgs = sum(1 for im in visible_images
                       if im.get("folder_id") not in visible_ids)
    return {"folders": out, "unfiled_documents": unfiled_docs, "unfiled_images": unfiled_imgs}


@app.post("/api/folders")
def create_folder(req: FolderRequest, user: dict = Depends(current_user)):
    name = (req.name or "").strip()
    if not name:
        raise HTTPException(400, "Il nome della cartella non può essere vuoto.")
    mine = _visible_folders(user)
    if any(f["name"].lower() == name.lower() and f.get("owner_id") == user["user_id"]
           for f in mine):
        raise HTTPException(400, "Esiste già una cartella con questo nome.")
    folder = {
        "folder_id": uuid.uuid4().hex[:10],
        "name":      name[:100],
        "owner_id":  user["user_id"],
        "created":   datetime.utcnow().isoformat(),
    }
    _folders.append(folder)
    _persist_folders()
    return folder


def _owned_folder_or_403(folder_id: str, user: dict) -> dict:
    folder = next((f for f in _folders if f["folder_id"] == folder_id), None)
    if not folder:
        raise HTTPException(404, "Cartella non trovata.")
    if user["role"] == auth.ROLE_DEVELOPER:
        return folder
    if folder.get("owner_id") != user["user_id"]:
        raise HTTPException(403, "Solo il proprietario puo' modificare questa cartella.")
    return folder


@app.patch("/api/folders/{folder_id}")
def rename_folder(folder_id: str, req: FolderRequest, user: dict = Depends(current_user)):
    folder = _owned_folder_or_403(folder_id, user)
    name = (req.name or "").strip()
    if not name:
        raise HTTPException(400, "Il nome non può essere vuoto.")
    folder["name"] = name[:100]
    _persist_folders()
    return folder


@app.delete("/api/folders/{folder_id}")
def delete_folder(folder_id: str, user: dict = Depends(current_user)):
    """Elimina la cartella. I file dentro NON vengono cancellati: tornano 'non in cartella'."""
    global _folders
    folder = _owned_folder_or_403(folder_id, user)
    for c in _chunk_store:
        if c.get("folder_id") == folder_id:
            c["folder_id"] = None
    for im in _image_store:
        if im.get("folder_id") == folder_id:
            im["folder_id"] = None
    _folders = [f for f in _folders if f["folder_id"] != folder_id]
    sharing.purge_target(sharing.TARGET_FOLDER, folder_id)
    sharing.purge_placements_for_folder(folder_id)
    _persist_folders()
    _persist_index()
    _persist_images()
    return {"success": True}


class AssignRequest(BaseModel):
    item_type: str
    item_id: str
    folder_id: Optional[str] = None


@app.post("/api/folders/assign")
def assign_to_folder(req: AssignRequest, user: dict = Depends(current_user)):
    """Sposta un documento o un'immagine in una cartella (o fuori, se folder_id=None).

    Il proprietario sposta l'originale. Chi ha ricevuto un documento per
    condivisione diretta ne cambia solo la collocazione nella propria vista, senza
    toccare l'archivio del proprietario. Chi lo ha ricevuto attraverso una cartella
    condivisa non puo' spostarlo, perche' la cartella e' il veicolo della
    condivisione."""
    is_dev = user["role"] == auth.ROLE_DEVELOPER

    if req.folder_id:
        dest = next((f for f in _folders if f["folder_id"] == req.folder_id), None)
        if not dest:
            raise HTTPException(404, "Cartella di destinazione non trovata.")
        if not is_dev and dest.get("owner_id") != user["user_id"]:
            raise HTTPException(403, "Puoi spostare solo dentro una cartella che ti appartiene.")

    if req.item_type == "document":
        owner_id = _doc_owner_of(req.item_id)
        if owner_id is None and not is_dev:
            raise HTTPException(404, "Documento non trovato.")

        if is_dev or owner_id == user["user_id"]:
            touched = False
            for c in _chunk_store:
                if c.get("doc_id") == req.item_id:
                    c["folder_id"] = req.folder_id
                    touched = True
            if not touched:
                raise HTTPException(404, "Documento non trovato.")
            _persist_index()
            return {"success": True, "folder_id": req.folder_id}

        split = shared_doc_split_for(user)
        if req.item_id in split["via_folder"]:
            raise HTTPException(
                403,
                "Questo documento ti e' stato condiviso attraverso una cartella e "
                "resta in quella cartella.")
        if req.item_id not in split["direct"]:
            raise HTTPException(403, "Solo il proprietario puo' spostare questo documento.")
        sharing.set_placement(user["user_id"], req.item_id, req.folder_id)
        return {"success": True, "folder_id": req.folder_id, "personal": True}

    elif req.item_type == "image":
        img = next((im for im in _image_store if im.get("img_id") == req.item_id), None)
        if not img:
            raise HTTPException(404, "Immagine non trovata.")
        if not is_dev and img.get("owner_id") != user["user_id"]:
            raise HTTPException(403, "Solo il proprietario puo' spostare questa immagine.")
        img["folder_id"] = req.folder_id
        _persist_images()
    else:
        raise HTTPException(400, "item_type deve essere 'document' o 'image'.")
    return {"success": True, "folder_id": req.folder_id}


def _reassign_orphans(user_id: int) -> dict:
    """Un utente cancellato lascia documenti, immagini e cartelle con un owner_id
    che non punta piu' a nessuno: sarebbero invisibili a chiunque tranne il
    developer, ma continuerebbero a occupare spazio e posizioni FAISS. Vengono
    riassegnati al developer, che decide se conservarli o eliminarli. Nessun
    contenuto viene distrutto."""
    dev_id = auth.developer_user_id()
    if dev_id is None or dev_id == user_id:
        return {"reassigned": False}
    n_chunks = 0
    docs = set()
    for c in _chunk_store:
        if c.get("owner_id") == user_id:
            c["owner_id"] = dev_id
            docs.add(c.get("doc_id"))
            n_chunks += 1
    n_imgs = 0
    for im in _image_store:
        if im.get("owner_id") == user_id:
            im["owner_id"] = dev_id
            n_imgs += 1
    n_folders = 0
    for f in _folders:
        if f.get("owner_id") == user_id:
            f["owner_id"] = dev_id
            n_folders += 1
    if n_chunks:
        _persist_index()
    if n_imgs:
        _persist_images()
    if n_folders:
        _persist_folders()
    n_scripts = 0
    try:
        n_scripts = code_store.reassign_scripts(user_id, dev_id)
    except Exception as e:
        logger.warning("Riassegnazione script non riuscita: %s", e)
    try:
        code_files.clear_files(user_id)
    except Exception as e:
        logger.warning("Pulizia file Code non riuscita: %s", e)
    n_workbooks = 0
    try:
        n_workbooks = sheets_store.reassign_workbooks(user_id, dev_id)
    except Exception as e:
        logger.warning("Riassegnazione cartelle sheets non riuscita: %s", e)
    return {"reassigned": True, "documents": len(docs),
            "images": n_imgs, "folders": n_folders, "scripts": n_scripts,
            "workbooks": n_workbooks}


def _is_share_owner(target_type: str, target_id: str, user_id: int) -> bool:
    """Vero se user_id possiede davvero l'elemento. Impedisce la ricondivisione:
    chi ha ricevuto un elemento non ne diventa proprietario e non puo' ridistribuirlo."""
    if target_type == sharing.TARGET_DOCUMENT:
        return _doc_owner_of(target_id) == user_id
    if target_type == sharing.TARGET_FOLDER:
        folder = next((f for f in _folders if f["folder_id"] == target_id), None)
        return bool(folder) and folder.get("owner_id") == user_id
    return False


def _reclaim_orphan_owners() -> None:
    """Recupera gli oggetti il cui owner_id non corrisponde piu' ad alcun utente.
    Serve quando un utente viene cancellato dalla riga di comando a server spento,
    perche' in quel caso la riassegnazione in memoria non puo' avvenire."""
    dev_id = auth.developer_user_id()
    if dev_id is None:
        return
    owners = {c.get("owner_id") for c in _chunk_store}
    owners |= {im.get("owner_id") for im in _image_store}
    owners |= {f.get("owner_id") for f in _folders}
    owners.discard(None)
    missing = {o for o in owners if auth.get_user_by_id(o) is None}
    if not missing:
        return
    for o in missing:
        sharing.purge_user(o)
        _reassign_orphans(o)
    logger.info("Recuperati oggetti di %d utenti non piu' esistenti.", len(missing))


@app.on_event("startup")
def startup():
    logger.info("OBS starting - warming up models")
    try:
        created = auth.bootstrap_developer()
        if created:
            logger.info("Account developer creato al primo avvio: %s", created)
        else:
            auth.init_db()
    except Exception as e:
        logger.warning("Bootstrap autenticazione non riuscito: %s", e)
    try:
        sharing.init_db()
    except Exception as e:
        logger.warning("Init sharing non riuscito: %s", e)
    try:
        code_store.init_db()
        code_store.purge_expired_tokens()
        code_files.init_dirs()
    except Exception as e:
        logger.warning("Init editor codice non riuscito: %s", e)
    try:
        if os.environ.get("OBS_SHEETS_ENABLED", "1") != "0":
            sheets_store.init_db()
    except Exception as e:
        logger.warning("Init pannello sheets non riuscito: %s", e)
    try:
        sharing_routes.register_ownership_check(_is_share_owner)
        auth_routes.register_user_cleanup(_reassign_orphans)
    except Exception as e:
        logger.warning("Registrazione hook non riuscita: %s", e)
    if model_setup.models_ready():
        get_embed_model()
        get_faiss_index()
    else:
        logger.info("Embedding model not present yet, deferring load until models are downloaded")
    try:
        _load_persisted_images()
    except Exception as e:
        logger.warning("Could not load persisted images: %s", e)
    try:
        _load_folders()
    except Exception as e:
        logger.warning("Could not load folders: %s", e)
    try:
        _reclaim_orphan_owners()
    except Exception as e:
        logger.warning("Recupero oggetti orfani non riuscito: %s", e)
    logger.info("OBS ready.")

if __name__ == "__main__":
    import uvicorn
    host = os.environ.get("OBS_HOST", "127.0.0.1")
    port = int(os.environ.get("OBS_PORT", "8000"))
    timeout = int(os.environ.get("OBS_TIMEOUT", "1800"))
    uvicorn.run(
        app,
        host=host,
        port=port,
        timeout_keep_alive=timeout,
        limit_concurrency=64,
        access_log=False,
    )
