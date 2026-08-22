# Homelab AI Knowledge & Long-Term Memory Hub

A high-performance, containerized Knowledge and Long-Term Memory infrastructure designed for AI Agents, LLM pipelines, and conversational interfaces (Open-WebUI, Aider, Antigravity, CrewAI, AutoGen).

---

## 🏗️ Architecture Overview

```
                        [ AI Clients & Agents ]
             (Open-WebUI, Hermes, Aider, Python SDKs)
                               │
                ┌──────────────┴──────────────┐
                ▼                             ▼
   [ Qdrant Vector Database ]        [ Mem0 Memory Engine ]
     • Port: 6333 (REST/UI)            • Port: 8000 (REST API)
     • Port: 6334 (gRPC)               • Semantic Search via Qdrant
     • Memory-mapped HNSW storage      • Relational Graph via Neo4j
                │                             │
                └──────────────┬──────────────┘
                               ▼
                    [ LiteLLM Proxy / Gateway ]
                  • Embeddings: BAAI/bge-m3 / text-embedding-3
                  • Chat/Extraction: hermes-default / gpt-4o-mini
```

---

## 📦 Services Included

| Service | Port | Description | Web Interface |
| :--- | :--- | :--- | :--- |
| **`qdrant`** | `6333`, `6334` | High-speed Rust Vector Search Engine with payload filtering. | `http://<host>:6333/dashboard` |
| **`mem0-api`** | `8000` | Intelligent, self-improving memory layer for personalized AI agents. | `http://<host>:8000/docs` (Swagger) |
| **`neo4j`** | `7474`, `7687` | Property Graph Database for entity relationship extraction (GraphRAG). | `http://<host>:7474` (Browser) |
| **`init-volumes`** | - | Automated storage permission and directory bootstrap. | - |

---

## 🚀 Quick Start & Deployment

### 1. Configure Environment
```bash
cp .env.example .env
nano .env
```

Set your `LITELLM_MASTER_KEY` so Mem0 can generate vector embeddings via your local LiteLLM gateway.

### 2. Launch the Stack
```bash
docker compose up -d
```

Check the logs to verify all databases and services are healthy:
```bash
docker compose logs -f
```

---

## 🔌 Connecting Services

### 1. Open-WebUI Vector Store (RAG)
In your Open-WebUI Admin Settings (or `compose.yaml`):
```env
VECTOR_DB=qdrant
QDRANT_URI=http://qdrant:6333
QDRANT_API_KEY=
```

### 2. Mem0 Python SDK Integration
You can use Mem0 directly via REST API or the official Python client:

```python
from mem0 import MemoryClient

# Connect to self-hosted Mem0 API
client = MemoryClient(api_key="none", host="http://100.83.191.68:8000")

# Add memory for a specific user or agent
client.add("User prefers dark mode and is building an AI homelab on ARM64.", user_id="user_123")

# Search relevant memories
memories = client.search("What is the user's infrastructure setup?", user_id="user_123")
print(memories)
```

---

## 🛡️ Resource Allocation & Performance Tuning (`oci01-flex`)

This stack is pre-tuned with explicit memory limits and reservations to run smoothly alongside LiteLLM and Open-WebUI on a 10GB RAM / 2-vCPU node:

* **Qdrant:** Limited to 3.0 GiB RAM (search threads capped at 2).
* **Mem0 API:** Limited to 1.5 GiB RAM.
* **Neo4j:** JVM Heap capped at 1.0 GiB + 512MB page cache.
