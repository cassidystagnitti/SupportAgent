"""
Build an embedding index from data/saved_replies.json (OpenAI text-embedding-3-small).

Writes:
  data/saved_replies.emb.npy   — float32 matrix, shape (N, 1536), L2-normalized rows
  data/saved_replies.emb.json  — model, source snapshot, per-row ids/names (order matches rows)

Environment:
  OPENAI_API_KEY

Run:
  .venv/bin/python build_saved_reply_embeddings.py
  .venv/bin/python build_saved_reply_embeddings.py --all-mailboxes-in-snapshot
  .venv/bin/python build_saved_reply_embeddings.py --mailbox-id 315752
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

import numpy as np
from dotenv import load_dotenv
from openai import APIError, OpenAI, RateLimitError

_SUPPORT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(_SUPPORT_DIR)
load_dotenv(os.path.join(_SUPPORT_DIR, ".env"))
load_dotenv(os.path.join(ROOT_DIR, ".env"))

EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_INPUT = os.path.join(_SUPPORT_DIR, "data", "saved_replies.json")
DEFAULT_VECTORS_OUT = os.path.join(_SUPPORT_DIR, "data", "saved_replies.emb.npy")
DEFAULT_META_OUT = os.path.join(_SUPPORT_DIR, "data", "saved_replies.emb.json")

# Default mailbox filter (1. Happier Support); use --all-mailboxes in pull to widen snapshot first.
DEFAULT_MAILBOX_ID = 185235


def _embed_input_for_reply(reply: dict) -> str:
    name = (reply.get("name") or "").strip()
    body = (reply.get("text_plain") or "").strip()
    if not body:
        body = (reply.get("chat_text_plain") or "").strip()
    if name and body:
        return f"{name}\n\n{body}"
    if name:
        return name
    if body:
        return body
    return "(no content)"


def _flatten_replies(
    data: dict,
    *,
    mailbox_id: int | None,
) -> tuple[list[dict], list[dict]]:
    """Return (flat_replies_for_embedding, meta_rows_aligned)."""
    flat: list[dict] = []
    meta_rows: list[dict] = []
    for mb in data.get("mailboxes", []):
        mid = mb.get("id")
        if mailbox_id is not None and int(mid) != int(mailbox_id):
            continue
        for sr in mb.get("saved_replies", []) or []:
            flat.append(sr)
            meta_rows.append(
                {
                    "saved_reply_id": sr.get("id"),
                    "mailbox_id": sr.get("mailbox_id", mid),
                    "name": sr.get("name"),
                    "embed_input_preview": _embed_input_for_reply(sr)[:200],
                }
            )
    return flat, meta_rows


def _batch_embed(
    client: OpenAI,
    texts: list[str],
    *,
    batch_size: int,
    max_retries: int,
) -> list[list[float]]:
    all_embeddings: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        chunk = texts[i : i + batch_size]
        attempt = 0
        while True:
            attempt += 1
            try:
                resp = client.embeddings.create(model=EMBEDDING_MODEL, input=chunk)
                # API returns embeddings in the same order as input.
                chunk_emb = [item.embedding for item in resp.data]
                if len(chunk_emb) != len(chunk):
                    raise RuntimeError(
                        f"embedding count mismatch: got {len(chunk_emb)}, expected {len(chunk)}"
                    )
                all_embeddings.extend(chunk_emb)
                break
            except RateLimitError as e:
                wait = min(60, 2**attempt)
                print(f"  Rate limited — sleeping {wait}s … ({e})")
                time.sleep(wait)
            except APIError as e:
                if attempt >= max_retries:
                    raise
                wait = min(30, 2**attempt)
                print(f"  API error — retry in {wait}s … ({e})")
                time.sleep(wait)
        print(f"  embedded {min(i + batch_size, len(texts))}/{len(texts)}")
    return all_embeddings


def _l2_normalize_rows(vecs: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms = np.maximum(norms, 1e-12)
    return (vecs / norms).astype(np.float32)


def main() -> None:
    parser = argparse.ArgumentParser(description="Embed saved replies snapshot for semantic search.")
    parser.add_argument("--input", "-i", default=DEFAULT_INPUT, help="Path to saved_replies JSON")
    parser.add_argument(
        "--vectors-out",
        default=DEFAULT_VECTORS_OUT,
        help="Output .npy path for float32 matrix",
    )
    parser.add_argument(
        "--meta-out",
        default=DEFAULT_META_OUT,
        help="Output .json path for metadata",
    )
    parser.add_argument(
        "--mailbox-id",
        type=int,
        default=DEFAULT_MAILBOX_ID,
        metavar="ID",
        help=f"Only embed replies for this mailbox (default: {DEFAULT_MAILBOX_ID}).",
    )
    parser.add_argument(
        "--all-mailboxes-in-snapshot",
        action="store_true",
        help="Embed every mailbox present in the snapshot (ignores --mailbox-id).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=64,
        metavar="N",
        help="Texts per OpenAI embeddings request (default: 64)",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=8,
        help="Max retries per batch on transient API errors",
    )
    args = parser.parse_args()

    key = os.getenv("OPENAI_API_KEY")
    if not key:
        print("ERROR: OPENAI_API_KEY is not set.", file=sys.stderr)
        sys.exit(1)

    in_path = os.path.abspath(args.input)
    if not os.path.isfile(in_path):
        print(f"ERROR: input file not found: {in_path}", file=sys.stderr)
        sys.exit(1)

    with open(in_path, encoding="utf-8") as f:
        snapshot = json.load(f)

    replies, meta_rows = _flatten_replies(
        snapshot,
        mailbox_id=None if args.all_mailboxes_in_snapshot else args.mailbox_id,
    )
    if not replies:
        print("ERROR: no saved replies to embed (check --mailbox-id and snapshot).", file=sys.stderr)
        sys.exit(1)

    texts = [_embed_input_for_reply(r) for r in replies]

    print(f"Embedding {len(texts)} saved replies with {EMBEDDING_MODEL} …")
    client = OpenAI(api_key=key)
    embeddings = _batch_embed(
        client,
        texts,
        batch_size=max(1, args.batch_size),
        max_retries=max(1, args.max_retries),
    )

    vecs = np.asarray(embeddings, dtype=np.float32)
    vecs = _l2_normalize_rows(vecs)
    dim = int(vecs.shape[1])

    for i, row in enumerate(meta_rows):
        row["index"] = i

    payload = {
        "embedding_model": EMBEDDING_MODEL,
        "dimensions": dim,
        "normalized": True,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "source_path": in_path,
        "source_fetched_at": snapshot.get("fetched_at"),
        "mailbox_filter": None if args.all_mailboxes_in_snapshot else args.mailbox_id,
        "all_mailboxes_in_snapshot": bool(args.all_mailboxes_in_snapshot),
        "row_count": len(meta_rows),
        "rows": meta_rows,
    }

    vec_path = os.path.abspath(args.vectors_out)
    meta_path = os.path.abspath(args.meta_out)
    os.makedirs(os.path.dirname(vec_path), exist_ok=True)
    os.makedirs(os.path.dirname(meta_path), exist_ok=True)

    np.save(vec_path, vecs)
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"Wrote {vec_path}  shape={vecs.shape}")
    print(f"Wrote {meta_path}")


if __name__ == "__main__":
    main()
