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
EMBEDDING_PRIMARY_URL = os.environ.get("EMBEDDING_PRIMARY_URL", "http://100.64.0.3:8089/embed")
EMBEDDING_PRIMARY_KEY = os.environ.get("EMBEDDING_PRIMARY_KEY", "sk-homelab-tei-secure-key")
EMBEDDING_FALLBACK_URL = os.environ.get("EMBEDDING_FALLBACK_URL", "http://litellm:4000/v1/embeddings")
EMBEDDING_FALLBACK_KEY = os.environ.get("EMBEDDING_FALLBACK_KEY", "")
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "BAAI/bge-m3")

RERANKER_PRIMARY_URL = os.environ.get("RERANKER_PRIMARY_URL", "http://100.64.0.3:8087/rerank")
RERANKER_PRIMARY_KEY = os.environ.get("RERANKER_PRIMARY_KEY", "sk-homelab-tei-secure-key")
RERANKER_FALLBACK_URL = os.environ.get("RERANKER_FALLBACK_URL", "http://litellm:4000/v1/rerank")
RERANKER_FALLBACK_KEY = os.environ.get("RERANKER_FALLBACK_KEY", "")
RERANKER_MODEL = os.environ.get("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3")

VISION_PRIMARY_PROVIDER = os.environ.get("VISION_PRIMARY_PROVIDER", "local")
VISION_PRIMARY_URL = os.environ.get("VISION_PRIMARY_URL", "http://100.64.0.3:11434/api/chat")
VISION_PRIMARY_KEY = os.environ.get("VISION_PRIMARY_KEY", "sk-homelab-ollama-secure-key")
VISION_PRIMARY_MODEL = os.environ.get("VISION_PRIMARY_MODEL", "qwen2.5vl:3b")

VISION_FALLBACK_PROVIDER = os.environ.get("VISION_FALLBACK_PROVIDER", "litellm")
VISION_FALLBACK_URL = os.environ.get("VISION_FALLBACK_URL", "http://litellm:4000/v1/chat/completions")
VISION_FALLBACK_KEY = os.environ.get("VISION_FALLBACK_KEY", "")
VISION_FALLBACK_MODEL = os.environ.get("VISION_FALLBACK_MODEL", "google/gemini-2.0-flash")

AUDIO_PRIMARY_URL = os.environ.get("AUDIO_PRIMARY_URL", "http://100.64.0.3:8086/v1/audio/transcriptions")
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
KNOWLEDGE_MCP_API_KEY = os.environ.get("KNOWLEDGE_MCP_API_KEY", "")

# --- Global Concurrency Guard ---
PIPELINE_SEMAPHORE = asyncio.Semaphore(MAX_CONCURRENT_JOBS)

# --- Clients ---
qdrant_client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT, api_key=QDRANT_API_KEY, timeout=30)
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

    # 2. Fallback to LiteLLM / OpenAI-compatible endpoint
    try:
        headers = {"Authorization": f"Bearer {EMBEDDING_FALLBACK_KEY}"} if EMBEDDING_FALLBACK_KEY else {}
        resp = await http_client.post(
            EMBEDDING_FALLBACK_URL,
            json={"input": [text[:4096]], "model": EMBEDDING_MODEL},
            headers=headers,
            timeout=20.0
        )
        if resp.status_code == 200:
            data = resp.json()
            return data["data"][0]["embedding"]
    except Exception as e:
        raise RuntimeError(f"All embedding providers failed: {str(e)}")

async def rerank_documents(query: str, texts: List[str], top_n: int = 5) -> List[Dict[str, Any]]:
    """Reranks candidate texts using primary TEI -> fallback LiteLLM cross-encoder."""
    if not texts:
        return []

    # 1. Try Primary TEI Reranker with Bearer Token
    try:
        headers = {"Authorization": f"Bearer {RERANKER_PRIMARY_KEY}"} if RERANKER_PRIMARY_KEY else {}
        resp = await http_client.post(
            RERANKER_PRIMARY_URL,
            json={"query": query, "texts": texts, "raw_scores": False},
            headers=headers,
            timeout=15.0
        )
        if resp.status_code == 200:
            results = resp.json()
            return sorted(results, key=lambda x: x.get("score", 0), reverse=True)[:top_n]
    except Exception as e:
        print(f"Warning: Primary Reranker failed ({str(e)[:40]}), trying fallback...")

    # 2. Fallback LiteLLM Rerank
    try:
        headers = {"Authorization": f"Bearer {RERANKER_FALLBACK_KEY}"} if RERANKER_FALLBACK_KEY else {}
        resp = await http_client.post(
            RERANKER_FALLBACK_URL,
            json={"query": query, "documents": texts, "model": RERANKER_MODEL, "top_n": top_n},
            headers=headers,
            timeout=20.0
        )
        if resp.status_code == 200:
            data = resp.json()
            return [{"index": r["index"], "score": r["relevance_score"]} for r in data.get("results", [])]
    except Exception:
        pass

    # Basic fallback if reranker fails entirely
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
    tags: Optional[List[str]] = None
) -> str:
    """
    Ingests, parses, chunks, and indexes any file (PDF page-by-page, images via Vision, audio via STT, code/text) into Qdrant.
    Transactional & atomic per document.
    
    Args:
        file_path: Absolute or workspace path to the file.
        collection: Qdrant collection name (default: 'workspace').
        tags: Optional categorization tags.
    """
    ensure_collection(collection)
    p = Path(file_path)
    if not p.exists() or not p.is_file():
        return f"Error: File '{file_path}' does not exist."

    suffix = p.suffix.lower()
    file_size_kb = p.stat().st_size / 1024
    t0 = time.time()

    async with PIPELINE_SEMAPHORE:
        try:
            staged_points = []
            file_bytes = await asyncio.to_thread(p.read_bytes)
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
                                "file_path": str(p.resolve()),
                                "file_name": p.name,
                                "file_hash": file_hash,
                                "document_type": "handwritten_scanned_pdf" if has_handwriting else "digital_pdf",
                                "page_number": page_idx + 1,
                                "total_pages": total_pages,
                                "has_handwriting": has_handwriting,
                                "tags": tags or [],
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
                            "file_path": str(p.resolve()),
                            "file_name": p.name,
                            "file_hash": file_hash,
                            "document_type": "image",
                            "tags": tags or [],
                            "content_text": image_desc,
                            "indexed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                        }
                    )
                )

            # ------------------------------------------------------------------
            # 3. AUDIO / SPEECH PIPELINE (Whisper STT Transcription)
            # ------------------------------------------------------------------
            elif suffix in [".mp3", ".wav", ".m4a", ".ogg", ".flac"]:
                transcript = await audio_transcribe(file_bytes, p.name)
                vector = await get_embedding(transcript)
                point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{file_path}_{file_hash[:8]}"))

                staged_points.append(
                    qmodels.PointStruct(
                        id=point_id,
                        vector=vector,
                        payload={
                            "file_path": str(p.resolve()),
                            "file_name": p.name,
                            "file_hash": file_hash,
                            "document_type": "audio_recording",
                            "tags": tags or [],
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
                                "file_path": str(p.resolve()),
                                "file_name": p.name,
                                "file_hash": file_hash,
                                "document_type": "code_or_text",
                                "chunk_id": c_idx + 1,
                                "total_chunks": len(chunks),
                                "tags": tags or [],
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
                                match=qmodels.MatchValue(value=str(p.resolve()))
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
                f"✅ **Successfully Indexed:** `{p.name}` ({file_size_kb:.1f} KB)\n"
                f"- **Collection:** `{collection}`\n"
                f"- **Vectors Created:** `{len(staged_points)}`\n"
                f"- **Processing Time:** `{duration_s:.2f}s`\n"
                f"- **Content Hash (SHA-256):** `{file_hash[:12]}...`"
            )

        except Exception as e:
            return f"❌ **Indexing Failed for `{p.name}`:** {str(e)} (Aborted; no partial vectors committed)."

@mcp.tool()
async def delete_file_from_knowledge(file_path: str, collection: str = DEFAULT_COLLECTION) -> str:
    """Removes all vectors and chunks associated with a specific file from Qdrant."""
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
    """Executes a Cypher query on the Neo4j Knowledge Graph to traverse entity relationships."""
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

@mcp.tool()
async def search_memory(query: str, user_id: str = "default") -> str:
    """Queries Mem0 long-term conversational memory for user context and facts."""
    try:
        headers = {"Authorization": f"Bearer {MEM0_API_KEY}"} if MEM0_API_KEY else {}
        resp = await http_client.post(
            f"{MEM0_API_URL}/v1/memories/search",
            json={"query": query, "user_id": user_id},
            headers=headers,
            timeout=10.0
        )
        if resp.status_code == 200:
            data = resp.json()
            return f"### 🧠 Episodic Memories for `{user_id}`\n```json\n{json.dumps(data, indent=2)}\n```"
        return f"Mem0 responded with status {resp.status_code}: {resp.text}"
    except Exception as e:
        return f"Mem0 Memory Search Error: {str(e)}"

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
# FASTAPI DUAL INTERFACE (REST Endpoints + MCP SSE Routes)
# ==============================================================================

app = FastAPI(title="Homelab AI Knowledge Hub & MCP Server", version="1.0.0")

@app.middleware("http")
async def api_key_auth_middleware(request: Request, call_next):
    if KNOWLEDGE_MCP_API_KEY and request.url.path not in ["/health", "/docs", "/openapi.json"]:
        auth_header = request.headers.get("Authorization", "")
        api_key_header = request.headers.get("X-API-Key", "")
        token = auth_header.replace("Bearer ", "").strip() if "Bearer " in auth_header else api_key_header
        if token != KNOWLEDGE_MCP_API_KEY:
            return JSONResponse(status_code=401, content={"error": "Unauthorized: Invalid or missing API key."})
    return await call_next(request)

class SearchRequest(BaseModel):
    query: str
    collection: Optional[str] = DEFAULT_COLLECTION
    limit: Optional[int] = 5
    min_score: Optional[float] = 0.50

class IndexFileRequest(BaseModel):
    file_path: str
    collection: Optional[str] = DEFAULT_COLLECTION
    tags: Optional[List[str]] = None

@app.get("/health")
def health():
    return {
        "status": "ok",
        "qdrant_host": QDRANT_HOST,
        "embedding_primary": EMBEDDING_PRIMARY_URL,
        "vision_primary": VISION_PRIMARY_URL,
        "mcp_sse_endpoint": "/sse"
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
    res = await index_file(req.file_path, req.collection or DEFAULT_COLLECTION, req.tags)
    return {"result": res}

@app.delete("/files")
async def rest_delete_file(file_path: str, collection: str = DEFAULT_COLLECTION):
    res = await delete_file_from_knowledge(file_path, collection)
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

    @app.get("/sse")
    async def sse_root(request: Request):
        return await sse_app(request.scope, request.receive, request._send)
except Exception as e:
    print("Notice: Mounting SSE route:", e)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8095)
