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

The platform integrates **4 Core Pillars** into a single, unified **Model Context Protocol (MCP)** server:
1. **Qdrant Vector Database**: Multi-modal semantic dense search, page-by-page PDF extraction, and Cross-Encoder reranking (`BAAI/bge-m3`, `bge-reranker-v2-m3`).
2. **Obsidian Notes Engine (via Ignis Web UI)**: Human-curated Markdown notes with live browser UI (`nobbe/ignis:latest`), full-text search, and bidirectional agent read/write tools.
3. **Mem0 Episodic Memory**: Autonomous long-term user profile evolution, conversational fact extraction, and episodic history.
4. **Neo4j Knowledge Graph**: Structural entity relationships and Cypher GraphRAG traversal.

---

## 🌟 Key Capabilities & Architectural Highlights

1. **Unified Single-MCP Integration**:
   - A single MCP connection (`http://knowledge-mcp:8095/mcp/sse`) provides AI agents with simultaneous access to Qdrant vector retrieval, Obsidian notes, Mem0 memory, and Neo4j graph traversal.
2. **Native Obsidian Vault Synchronization**:
   - Notes are standard Markdown files stored on host disk (`/srv/data/ai-knowledge/vaults`).
   - Edits made by Hermes or other agents via MCP immediately appear in the **Ignis web interface** through live filesystem watchers.
3. **4-Layer Smart PDF & Document Inspection Engine**:
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
                        │   Ignis Obsidian Web (:8080)  │
                        └───────────────┬───────────────┘
                                        │
                                (Markdown Files)
                                        ▼
┌───────────────────────────────────────────────────────────────────────────────────────────┐
│                     Shared Host Storage (/srv/data/ai-knowledge/vaults)                   │
└───────────────────────────────────────┬───────────────────────────────────────────────────┘
                                        │ (Mounted as /vault)
                                        ▼
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
> On container startup, Hermes queries `http://knowledge-mcp:8095/mcp/sse` via Server-Sent Events (SSE), negotiates protocol capabilities, and dynamically registers all available tools (`search_knowledge`, `add_memory`, `read_note`, etc.) directly into its LLM context.

---

### B. Hermes Agent Config File (`~/.hermes/config.yaml` or `/app/config.yaml`)

If using standalone Hermes CLI, local development, or explicit configuration files, add `knowledge_hub` to your `mcp_servers` section:

```yaml
# ==============================================================================
# Hermes Agent Configuration (~/.hermes/config.yaml)
# ==============================================================================

mcp_servers:
  # Unified Knowledge Hub: Qdrant Vector Search + Obsidian Vault + Mem0 Memory
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
| **`search_memory`** | **Mem0** | `query` *(str)*, `user_id="default"`, `agent_id=None`, `limit=5` | Searches Mem0 episodic conversational memory for personalized facts, preferences, and user context. |
| **`add_memory`** | **Mem0** | `content` *(str)*, `user_id="default"`, `agent_id=None`, `metadata=None` | Records a new memory, preference, or fact into Mem0. Mem0 automatically extracts entities and saves them to Qdrant & Neo4j. |
| **`get_memories`** | **Mem0** | `user_id="default"`, `agent_id=None`, `limit=20` | Retrieves all stored long-term memories for a specific user or agent. |
| **`delete_memory`** | **Mem0** | `memory_id` *(str)* | Deletes a specific memory entry from Mem0 by its unique identifier. |
| **`query_knowledge_graph`** | **Neo4j** | `cypher_query` *(str)* | Runs raw Cypher queries on the Neo4j Graph Database to traverse entity relationships and knowledge links. |
| **`read_note`** | **Obsidian** | `path` *(str)* | Reads the full Markdown content of a specific note from the Obsidian vault. Auto-appends `.md` if omitted. |
| **`write_note`** | **Obsidian** | `path` *(str)*, `content` *(str)* | Creates or overwrites a note in the Obsidian vault. Automatically creates any missing parent directories. |
| **`append_note`** | **Obsidian** | `path` *(str)*, `content` *(str)* | Appends Markdown text to an existing note (or creates a new one). Handles newlines and bullet formatting cleanly. |
| **`list_notes`** | **Obsidian** | `directory=""` | Recursively lists all Markdown files (`.md`), sizes, and relative paths in the vault or within a subfolder. |
| **`search_notes`** | **Obsidian** | `query` *(str)*, `max_results=10` | In-vault keyword search across all notes, returning matching file paths, line numbers, and text snippets. |
| **`delete_note`** | **Obsidian** | `path` *(str)* | Safely deletes a Markdown note from the Obsidian vault (with strict path-traversal jail guard). |
| **`index_note_to_knowledge`** | **Bridge** | `path` *(str)*, `collection="notes"`, `tags="obsidian,vault"` | Ingests a specific Obsidian note into Qdrant vector database for hybrid semantic search. |
| **`index_vault_to_knowledge`**| **Bridge** | `directory=""`, `collection="notes"`, `tags="obsidian,vault"` | Batch-vectorizes all Markdown notes in the Obsidian vault (or subfolder) into Qdrant. |

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

### 🧠 Scenario 2: Mem0 Autonomous Long-Term Memory & User Personalization
**Goal**: Hermes learns the user's coding style and project constraints during a conversation, records it to long-term memory, and recalls it in future sessions.

1. **User says**: *"Keep in mind that I prefer async Python with type hints, and all Docker services must run on ARM64 without host port exposure."*
2. **Hermes saves this fact to Mem0**:
   ```json
   {
     "name": "add_memory",
     "arguments": {
       "content": "User prefers async Python with strict type hints. All Docker services in the homelab must run on ARM64 and communicate exclusively via internal Swarm overlay network with zero exposed host ports.",
       "user_id": "mzarka",
       "agent_id": "hermes"
     }
   }
   ```
   *Mem0 automatically extracts key entities (`Python`, `Docker`, `ARM64`, `Swarm`), stores them in Qdrant collection `memories`, and registers the relationship graph in Neo4j.*

3. **In a future session, Hermes searches user context before architecting a service**:
   ```json
   {
     "name": "search_memory",
     "arguments": {
       "query": "Docker network port conventions and Python guidelines",
       "user_id": "mzarka",
       "limit": 3
     }
   }
   ```
   *Hermes instantly tailors its code and compose architecture to the user's recorded preferences.*

---

### 📓 Scenario 3: Obsidian Live Notes & Human-in-the-Loop Collaboration
**Goal**: Hermes helps the user maintain an academic research log and a daily engineering journal in Obsidian, rendered live in the Ignis web browser UI.

1. **Hermes creates a structured literature review note**:
   ```json
   {
     "name": "write_note",
     "arguments": {
       "path": "Research/Papers/AttentionIsAllYouNeed.md",
       "content": "# Attention Is All You Need (Vaswani et al.)\n\n## Abstract Summary\nIntroduced the Transformer architecture relying entirely on self-attention mechanisms without recurrent or convolutional layers.\n\n## Core Formula\n$$\\text{Attention}(Q, K, V) = \\text{softmax}\\left(\\frac{QK^T}{\\sqrt{d_k}}\\right)V$$\n\n## Tags\n#ai #transformers #nlp #deep-learning"
     }
   }
   ```
   *The note is immediately written to disk at `/srv/data/ai-knowledge/vaults/default/Research/Papers/AttentionIsAllYouNeed.md` and displays in real time on the user's browser in Ignis.*

2. **Hermes logs progress in a daily engineering journal**:
   ```json
   {
     "name": "append_note",
     "arguments": {
       "path": "Daily/2026-09-19.md",
       "content": "\n- **16:45**: Completed integration of unified Knowledge MCP with Qdrant, Mem0, and Obsidian."
     }
   }
   ```
   *The server appends the line with newline normalization, auto-creating `Daily/2026-09-19.md` if it doesn't already exist.*

3. **Hermes searches notes via in-vault text search**:
   ```json
   {
     "name": "search_notes",
     "arguments": {
       "query": "#transformers",
       "max_results": 5
     }
   }
   ```

---

### 🔍 Scenario 4: Fast Keyword Search vs Deep Semantic Search
**Understanding when to use which tool**:

* **Use `search_notes`** when you want exact keyword, tag, or variable matches inside your curated Obsidian vault:
  ```json
  {
    "name": "search_notes",
    "arguments": {
      "query": "#todo/thesis"
    }
  }
  ```
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

### 🌉 Scenario 5: Promoting an Obsidian Note into Vector Search
**Goal**: You wrote comprehensive lecture notes in Ignis, and you want Hermes to be able to semantically search across them alongside your reference textbooks.

```json
{
  "name": "index_note_to_knowledge",
  "arguments": {
    "path": "Lectures/Distributed_Systems_Week3.md",
    "collection": "workspace",
    "tags": "lecture,distributed-systems,raft"
  }
}
```
*The note is automatically parsed, chunked, embedded with `BAAI/bge-m3`, and stored in Qdrant.*

---

### 📦 Scenario 6: Batch Vault Vectorization (`index_vault_to_knowledge`)
**Goal**: You already have dozens of Markdown notes in your Obsidian vault, and you want to make them all searchable via semantic vector search in Qdrant.

```json
{
  "name": "index_vault_to_knowledge",
  "arguments": {
    "directory": "Research",
    "collection": "notes",
    "tags": "obsidian,research,vault"
  }
}
```
*The server scans the `Research/` subfolder, parses every `.md` file, chunks long sections, computes embeddings, and indexes them into Qdrant. Hermes can now use `search_knowledge(query="...", collection="notes")` to find concepts across all your notes.*

---

### 🔄 Scenario 7: The Tri-Pillar Synergy Loop (Qdrant ➔ Mem0 ➔ Obsidian ➔ Qdrant)
**Goal**: The compound workflow demonstrating how all 3 services interact synergistically.

1. **Step 1 (Ingest)**: Hermes ingests a vendor specification PDF into Qdrant (`index_file`).
2. **Step 2 (Recall)**: Hermes queries Mem0 (`search_memory`) to retrieve the user's deployment goals and security requirements.
3. **Step 3 (Analyze & Document)**: Hermes synthesizes the PDF against the user's goals and writes a comprehensive implementation plan to Obsidian (`write_note`).
4. **Step 4 (Bridge)**: Hermes indexes the newly created Obsidian note back into Qdrant (`index_note_to_knowledge`).
5. **Outcome**: The human reviews the formatted note in **Ignis**; **Hermes** retains the episodic context in **Mem0**; and the entire cluster's **Qdrant** index now possesses deep semantic understanding of the new note!

---

## 💡 Hints, Tips & Best Practices

### 📓 Obsidian Vault Best Practices
> [!TIP]
> **Path Conventions & Extensions**:
> Always use relative paths without a leading slash (e.g., `Notes/Ideas.md` instead of `/vault/Notes/Ideas.md`). If you omit the extension (e.g. `Research/Paper`), the server will automatically append `.md` for you.
> 
> **Automatic Folder Creation**:
> When calling `write_note` or `append_note`, you do not need to create parent folders in advance. The server automatically creates any missing subdirectories (e.g. `Courses/2026/Spring/Math.md`).
> 
> **Structured Organization**:
> Group notes by domain (e.g., `Research/`, `Daily/`, `Architecture/`). This keeps your view in Ignis clean and allows targeted batch vectorization using `index_vault_to_knowledge(directory="Research")`.

### 🧠 Mem0 Conversational Memory Best Practices
> [!TIP]
> **User & Agent Scoping**:
> Always specify `user_id` (e.g., `user_id="mzarka"`) and optionally `agent_id="hermes"`. This isolates personal preferences from system agent states and prevents memory pollution across multiple family members or cluster users.
> 
> **Concise Memory Statements**:
> Use `add_memory` for concise, declarative facts (e.g., *"User prefers dark mode and Python 3.12"*) rather than passing huge raw chat dumps. This maximizes entity extraction quality in both Qdrant and the Neo4j Knowledge Graph.
> 
> **Context Pre-Warming**:
> Before starting complex multi-step reasoning, have Hermes invoke `search_memory` with keywords from the prompt to inject relevant past architectural decisions into the conversation context.

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
> # List all Obsidian notes in the vault
> curl -H "X-API-Key: $KEY" http://knowledge-mcp:8095/notes
> 
> # Search Mem0 long-term memories
> curl -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
>   -d '{"query": "coding style", "user_id": "mzarka"}' \
>   http://knowledge-mcp:8095/memory/search
> 
> # Semantic vector search in Qdrant
> curl -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
>   -d '{"query": "Raft leader election", "limit": 3}' \
>   http://knowledge-mcp:8095/search
> ```

---

## ⚠️ Important Warnings & Gotchas

> [!WARNING]
> **Authelia 2FA & Group Authorization**:
> Ignis has no built-in login form. It is protected by Traefik with `authelia-sso@file`. To access `https://ignis.bluewave.work`, the user **must belong to the `ai-agents` LDAP group**. Users without this group will receive an HTTP 403 Forbidden error from Authelia.

> [!WARNING]
> **Vault Jail & Path Traversal Prevention**:
> All Obsidian note operations are validated through `get_vault_safe_path()`. Attempting to access paths outside `/vault` (e.g., `../../etc/shadow` or `/proc/`) will be immediately rejected with an `Access denied` exception.

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
IGNIS_DOMAIN=ignis.example.com
KNOWLEDGE_MCP_DOMAIN=knowledge-mcp.example.com

# --- 3. Ignis Web Obsidian Interface ---
IGNIS_IMAGE=nobbe/ignis:latest
IGNIS_PORT=8080
IGNIS_APP_VOLUME=knowledge_ignis_app
OBSIDIAN_VAULT_NAME=default
PUID=1000
PGID=1000

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
