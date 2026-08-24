#!/usr/bin/env python3
"""
Homelab Smart Knowledge Walker & Incremental Sync Engine
-------------------------------------------------------
Walks a target directory (e.g. /workspace), computes SHA-256 hashes,
skips unchanged files (<1ms), indexes new/modified files via Knowledge MCP,
and cleans up deleted files from Qdrant.
"""

import os
import sys
import json
import time
import hashlib
import argparse
from pathlib import Path
import urllib.request
import urllib.parse
from typing import Dict, Any, List

def compute_sha256(file_path: Path) -> str:
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()

def sync_workspace(
    target_dir: str,
    server_url: str = "http://127.0.0.1:8095",
    collection: str = "workspace",
    cache_file: str = ".knowledge_cache.json",
    extensions: List[str] = None
):
    base_path = Path(target_dir).resolve()
    if not base_path.exists():
        print(f"❌ Error: Target directory '{target_dir}' does not exist.")
        sys.exit(1)

    cache_path = base_path / cache_file
    state: Dict[str, Any] = {}
    if cache_path.exists():
        try:
            state = json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            state = {}

    allowed_exts = set(extensions or [
        ".pdf", ".md", ".txt", ".py", ".json", ".yaml", ".yml",
        ".sh", ".c", ".cpp", ".rs", ".java", ".docx", ".xlsx",
        ".png", ".jpg", ".jpeg", ".webp", ".mp3", ".wav", ".m4a"
    ])

    print("=" * 70)
    print(f"🚀 [Knowledge Walker] Scanning '{base_path}' -> Collection: '{collection}'")
    print("=" * 70)

    current_files = {}
    indexed_count = 0
    skipped_count = 0
    failed_count = 0

    # 1. Walk filesystem
    for root, dirs, files in os.walk(base_path):
        # Ignore hidden / system dirs
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ["node_modules", "venv", "__pycache__", "build", "dist"]]
        for f in files:
            if f.startswith(".") or f == cache_file:
                continue
            fp = Path(root) / f
            if fp.suffix.lower() in allowed_exts:
                current_files[str(fp.resolve())] = fp

    # 2. Check for new or modified files
    for file_str, fp in current_files.items():
        try:
            file_hash = compute_sha256(fp)
            cached = state.get(file_str, {})

            if cached.get("sha256") == file_hash:
                # Unchanged -> Skip instantly
                skipped_count += 1
                continue

            print(f"⚙️  Indexing: {fp.name} ({fp.stat().st_size / 1024:.1f} KB)...")
            payload = json.dumps({
                "file_path": file_str,
                "collection": collection,
                "tags": [fp.suffix.replace(".", "")]
            }).encode("utf-8")

            req = urllib.request.Request(
                f"{server_url}/index-file",
                data=payload,
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=300) as resp:
                res = json.loads(resp.read().decode("utf-8"))
                result_msg = res.get("result", "")

                if "Successfully Indexed" in result_msg:
                    print(f"  🟢 {fp.name} indexed successfully.")
                    state[file_str] = {
                        "sha256": file_hash,
                        "last_indexed": time.time(),
                        "size_bytes": fp.stat().st_size
                    }
                    indexed_count += 1
                else:
                    print(f"  ⚠️ {fp.name} indexing error: {result_msg}")
                    failed_count += 1

        except Exception as e:
            print(f"  ❌ Failed to process {fp.name}: {e}")
            failed_count += 1

    # 3. Clean up deleted files from Qdrant
    deleted_files = [f for f in state.keys() if f not in current_files]
    for del_file in deleted_files:
        try:
            print(f"🗑️  Purging deleted file from knowledge: {Path(del_file).name}...")
            del_url = f"{server_url}/files?file_path={urllib.parse.quote(del_file)}&collection={collection}"
            req = urllib.request.Request(del_url, method="DELETE")
            urllib.request.urlopen(req, timeout=10)
            del state[del_file]
        except Exception as e:
            print(f"  ⚠️ Error purging {del_file}: {e}")

    # 4. Save state cache
    cache_path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    print("\n" + "=" * 70)
    print(f"🏁 [Sync Complete] Indexed: {indexed_count} | Skipped: {skipped_count} | Deleted: {len(deleted_files)} | Failed: {failed_count}")
    print("=" * 70)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Smart Incremental Knowledge Walker for Hermes & Homelab")
    parser.add_argument("--dir", default="/workspace", help="Target directory to sync")
    parser.add_argument("--server", default=os.environ.get("KNOWLEDGE_MCP_URL", "http://127.0.0.1:8095"), help="Knowledge MCP server URL")
    parser.add_argument("--collection", default=os.environ.get("QDRANT_COLLECTION", "workspace"), help="Qdrant collection name")
    parser.add_argument("--cache-file", default=".knowledge_cache.json", help="Cache filename")

    args = parser.parse_args()
    sync_workspace(
        target_dir=args.dir,
        server_url=args.server,
        collection=args.collection,
        cache_file=args.cache_file
    )
