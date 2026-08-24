FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# Install system dependencies (mupdf libraries, build essentials, curl)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    wget \
    ca-certificates \
    libmupdf-dev \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Install FastMCP, Qdrant Client, PyMuPDF, Pillow, Neo4j, and HTTP utilities
RUN pip install --no-cache-dir \
    fastapi \
    "uvicorn[standard]" \
    pydantic \
    mcp \
    httpx \
    sse-starlette \
    qdrant-client \
    pymupdf \
    pillow \
    neo4j \
    python-docx \
    openpyxl

WORKDIR /app
COPY server.py /app/server.py
COPY smart_walker.py /app/smart_walker.py

EXPOSE 8095

ENTRYPOINT ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8095"]
