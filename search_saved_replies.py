"""
Semantic search over saved replies using the embedding index from build_saved_reply_embeddings.py.

Environment:
  OPENAI_API_KEY

Examples:
  .venv/bin/python search_saved_replies.py -q "customer wants to cancel Apple subscription"
  .venv/bin/python search_saved_replies.py "cancel apple" --top-k 10
  echo "refund request" | .venv/bin/python search_saved_replies.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np
from dotenv import load_dotenv
from openai import OpenAI

_SUPPORT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(_SUPPORT_DIR)
load_dotenv(os.path.join(_SUPPORT_DIR, ".env"))
load_dotenv(os.path.join(ROOT_DIR, ".env"))

EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_VECTORS = os.path.join(_SUPPORT_DIR, "data", "saved_replies.emb.npy")
DEFAULT_META = os.path.join(_SUPPORT_DIR, "data", "saved_replies.emb.json")


def _l2_normalize(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    if n < 1e-12:
        return v.astype(np.float32)
    return (v / n).astype(np.float32)


def _resolve_query_text(args: argparse.Namespace) -> str:
    text = (args.query or "").strip()
    if not text:
        text = " ".join(args.query_positional).strip()
    if not text and not sys.stdin.isatty():
        text = sys.stdin.read().strip()
    return text


def main() -> None:
    parser = argparse.ArgumentParser(description="Search saved reply embeddings (cosine ~ dot product on normalized vectors).")
    parser.add_argument("--query", "-q", default=None, metavar="TEXT", help="Search query")
    parser.add_argument(
        "query_positional",
        nargs="*",
        metavar="WORD",
        help="Query words (if not using -q or stdin)",
    )
    parser.add_argument("--top-k", "-k", type=int, default=5, metavar="N")
    parser.add_argument("--vectors", default=DEFAULT_VECTORS, help="Path to .npy matrix")
    parser.add_argument("--meta", default=DEFAULT_META, help="Path to .emb.json metadata")
    args = parser.parse_args()

    key = os.getenv("OPENAI_API_KEY")
    if not key:
        print("ERROR: OPENAI_API_KEY is not set.", file=sys.stderr)
        sys.exit(1)

    vec_path = os.path.abspath(args.vectors)
    meta_path = os.path.abspath(args.meta)
    if not os.path.isfile(vec_path) or not os.path.isfile(meta_path):
        print(
            f"ERROR: missing index files. Run build_saved_reply_embeddings.py first.\n"
            f"  vectors: {vec_path}\n"
            f"  meta:    {meta_path}",
            file=sys.stderr,
        )
        sys.exit(1)

    qtext = _resolve_query_text(args)
    if not qtext:
        parser.print_help()
        print("\nError: provide --query, positional words, or pipe text on stdin.", file=sys.stderr)
        sys.exit(2)

    with open(meta_path, encoding="utf-8") as f:
        meta = json.load(f)

    rows = meta.get("rows") or []
    vecs = np.load(vec_path).astype(np.float32)
    if vecs.shape[0] != len(rows):
        print(
            f"ERROR: row count mismatch — matrix has {vecs.shape[0]} rows, meta has {len(rows)}.",
            file=sys.stderr,
        )
        sys.exit(1)

    model = meta.get("embedding_model")
    if model and model != EMBEDDING_MODEL:
        print(
            f"Warning: meta embedding_model is {model!r}, this script uses {EMBEDDING_MODEL!r}.",
            file=sys.stderr,
        )

    client = OpenAI(api_key=key)
    resp = client.embeddings.create(model=EMBEDDING_MODEL, input=qtext)
    q = _l2_normalize(np.asarray(resp.data[0].embedding, dtype=np.float32))
    if int(meta.get("dimensions") or vecs.shape[1]) != q.shape[0]:
        print("ERROR: query vector dimension does not match index.", file=sys.stderr)
        sys.exit(1)

    scores = vecs @ q
    k = max(1, min(args.top_k, len(rows)))
    top_idx = np.argpartition(-scores, k - 1)[:k]
    top_idx = top_idx[np.argsort(-scores[top_idx])]

    print(f"query: {qtext!r}")
    print(f"model: {EMBEDDING_MODEL}  |  index: {meta_path}  |  rows: {len(rows)}")
    print()
    for rank, i in enumerate(top_idx, start=1):
        r = rows[int(i)]
        sid = r.get("saved_reply_id")
        name = r.get("name")
        mb = r.get("mailbox_id")
        s = float(scores[int(i)])
        print(f"{rank}. score={s:.4f}  id={sid}  mailbox={mb}  name={name!r}")


if __name__ == "__main__":
    main()
