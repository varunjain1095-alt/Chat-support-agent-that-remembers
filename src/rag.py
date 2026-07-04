"""
rag.py — Policy document chunking, embedding (text-embedding-3-small), and retrieval.
"""

import os
import json
import logging
import pathlib
import sys
from openai import OpenAI

# Ensure config can be resolved
project_root = pathlib.Path(__file__).parent.parent.resolve()
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

import config

logger = logging.getLogger(__name__)

def chunk_text(text: str, chunk_size: int = 500, overlap: int = 100) -> list[str]:
    """
    Splits text into fixed-size chunks with a defined overlap.
    """
    if not text:
        return []
    if overlap >= chunk_size:
        overlap = chunk_size // 2
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        # If we reached the end of the text, break
        if end >= len(text):
            break
        start += chunk_size - overlap
    return chunks

def build_index(db_dir: pathlib.Path = config.DATA_POLICY_DIR, index_dir: pathlib.Path = config.VECTOR_STORE_DIR) -> None:
    """
    Reads markdown documents from the policy directory, chunks them,
    computes embeddings via OpenAI, and stores the serialized index.
    """
    if not db_dir.exists():
        logger.warning(f"Policy directory {db_dir} does not exist.")
        return

    all_chunks = []
    # Read files
    for filepath in db_dir.glob("*.md"):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            filename = filepath.name
            chunks = chunk_text(content)
            for chunk in chunks:
                all_chunks.append({
                    "text": chunk,
                    "source": filename
                })
        except Exception as e:
            logger.error(f"Error reading {filepath}: {e}")

    if not all_chunks:
        logger.info("No policy content chunks found to index.")
        return

    # Embed chunks in a single batch
    try:
        client = OpenAI(api_key=config.OPENAI_API_KEY)
        chunk_texts = [item["text"] for item in all_chunks]
        response = client.embeddings.create(
            model=config.EMBEDDING_MODEL,
            input=chunk_texts
        )
        for idx, data_obj in enumerate(response.data):
            all_chunks[idx]["embedding"] = data_obj.embedding
    except Exception as e:
        logger.error(f"Failed to generate embeddings: {e}")
        raise

    # Store index
    try:
        index_dir.mkdir(parents=True, exist_ok=True)
        index_path = index_dir / "index.json"
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(all_chunks, f, indent=2)
        logger.info(f"Successfully built and saved RAG index containing {len(all_chunks)} chunks to {index_path}")
    except Exception as e:
        logger.error(f"Failed to write RAG index file: {e}")
        raise

def retrieve(query: str, top_k: int = config.RAG_TOP_K, index_dir: pathlib.Path = config.VECTOR_STORE_DIR) -> list[str]:
    """
    Computes embedding for the query, computes similarity with all indexed chunks,
    and returns top matching chunks above similarity threshold.
    """
    if not query or not query.strip():
        return []

    index_path = index_dir / "index.json"
    if not index_path.exists():
        logger.warning(f"RAG index not found at {index_path}. Returning empty.")
        return []

    try:
        with open(index_path, "r", encoding="utf-8") as f:
            index_data = json.load(f)
    except Exception as e:
        logger.error(f"Failed to read RAG index from {index_path}: {e}")
        return []

    # Embed query
    import time
    t_embed_start = time.time()
    try:
        client = OpenAI(api_key=config.OPENAI_API_KEY)
        response = client.embeddings.create(
            model=config.EMBEDDING_MODEL,
            input=[query]
        )
        query_embedding = response.data[0].embedding
    except Exception as e:
        logger.error(f"Failed to embed query: {e}")
        return []
    logger.info(f"[TIMING] RAG query embedding took: {((time.time() - t_embed_start) * 1000):.2f} ms")

    # Score chunks
    t_score_start = time.time()
    scored_chunks = []
    for item in index_data:
        chunk_embedding = item.get("embedding")
        if not chunk_embedding:
            continue
        # Cosine similarity: Dot product (since OpenAI embeddings are unit normalized)
        sim = sum(q * c for q, c in zip(query_embedding, chunk_embedding))
        if sim >= config.RAG_SIMILARITY_THRESHOLD:
            scored_chunks.append((sim, item["text"]))

    # Sort descending by similarity score
    scored_chunks.sort(key=lambda x: x[0], reverse=True)
    logger.info(f"[TIMING] RAG cosine similarity search took: {((time.time() - t_score_start) * 1000):.2f} ms")

    # Return top_k text chunks
    return [text for sim, text in scored_chunks[:top_k]]
