# 🧠 Homelab AI Knowledge Hub & Multi-Modal MCP Server

A sovereign, high-performance **Multi-Modal AI Knowledge & Long-Term Memory Engine** designed for **Hermes Agent**, **Open-WebUI**, **Claude**, and **Autonomous Coding Agents**.

The platform unifies **Qdrant Vector Database**, **Neo4j Knowledge Graph**, **Mem0 Episodic Memory**, and **Local AI Models** (`BAAI/bge-m3`, `BAAI/bge-reranker-v2-m3`, `Qwen2.5-VL`, `Faster-Whisper-Large-v3`) into a single, high-speed **Model Context Protocol (MCP)** server.

---

## 🌟 Key Capabilities & Architectural Highlights

1. **4-Layer Smart PDF & Document Inspection Engine**:
   - Analyzes document AST in RAM ($< 0.5$ ms) before deciding whether to call Vision AI.
   - **Layer 1 (Raster Bitmaps)**: Detects embedded images, photos, and figures.
   - **Layer 2 (Vector Graphics)**: Identifies diagrams, flowcharts, and plots (`len(drawings) > 5`).
   - **Layer 3 (Math & LaTeX Detection)**: Flags LaTeX equations, math fonts (`CMSY10`, `MathJax`), and formulas.
   - **Layer 4 (Scanned Page Detection)**: Identifies scanned papers and handwritten exams ($0$ selectable text + image).
2. **Native Single-Page PDF Ingestion**:
   - Multi-page PDFs are split into **standalone single-page PDFs** in RAM with full document metadata inheritance.
   - Preserves original digital text, fonts, and vector paths without converting blindly to flat lossy images.
3. **150 DPI In-Memory Normalized Rendering**:
   - Visual pages and handwritten student answer sheets are rendered in RAM at **150 DPI** (configurable via `PDF_RENDER_DPI=150`) for sharp OCR/math transcription with minimum CPU memory footprint.
4. **Multi-Modal Ingestion Pipeline**:
   - **Text & Code** (`.md`, `.py`, `.json`, `.yaml`, `.c`, `.cpp`, `.rs`, `.java`, `.txt`): Structure-aware chunking.
   - **PDFs** (`.pdf`): Digital text extraction + Qwen2.5-VL academic handwriting/math transcription.
   - **Images** (`.png`, `.jpg`, `.jpeg`, `.webp`): 150 DPI normalized description via Vision LLM.
   - **Audio & Speech** (`.mp3`, `.wav`, `.m4a`, `.ogg`, `.flac`): Whisper-Large-v3 speech-to-text with timestamps.
5. **Transactional All-or-Nothing Ingestion**:
   - If any page in a multi-page document fails during parsing, the transaction aborts cleanly with **0 partial/broken vectors committed to Qdrant**.
6. **Strict CPU Concurrency Guard**:
   - Limits parallel inference to `MAX_CONCURRENT_INDEXING_JOBS=1` to prevent CPU core starvation on compute nodes.
7. **Transparent Primary & Fallback Failover**:
   - Automatically fails over from local `zap-srv` models to LiteLLM / external providers if a service is busy or offline (respecting the 1024-dimension vector constraint).

---

## 🏗️ Architecture & Topology Diagram

```
                                  [ Hermes Agent / Open-WebUI ]
                                                │
                                    (MCP Tools via SSE / REST)
                                                ▼
                        ┌───────────────────────────────────────────────┐
                        │    Homelab AI Knowledge MCP Server (:8095)    │
                        └───────┬───────────────┬───────────────┬───────┘
                                │               │               │
        ┌───────────────────────┼───────────────┼───────────────┼───────────────────────┐
        ▼                       ▼               ▼               ▼                       ▼
┌───────────────┐       ┌───────────────┐ ┌───────────┐ ┌───────────────┐       ┌───────────────┐
│ Qdrant Vector │       │ TEI Embedding │ │ TEI Rerank│ │ Ollama Vision │       │ Speaches STT  │
│  Store :6333  │       │ BAAI/bge-m3   │ │ bge-v2-m3 │ │ qwen2.5vl:3b  │       │ Whisper-v3    │
│  (1024 dims)  │       │     :8089     │ │   :8087   │ │    :11434     │       │     :8086     │
└───────────────┘       └───────┬───────┘ └─────┬─────┘ └───────┬───────┘       └───────┬───────┘
                                │ (Failover)    │ (Failover)    │ (Failover)            │ (Failover)
                                ▼               ▼               ▼                       ▼
                        ┌───────────────────────────────────────────────────────────────────────┐
                        │              LiteLLM Gateway (Proxy & Cloud Fallbacks)                │
                        └───────────────────────────────────────────────────────────────────────┘
```

---

## 🛠️ MCP Tools Reference

The Knowledge MCP server exposes the following tools to AI agents:

| Tool Name | Parameters | Description |
| :--- | :--- | :--- |
| `search_knowledge` | `query`, `collection="workspace"`, `limit=5`, `min_score=0.50` | Dense vector search in Qdrant with Cross-Encoder reranking. Returns structured Markdown chunks with file & page coordinates. |
| `index_file` | `file_path`, `collection="workspace"`, `tags=[]` | Automatically parses, inspects, chunks, embeds, and saves any file (PDF, image, audio, code) to Qdrant. |
| `delete_file_from_knowledge` | `file_path`, `collection="workspace"` | Removes all vector points and metadata associated with a given file from Qdrant. |
| `query_knowledge_graph` | `cypher_query` | Executes Cypher graph traversal on Neo4j for structural entity dependencies. |
| `search_memory` | `query`, `user_id="default"` | Queries Mem0 long-term episodic conversational memory. |
| `list_collections` | None | Lists available knowledge collections, vector counts, and dimensions. |

---

## 🤖 Configuring Hermes Agent with Knowledge MCP

Add the Knowledge MCP server to your Hermes Agent configuration file (`~/.hermes/config.yaml` or `/app/config.yaml`):

```yaml
# ==============================================================================
# Hermes Agent Configuration (~/.hermes/config.yaml)
# ==============================================================================

mcp_servers:
  # 1. Homelab AI Knowledge Hub (Vector Search, File Ingestion, Neo4j, Mem0)
  knowledge_hub:
    transport: sse
    url: http://100.110.173.116:8095/sse
    timeout: 300
    headers:
      Content-Type: application/json

  # 2. Homelab Agent Sandbox (Multi-Language Compiler & Execution Engine)
  agent_sandbox:
    transport: sse
    url: http://100.110.173.116:8088/sse
    timeout: 120

# Optional: Configure Mem0 directly for conversational history
memory:
  provider: mem0
  api_url: http://mem0-api:8000
  collection: memories
```

---

## 🔄 Automated Incremental Sync (Smart Walker Cron for Hermes)

To keep your `/workspace` continuously synchronized with Qdrant without wasting CPU on unchanged files, deploy the **Smart Walker Script** (`smart_walker.py`).

### How the Smart Walker Works:
1. **Hash Verification**: Calculates SHA-256 for each file and compares against `.knowledge_cache.json`.
2. **Instant Skip**: Unchanged files are skipped in $< 0.1$ ms.
3. **Atomic Updates**: Modified/new files are sent to `index_file`.
4. **Automatic Garbage Collection**: Deleted files are purged from Qdrant.

---

### Step 1: Deploying `smart_walker.py` in Hermes Container
The script is located at `/app/smart_walker.py`. You can run a manual test run at any time:

```bash
python3 /app/smart_walker.py --dir /workspace --server http://127.0.0.1:8095 --collection hermes_workspace
```

---

### Step 2: Setting up the Scheduled Cron Task in Hermes
Inside the Hermes container or host system, add a cron job (e.g. running every 30 minutes or every hour):

```bash
# Open crontab editor
crontab -e
```

Add the following entry:

```cron
# Run Smart Knowledge Sync every 30 minutes
*/30 * * * * python3 /app/smart_walker.py --dir /workspace --server http://knowledge-mcp:8095 --collection hermes_workspace >> /var/log/knowledge_sync.log 2>&1
```

Or trigger it directly in your agent's end-of-task workflow:
```python
import subprocess

def on_agent_task_complete():
    subprocess.run(["python3", "/app/smart_walker.py", "--dir", "/workspace"], check=True)
```

---

## 💡 Practical Examples: Using Knowledge MCP with Hermes Agent

### Example 1: Finding Information in Lecture Notes or Exams
**User:** *"What was the student's answer to the C pointer allocation question in exam #25?"*

**Hermes Action:**
```json
{
  "name": "search_knowledge",
  "arguments": {
    "query": "examen pratique algorithmique insertion en tete voiture liste chainee malloc",
    "collection": "workspace",
    "limit": 3
  }
}
```

**Hermes Response:**
> *"According to **Page 2 of `244255.pdf`** (Student #25, Hannan Abid), the student implemented `insererTete` as follows:*
> ```c
> Voiture* insererTete(Voiture *tete, int num_plaque, int nb_heures) {
>     Voiture *nv;
>     nv = (Voiture*) malloc(sizeof(Voiture));
>     nv->num_plaque = num_plaque;
>     nv->nb_heures = nb_heures;
>     nv->suiv = tete;
>     tete = nv;
>     return tete;
> }
> ```
> *The code allocates memory, initializes fields, and correctly inserts the new node at the head of the list."*

---

### Example 2: Ingesting a Newly Created Architecture Diagram
**User:** *"I just dropped `network_topology.png` into the workspace. Index it."*

**Hermes Action:**
```json
{
  "name": "index_file",
  "arguments": {
    "file_path": "/workspace/network_topology.png",
    "collection": "workspace",
    "tags": ["network", "architecture"]
  }
}
```

---

## ⚙️ Environment Configuration Reference (`.env`)

```dotenv
# --- Ingress & Ports ---
KNOWLEDGE_MCP_PORT=8095
KNOWLEDGE_MCP_DOMAIN=knowledge-mcp.bluewave.work
QDRANT_COLLECTION_WORKSPACE=workspace

# --- Concurrency & Resolution Tuning ---
PDF_RENDER_DPI=150
MAX_CONCURRENT_INDEXING_JOBS=1
INDEXING_REQUEST_TIMEOUT=300

# --- Primary Local Models (zap-srv) ---
EMBEDDING_PRIMARY_URL=http://100.110.173.116:8089/embed
RERANKER_PRIMARY_URL=http://100.110.173.116:8087/rerank
VISION_PRIMARY_PROVIDER=local
VISION_PRIMARY_URL=http://100.110.173.116:11434/api/chat
VISION_PRIMARY_MODEL=qwen2.5vl:3b
AUDIO_PRIMARY_URL=http://100.110.173.116:8086/v1/audio/transcriptions
AUDIO_PRIMARY_MODEL=Systran/faster-whisper-large-v3

# --- Cloud / LiteLLM Fallback Providers ---
EMBEDDING_FALLBACK_URL=http://litellm:4000/v1/embeddings
EMBEDDING_FALLBACK_KEY=sk-homelab-master-key
EMBEDDING_MODEL=BAAI/bge-m3

RERANKER_FALLBACK_URL=http://litellm:4000/v1/rerank
RERANKER_FALLBACK_KEY=sk-homelab-master-key
RERANKER_MODEL=BAAI/bge-reranker-v2-m3

VISION_FALLBACK_PROVIDER=litellm
VISION_FALLBACK_URL=http://litellm:4000/v1/chat/completions
VISION_FALLBACK_KEY=sk-homelab-master-key
VISION_FALLBACK_MODEL=google/gemini-2.0-flash

AUDIO_FALLBACK_URL=http://litellm:4000/v1/audio/transcriptions
AUDIO_FALLBACK_KEY=sk-homelab-master-key
AUDIO_FALLBACK_MODEL=openai/whisper-1
```
