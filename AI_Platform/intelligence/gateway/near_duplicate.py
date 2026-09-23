"""Near-duplicate screening across the live store.

Why this is a report and not a gate: `submit_candidate` already refuses text that is
*byte-identical* to another live record, and a hash is the right tool for that. "The same
thing said differently" is the kind that actually accumulates in a knowledge base, and no
hash can decide it - but a human does not have to decide it either, because the gateway
already ranks text against text with the production retriever (BM25 + bge-m3 vectors +
weighted RRF). So this scan asks the read path's own question - *how close is this to what
we already have?* - and reports the pairs above a threshold.

Deliberately no refusal and no threshold in the write path: a near copy is sometimes
intentional (a Chinese restatement of an English original, a project-scoped variant of a
general rule), and blocking a submission on a similarity score nobody has calibrated
would trade a review cost for a refusal cost with worse failure modes. Output is a list
for a human; the weekly job decides whether anyone hears about it.

It screens with `local-qa` because that identity reads candidates as well as approved
records, and a duplicate forming *among candidates* is the earlier and cheaper catch.

    python3 near_duplicate.py                     # one line per suspicious pair
    python3 near_duplicate.py --threshold 0.95 --json
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
from typing import Any

AI_PLATFORM = pathlib.Path(os.environ.get(
    "INTELLIGENCE_PLATFORM", "/mnt/d/intelligence-layer/AI_Platform"))
if str(AI_PLATFORM) not in sys.path:
    sys.path.insert(0, str(AI_PLATFORM))

DEFAULT_ROOT = AI_PLATFORM / "intelligence"
KINDS = ("knowledge", "experience", "skill", "source")
# Screening identity: needs read:candidate as well as read:approved.
SCREENER = "local-qa"


def scan(store: Any, actor: Any, rank_limit: int = 2,
         kinds: tuple[str, ...] = KINDS, neighbours: int = 4) -> dict[str, Any]:
    """Near-duplicate pairs, judged by *rank agreement between both retrievers*.

    The first version of this function thresholded on the fused score and was useless: that
    score is the RRF value (~0.11 for a perfect hit, ~0.016 for a fifth-place vector-only
    match), not a similarity, so no threshold on it means what a reader would assume. Two
    fixes were possible - recompute cosine similarity beside the ranker, or use the signal
    the ranker already emits. The second is better: `why` carries `lexical_rank` and
    `vector_rank`, and "the other record is the nearest hit for this text in *both* the
    lexical and the semantic retriever" is precisely the question "is this a near copy or
    just the same topic?".

    Requiring both ranks means a lexical-only or vector-only match is *not* reported: shared
    vocabulary alone is exactly the false positive that would make the report ignorable.

    Returns ``{"pairs", "vector_retriever_ran", "documents"}``. The second field exists
    because the criterion is unsatisfiable without the vector half: with the embedder down
    the scan finds nothing and would otherwise look exactly like a clean corpus. A screen
    that could not run has to say so.
    """
    findings: dict[tuple[str, str], dict[str, Any]] = {}
    vector_ran = False
    documents_seen = 0
    for kind in kinds:
        documents = store._search_documents(actor, kind, None)
        documents_seen += len(documents)
        if len(documents) < 2:
            continue
        for key, document in documents.items():
            artifact = document["artifact"]
            probe = f"{artifact.get('title') or ''}\n{(artifact.get('content') or '')[:1500]}"
            ranked, _ = store.retriever.rank(probe, documents, limit=neighbours, embed_budget=8)
            best: dict[str, Any] | None = None
            for item in ranked:
                why = item.get("why") or {}
                if isinstance(why.get("vector_rank"), int):
                    vector_ran = True
                if item["key"] == key:
                    continue
                lexical, vector = why.get("lexical_rank"), why.get("vector_rank")
                if not isinstance(lexical, int) or not isinstance(vector, int):
                    continue  # one retriever matched: same vocabulary, not the same text
                if lexical <= rank_limit and vector <= rank_limit:
                    best = {"rrf": round(float(item["score"]), 4),
                            "lexical_rank": lexical, "vector_rank": vector,
                            "neighbour": item["key"]}
                    break
            if best is None:
                continue
            pair = tuple(sorted((key, best["neighbour"])))
            entry = findings.get(pair)
            if entry is None or best["rrf"] > entry["rrf"]:
                findings[pair] = {"left": pair[0], "right": pair[1], **{k: v for k, v in best.items() if k != "neighbour"}}
    return {
        "pairs": sorted(findings.values(), key=lambda entry: -entry["rrf"]),
        "vector_retriever_ran": vector_ran,
        "documents": documents_seen,
    }


def main(argv: list[str] | None = None) -> int:
    from intelligence.experimental.api.server import default_actors
    from intelligence.gateway.service import IntelligenceGateway

    parser = argparse.ArgumentParser(description="Screen live artifacts for near-duplicates.")
    parser.add_argument("--store", default=str(DEFAULT_ROOT))
    parser.add_argument("--rank-limit", type=int, default=2,
                        help="report a pair only when both retrievers rank the neighbour this high (default 2)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    gateway = IntelligenceGateway(pathlib.Path(args.store).expanduser().resolve())
    actors = default_actors()
    if SCREENER not in actors:
        print(f"unknown screening identity {SCREENER!r}")
        return 2
    report = scan(gateway, actors[SCREENER], rank_limit=args.rank_limit)
    pairs = report["pairs"]
    if args.json:
        print(json.dumps(report, ensure_ascii=False))
        return 0
    if not report["vector_retriever_ran"]:
        # Louder than "no duplicates found", because it is a different statement.
        print("⚠️ 近似重复检查本次没跑成：向量检索没有参与（embedder 不可用？）。"
              "只靠词法判不了「换个说法」，所以这次的「没发现」不算数。")
    if pairs:
        print(f"近似重复 {len(pairs)} 对（判定：词法与向量都把对方排在前 {args.rank_limit}）：")
        for entry in pairs:
            print(f"  {entry['left']}  <->  {entry['right']}"
                  f"   （词法第 {entry['lexical_rank']} / 向量第 {entry['vector_rank']}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
