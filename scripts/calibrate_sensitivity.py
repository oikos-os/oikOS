"""One-time calibration script for the cosine sensitivity threshold.

Usage:
    python -m scripts.calibrate_sensitivity

Computes identity-tier centroid from LanceDB, runs test queries through
the embedding model, and reports cosine similarity distributions to help
determine the optimal ROUTING_COSINE_SENSITIVITY_THRESHOLD.
"""

from __future__ import annotations

import sys
sys.path.insert(0, ".")

from core.config import TABLE_NAME
from core.embedder import embed_single
from core.indexer import get_db, _table_exists
from core.sensitivity import cosine_similarity

# ── Test queries ─────────────────────────────────────────────────────

SOVEREIGN_QUERIES = [
    "what are my core beliefs about creative work",
    "what are my current goals and priorities",
    "tell me about my music production projects",
    "what strategies am I using right now",
    "what have I learned recently",
    "what are my biggest challenges",
    "describe my mission and purpose",
    "what mental models do I use",
    "what narratives shape my identity",
    "what ideas am I exploring",
    "how is my financial situation",
    "what are my health and fitness protocols",
    "what is my communication style",
    "describe my political and philosophical views",
    "what are my active projects and their status",
    "what decisions have I been avoiding",
    "what patterns keep repeating in my life",
    "am I making progress on my goals",
    "what should I be working on right now",
    "what do I believe about technology and sovereignty",
]

NON_SOVEREIGN_QUERIES = [
    "explain quantum computing in simple terms",
    "how does TCP handshake work",
    "what is the capital of France",
    "write a Python function to sort a list",
    "explain the difference between REST and GraphQL",
    "what is photosynthesis",
    "how do neural networks learn",
    "explain the pythagorean theorem",
    "what causes inflation in an economy",
    "describe the water cycle",
    "how does DNS resolution work",
    "what is the difference between a stack and a queue",
    "explain how RSA encryption works",
    "what is the speed of light",
    "how do vaccines work",
    "explain object oriented programming",
    "what is the second law of thermodynamics",
    "how does git branching work",
    "what is a bloom filter",
    "explain the CAP theorem",
]


def main():
    db = get_db()
    if not _table_exists(db, TABLE_NAME):
        print("ERROR: No vault index found. Run 'oikos index' first.")
        return

    table = db.open_table(TABLE_NAME)
    rows = table.search().where("tier = 'core'").select(["vector"]).to_list()

    if not rows:
        print("ERROR: No identity-tier vectors found in index.")
        return

    # Compute centroid
    dims = len(rows[0]["vector"])
    centroid = [0.0] * dims
    for row in rows:
        for i, v in enumerate(row["vector"]):
            centroid[i] += v
    centroid = [c / len(rows) for c in centroid]

    print(f"Identity centroid computed from {len(rows)} vectors ({dims} dims).\n")

    # Score sovereign queries
    print("=== SOVEREIGN QUERIES ===")
    sov_scores = []
    for q in SOVEREIGN_QUERIES:
        vec = embed_single(q)
        sim = cosine_similarity(vec, centroid)
        sov_scores.append(sim)
        print(f"  {sim:.4f}  {q}")

    print()

    # Score non-sovereign queries
    print("=== NON-SOVEREIGN QUERIES ===")
    nonsov_scores = []
    for q in NON_SOVEREIGN_QUERIES:
        vec = embed_single(q)
        sim = cosine_similarity(vec, centroid)
        nonsov_scores.append(sim)
        print(f"  {sim:.4f}  {q}")

    print()

    # Statistics
    sov_min, sov_max, sov_mean = min(sov_scores), max(sov_scores), sum(sov_scores) / len(sov_scores)
    nonsov_min, nonsov_max, nonsov_mean = min(nonsov_scores), max(nonsov_scores), sum(nonsov_scores) / len(nonsov_scores)

    print("=== DISTRIBUTION ===")
    print(f"  Sovereign:     min={sov_min:.4f}  max={sov_max:.4f}  mean={sov_mean:.4f}")
    print(f"  Non-sovereign: min={nonsov_min:.4f}  max={nonsov_max:.4f}  mean={nonsov_mean:.4f}")
    print(f"  Gap:           {sov_mean - nonsov_mean:.4f}")
    print()

    # Recommend threshold (midpoint of means)
    recommended = (sov_mean + nonsov_mean) / 2
    print(f"=== RECOMMENDED THRESHOLD: {recommended:.4f} ===")
    print(f"  Set ROUTING_COSINE_SENSITIVITY_THRESHOLD = {recommended:.2f} in core/config.py")


if __name__ == "__main__":
    main()
