> ### 🌐 [Homelab Sovereign Cluster Architecture](https://github.com/medzarka/homelab-nodes)
> This repository is a modular component of the **Homelab Sovereign Multi-Node Cluster** — an enterprise-grade, privacy-first, self-hosted infrastructure spanning cloud VPS, on-premise compute servers, and edge ARM nodes.
> 
> * **Zero-Trust Network**: Multi-host WireGuard mesh interconnect via **Tailscale** with strict **Firewalld** zoning (`iptables: false`).
> * **Unified Identity & Ingress**: Centralized reverse proxy via **Traefik v3**, **Authelia SSO (2FA)**, and **LLDAP Directory**.
> * **Cluster Orchestration & GitOps**: High-availability **Docker Swarm** managed declaratively via **Arcane Cockpit**.
> * **End-to-End Observability**: Centralized portal (**Homepage**), metrics (**Beszel**), real-time logs (**Dozzle**), and uptime monitoring (**Uptime Kuma**).
> * **Sovereign Local AI & Compute**: Distributed inference (**LiteLLM**, **Ollama**, **Qdrant**, **Mem0**, **Hermes Agents**).
> * **Private Cloud & Storage**: Encrypted data synchronization, automated backups, and multi-cloud mirrors.

---

# 🧠 Homelab Unified AI Knowledge, Memory & Notes Hub

A sovereign, high-performance **Multi-Modal AI Knowledge & Long-Term Memory Engine** designed for **Hermes Agent**, **Open-WebUI**, **Claude**, and **Autonomous Coding Agents**.

The platform provides a high-performance Qdrant-based **Model Context Protocol (MCP)** server specifically for document ingestion, multimodal parsing, and dense semantic retrieval (`BAAI/bge-m3`, `bge-reranker-v2-m3`).
Note: Mem0 (conversational memory) and Neo4j (graph memory) are deployed alongside Qdrant, but Hermes interacts with Mem0 directly via REST rather than through this MCP.

---

## 🌟 Key Capabilities & Architectural Highlights

1. **Dedicated Qdrant MCP Integration**:
   - A single MCP connection (`http://knowledge-mcp:8095/mcp/sse`) provides AI agents with high-performance semantic search and document ingestion tools.
2. **4-Layer Smart PDF & Document Inspection Engine**:
   - Analyzes document AST in RAM ($< 0.5$ ms) before deciding whether to call Vision AI.
   - **Layer 1 (Raster Bitmaps)**: Detects embedded images, photos, and figures.
   - **Layer 2 (Vector Graphics)**: Identifies diagrams, flowcharts, and plots (`len(drawings) > 5`).
   - **Layer 3 (Math & LaTeX Detection)**: Flags LaTeX equations, math fonts (`CMSY10`, `MathJax`), and formulas.
   - **Layer 4 (Scanned Page Detection)**: Identifies scanned papers and handwritten exams ($0$ selectable text + image).
4. **150 DPI In-Memory Normalized Rendering**:
   - Visual pages and handwritten answer sheets are rendered in RAM at **150 DPI** (`PDF_RENDER_DPI=150`) for sharp OCR/math transcription with minimum CPU memory footprint.
5. **Transactional All-or-Nothing Ingestion**:
   - If any page in a multi-page document fails during parsing, the transaction aborts cleanly with **0 partial/broken vectors committed to Qdrant**.
6. **Strict CPU Concurrency Guard**:
   - Limits parallel inference to `MAX_CONCURRENT_INDEXING_JOBS=1` to prevent CPU core starvation on compute nodes.
7. **Transparent Primary & Fallback Failover**:
   - Automatically fails over from local compute models to LiteLLM / external providers if a service is busy or offline (respecting the 1024-dimension vector constraint).

---

## 🏗️ Architecture & Topology Diagram

```
                                [ Browser / User ]
                                        │
                            (HTTPS + Authelia 2FA)
                                        ▼
                        ┌───────────────────────────────┐
                        ┌───────────────────────────────────────────────────────────────────────────────────────────┐
                        ┌───────────────────────────────┐
                        │  Knowledge Hub MCP (:8095)    │ ◄──── [ Hermes Agent / Open-WebUI ]
                        └───────┬───────┬───────┬───────┘       (Single SSE Connection)
                                │       │       │
        ┌───────────────────────┼───────┼───────┼───────┬───────┐
        ▼                       ▼       ▼       ▼       ▼       ▼
┌───────────────┐       ┌───────────┐ ┌───┐ ┌───────────┐       ┌───────────────┐
│ Qdrant Vector │       │   Mem0    │ │Neo│ │ TEI Embed │       │ Ollama Vision │
│  Store :6333  │       │ API :8000 │ │4j │ │   :8089   │       │ Qwen2.5-VL    │
└───────────────┘       └───────────┘ └───┘ └─────┬─────┘       └───────────────┘
                                                  │ (Failover)
                                                  ▼
                                        ┌───────────────────┐
                                        │  LiteLLM Gateway  │
                                        └───────────────────┘
```

---

## 🔌 1. Connecting Knowledge MCP to Hermes Agent & AI Clients

### A. Automatic Docker Swarm Integration (Recommended for Hermes Agent)

In `homelab-ai-agents/compose.yaml`, Hermes connects to `knowledge-mcp` across the shared Docker Swarm overlay network (`homelab_swarm_net`) without exposing any public ports.

```yaml
services:
  hermes:
    image: ghcr.io/medzarka/homelab-hermes-agent:latest
    environment:
      # --- Unified Knowledge MCP Integration ---
      - KNOWLEDGE_MCP_URL=http://knowledge-mcp:8095/mcp/sse
      - KNOWLEDGE_MCP_API_KEY=${KNOWLEDGE_MCP_API_KEY:-}

      # --- Conversational Memory Backend (Mem0 Engine) ---
      - MEMORY_BACKEND=mem0
      - MEM0_API_URL=http://mem0-api:8000
      - MEM0_API_KEY=${MEM0_API_KEY:-}
    networks:
      - homelab_swarm_net
```

> [!NOTE]
> On container startup, Hermes queries `http://knowledge-mcp:8095/mcp/sse` via Server-Sent Events (SSE), negotiates protocol capabilities, and dynamically registers available tools (e.g., `search_knowledge`, `index_file`) directly into its LLM context.

---

### B. Hermes Agent Config File (`~/.hermes/config.yaml` or `/app/config.yaml`)

If using standalone Hermes CLI, local development, or explicit configuration files, add `knowledge_hub` to your `mcp_servers` section:

```yaml
# ==============================================================================
# Hermes Agent Configuration (~/.hermes/config.yaml)
# ==============================================================================

mcp_servers:
  # Qdrant Vector Search & Document Ingestion
  knowledge_hub:
    transport: sse
    url: http://knowledge-mcp:8095/mcp/sse
    timeout: 300
    headers:
      Content-Type: application/json
      X-API-Key: "your_secure_mcp_api_key_here"  # Matches KNOWLEDGE_MCP_API_KEY in .env

# Direct Mem0 backend integration for automatic session memory
memory:
  provider: mem0
  api_url: http://mem0-api:8000
  api_key: "your_secure_mem0_api_key_here"
  collection: memories
```

> [!TIP]
> Both `http://knowledge-mcp:8095/mcp/sse` and `http://knowledge-mcp:8095/sse` are supported routes. If connecting from an external host over the internet, use your Traefik public ingress URL: `https://knowledge-mcp.bluewave.work/sse` with `Authorization: Bearer <KEY>`.

---

### C. Open-WebUI Configuration

1. In Open-WebUI, navigate to **Admin Panel ➔ Settings ➔ Tools ➔ External MCP**.
2. Add a new **SSE MCP Server**:
   - **Name**: `Homelab Unified Knowledge & Notes`
   - **URL**: `http://knowledge-mcp:8095/mcp/sse` (or `https://knowledge-mcp.yourdomain.com/sse`)
   - **Headers**: `{"X-API-Key": "your_secure_mcp_api_key_here"}`
3. Click **Save** and verify the status shows **Connected**. All 14 tools will become active in chat conversations.

---

### D. Claude Code / Claude Desktop Configuration (`claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "homelab-knowledge": {
      "command": "curl",
      "args": [
        "-H", "X-API-Key: your_secure_mcp_api_key_here",
        "https://knowledge-mcp.yourdomain.com/sse"
      ]
    }
  }
}
```

---

## 🛠️ Complete MCP Tools Reference

| Tool Name | Pillar | Parameters | Description |
| :--- | :--- | :--- | :--- |
| **`search_knowledge`** | **Qdrant** | `query` *(str)*, `collection="workspace"`, `limit=5`, `min_score=0.50` | Semantic dense vector search in Qdrant with Cross-Encoder reranking (`bge-reranker-v2-m3`). Returns ranked chunks with source files and page numbers. |
| **`index_file`** | **Qdrant** | `file_path` *(str)*, `collection="workspace"`, `tags=""`, `file_content_base64=None` | Ingests, parses, and vectors any file (PDF page-by-page, images via Vision OCR, audio via Whisper, code/markdown). Deduplicated via SHA-256. |
| **`delete_file_from_knowledge`** | **Qdrant** | `file_path` *(str)*, `collection="workspace"` | Atomically deletes all vector embeddings and chunks associated with a file from Qdrant. |
| **`list_collections`** | **Qdrant** | None | Lists all Qdrant knowledge collections, total point counts, vector dimensions, and distance metrics. |

---

## 💡 Practical Scenarios & Deep-Dive Workflows

### 🏛️ Scenario 1: Qdrant Deep Semantic RAG & Technical Document Ingestion
**Goal**: Hermes needs to answer a complex technical question based on a 60-page PDF containing diagrams and math formulas stored in `/workspace`.

1. **Hermes indexes the technical PDF**:
   ```json
   {
     "name": "index_file",
     "arguments": {
       "file_path": "/workspace/papers/distributed_raft_consensus.pdf",
       "collection": "workspace",
       "tags": "consensus,raft,distributed-systems"
     }
   }
   ```
   *The server parses the document page-by-page. For pages with diagrams or math, it renders 150 DPI bitmaps in RAM and calls Qwen2.5-VL to transcribe equations into LaTeX before computing BGE-M3 embeddings.*

2. **Hermes queries Qdrant with Cross-Encoder reranking**:
   ```json
   {
     "name": "search_knowledge",
     "arguments": {
       "query": "How does Raft guarantee log matching and handle election split-vote ties?",
       "collection": "workspace",
       "limit": 3,
       "min_score": 0.60
     }
   }
   ```
   *Qdrant retrieves the top 9 vector candidates; the Cross-Encoder (`bge-reranker-v2-m3`) computes precise semantic relevance and returns the top 3 scored text chunks with page citations.*

---





### 🔍 Scenario 4: Fast Keyword Search vs Deep Semantic Search
**Understanding when to use which tool**:

* **Use `search_knowledge`** when you want conceptual, semantic search across large uncurated documents (50-page PDFs, books, code repositories, transcribed lecture recordings):
  ```json
  {
    "name": "search_knowledge",
    "arguments": {
      "query": "how is memory mapped when allocating huge pages in Linux kernel?",
      "collection": "workspace"
    }
  }
  ```

---







## 💡 Hints, Tips & Best Practices

### 📚 Qdrant Semantic Search Best Practices
> [!TIP]
> **Cross-Encoder Score Filtering**:
> In `search_knowledge`, `min_score` filters out weakly related vectors. A threshold of `0.55`–`0.65` provides high-precision answers with minimal hallucinations.
> 
> **Multi-Collection Segregation**:
> Keep distinct datasets in separate collections:
> - `workspace`: Source code, developer documentation, and uploaded research PDFs.
> - `notes`: Obsidian notes promoted into vectors.
> - `memories`: Mem0 conversational fact embeddings.

### 🌐 Direct REST & Scripting Access
> [!TIP]
> In addition to MCP SSE, the Knowledge Hub exposes standard FastAPI REST endpoints:
> ```bash
> # Check health of all 3 pillars (Qdrant, Mem0, Obsidian Vault)
> curl http://knowledge-mcp:8095/health
> 
> # Semantic vector search in Qdrant
> curl -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
>   -d '{"query": "Raft leader election", "limit": 3}' \
>   http://knowledge-mcp:8095/search
> ```

---

## ⚠️ Important Warnings & Gotchas

> [!WARNING]
> **Strict 1024-Dimension Vector Constraint**:
> Qdrant collections are configured for **1024-dimensional vectors** (`BAAI/bge-m3`). Do not switch embedding models to models with different dimensions (e.g., OpenAI `text-embedding-3-small` at 1536 dims) without recreating the collections, as vector dimension mismatch will cause Qdrant upsert failures.

> [!WARNING]
> **CPU Concurrency Guard on Compute Nodes**:
> `MAX_CONCURRENT_INDEXING_JOBS` is set to `1` by default. Multi-modal document parsing, OCR, and embeddings are CPU-intensive. Keeping this at `1` guarantees that your server won't suffer CPU starvation or frozen SSH sessions while indexing large PDFs or audio recordings.

> [!WARNING]
> **Zero Host Port Exposure**:
> Knowledge MCP and Mem0 API listen on the internal Docker Swarm network (`homelab_swarm_net`). They do **not** bind to host ports (`0.0.0.0:8095` or `0.0.0.0:8000`). All agent communication is securely routed over overlay network bridges or authenticated through Traefik reverse proxy.

---

## ⚙️ Environment Configuration Reference (`.env`)

```dotenv
# ==============================================================================
# Homelab AI Knowledge & Long-Term Memory Stack (.env)
# ==============================================================================

# --- 1. Storage & Runtime Paths ---
DATA_DIR=/srv/data/ai-knowledge

# --- 2. Ingress & Public Routing Domains ---
QDRANT_DOMAIN=qdrant.example.com
MEM0_DOMAIN=mem0.example.com
NEO4J_DOMAIN=neo4j.example.com
KNOWLEDGE_MCP_DOMAIN=knowledge-mcp.example.com

# --- 4. Unified Knowledge MCP Server ---
KNOWLEDGE_MCP_PORT=8095
KNOWLEDGE_MCP_API_KEY=your_secure_mcp_api_key_here
QDRANT_COLLECTION_WORKSPACE=workspace
PDF_RENDER_DPI=150
MAX_CONCURRENT_INDEXING_JOBS=1
INDEXING_REQUEST_TIMEOUT=300

# --- 5. Primary Compute Models (Compute Node) ---
EMBEDDING_PRIMARY_URL=http://compute_embeddings:80/embed
EMBEDDING_MODEL=BAAI/bge-m3
RERANKER_PRIMARY_URL=http://compute_reranker:80/rerank
RERANKER_MODEL=BAAI/bge-reranker-v2-m3
VISION_PRIMARY_PROVIDER=local
VISION_PRIMARY_URL=http://compute_ollama:11434/api/chat
VISION_PRIMARY_MODEL=qwen2.5vl:3b
AUDIO_PRIMARY_URL=http://compute_speaches:8000/v1/audio/transcriptions
AUDIO_PRIMARY_MODEL=Systran/faster-whisper-large-v3

# --- 6. Cloud / LiteLLM Fallback Providers ---
EMBEDDING_FALLBACK_URL=http://litellm:4000/v1/embeddings
EMBEDDING_FALLBACK_KEY=sk-homelab-master-key
RERANKER_FALLBACK_URL=http://litellm:4000/v1/rerank
RERANKER_FALLBACK_KEY=sk-homelab-master-key
VISION_FALLBACK_PROVIDER=litellm
VISION_FALLBACK_URL=http://litellm:4000/v1/chat/completions
VISION_FALLBACK_KEY=sk-homelab-master-key
VISION_FALLBACK_MODEL=google/gemini-2.0-flash
AUDIO_FALLBACK_URL=http://litellm:4000/v1/audio/transcriptions
AUDIO_FALLBACK_KEY=sk-homelab-master-key
AUDIO_FALLBACK_MODEL=openai/whisper-1

# --- 7. Databases Authentication ---
QDRANT_API_KEY=
MEM0_API_KEY=generate_a_secure_mem0_api_key
NEO4J_PASSWORD=generate_a_secure_neo4j_password

# --- 8. Docker Networks ---
SHARED_NETWORK=shared_net
SWARM_NETWORK=homelab_swarm_net
```
