"""Retrieval tests: the ranking half of the read surface.
Two kinds of assertion live here. The mechanical ones (BM25 finds an identifier,
the cache invalidates when content moves, a dead embedder degrades instead of
failing) protect the feature. The security ones matter more: ranking must never
see an artifact the caller may not read, so no score, trace or count can leak a
candidate's existence to a reader without candidate scope.
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

# Locate the checkout root by looking for the package itself instead of counting
# parent directories: a fixed depth breaks the moment the tree is laid out
# differently (a clone, a worktree, a CI checkout), and the failure looks like a
# missing package rather than a wrong path.
_ROOT = next(path for path in Path(__file__).resolve().parents if (path / "AI_Platform").is_dir())
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import json
import tempfile
import unittest
# Retrieval runs lexical-only in unit tests: fast, deterministic, and independent of
# whether a model server happens to be running on the machine.
os.environ.setdefault("INTELLIGENCE_EMBED_DISABLE", "1")
from AI_Platform.intelligence.experimental.api.server import default_actors  # noqa: E402
from AI_Platform.intelligence.gateway.retrieval import (  # noqa: E402
    BM25, EmbeddingCache, NoopReranker, OllamaEmbedder, RetrievalUnavailable,
    Retriever, cosine, prefixes_for, rrf, split_passages, tokenize,
)
from AI_Platform.intelligence.gateway.service import IntelligenceGateway  # noqa: E402
TRUSTED = "local-agent"
def note(artifact_id: str, title: str, content: str, tags: list[str] | None = None) -> dict:
    now = "2026-09-20T00:00:00Z"
    return {
        "id": artifact_id, "kind": "knowledge", "scope": "domain", "status": "candidate",
        "version": "1.0.0", "title": title, "content": content, "created_by": TRUSTED,
        "created_at": now, "updated_at": now,
        "source": [{"type": "session_evidence", "retrieved_at": now}],
        "provenance": [{"type": "mcp_write_surface", "created_at": now, "agent": TRUSTED}],
        "verified": False, "verified_by": None, "verified_at": None,
        "applies_to": ["hermes"], "compatibility": ["test"], "expires_at": None,
        "review_interval_days": 90, "tests": [], "evidence": [],
        "metadata": {"name": artifact_id, "tags": tags or [], "permissions": ["read-only"]},
    }
class TokenizerTests(unittest.TestCase):
    def test_identifiers_stay_whole(self) -> None:
        tokens = tokenize("See pit-available-time-semantics for details")
        self.assertIn("pit-available-time-semantics", tokens)
        self.assertIn("available", tokens)
    def test_versions_and_codes_do_not_decay(self) -> None:
        self.assertIn("v1.1.0", tokenize("fixed in v1.1.0"))
        self.assertIn("403", tokenize("the gateway returns 403"))
    def test_chinese_is_indexed_as_bigrams(self) -> None:
        """Without a segmentation model, bigrams are what make CJK searchable."""
        tokens = tokenize("自动准入")
        self.assertIn("自动", tokens)
        self.assertIn("准入", tokens)
class LexicalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.index = BM25().fit({
            "pit": [("pit-available-time-semantics", 3.0), ("分时数据的可用时间与业务日期不同", 1.0)],
            "other": [("unrelated-note", 3.0), ("关于备份与恢复演练的说明", 1.0)],
        })
    def test_an_identifier_query_finds_its_artifact(self) -> None:
        scores = self.index.score("pit-available-time-semantics")
        self.assertEqual(max(scores, key=scores.get), "pit")
    def test_a_chinese_query_matches_chinese_content(self) -> None:
        scores = self.index.score("业务日期")
        self.assertIn("pit", scores)
    def test_unmatched_terms_produce_no_scores(self) -> None:
        self.assertEqual(self.index.score("zzzz-nothing-here"), {})
class FusionTests(unittest.TestCase):
    def test_rrf_rewards_agreement_between_retrievers(self) -> None:
        fused = rrf([["a", "b", "c"], ["b", "a", "d"]], k=10)
        self.assertGreater(fused["a"], fused["c"])
        self.assertGreater(fused["b"], fused["d"])
    def test_weights_shift_the_fusion(self) -> None:
        lexical, vector = ["a", "b"], ["b", "a"]
        equal = rrf([lexical, vector], k=10)
        lexical_heavy = rrf([lexical, vector], k=10, weights=[3.0, 0.1])
        self.assertAlmostEqual(equal["a"], equal["b"])
        self.assertGreater(lexical_heavy["a"], lexical_heavy["b"])
    def test_a_zero_weight_drops_that_ranking(self) -> None:
        fused = rrf([["a"], ["b"]], k=10, weights=[1.0, 0.0])
        self.assertIn("a", fused)
        self.assertNotIn("b", fused)
    def test_cosine_behaviour(self) -> None:
        self.assertAlmostEqual(cosine([1, 0], [1, 0]), 1.0)
        self.assertAlmostEqual(cosine([1, 0], [0, 1]), 0.0)
        self.assertEqual(cosine([], [1]), 0.0)
        self.assertEqual(cosine([1, 2], [1, 2, 3]), 0.0)
class FakeEmbedder:
    """Deterministic vectors: 'query about X' is close to the doc tagged X."""
    def __init__(self, vectors: dict[str, list[float]]) -> None:
        self.vectors = vectors
        self.calls = 0
    def embed(self, texts, role="document"):
        self.calls += 1
        out = []
        for text in texts:
            key = "a" if "alpha" in text or "阿尔法" in text else "b" if "beta" in text or "贝塔" in text else "x"
            out.append([1.0, 0.0] if key == "a" else [0.0, 1.0] if key == "b" else [0.5, 0.5])
        return out
class BrokenEmbedder:
    def embed(self, texts, role="document"):
        raise RetrievalUnavailable("embedder is down")
def documents() -> dict[str, dict]:
    return {
        "knowledge/alpha": {"digest": "d-alpha", "fields": [("alpha-note", 3.0), ("about alpha 阿尔法", 1.0)],
                            "embed_text": "alpha 阿尔法", "rerank_text": "alpha 阿尔法"},
        "knowledge/beta": {"digest": "d-beta", "fields": [("beta-note", 3.0), ("about beta 贝塔", 1.0)],
                           "embed_text": "beta 贝塔", "rerank_text": "beta 贝塔"},
    }
class RetrieverTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.cache_path = Path(self._tmp.name) / "qa" / "embeddings.json"
    def tearDown(self) -> None:
        self._tmp.cleanup()
    def test_hybrid_ranks_with_both_signals(self) -> None:
        cache = EmbeddingCache(self.cache_path, "fake")
        retriever = Retriever(cache=cache, embedder=FakeEmbedder({}))
        results, summary = retriever.rank("query about alpha", documents())
        self.assertEqual(results[0]["key"], "knowledge/alpha")
        self.assertEqual(summary["mode"], "hybrid")
        self.assertIn("lexical_rank", results[0]["why"])
        self.assertIn("vector_rank", results[0]["why"])
    def test_a_dead_embedder_degrades_to_lexical(self) -> None:
        """A knowledge base must not stop answering because a model server restarted."""
        retriever = Retriever(cache=EmbeddingCache(self.cache_path, "fake"), embedder=BrokenEmbedder())
        results, summary = retriever.rank("alpha", documents())
        self.assertEqual(summary["mode"], "lexical")
        self.assertIn("embeddings unavailable", summary["note"])
        self.assertEqual(results[0]["key"], "knowledge/alpha")
    def test_embedding_is_cached_by_digest_and_reused(self) -> None:
        embedder = FakeEmbedder({})
        retriever = Retriever(cache=EmbeddingCache(self.cache_path, "fake"), embedder=embedder)
        retriever.rank("alpha", documents())
        after_first = embedder.calls  # one batched call for the documents, one for the query
        retriever.rank("alpha", documents())
        self.assertEqual(embedder.calls - after_first, 1,
                         "a repeat search embeds only the query; unchanged artifacts must not be re-embedded")
    def test_changing_a_model_invalidates_the_cache(self) -> None:
        """Mixing vectors from two models in one similarity computation is nonsense."""
        cache = EmbeddingCache(self.cache_path, "model-one")
        cache.put("d-alpha", [[1.0, 0.0]]); cache.save(force=True)
        self.assertIsNone(EmbeddingCache(self.cache_path, "model-two").get("d-alpha"))
    def test_vectors_for_vanished_artifacts_are_pruned(self) -> None:
        cache = EmbeddingCache(self.cache_path, "fake")
        cache.put("d-gone", [[1.0, 0.0]]); cache.put("d-alpha", [[1.0, 0.0]])
        cache.prune({"d-alpha"})
        self.assertIsNone(cache.get("d-gone"))
        self.assertIsNotNone(cache.get("d-alpha"))
    def test_the_embed_budget_is_respected(self) -> None:
        """A first search after a bulk import must not stall the read path."""
        cache = EmbeddingCache(self.cache_path, "fake")
        retriever = Retriever(cache=cache, embedder=FakeEmbedder({}))
        results, summary = retriever.rank("alpha", documents(), embed_budget=1)
        self.assertEqual(len(cache._vectors), 1)
        self.assertIn("not embedded yet", summary.get("note", ""))
    def test_an_empty_corpus_is_not_an_error(self) -> None:
        results, summary = Retriever(cache=None, embedder=FakeEmbedder({})).rank("anything", {})
        self.assertEqual(results, [])
        self.assertEqual(summary["mode"], "empty")
    def test_rerankers_must_return_a_usable_payload(self) -> None:
        class BadReranker:
            name = "bad"
            def rerank(self, query, documents):
                return None  # a failed rerank must fall back, not crash
        retriever = Retriever(cache=None, embedder=None, reranker=BadReranker())
        results, summary = retriever.rank("alpha", documents())
        self.assertEqual(results[0]["key"], "knowledge/alpha")
        self.assertNotIn("rerank", summary["mode"])
class OllamaContractTests(unittest.TestCase):
    def test_task_prefixes_follow_the_model_family(self) -> None:
        """The prefix is part of nomic's contract; models without one get none."""
        self.assertEqual(prefixes_for("nomic-embed-text"), ("search_document: ", "search_query: "))
        self.assertEqual(prefixes_for("bge-m3"), ("", ""))
    def test_an_unreachable_server_degrades_rather_than_raises_through(self) -> None:
        embedder = OllamaEmbedder(model="bge-m3", host="http://127.0.0.1:9", timeout=1.0)
        with self.assertRaises(RetrievalUnavailable):
            embedder.embed(["x"])
class SearchSurfaceTests(unittest.TestCase):
    """Ranking must never see, count or hint at an artifact the caller may not read."""
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.gateway = IntelligenceGateway(self.root, auto_admission="enforce")
        self.actors = default_actors()
        self.gateway.submit_candidate(self.actors[TRUSTED], note(
            "public-note", "Public note", "关于备份与恢复演练的说明 恢复过才算数"))
        for artifact_id in ("secret-note",):
            self.gateway.submit_candidate(self.actors[TRUSTED], note(
                artifact_id, "Secret note", "同样讲备份与恢复演练 但这条还没批准 alpha beta"))
        self.gateway.validate_candidate(self.actors["local-qa"], "public-note", "knowledge")
        self.gateway.approve(self.actors["local-human"], "public-note", "knowledge")
    def tearDown(self) -> None:
        self._tmp.cleanup()
    def test_a_reader_without_candidate_scope_cannot_reach_a_candidate(self) -> None:
        matches, summary = self.gateway.retrieve(self.actors["local-hermes"], "knowledge", "备份 恢复演练")
        self.assertEqual([item["id"] for item in matches], ["public-note"])
        self.assertEqual(summary["candidates"], 1, "the candidate must not even be counted")
    def test_a_candidate_reader_can_reach_both(self) -> None:
        matches, _ = self.gateway.retrieve(self.actors["local-hermes-writer"], "knowledge", "备份 恢复演练")
        self.assertEqual({item["id"] for item in matches}, {"public-note", "secret-note"})
    def test_results_carry_a_trace_of_why_they_ranked(self) -> None:
        matches, summary = self.gateway.retrieve(self.actors["local-hermes"], "knowledge", "备份")
        self.assertTrue(matches)
        self.assertIn("score", matches[0])
        self.assertIn("lexical_rank", matches[0]["why"])
        self.assertIn("mode", summary)
    def test_a_query_with_nothing_to_match_is_recorded_as_a_miss(self) -> None:
        """Vocabulary gaps become visible; that is the most actionable telemetry here."""
        self.gateway.search(self.actors["local-hermes"], "knowledge", "完全不相干的查询词")
        usage = self.gateway.usage_summary()
        self.assertTrue(any("完全不相干" in key for key in usage["misses"]))
    def test_search_still_records_usage(self) -> None:
        self.gateway.search(self.actors["local-hermes"], "knowledge", "备份")
        self.assertIn("knowledge/public-note", self.gateway.usage_summary()["surfaced"])
    def test_limits_are_still_enforced(self) -> None:
        with self.assertRaises(ValueError):
            self.gateway.retrieve(self.actors["local-hermes"], "knowledge", "备份", max_items=0)
class PassageTests(unittest.TestCase):
    """Splitting, and the reason it exists: a broad document must not swallow a
    specific question. Chunking also keeps a document inside the embedding model's
    2048-token window, which whole-document embedding silently exceeded."""
    def test_split_is_deterministic_and_bounded(self) -> None:
        text = "。".join(f"第{i}句讲的是完全不同的内容" for i in range(60))
        first = split_passages(text)
        self.assertEqual(first, split_passages(text), "cache maps vectors back by index; splits must repeat")
        self.assertGreater(len(first), 1)
        self.assertTrue(all(len(piece) <= 1400 for piece in first))
    def test_edge_cases(self) -> None:
        self.assertEqual(split_passages(""), [])
        self.assertEqual(len(split_passages("一句话。")), 1)
        self.assertEqual(len(split_passages("第一段。\n\n第二段。\n\n第三段。")), 1, "tiny paragraphs merge")
        monster = split_passages("y" * 5000)
        self.assertGreater(len(monster), 1, "an unbroken 5000-char block must still be cut")
    def test_a_long_document_competes_passage_by_passage(self) -> None:
        class KeywordEmbedder:
            """Bag-of-words-ish: a passage scores on what it actually contains."""
            def embed(self, texts, role="document"):
                out = []
                for text in texts:
                    out.append([1.0 if "target" in text else 0.0,
                                1.0 if "noise" in text else 0.0,
                                0.1])
                return out
        broad = {"knowledge/broad": {
            "digest": "d-broad", "fields": [("broad-note", 3.0)],
            "embed_text": ("noise " * 300) + "\n\ntarget lives here\n\n" + ("noise " * 300),
            "rerank_text": "broad"}}
        specific = {"knowledge/specific": {
            "digest": "d-specific", "fields": [("specific-note", 3.0)],
            "embed_text": "target", "rerank_text": "target"}}
        with tempfile.TemporaryDirectory() as scratch:
            cache = EmbeddingCache(Path(scratch) / "qa" / "embeddings.json", "fake")
            retriever = Retriever(cache=cache, embedder=KeywordEmbedder(), rrf_k=10, weights=[1.0, 0.25])
            results, _ = retriever.rank("target", {**broad, **specific})
            self.assertEqual(results[0]["key"], "knowledge/specific")
            by_key = {row["key"]: row for row in results}
            self.assertGreater(len(results), 1)
            self.assertIn("passage", by_key["knowledge/broad"]["why"],
                          "a chunked result should say which passage matched")
    def test_a_cache_from_the_old_format_is_dropped_not_reinterpreted(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            path = Path(scratch) / "qa" / "embeddings.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"model": "fake", "dimension": 2,
                                        "vectors": {"d-old": [1.0, 0.0]}}), encoding="utf-8")
            cache = EmbeddingCache(path, "fake")
            self.assertIsNone(cache.get("d-old"),
                              "one vector per document would be misread as a single-passage document")
    def test_chunking_off_keeps_one_passage(self) -> None:
        document = {"digest": "d", "fields": [], "embed_text": "a.\n\nb.\n\nc.", "rerank_text": ""}
        retriever = Retriever(cache=None, embedder=None, chunk=False)
        self.assertEqual(retriever._passages(document), ["a.\n\nb.\n\nc."])
        retriever = Retriever(cache=None, embedder=None, chunk=True)
        self.assertEqual(len(retriever._passages(document)), 1)
if __name__ == "__main__":
    unittest.main(verbosity=2)
