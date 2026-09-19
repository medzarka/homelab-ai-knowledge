import os
import sys
import io
import re
import time
import json
import uuid
import base64
import hashlib
import asyncio
import secrets
import urllib.parse
from pathlib import Path
from typing import Dict, List, Optional, Any, Union, Tuple

import fitz  # PyMuPDF
from PIL import Image
import httpx
from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# FastMCP / MCPServer Import
try:
    from mcp.server.mcpserver import MCPServer
    from mcp.server.transport_security import TransportSecuritySettings
except ImportError:
    from mcp.server.fastmcp import FastMCP as MCPServer
    TransportSecuritySettings = None

from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

# --- Configuration & Defaults ---
QDRANT_HOST = os.environ.get("QDRANT_HOST", "qdrant")
QDRANT_PORT = int(os.environ.get("QDRANT_PORT", 6333))
QDRANT_API_KEY = os.environ.get("QDRANT_API_KEY") or None
DEFAULT_COLLECTION = os.environ.get("QDRANT_COLLECTION_WORKSPACE", "workspace")
VECTOR_DIMENSIONS = int(os.environ.get("VECTOR_DIMENSIONS", 1024))

PDF_RENDER_DPI = int(os.environ.get("PDF_RENDER_DPI", 150))
MAX_CONCURRENT_JOBS = int(os.environ.get("MAX_CONCURRENT_INDEXING_JOBS", 1))
REQUEST_TIMEOUT = float(os.environ.get("INDEXING_REQUEST_TIMEOUT", 300))

# --- AI Services & Fallback Configuration ---
EMBEDDING_PRIMARY_URL = os.environ.get("EMBEDDING_PRIMARY_URL", "http://compute_embeddings:80/embed")
EMBEDDING_PRIMARY_KEY = os.environ.get("EMBEDDING_PRIMARY_KEY", "sk-homelab-tei-secure-key")
EMBEDDING_FALLBACK_URL = os.environ.get("EMBEDDING_FALLBACK_URL", "http://litellm:4000/v1/embeddings")
EMBEDDING_FALLBACK_KEY = os.environ.get("EMBEDDING_FALLBACK_KEY", "")
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "BAAI/bge-m3")

RERANKER_PRIMARY_URL = os.environ.get("RERANKER_PRIMARY_URL", "http://compute_reranker:80/rerank")
RERANKER_PRIMARY_KEY = os.environ.get("RERANKER_PRIMARY_KEY", "sk-homelab-tei-secure-key")
RERANKER_FALLBACK_URL = os.environ.get("RERANKER_FALLBACK_URL", "http://litellm:4000/v1/rerank")
RERANKER_FALLBACK_KEY = os.environ.get("RERANKER_FALLBACK_KEY", "")
RERANKER_MODEL = os.environ.get("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3")

VISION_PRIMARY_PROVIDER = os.environ.get("VISION_PRIMARY_PROVIDER", "local")
VISION_PRIMARY_URL = os.environ.get("VISION_PRIMARY_URL", "http://compute_ollama:11434/api/chat")
VISION_PRIMARY_KEY = os.environ.get("VISION_PRIMARY_KEY", "sk-homelab-ollama-secure-key")
VISION_PRIMARY_MODEL = os.environ.get("VISION_PRIMARY_MODEL", "qwen2.5vl:3b")

VISION_FALLBACK_PROVIDER = os.environ.get("VISION_FALLBACK_PROVIDER", "litellm")
VISION_FALLBACK_URL = os.environ.get("VISION_FALLBACK_URL", "http://litellm:4000/v1/chat/completions")
VISION_FALLBACK_KEY = os.environ.get("VISION_FALLBACK_KEY", "")
VISION_FALLBACK_MODEL = os.environ.get("VISION_FALLBACK_MODEL", "google/gemini-2.0-flash")

AUDIO_PRIMARY_URL = os.environ.get("AUDIO_PRIMARY_URL", "http://compute_speaches:8000/v1/audio/transcriptions")
AUDIO_PRIMARY_KEY = os.environ.get("AUDIO_PRIMARY_KEY", "sk-homelab-speaches-secure-key")
AUDIO_PRIMARY_MODEL = os.environ.get("AUDIO_PRIMARY_MODEL", "Systran/faster-whisper-large-v3")
AUDIO_FALLBACK_URL = os.environ.get("AUDIO_FALLBACK_URL", "http://litellm:4000/v1/audio/transcriptions")
AUDIO_FALLBACK_KEY = os.environ.get("AUDIO_FALLBACK_KEY", "")
AUDIO_FALLBACK_MODEL = os.environ.get("AUDIO_FALLBACK_MODEL", "openai/whisper-1")

NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://neo4j:7687")
NEO4J_USER = os.environ.get("NEO4J_USERNAME", "neo4j")
NEO4J_PASS = os.environ.get("NEO4J_PASSWORD", "mem0graph_secure_pass")

MEM0_API_URL = os.environ.get("MEM0_API_URL", "http://mem0-api:8000")
MEM0_API_KEY = os.environ.get("MEM0_API_KEY", "")
KNOWLEDGE_MCP_API_KEY = (os.environ.get("KNOWLEDGE_MCP_API_KEY") or "").strip()
OBSIDIAN_VAULT_PATH = Path(os.environ.get("OBSIDIAN_VAULT_PATH", "/vault")).resolve()

def get_vault_safe_path(rel_path: str) -> Path:
    clean_path = rel_path.strip().lstrip("/")
    target = (OBSIDIAN_VAULT_PATH / clean_path).resolve()
    if not str(target).startswith(str(OBSIDIAN_VAULT_PATH)):
        raise ValueError(f"Access denied: path '{rel_path}' resolves outside the Obsidian vault.")
    return target

# --- Global Concurrency Guard ---
PIPELINE_SEMAPHORE = asyncio.Semaphore(MAX_CONCURRENT_JOBS)

# --- Clients ---
qdrant_client = QdrantClient(
    host=QDRANT_HOST, 
    port=QDRANT_PORT, 
    api_key=QDRANT_API_KEY, 
    https=False,
    timeout=30
)
http_client = httpx.AsyncClient(timeout=httpx.Timeout(REQUEST_TIMEOUT, connect=10.0))

# --- Academic Vision Prompt ---
ACADEMIC_VLM_PROMPT = """
You are an expert academic document analyzer and transcription engine.
Transcribe this page into structured, searchable Markdown following these strict rules:

1. TEXT & HANDWRITING: Transcribe all printed text and handwritten notes accurately (including cursive, margin comments, circled options, and checkmarks).
2. MATHEMATICS: Convert all equations, formulas, and math derivations into standard LaTeX ($...$ for inline, $$...$$ for block).
3. TABLES: Convert tables into clean GitHub-flavored Markdown tables.
4. DIAGRAMS & CHARTS: Provide a descriptive '[Diagram: ...]' section detailing structure, labels, axes, and architecture.
5. EXAMS & SCORES: Preserve question numbers (e.g. 'Q1.', 'Part 2:'), point values, and student choices accurately.

Output only the clean Markdown transcription without conversational preamble.
"""

MATH_REGEX = re.compile(r'[\u2200-\u22FF\u2A00-\u2AFF]|\b(sum|int|lim|sqrt|frac|alpha|beta|theta|pi|partial|nabla)\b|\$.*?\$|\\\[.*?\\\]')

# --- Helper Utilities ---

def ensure_collection(collection_name: str):
    """Ensures a Qdrant collection exists with the standard 1024-dim cosine config."""
    try:
        collections = [c.name for c in qdrant_client.get_collections().collections]
        if collection_name not in collections:
            qdrant_client.create_collection(
                collection_name=collection_name,
                vectors_config=qmodels.VectorParams(
                    size=VECTOR_DIMENSIONS,
                    distance=qmodels.Distance.COSINE
                )
            )
    except Exception as e:
        print(f"Notice: Ensure collection '{collection_name}': {e}")

# Ensure default collection on boot
try:
    ensure_collection(DEFAULT_COLLECTION)
except Exception:
    pass

async def get_embedding(text: str) -> List[float]:
    """Generates 1024-dim dense embedding with primary TEI -> fallback LiteLLM failover."""
    # 1. Try Primary Local TEI with Bearer Token
    try:
        headers = {"Authorization": f"Bearer {EMBEDDING_PRIMARY_KEY}"} if EMBEDDING_PRIMARY_KEY else {}
        resp = await http_client.post(
            EMBEDDING_PRIMARY_URL,
            json={"inputs": [text[:4096]], "normalize": True},
            headers=headers,
            timeout=15.0
        )
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list) and len(data) > 0:
                return data[0] if isinstance(data[0], list) else data
    except Exception as e:
        print(f"Warning: Primary Embedding failed ({str(e)[:40]}), trying fallback...")

    # 2. Fallback to LiteLLM / OpenAI-compatible endpoint (if configured)
    if EMBEDDING_FALLBACK_URL and EMBEDDING_FALLBACK_URL.strip():
        try:
            headers = {"Authorization": f"Bearer {EMBEDDING_FALLBACK_KEY}"} if EMBEDDING_FALLBACK_KEY else {}
            resp = await http_client.post(
                EMBEDDING_FALLBACK_URL.strip(),
                json={"input": [text[:4096]], "model": EMBEDDING_MODEL},
                headers=headers,
                timeout=20.0
            )
            if resp.status_code == 200:
                data = resp.json()
                return data["data"][0]["embedding"]
        except Exception as e:
            raise RuntimeError(f"All embedding providers failed: {str(e)}")
    else:
        raise RuntimeError("Primary embedding service unavailable and fallback is disabled.")

async def rerank_documents(query: str, texts: List[str], top_n: int = 5) -> List[Dict[str, Any]]:
    """Reranks candidate texts using primary TEI -> fallback LiteLLM cross-encoder."""
    if not texts:
        return []

    # 1. Try Primary TEI Reranker with Bearer Token
    if RERANKER_PRIMARY_URL and RERANKER_PRIMARY_URL.strip():
        try:
            headers = {"Authorization": f"Bearer {RERANKER_PRIMARY_KEY}"} if RERANKER_PRIMARY_KEY else {}
            resp = await http_client.post(
                RERANKER_PRIMARY_URL.strip(),
                json={"query": query, "texts": texts, "raw_scores": False},
                headers=headers,
                timeout=15.0
            )
            if resp.status_code == 200:
                results = resp.json()
                return sorted(results, key=lambda x: x.get("score", 0), reverse=True)[:top_n]
        except Exception as e:
            print(f"Warning: Primary Reranker failed ({str(e)[:40]}), trying fallback...")

    # 2. Fallback LiteLLM Rerank (if configured)
    if RERANKER_FALLBACK_URL and RERANKER_FALLBACK_URL.strip():
        try:
            headers = {"Authorization": f"Bearer {RERANKER_FALLBACK_KEY}"} if RERANKER_FALLBACK_KEY else {}
            resp = await http_client.post(
                RERANKER_FALLBACK_URL.strip(),
                json={"query": query, "documents": texts, "model": RERANKER_MODEL, "top_n": top_n},
                headers=headers,
                timeout=20.0
            )
            if resp.status_code == 200:
                data = resp.json()
                return [{"index": r["index"], "score": r["relevance_score"]} for r in data.get("results", [])]
        except Exception:
            pass

    # Basic fallback if reranker fails or is disabled (Pass raw candidate ranking)
    return [{"index": i, "score": 1.0 - (i * 0.05)} for i in range(min(len(texts), top_n))]

async def vision_transcribe(image_bytes: bytes, prompt: str = ACADEMIC_VLM_PROMPT) -> str:
    """Sends image to Vision LLM with primary Ollama Qwen2.5-VL -> fallback LiteLLM."""
    b64_img = base64.b64encode(image_bytes).decode("utf-8")

    # 1. Try Primary Local Ollama (qwen2.5vl:3b)
    if VISION_PRIMARY_PROVIDER == "local":
        try:
            headers = {"Authorization": f"Bearer {VISION_PRIMARY_KEY}"} if VISION_PRIMARY_KEY else {}
            payload = {
                "model": VISION_PRIMARY_MODEL,
                "messages": [
                    {
                        "role": "user",
                        "content": prompt,
                        "images": [b64_img]
                    }
                ],
                "stream": False,
                "options": {"temperature": 0.1}
            }
            resp = await http_client.post(VISION_PRIMARY_URL, json=payload, headers=headers, timeout=60.0)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("message", {}).get("content", "").strip()
        except Exception as e:
            print(f"Warning: Primary Vision AI failed ({str(e)[:40]}), trying fallback...")

    # 2. Fallback to LiteLLM / Gemini / GPT-4o
    try:
        headers = {"Authorization": f"Bearer {VISION_FALLBACK_KEY}"} if VISION_FALLBACK_KEY else {}
        payload = {
            "model": VISION_FALLBACK_MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64_img}"}}
                    ]
                }
            ],
            "temperature": 0.1
        }
        resp = await http_client.post(VISION_FALLBACK_URL, json=payload, headers=headers, timeout=60.0)
        if resp.status_code == 200:
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        raise RuntimeError(f"All Vision AI providers failed: {str(e)}")

async def audio_transcribe(audio_bytes: bytes, filename: str = "audio.wav") -> str:
    """Transcribes speech with primary Speaches Whisper -> fallback LiteLLM."""
    # 1. Try Primary Speaches Whisper with Bearer Token
    try:
        headers = {"Authorization": f"Bearer {AUDIO_PRIMARY_KEY}"} if AUDIO_PRIMARY_KEY else {}
        files = {"file": (filename, audio_bytes, "audio/wav")}
        data = {"model": AUDIO_PRIMARY_MODEL, "response_format": "text"}
        resp = await http_client.post(AUDIO_PRIMARY_URL, files=files, data=data, headers=headers, timeout=90.0)
        if resp.status_code == 200:
            return resp.text.strip()
    except Exception as e:
        print(f"Warning: Primary Audio STT failed ({str(e)[:40]}), trying fallback...")

    # 2. Fallback LiteLLM Audio
    try:
        headers = {"Authorization": f"Bearer {AUDIO_FALLBACK_KEY}"} if AUDIO_FALLBACK_KEY else {}
        files = {"file": (filename, audio_bytes, "audio/wav")}
        data = {"model": AUDIO_FALLBACK_MODEL}
        resp = await http_client.post(AUDIO_FALLBACK_URL, files=files, data=data, headers=headers, timeout=90.0)
        if resp.status_code == 200:
            return resp.json().get("text", "").strip()
    except Exception as e:
        raise RuntimeError(f"All Audio transcription providers failed: {str(e)}")

def analyze_pdf_page(page: fitz.Page) -> Dict[str, Any]:
    """4-Layer fast AST inspection to decide whether VLM rendering is needed."""
    images = page.get_images()
    drawings = page.get_drawings()
    raw_text = page.get_text().strip()

    has_images = len(images) > 0
    has_charts = len(drawings) > 5
    is_scanned = len(raw_text) < 60 and has_images
    has_math = bool(MATH_REGEX.search(raw_text)) or any("math" in f[3].lower() or "cmsy" in f[3].lower() for f in page.get_fonts())

    needs_vlm = has_images or has_charts or is_scanned or has_math

    return {
        "needs_vlm": needs_vlm,
        "is_scanned": is_scanned,
        "has_images": has_images,
        "has_charts": has_charts,
        "has_math": has_math,
        "raw_text": raw_text
    }

def render_page_image(page: fitz.Page, target_dpi: int = PDF_RENDER_DPI) -> bytes:
    """Renders single PDF page in RAM at target DPI."""
    zoom = target_dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    return pix.tobytes("png")

def normalize_standalone_image(image_bytes: bytes, target_dpi: int = PDF_RENDER_DPI) -> bytes:
    """Resizes standalone images to match 150 DPI A4 max dimension."""
    img = Image.open(io.BytesIO(image_bytes))
    max_dim = int(1754 * (target_dpi / 150))
    if max(img.size) > max_dim:
        img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=85, dpi=(target_dpi, target_dpi))
    return out.getvalue()

# --- Initialize FastMCP Server ---
mcp = MCPServer("Homelab-AI-Knowledge-Hub")

# ==============================================================================
# MCP TOOLS (For Hermes Agent, Claude, Open-WebUI)
# ==============================================================================

@mcp.tool()
async def search_knowledge(
    query: str,
    collection: str = DEFAULT_COLLECTION,
    limit: int = 5,
    min_score: float = 0.50
) -> str:
    """
    Semantically searches the Homelab Knowledge Base (Qdrant) and reranks results with a Cross-Encoder.
    
    Args:
        query: The natural language search query.
        collection: The target collection name (default: 'workspace').
        limit: Number of top results to return (default: 5).
        min_score: Minimum relevance score threshold (0.0 - 1.0).
    """
    ensure_collection(collection)
    t0 = time.time()

    # 1. Embed query
    query_vector = await get_embedding(query)

    # 2. Vector search in Qdrant (fetch limit * 3 candidates for reranking)
    candidates = qdrant_client.query_points(
        collection_name=collection,
        query=query_vector,
        limit=min(limit * 3, 30),
        with_payload=True
    ).points

    if not candidates:
        return f"No matching knowledge found in collection `{collection}` for query: '{query}'"

    # 3. Cross-Encoder Rerank candidates
    doc_texts = [p.payload.get("content_text", "") for p in candidates]
    reranked = await rerank_documents(query, doc_texts, top_n=limit)

    elapsed_ms = (time.time() - t0) * 1000
    results_md = [
        f"### 🔍 Knowledge Search Results ({len(reranked)} matches in {elapsed_ms:.1f}ms)",
        f"**Collection:** `{collection}` | **Query:** *{query}*\n"
    ]

    for item in reranked:
        idx = item["index"]
        score = item["score"]
        if score < min_score:
            continue
        point = candidates[idx]
        payload = point.payload

        file_name = payload.get("file_name", "Unknown")
        file_path = payload.get("file_path", "")
        page_num = payload.get("page_number")
        page_info = f" (Page {page_num}/{payload.get('total_pages')})" if page_num else ""
        doc_type = payload.get("document_type", "document")
        content = payload.get("content_text", "").strip()

        results_md.append(f"#### 📄 **{file_name}**{page_info} `[Score: {score:.3f} | {doc_type}]`")
        if file_path:
            results_md.append(f"*Path:* `{file_path}`")
        results_md.append(f"\n```markdown\n{content}\n```\n---")

    return "\n".join(results_md)

@mcp.tool()
async def index_file(
    file_path: str,
    collection: str = DEFAULT_COLLECTION,
    tags: str = "",
    file_content_base64: Optional[str] = None
) -> str:
    """
    Ingests, parses, chunks, and indexes any file (PDF page-by-page, images via Vision, audio via STT, code/text) into Qdrant.
    Transactional & atomic per document.
    
    Args:
        file_path: Absolute or workspace path to the file.
        collection: Qdrant collection name (default: 'workspace').
        tags: Optional comma-separated list of categorization tags (e.g., 'pdf,report,urgent').
        file_content_base64: Optional base64 encoded file content for cross-host ingestion.
    """
    ensure_collection(collection)
    file_path_str = str(Path(file_path))

    if file_content_base64:
        try:
            file_bytes = base64.b64decode(file_content_base64)
            suffix = Path(file_path).suffix.lower()
            file_size_kb = len(file_bytes) / 1024
            file_name = Path(file_path).name
        except Exception as e:
            return f"Error decoding base64 file content: {str(e)}"
    else:
        p = Path(file_path)
        if not p.exists() or not p.is_file():
            return f"Error: File '{file_path}' does not exist."

        suffix = p.suffix.lower()
        file_size_kb = p.stat().st_size / 1024
        file_name = p.name
        file_bytes = await asyncio.to_thread(p.read_bytes)
        file_path_str = str(p.resolve())

    t0 = time.time()

    async with PIPELINE_SEMAPHORE:
        try:
            staged_points = []
            file_hash = hashlib.sha256(file_bytes).hexdigest()

            # ------------------------------------------------------------------
            # 1. PDF DOCUMENT PIPELINE (Page-by-page split with 4-layer inspection)
            # ------------------------------------------------------------------
            if suffix == ".pdf":
                doc = fitz.open(stream=file_bytes, filetype="pdf")
                total_pages = len(doc)

                for page_idx in range(total_pages):
                    page = doc[page_idx]
                    analysis = analyze_pdf_page(page)

                    page_text = ""
                    has_handwriting = False

                    if analysis["needs_vlm"]:
                        # Render 150 DPI image in RAM and send to Qwen2.5-VL
                        img_buf = render_page_image(page, PDF_RENDER_DPI)
                        vlm_out = await vision_transcribe(img_buf, ACADEMIC_VLM_PROMPT)
                        page_text = vlm_out
                        has_handwriting = analysis["is_scanned"]
                    else:
                        # Direct clean text extraction
                        page_text = analysis["raw_text"]

                    if not page_text.strip():
                        page_text = f"[Empty page or graphical header on page {page_idx+1}]"

                    # Generate Vector
                    vector = await get_embedding(page_text)
                    point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{file_path}_p{page_idx+1}_{file_hash[:8]}"))

                    staged_points.append(
                        qmodels.PointStruct(
                            id=point_id,
                            vector=vector,
                            payload={
                                "file_path": file_path_str,
                                "file_name": file_name,
                                "file_hash": file_hash,
                                "document_type": "handwritten_scanned_pdf" if has_handwriting else "digital_pdf",
                                "page_number": page_idx + 1,
                                "total_pages": total_pages,
                                "has_handwriting": has_handwriting,
                                "tags": [t.strip() for t in tags.split(",") if t.strip()] if tags else [],
                                "content_text": page_text,
                                "indexed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                            }
                        )
                    )

            # ------------------------------------------------------------------
            # 2. STANDALONE IMAGE PIPELINE (Vision AI @ 150 DPI)
            # ------------------------------------------------------------------
            elif suffix in [".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"]:
                normalized_img = normalize_standalone_image(file_bytes, PDF_RENDER_DPI)
                image_desc = await vision_transcribe(normalized_img, ACADEMIC_VLM_PROMPT)

                vector = await get_embedding(image_desc)
                point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{file_path}_{file_hash[:8]}"))

                staged_points.append(
                    qmodels.PointStruct(
                        id=point_id,
                        vector=vector,
                        payload={
                            "file_path": file_path_str,
                            "file_name": file_name,
                            "file_hash": file_hash,
                            "document_type": "image",
                            "tags": [t.strip() for t in tags.split(",") if t.strip()] if tags else [],
                            "content_text": image_desc,
                            "indexed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                        }
                    )
                )

            # ------------------------------------------------------------------
            # 3. AUDIO / SPEECH PIPELINE (Whisper STT Transcription)
            # ------------------------------------------------------------------
            elif suffix in [".mp3", ".wav", ".m4a", ".ogg", ".flac"]:
                transcript = await audio_transcribe(file_bytes, file_name)
                vector = await get_embedding(transcript)
                point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{file_path}_{file_hash[:8]}"))

                staged_points.append(
                    qmodels.PointStruct(
                        id=point_id,
                        vector=vector,
                        payload={
                            "file_path": file_path_str,
                            "file_name": file_name,
                            "file_hash": file_hash,
                            "document_type": "audio_recording",
                            "tags": [t.strip() for t in tags.split(",") if t.strip()] if tags else [],
                            "content_text": transcript,
                            "indexed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                        }
                    )
                )

            # ------------------------------------------------------------------
            # 4. PLAIN TEXT / CODE / MARKDOWN PIPELINE
            # ------------------------------------------------------------------
            else:
                raw_text = file_bytes.decode("utf-8", errors="replace")
                # Chunking logic for long scripts / documents (~1000 tokens / 3000 chars per chunk)
                chunk_size = 3000
                chunks = [raw_text[i:i+chunk_size] for i in range(0, len(raw_text), chunk_size - 200)] or [raw_text]

                for c_idx, chunk in enumerate(chunks):
                    vector = await get_embedding(chunk)
                    point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{file_path}_c{c_idx}_{file_hash[:8]}"))

                    staged_points.append(
                        qmodels.PointStruct(
                            id=point_id,
                            vector=vector,
                            payload={
                                "file_path": file_path_str,
                                "file_name": file_name,
                                "file_hash": file_hash,
                                "document_type": "code_or_text",
                                "chunk_id": c_idx + 1,
                                "total_chunks": len(chunks),
                                "tags": [t.strip() for t in tags.split(",") if t.strip()] if tags else [],
                                "content_text": chunk,
                                "indexed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                            }
                        )
                    )

            # ------------------------------------------------------------------
            # 5. ATOMIC COMMIT TO QDRANT
            # ------------------------------------------------------------------
            # First, clean up any previous vectors for this file
            qdrant_client.delete(
                collection_name=collection,
                points_selector=qmodels.FilterSelector(
                    filter=qmodels.Filter(
                        must=[
                            qmodels.FieldCondition(
                                key="file_path",
                                match=qmodels.MatchValue(value=file_path_str)
                            )
                        ]
                    )
                )
            )

            # Upsert new batch
            qdrant_client.upsert(
                collection_name=collection,
                points=staged_points
            )

            duration_s = time.time() - t0
            return (
                f"✅ **Successfully Indexed:** `{file_name}` ({file_size_kb:.1f} KB)\n"
                f"- **Collection:** `{collection}`\n"
                f"- **Vectors Created:** `{len(staged_points)}`\n"
                f"- **Processing Time:** `{duration_s:.2f}s`\n"
                f"- **Content Hash (SHA-256):** `{file_hash[:12]}...`"
            )

        except Exception as e:
            return f"❌ **Indexing Failed for `{file_name}`:** {str(e)} (Aborted; no partial vectors committed)."

@mcp.tool()
async def delete_file_from_knowledge(file_path: str, collection: str = DEFAULT_COLLECTION) -> str:
    """
    Removes all vectors and chunks associated with a specific file from Qdrant.
    
    Args:
        file_path: Absolute or workspace path to the file to delete.
        collection: Qdrant collection name (default: 'workspace').
    """
    ensure_collection(collection)
    resolved_path = str(Path(file_path).resolve())
    try:
        qdrant_client.delete(
            collection_name=collection,
            points_selector=qmodels.FilterSelector(
                filter=qmodels.Filter(
                    must=[
                        qmodels.FieldCondition(
                            key="file_path",
                            match=qmodels.MatchValue(value=resolved_path)
                        )
                    ]
                )
            )
        )
        return f"Successfully removed `{file_path}` vectors from collection `{collection}`."
    except Exception as e:
        return f"Error deleting `{file_path}`: {str(e)}"

@mcp.tool()
async def query_knowledge_graph(cypher_query: str) -> str:
    """
    Executes a Cypher query on the Neo4j Knowledge Graph to traverse entity relationships.
    
    Args:
        cypher_query: The Cypher query string to execute against the Neo4j database.
    """
    from neo4j import GraphDatabase
    try:
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
        with driver.session() as session:
            result = session.run(cypher_query)
            records = [record.data() for record in result]
        driver.close()
        return f"### Knowledge Graph Results ({len(records)} rows)\n```json\n{json.dumps(records, indent=2)}\n```"
    except Exception as e:
        return f"Knowledge Graph Error: {str(e)}"

# ==============================================================================
# MEM0 EPISODIC & CONVERSATIONAL MEMORY TOOLS
# User context, facts, agent preferences, and graph-backed memory
# ==============================================================================

async def call_mem0(method: str, path: str, json_data: Optional[dict] = None, params: Optional[dict] = None) -> httpx.Response:
    """Robust internal caller for Mem0 API, supporting both /memories and /v1/memories."""
    headers = {}
    if MEM0_API_KEY:
        headers["Authorization"] = f"Bearer {MEM0_API_KEY}"
        headers["X-API-Key"] = MEM0_API_KEY

    clean_path = "/" + path.lstrip("/")
    base_url = MEM0_API_URL.rstrip("/")
    url = f"{base_url}{clean_path}"

    try:
        resp = await http_client.request(method, url, json=json_data, params=params, headers=headers, timeout=15.0)
        # If 404, toggle /v1 prefix as fallback
        if resp.status_code == 404:
            if clean_path.startswith("/v1/"):
                fallback_path = clean_path.replace("/v1/", "/", 1)
            else:
                fallback_path = f"/v1{clean_path}"
            fallback_url = f"{base_url}{fallback_path}"
            resp_fallback = await http_client.request(method, fallback_url, json=json_data, params=params, headers=headers, timeout=15.0)
            if resp_fallback.status_code != 404:
                return resp_fallback
        return resp
    except Exception as e:
        raise e

@mcp.tool()
async def search_memory(query: str, user_id: str = "default", agent_id: Optional[str] = None, limit: int = 5) -> str:
    """
    Searches Mem0 episodic conversational memory for user context, past discussions, facts, and preferences.
    
    Args:
        query: Natural language search query to find relevant memories.
        user_id: ID of the user whose memories to search (default: 'default').
        agent_id: Optional agent ID filter.
        limit: Maximum number of relevant memories to retrieve (default: 5).
    """
    try:
        payload = {"query": query, "user_id": user_id, "limit": limit}
        if agent_id:
            payload["agent_id"] = agent_id

        resp = await call_mem0("POST", "/memories/search", json_data=payload)
        if resp.status_code == 200:
            data = resp.json()
            mem_list = data if isinstance(data, list) else data.get("results", data.get("memories", []))
            if not mem_list:
                return f"No memories found matching '{query}' for user `{user_id}`."

            out = [f"### 🧠 Mem0 Search Results for `{user_id}` ({len(mem_list)} memories found)\n"]
            for idx, m in enumerate(mem_list, 1):
                m_id = m.get("id", "N/A")
                text = m.get("memory") or m.get("text") or m.get("content") or json.dumps(m)
                score = m.get("score")
                score_str = f" `[Score: {score:.3f}]`" if score is not None else ""
                created = m.get("created_at") or m.get("timestamp") or ""
                created_str = f" *({created})*" if created else ""
                out.append(f"{idx}. **{text}**{score_str}{created_str} *(ID: `{m_id}`)*")
            return "\n".join(out)
        return f"Mem0 search returned status {resp.status_code}: {resp.text}"
    except Exception as e:
        return f"Mem0 Memory Search Error: {str(e)}"

@mcp.tool()
async def add_memory(content: str, user_id: str = "default", agent_id: Optional[str] = None, metadata: Optional[str] = None) -> str:
    """
    Stores a new memory, user preference, or fact into Mem0 long-term memory.
    Mem0 automatically extracts entities and relationships, storing them in Qdrant vector store and Neo4j graph.
    
    Args:
        content: The text content, conversation message, or statement to remember (e.g. 'MZ prefers dark mode in all UI tools').
        user_id: The ID of the user to associate with this memory (default: 'default').
        agent_id: Optional agent ID (e.g. 'hermes').
        metadata: Optional JSON string or comma-separated tags to attach to the memory.
    """
    try:
        parsed_meta = None
        if metadata:
            try:
                parsed_meta = json.loads(metadata)
            except Exception:
                parsed_meta = {"tags": [t.strip() for t in metadata.split(",") if t.strip()]}

        payload = {
            "messages": [{"role": "user", "content": content}],
            "user_id": user_id
        }
        if agent_id:
            payload["agent_id"] = agent_id
        if parsed_meta:
            payload["metadata"] = parsed_meta

        resp = await call_mem0("POST", "/memories", json_data=payload)
        if resp.status_code in (200, 201):
            data = resp.json()
            return f"✅ **Memory Stored Successfully in Mem0:**\n- **User:** `{user_id}`\n- **Agent:** `{agent_id or 'none'}`\n- **Content:** {content}\n- **Response:**\n```json\n{json.dumps(data, indent=2)}\n```"
        return f"Mem0 store returned status {resp.status_code}: {resp.text}"
    except Exception as e:
        return f"Mem0 Add Memory Error: {str(e)}"

@mcp.tool()
async def get_memories(user_id: str = "default", agent_id: Optional[str] = None, limit: int = 20) -> str:
    """
    Retrieves stored long-term memories for a specific user or agent from Mem0.
    
    Args:
        user_id: The ID of the user whose memories to retrieve (default: 'default').
        agent_id: Optional agent ID filter.
        limit: Maximum number of memories to return (default: 20).
    """
    try:
        params = {"user_id": user_id, "limit": limit}
        if agent_id:
            params["agent_id"] = agent_id

        resp = await call_mem0("GET", "/memories", params=params)
        if resp.status_code == 200:
            data = resp.json()
            mem_list = data if isinstance(data, list) else data.get("results", data.get("memories", []))
            if not mem_list:
                return f"No memories found for user `{user_id}`."
            out = [f"### 🧠 Mem0 Stored Memories for `{user_id}` ({len(mem_list)} memories)\n"]
            for idx, m in enumerate(mem_list, 1):
                m_id = m.get("id", "N/A")
                text = m.get("memory") or m.get("text") or m.get("content") or json.dumps(m)
                created = m.get("created_at") or m.get("timestamp") or ""
                created_str = f" *({created})*" if created else ""
                out.append(f"{idx}. **{text}**{created_str} *(ID: `{m_id}`)*")
            return "\n".join(out)
        return f"Mem0 get memories returned status {resp.status_code}: {resp.text}"
    except Exception as e:
        return f"Mem0 Get Memories Error: {str(e)}"

@mcp.tool()
async def delete_memory(memory_id: str) -> str:
    """
    Deletes a specific memory entry from Mem0 by its memory ID.
    
    Args:
        memory_id: Unique UUID or identifier of the memory to delete.
    """
    try:
        resp = await call_mem0("DELETE", f"/memories/{memory_id}")
        if resp.status_code in (200, 204):
            return f"🗑️ Successfully deleted memory `{memory_id}` from Mem0."
        return f"Mem0 delete memory returned status {resp.status_code}: {resp.text}"
    except Exception as e:
        return f"Mem0 Delete Memory Error: {str(e)}"

@mcp.tool()
async def list_collections() -> str:
    """Lists all available Qdrant knowledge collections and point counts."""
    try:
        collections = qdrant_client.get_collections().collections
        out = ["### 📚 Available Knowledge Collections\n"]
        for c in collections:
            info = qdrant_client.get_collection(c.name)
            out.append(f"- **`{c.name}`**: `{info.points_count}` vectors (Dimension: `{info.config.params.vectors.size}`, Metric: `{info.config.params.vectors.distance}`)")
        return "\n".join(out)
    except Exception as e:
        return f"Error listing collections: {str(e)}"

# ==============================================================================
# OBSIDIAN KNOWLEDGE VAULT TOOLS (Read, Write, Append, Search, Index)
# Direct synchronization with Ignis Web UI (/vault)
# ==============================================================================

@mcp.tool()
async def list_notes(directory: str = "") -> str:
    """
    Lists all Markdown notes (.md) stored in the Obsidian vault (or within a specified subfolder).
    
    Args:
        directory: Optional relative subfolder inside the vault to inspect (e.g., 'Lectures' or 'Research').
    """
    try:
        target_dir = get_vault_safe_path(directory) if directory else OBSIDIAN_VAULT_PATH
        if not target_dir.exists() or not target_dir.is_dir():
            return f"Directory `{directory}` does not exist in Obsidian vault."
        
        notes = []
        for p in sorted(target_dir.rglob("*.md")):
            rel = p.relative_to(OBSIDIAN_VAULT_PATH).as_posix()
            notes.append(f"- 📄 `{rel}` ({p.stat().st_size / 1024:.1f} KB)")
            
        if not notes:
            return f"No markdown notes found in vault directory `{directory or '/'}`."
            
        return f"### 📓 Obsidian Vault Notes ({len(notes)} total in `{directory or '/'}`)\n" + "\n".join(notes)
    except Exception as e:
        return f"Error listing vault notes: {str(e)}"

@mcp.tool()
async def read_note(path: str) -> str:
    """
    Reads the full Markdown content of a specific note from the Obsidian vault.
    
    Args:
        path: Relative path to the note inside the vault (e.g., 'Research/Quantum.md' or 'QuickNotes').
    """
    try:
        target = get_vault_safe_path(path)
        if not target.suffix:
            target = target.with_suffix(".md")
        if not target.exists() or not target.is_file():
            return f"Error: Note `{path}` does not exist in the Obsidian vault."
        content = await asyncio.to_thread(target.read_text, encoding="utf-8")
        rel_path = target.relative_to(OBSIDIAN_VAULT_PATH).as_posix()
        return f"### 📄 `{rel_path}`\n\n```markdown\n{content}\n```"
    except Exception as e:
        return f"Error reading note `{path}`: {str(e)}"

@mcp.tool()
async def write_note(path: str, content: str) -> str:
    """
    Creates or overwrites a Markdown note in the Obsidian vault. Automatically creates any parent directories.
    Modifications immediately reflect in the Ignis web browser UI.
    
    Args:
        path: Relative path to the note inside the vault (e.g., 'Lectures/Week1.md').
        content: The Markdown content to write.
    """
    try:
        target = get_vault_safe_path(path)
        if not target.suffix:
            target = target.with_suffix(".md")
        target.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(target.write_text, content, encoding="utf-8")
        rel_path = target.relative_to(OBSIDIAN_VAULT_PATH).as_posix()
        return f"✅ Successfully written note `{rel_path}` to Obsidian vault ({len(content)} characters)."
    except Exception as e:
        return f"Error writing note `{path}`: {str(e)}"

@mcp.tool()
async def append_note(path: str, content: str) -> str:
    """
    Appends Markdown content to an existing note in the Obsidian vault (or creates it if it doesn't exist).
    
    Args:
        path: Relative path to the note inside the vault (e.g., 'Daily/Log.md').
        content: The Markdown text to append.
    """
    try:
        target = get_vault_safe_path(path)
        if not target.suffix:
            target = target.with_suffix(".md")
        target.parent.mkdir(parents=True, exist_ok=True)
        
        def _do_append():
            with open(target, "a", encoding="utf-8") as f:
                f.write("\n" + content)
                
        await asyncio.to_thread(_do_append)
        rel_path = target.relative_to(OBSIDIAN_VAULT_PATH).as_posix()
        return f"✅ Successfully appended content to `{rel_path}` in Obsidian vault."
    except Exception as e:
        return f"Error appending to note `{path}`: {str(e)}"

@mcp.tool()
async def search_notes(query: str, max_results: int = 10) -> str:
    """
    Performs full-text keyword/phrase search across all Markdown notes in the Obsidian vault,
    returning matching note paths and line excerpts.
    
    Args:
        query: The search term or phrase to locate.
        max_results: Maximum number of matching notes to return (default: 10).
    """
    try:
        if not OBSIDIAN_VAULT_PATH.exists():
            return "Obsidian vault path does not exist."
            
        q_lower = query.lower()
        
        def _scan_vault():
            matches = []
            for p in sorted(OBSIDIAN_VAULT_PATH.rglob("*.md")):
                try:
                    text = p.read_text(encoding="utf-8", errors="ignore")
                    if q_lower in text.lower():
                        line_snippets = []
                        for i, line in enumerate(text.splitlines(), start=1):
                            if q_lower in line.lower():
                                line_snippets.append(f"  - **L{i}**: `{line.strip()}`")
                                if len(line_snippets) >= 3:
                                    break
                        rel = p.relative_to(OBSIDIAN_VAULT_PATH).as_posix()
                        matches.append(f"#### 📄 `{rel}`\n" + "\n".join(line_snippets))
                        if len(matches) >= max_results:
                            break
                except Exception:
                    continue
            return matches
            
        matches = await asyncio.to_thread(_scan_vault)
        if not matches:
            return f"No matches found for query: `{query}` across Obsidian vault notes."
            
        return f"### 🔍 Obsidian Notes Search Results for `{query}` ({len(matches)} matching files)\n\n" + "\n\n".join(matches)
    except Exception as e:
        return f"Error searching vault notes: {str(e)}"

@mcp.tool()
async def delete_note(path: str) -> str:
    """
    Deletes a Markdown note from the Obsidian vault.
    
    Args:
        path: Relative path to the note to delete (e.g., 'OldNotes/Draft.md').
    """
    try:
        target = get_vault_safe_path(path)
        if not target.suffix:
            target = target.with_suffix(".md")
        if not target.exists() or not target.is_file():
            return f"Error: Note `{path}` does not exist in Obsidian vault."
        target.unlink()
        rel_path = target.relative_to(OBSIDIAN_VAULT_PATH).as_posix()
        return f"🗑️ Successfully deleted note `{rel_path}` from Obsidian vault."
    except Exception as e:
        return f"Error deleting note `{path}`: {str(e)}"

@mcp.tool()
async def index_note_to_knowledge(
    path: str,
    collection: str = "notes",
    tags: str = "obsidian,vault"
) -> str:
    """
    Extracts an Obsidian note and indexes it into Qdrant vector database for hybrid semantic search.
    Enables searching Obsidian notes alongside PDFs, documentation, and agent memories.
    
    Args:
        path: Relative path to the note inside the vault (e.g., 'Research/AI_Paper.md').
        collection: Qdrant collection to store vectors in (default: 'notes').
        tags: Optional categorization tags (default: 'obsidian,vault').
    """
    try:
        target = get_vault_safe_path(path)
        if not target.suffix:
            target = target.with_suffix(".md")
        if not target.exists() or not target.is_file():
            return f"Error: Note `{path}` not found in Obsidian vault."
            
        return await index_file(file_path=str(target), collection=collection, tags=tags)
    except Exception as e:
        return f"Error indexing note `{path}` to knowledge: {str(e)}"

@mcp.tool()
async def index_vault_to_knowledge(
    directory: str = "",
    collection: str = "notes",
    tags: str = "obsidian,vault"
) -> str:
    """
    Indexes all Markdown notes from the Obsidian vault (or a specified subfolder) into Qdrant vector database.
    Allows batch vectorization of notes for semantic retrieval across the entire knowledge base.
    
    Args:
        directory: Optional relative subfolder inside the vault to index (default: entire vault).
        collection: Qdrant collection to store vectors in (default: 'notes').
        tags: Optional categorization tags (default: 'obsidian,vault').
    """
    try:
        target_dir = get_vault_safe_path(directory) if directory else OBSIDIAN_VAULT_PATH
        if not target_dir.exists() or not target_dir.is_dir():
            return f"Directory `{directory}` does not exist in Obsidian vault."

        notes_files = sorted(target_dir.rglob("*.md"))
        if not notes_files:
            return f"No markdown notes found to index in `{directory or '/'}`."

        successful = 0
        failed = []
        for p in notes_files:
            rel = p.relative_to(OBSIDIAN_VAULT_PATH).as_posix()
            try:
                res = await index_file(file_path=str(p), collection=collection, tags=tags)
                if "Successfully Indexed" in res:
                    successful += 1
                else:
                    failed.append(f"{rel}: {res}")
            except Exception as e:
                failed.append(f"{rel}: {str(e)}")

        out = [
            f"### 📚 Obsidian Vault Batch Indexing Complete",
            f"- **Target Directory:** `{directory or '/'}`",
            f"- **Target Collection:** `{collection}`",
            f"- **Total Notes Processed:** `{len(notes_files)}`",
            f"- **Successfully Indexed:** `{successful}`",
        ]
        if failed:
            out.append(f"- **Failed Notes ({len(failed)}):**\n  - " + "\n  - ".join(failed[:10]))
            if len(failed) > 10:
                out.append(f"  *... and {len(failed) - 10} more*")
        return "\n".join(out)
    except Exception as e:
        return f"Error batch indexing Obsidian vault: {str(e)}"

# ==============================================================================
# FASTAPI DUAL INTERFACE (REST Endpoints + MCP SSE Routes)
# ==============================================================================

app = FastAPI(title="Homelab AI Knowledge Hub & MCP Server", version="1.0.0")

class APIKeyAuthASGIMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        if KNOWLEDGE_MCP_API_KEY and scope.get("path", "") not in ["/health", "/docs", "/openapi.json"]:
            headers = dict(scope.get("headers", []))
            auth_header = headers.get(b"authorization", b"").decode("utf-8", errors="ignore")
            api_key_header = headers.get(b"x-api-key", b"").decode("utf-8", errors="ignore")

            # Check query string for ?api_key= or ?token=
            query_str = scope.get("query_string", b"").decode("utf-8", errors="ignore")
            query_params = urllib.parse.parse_qs(query_str)
            query_token = (query_params.get("api_key") or query_params.get("token") or [""])[0]

            candidates = []
            if "Bearer " in auth_header:
                candidates.append(auth_header.replace("Bearer ", "").strip())
            elif auth_header:
                candidates.append(auth_header.strip())
            if api_key_header:
                candidates.append(api_key_header.strip())
            if query_token:
                candidates.append(query_token.strip())

            # Find first candidate that is not an unexpanded template placeholder
            token = ""
            for cand in candidates:
                if cand and not cand.startswith("${"):
                    token = cand
                    break

            if not token or not secrets.compare_digest(token, KNOWLEDGE_MCP_API_KEY):
                await send({
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [(b"content-type", b"application/json")]
                })
                await send({
                    "type": "http.response.body",
                    "body": b'{"error": "Unauthorized: Invalid or missing Knowledge MCP API key."}'
                })
                return

        return await self.app(scope, receive, send)

app.add_middleware(APIKeyAuthASGIMiddleware)

class SearchRequest(BaseModel):
    query: str
    collection: Optional[str] = DEFAULT_COLLECTION
    limit: Optional[int] = 5
    min_score: Optional[float] = 0.50

class IndexFileRequest(BaseModel):
    file_path: str
    collection: Optional[str] = DEFAULT_COLLECTION
    tags: Optional[List[str]] = None
    file_content_base64: Optional[str] = None

class DeleteFileRequest(BaseModel):
    file_path: str
    collection: Optional[str] = DEFAULT_COLLECTION

@app.get("/health")
async def health():
    vault_accessible = OBSIDIAN_VAULT_PATH.is_dir()
    notes_count = len(list(OBSIDIAN_VAULT_PATH.rglob("*.md"))) if vault_accessible else 0

    qdrant_ok = False
    try:
        qdrant_client.get_collections()
        qdrant_ok = True
    except Exception:
        pass

    mem0_ok = False
    try:
        resp = await http_client.get(f"{MEM0_API_URL}/openapi.json", timeout=2.0)
        if resp.status_code == 200:
            mem0_ok = True
    except Exception:
        pass

    return {
        "status": "ok",
        "pillars": {
            "qdrant": {
                "status": "healthy" if qdrant_ok else "unreachable",
                "host": f"{QDRANT_HOST}:{QDRANT_PORT}",
                "workspace_collection": DEFAULT_COLLECTION
            },
            "mem0": {
                "status": "healthy" if mem0_ok else "unreachable",
                "api_url": MEM0_API_URL
            },
            "obsidian": {
                "status": "accessible" if vault_accessible else "missing",
                "vault_path": str(OBSIDIAN_VAULT_PATH),
                "notes_count": notes_count
            }
        },
        "models": {
            "embedding": EMBEDDING_PRIMARY_URL,
            "vision": VISION_PRIMARY_URL
        },
        "mcp_sse_endpoint": "/mcp/sse"
    }

@app.get("/collections")
async def rest_collections():
    res = await list_collections()
    return {"result": res}

@app.post("/search")
async def rest_search(req: SearchRequest):
    res = await search_knowledge(req.query, req.collection or DEFAULT_COLLECTION, req.limit or 5, req.min_score or 0.50)
    return {"result": res}

@app.post("/index-file")
async def rest_index_file(req: IndexFileRequest):
    tags_str = ",".join(req.tags) if req.tags else ""
    res = await index_file(req.file_path, req.collection or DEFAULT_COLLECTION, tags_str, req.file_content_base64)
    return {"result": res}

@app.delete("/files")
async def rest_delete_file(file_path: str, collection: str = DEFAULT_COLLECTION):
    res = await delete_file_from_knowledge(file_path, collection)
    return {"result": res}

@app.post("/delete-file")
@app.delete("/delete-file")
async def rest_post_delete_file(req: DeleteFileRequest):
    res = await delete_file_from_knowledge(req.file_path, req.collection or DEFAULT_COLLECTION)
    return {"result": res}

# --- Mem0 Conversational Memory REST Endpoints ---
class SearchMemoryRequest(BaseModel):
    query: str
    user_id: Optional[str] = "default"
    agent_id: Optional[str] = None
    limit: Optional[int] = 5

class AddMemoryRequest(BaseModel):
    content: str
    user_id: Optional[str] = "default"
    agent_id: Optional[str] = None
    metadata: Optional[str] = None

@app.post("/memory/search")
async def rest_search_memory(req: SearchMemoryRequest):
    res = await search_memory(req.query, req.user_id or "default", req.agent_id, req.limit or 5)
    return {"result": res}

@app.post("/memory")
async def rest_add_memory(req: AddMemoryRequest):
    res = await add_memory(req.content, req.user_id or "default", req.agent_id, req.metadata)
    return {"result": res}

@app.get("/memory")
async def rest_get_memories(user_id: str = "default", agent_id: Optional[str] = None, limit: int = 20):
    res = await get_memories(user_id, agent_id, limit)
    return {"result": res}

@app.delete("/memory/{memory_id}")
async def rest_delete_memory(memory_id: str):
    res = await delete_memory(memory_id)
    return {"result": res}

# --- Obsidian Notes REST Endpoints ---
class WriteNoteRequest(BaseModel):
    path: str
    content: str

class AppendNoteRequest(BaseModel):
    path: str
    content: str

class SearchNoteRequest(BaseModel):
    query: str
    max_results: Optional[int] = 10

class IndexNoteRequest(BaseModel):
    path: str
    collection: Optional[str] = "notes"
    tags: Optional[str] = "obsidian,vault"

class IndexVaultRequest(BaseModel):
    directory: Optional[str] = ""
    collection: Optional[str] = "notes"
    tags: Optional[str] = "obsidian,vault"

@app.get("/notes")
async def rest_list_notes(directory: str = ""):
    res = await list_notes(directory)
    return {"result": res}

@app.get("/notes/{path:path}")
async def rest_read_note(path: str):
    res = await read_note(path)
    return {"result": res}

@app.post("/notes")
async def rest_write_note(req: WriteNoteRequest):
    res = await write_note(req.path, req.content)
    return {"result": res}

@app.post("/notes/append")
async def rest_append_note(req: AppendNoteRequest):
    res = await append_note(req.path, req.content)
    return {"result": res}

@app.post("/notes/search")
async def rest_search_notes(req: SearchNoteRequest):
    res = await search_notes(req.query, req.max_results or 10)
    return {"result": res}

@app.delete("/notes/{path:path}")
async def rest_delete_note(path: str):
    res = await delete_note(path)
    return {"result": res}

@app.post("/notes/index")
async def rest_index_note(req: IndexNoteRequest):
    res = await index_note_to_knowledge(req.path, req.collection or "notes", req.tags or "obsidian,vault")
    return {"result": res}

@app.post("/notes/index-all")
async def rest_index_vault(req: IndexVaultRequest):
    res = await index_vault_to_knowledge(req.directory or "", req.collection or "notes", req.tags or "obsidian,vault")
    return {"result": res}

# Mount MCP SSE application
try:
    if TransportSecuritySettings:
        ts_settings = TransportSecuritySettings(
            enable_dns_rebinding_protection=False,
            allowed_hosts=["*"],
            allowed_origins=["*"]
        )
        sse_app = mcp.sse_app(transport_security=ts_settings)
    else:
        sse_app = mcp.sse_app()

    app.mount("/mcp", sse_app)

    @app.api_route("/sse", methods=["GET"])
    async def sse_root(request: Request):
        return await sse_app(request.scope, request.receive, request._send)

    @app.api_route("/messages", methods=["GET", "POST"])
    @app.api_route("/messages/{path:path}", methods=["GET", "POST"])
    async def sse_messages_root(request: Request, path: str = ""):
        return await sse_app(request.scope, request.receive, request._send)
except Exception as e:
    print("Notice: Mounting SSE route:", e)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8095)
