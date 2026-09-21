"""Hybrid retrieval for the Intelligence Layer.

Why hybrid rather than "just vectors": this corpus is full of artifact ids
(`pit-available-time-semantics`), version strings (`v1.1.0`) and codes (`403`),
and dense embeddings are notoriously weak at exactly those tokens while lexical
matching is strong at them. The reverse holds for paraphrased intent, and this
corpus is written in Chinese while the default embedding model is English-first,
so neither retriever alone is trustworthy here.

Pipeline: BM25 (lexical) + embeddings (dense) -> reciprocal rank fusion -> optional
rerank. RRF is rank-based (Cormack et al., SIGIR'09, k=60) so it never has to
reconcile BM25's unbounded scores with cosine's [-1,1]; fusing by rank is what
makes the two retrievers safe to combine without per-corpus tuning.

Everything here is stdlib-only on purpose: the gateway runs under the system
python with no third-party packages, and at this corpus size brute-force cosine
over cached vectors is faster than the round trip to a vector store would be.
Revisit that when the corpus reaches thousands of chunks, not before.
"""
from __future__ import annotations

import json
import math
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

# ---------------------------------------------------------------- tokenisation

_IDENTIFIER = re.compile(r"[a-z0-9]+(?:[-_.][a-z0-9]+)+")
_WORD = re.compile(r"[a-z0-9]{2,}")
_CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")


def tokenize(text: str) -> list[str]:
    """Tokens that keep identifiers whole and still match Chinese text.

    Two corpus-specific decisions: (1) `pit-available-time-semantics` stays one
    token *and* contributes its parts, while `v1.1.0` does not decay into `v1`
    `1` `0`; (2) CJK has no word boundaries, so it is indexed as character
    bigrams - the cheap standard trick that makes lexical search work at all for
    a Chinese corpus without shipping a segmentation model.
    """
    lowered = (text or "").casefold()
    tokens: list[str] = []
    for identifier in _IDENTIFIER.findall(lowered):
        tokens.append(identifier)
        tokens.extend(part for part in re.split(r"[-_.]", identifier) if len(part) > 1)
    remainder = _IDENTIFIER.sub(" ", lowered)
    tokens.extend(_WORD.findall(remainder))
    for run in _CJK_RUN.findall(lowered):
        if len(run) == 1:
            tokens.append(run)
        else:
            tokens.extend(run[index:index + 2] for index in range(len(run) - 1))
    return tokens


# ---------------------------------------------------------------------- BM25

class BM25:
    """Okapi BM25 over weighted fields, with no external dependency.

    Field weights let an id match outrank a body mention, which matters when a
    query names an artifact: the id is the strongest available signal and plain
    BM25 over concatenated text would drown it in the body.
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self._doc_freq: dict[str, int] = {}
        self._freqs: dict[str, dict[str, float]] = {}
        self._lengths: dict[str, float] = {}
        self._average_length = 0.0

    def fit(self, documents: dict[str, Sequence[tuple[str, float]]]) -> "BM25":
        self._doc_freq, self._freqs, self._lengths = {}, {}, {}
        for key, fields in documents.items():
            counts: dict[str, float] = {}
            for text, weight in fields:
                for token in tokenize(text):
                    counts[token] = counts.get(token, 0.0) + weight
            self._freqs[key] = counts
            self._lengths[key] = sum(counts.values()) or 1.0
            for token in counts:
                self._doc_freq[token] = self._doc_freq.get(token, 0) + 1
        self._average_length = (sum(self._lengths.values()) / len(self._lengths)) if self._lengths else 1.0
        return self

    def distinctive(self, query: str) -> dict[str, float]:
        """Per document: the highest idf among the query tokens it matched.

        This is what makes a gate safe for a corpus full of identifiers. A raw BM25
        floor punishes short queries: `403` or `v2.0.1` carries little score mass, so
        a score threshold throws away exactly the queries lexical search exists for.
        Matching one *rare* token is the real signal - a token that appears in one
        document of eighteen (idf 2.5) means far more than one appearing in half of
        them (idf 0.8) - so the gate asks about distinctiveness, not magnitude.
        """
        total = len(self._freqs) or 1
        scored: dict[str, float] = {}
        for token in set(tokenize(query)):
            frequency = self._doc_freq.get(token)
            if not frequency:
                continue
            idf = math.log(1 + (total - frequency + 0.5) / (frequency + 0.5))
            for key in self._freqs:
                if token in self._freqs[key]:
                    scored[key] = max(scored.get(key, 0.0), idf)
        return scored

    def score(self, query: str) -> dict[str, float]:
        total = len(self._freqs) or 1
        scored: dict[str, float] = {}
        for token in tokenize(query):
            frequency = self._doc_freq.get(token)
            if not frequency:
                continue
            # Probabilistic idf with the usual +0.5 smoothing.
            idf = math.log(1 + (total - frequency + 0.5) / (frequency + 0.5))
            for key, counts in self._freqs.items():
                term_frequency = counts.get(token)
                if not term_frequency:
                    continue
                norm = 1 - self.b + self.b * (self._lengths[key] / self._average_length)
                scored[key] = scored.get(key, 0.0) + idf * (term_frequency * (self.k1 + 1)) / (term_frequency + self.k1 * norm)
        return scored


def rrf(rankings: Iterable[Sequence[str]], k: int = 60,
        weights: Sequence[float] | None = None) -> dict[str, float]:
    """Reciprocal Rank Fusion: sum of weight/(k + rank) over the input rankings.

    Rank-based fusion is why BM25 and cosine can be combined here at all: their
    scores live on incomparable scales, but their *orderings* are comparable.

    k is not a universal constant. The 60 from the original paper pools deep
    rankings of thousands of documents, where 1/(60+rank) still separates the head
    from the tail; on a corpus of a few dozen records every candidate lands in the
    top 20 of both retrievers, the terms flatten out, and the fusion degenerates
    into counting votes. Measure k per corpus - the eval harness sweeps it.

    Weights exist for the same reason: when one retriever is measurably weaker on
    this corpus, saying so explicitly beats pretending the two are equal.
    """
    fused: dict[str, float] = {}
    for order, ranking in enumerate(rankings):
        weight = 1.0 if not weights else weights[order] if order < len(weights) else 1.0
        if not weight:
            continue
        for position, key in enumerate(ranking, start=1):
            fused[key] = fused.get(key, 0.0) + weight / (k + position)
    return fused


def cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    norm_left = math.sqrt(sum(a * a for a in left))
    norm_right = math.sqrt(sum(b * b for b in right))
    if not norm_left or not norm_right:
        return 0.0
    return dot / (norm_left * norm_right)


# ------------------------------------------------------------------ passages

_SENTENCE_BREAK = re.compile(r"(?<=[。！？；!?;])\s*|\n+")


def split_passages(text: str, target: int = 600, hard_max: int = 1400) -> list[str]:
    """Cut a document into passages for embedding, deterministically.

    Two problems this solves at once. A long, broad document embeds to a single
    vector that sits near the middle of its topic, so it wins similarity against
    every specific question about that topic - chunking lets the one relevant
    paragraph compete instead of the whole document. And the embedding model has a
    2048-token window, so anything past it was previously invisible to the vector
    half; passages fit.

    Determinism is load-bearing: cached vectors are stored per passage *index*, so
    the same text must always cut the same way or a cached vector would be matched
    to the wrong passage. That is also why the split never depends on the model.
    """
    body = (text or "").strip()
    if not body:
        return []
    pieces: list[str] = []
    for block in re.split(r"\n\s*\n", body):
        block = block.strip()
        if not block:
            continue
        if len(block) <= target:
            pieces.append(block)
            continue
        # Longer than a passage: pack whole sentences up to `target` rather than
        # cutting mid-sentence, and only fragment a sentence that cannot fit even
        # the hard limit (there is no boundary left to respect at that point).
        buffer = ""
        for sentence in (part.strip() for part in _SENTENCE_BREAK.split(block)):
            if not sentence:
                continue
            if len(sentence) > hard_max:
                if buffer:
                    pieces.append(buffer)
                    buffer = ""
                pieces.extend(sentence[start:start + hard_max]
                              for start in range(0, len(sentence), hard_max))
                continue
            if len(buffer) + len(sentence) + 1 <= target:
                buffer = f"{buffer}\n{sentence}".strip()
            else:
                if buffer:
                    pieces.append(buffer)
                buffer = sentence
        if buffer:
            pieces.append(buffer)
    # Merge undersized neighbours so a document of many short paragraphs does not
    # become many thin passages.
    merged: list[str] = []
    for piece in pieces:
        if merged and len(merged[-1]) + len(piece) + 1 <= target:
            merged[-1] = f"{merged[-1]}\n{piece}"
        else:
            merged.append(piece)
    return merged


# ----------------------------------------------------------------- embeddings

class RetrievalUnavailable(RuntimeError):
    """Raised when a retrieval component cannot answer; callers degrade, never fail."""


# The embedding model is English-first, so the task prefix is part of its
# documented contract, not decoration. Models that do not use prefixes (bge-m3,
# e5 with its own template) simply get an empty prefix.
_PREFIXES = {
    "nomic": ("search_document: ", "search_query: "),
    "": ("", ""),
}


def prefixes_for(model: str) -> tuple[str, str]:
    family = "nomic" if "nomic" in (model or "").casefold() else ""
    return _PREFIXES[family]


class OllamaEmbedder:
    """Embeddings from a local ollama server, over stdlib HTTP."""

    def __init__(self, model: str = "nomic-embed-text", host: str | None = None,
                 timeout: float = 20.0, context_chars: int = 6000) -> None:
        self.model = model
        self.host = (host or os.environ.get("INTELLIGENCE_OLLAMA", "http://127.0.0.1:11434")).rstrip("/")
        self.timeout = timeout
        # nomic-embed-text has a 2048-token window; truncating here keeps a long
        # skill from being silently embedded as its first half. Anything past the
        # window is still reachable through BM25, which is a reason to keep both.
        self.context_chars = context_chars
        self.document_prefix, self.query_prefix = prefixes_for(model)

    def embed(self, texts: Sequence[str], role: str = "document") -> list[list[float]]:
        if not texts:
            return []
        prefix = self.query_prefix if role == "query" else self.document_prefix
        payload = {"model": self.model, "input": [prefix + text[: self.context_chars] for text in texts]}
        request = urllib.request.Request(
            f"{self.host}/api/embed",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.load(response)
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
            raise RetrievalUnavailable(f"ollama embed failed: {type(error).__name__}: {error}") from error
        vectors = body.get("embeddings")
        if not isinstance(vectors, list) or len(vectors) != len(texts):
            raise RetrievalUnavailable("ollama embed returned an unexpected payload")
        return vectors


PASSAGE_FORMAT = "passages-v1"


class EmbeddingCache:
    """Passage vectors keyed by artifact digest.

    Keying by digest means a content edit re-embeds automatically and an
    unchanged artifact never pays twice - the same fingerprint that evidence is
    bound to, reused so there is one notion of "this artifact changed".
    A model swap invalidates the whole cache: mixing vectors from two models in
    one similarity computation silently produces nonsense.
    """

    def __init__(self, path: Path, model: str, dimension: int | None = None) -> None:
        self.path = path
        self.model = model
        self.dimension = dimension
        self._vectors: dict[str, list[list[float]]] = {}
        self._dirty = False
        if path.is_file():
            try:
                state = json.loads(path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                state = {}
            # An older format (one vector per document) would silently be read as a
            # one-passage document, so it is dropped rather than reinterpreted.
            if state.get("model") == model and state.get("format") == PASSAGE_FORMAT:
                self._vectors = {key: [[float(x) for x in vec] for vec in value]
                                 for key, value in (state.get("vectors") or {}).items()
                                 if isinstance(value, list) and value and isinstance(value[0], list)}
                self.dimension = state.get("dimension") or dimension

    def get(self, digest: str) -> list[list[float]] | None:
        return self._vectors.get(digest)

    def put(self, digest: str, vectors: Sequence[Sequence[float]]) -> None:
        self._vectors[digest] = [[float(x) for x in vector] for vector in vectors]
        if self._vectors[digest]:
            self.dimension = self.dimension or len(self._vectors[digest][0])
        self._dirty = True

    def prune(self, live_digests: set[str]) -> None:
        """Drop vectors for artifacts that no longer exist, or whose content moved on."""
        stale = [digest for digest in self._vectors if digest not in live_digests]
        for digest in stale:
            self._vectors.pop(digest, None)
        if stale:
            self._dirty = True

    def save(self, force: bool = False) -> None:
        if not self._dirty and not force:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        state = {"model": self.model, "format": PASSAGE_FORMAT, "dimension": self.dimension,
                 "vectors": self._vectors}
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        os.replace(temp, self.path)
        self._dirty = False


# ------------------------------------------------------------------ rerankers

class NoopReranker:
    """Default. Measured against the alternatives before being trusted."""

    name = "none"

    def rerank(self, query: str, documents: dict[str, str]) -> dict[str, float] | None:
        return None


class LlmReranker:
    """Local listwise-ish rerank by asking a small model to score each candidate.

    Kept optional and off by default: it costs a generation per candidate, and a
    7B model's relevance judgement is not automatically better than RRF's
    ordering. It has to earn its place in the eval harness first.
    """

    name = "ollama-llm"

    def __init__(self, model: str = "qwen2.5:7b", host: str | None = None, timeout: float = 60.0,
                 max_chars: int = 1200) -> None:
        self.model = model
        self.host = (host or os.environ.get("INTELLIGENCE_OLLAMA", "http://127.0.0.1:11434")).rstrip("/")
        self.timeout = timeout
        self.max_chars = max_chars

    def rerank(self, query: str, documents: dict[str, str]) -> dict[str, float] | None:
        scores: dict[str, float] = {}
        for key, text in documents.items():
            prompt = (
                "Rate how well the passage answers the query, 0-10. "
                "Reply with the number only.\n\n"
                f"Query: {query}\n\nPassage: {text[: self.max_chars]}\n\nScore:"
            )
            payload = {"model": self.model, "prompt": prompt, "stream": False,
                       "options": {"temperature": 0, "num_predict": 4}}
            request = urllib.request.Request(
                f"{self.host}/api/generate",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    reply = (json.load(response).get("response") or "").strip()
            except (urllib.error.URLError, TimeoutError, OSError, ValueError):
                return None
            match = re.search(r"\d+(?:\.\d+)?", reply)
            if match:
                scores[key] = float(match.group())
        return scores or None


class HttpReranker:
    """A real cross-encoder (Jina/Cohere-style /rerank) when a key is configured.

    Cross-encoders read query and document together, which is what RRF cannot do;
    that is the one thing worth paying an external API for in this pipeline.
    """

    name = "http"

    def __init__(self, url: str, api_key: str = "", model: str = "", timeout: float = 30.0,
                 max_chars: int = 2000) -> None:
        self.url = url
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.max_chars = max_chars

    def rerank(self, query: str, documents: dict[str, str]) -> dict[str, float] | None:
        keys = list(documents)
        payload: dict[str, Any] = {"query": query, "documents": [documents[k][: self.max_chars] for k in keys],
                                   "top_n": len(keys)}
        if self.model:
            payload["model"] = self.model
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(self.url, data=json.dumps(payload).encode("utf-8"), headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.load(response)
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            return None
        results = body.get("results") or body.get("data") or []
        scores: dict[str, float] = {}
        for item in results:
            if not isinstance(item, dict):
                continue
            index = item.get("index")
            score = item.get("relevance_score", item.get("score"))
            if isinstance(index, int) and 0 <= index < len(keys) and score is not None:
                scores[keys[index]] = float(score)
        return scores or None


def build_reranker() -> Any:
    """Pick a reranker from the environment; default to none."""
    kind = (os.environ.get("INTELLIGENCE_RERANK") or "none").strip().casefold()
    if kind in ("ollama", "llm"):
        return LlmReranker(model=os.environ.get("INTELLIGENCE_RERANK_MODEL", "qwen2.5:7b"))
    if kind == "http" and os.environ.get("INTELLIGENCE_RERANK_URL"):
        return HttpReranker(
            url=os.environ["INTELLIGENCE_RERANK_URL"],
            api_key=os.environ.get("INTELLIGENCE_RERANK_API_KEY", ""),
            model=os.environ.get("INTELLIGENCE_RERANK_MODEL", ""),
        )
    return NoopReranker()


# ------------------------------------------------------------------ retrieval

class Retriever:
    """Ranks documents it is given. It never selects them.

    That split is deliberate: permission and status filtering stay in the service
    layer, so no ranking path can surface an artifact the actor may not read.
    """

    def __init__(self, cache: EmbeddingCache | None = None, embedder: Any = None,
                 reranker: Any = None, rrf_k: int = 60,
                 weights: Sequence[float] | None = None, lexical: bool = True,
                 min_cosine: float = 0.55, idf_ratio: float = 0.6,
                 passage_chars: int = 600, chunk: bool = True) -> None:
        self.cache = cache
        self.embedder = embedder
        self.reranker = reranker if reranker is not None else NoopReranker()
        self.rrf_k = rrf_k
        self.weights = weights
        self.lexical = lexical
        # A relevance gate, because "rank everything and return the top k" means an
        # unrelated query still gets k confident-looking answers - and then the
        # zero-result signal that drives review never fires.
        #
        # The two halves are deliberately different kinds of threshold. Cosine is
        # bounded and transfers across corpus sizes, so the semantic gate is
        # absolute (0.55 for bge-m3; measured: unrelated queries top out around
        # 0.4-0.5). idf is not bounded - a token appearing in one of five documents
        # has far less idf than one appearing in one of eighteen - so an absolute
        # lexical floor would silently depend on how big the corpus happens to be.
        # The lexical gate therefore asks a relative question: did this document
        # match a token that is distinctive *for this corpus and this query*?
        self.min_cosine = min_cosine
        self.idf_ratio = idf_ratio
        self.passage_chars = passage_chars
        self.chunk = chunk
        self.last_mode = "lexical"

    def _passages(self, document: dict[str, Any]) -> list[str]:
        if not self.chunk:
            text = document["embed_text"].strip()
            return [text] if text else []
        return split_passages(document["embed_text"], target=self.passage_chars)

    def _vectors(self, documents: dict[str, dict[str, Any]],
                 budget: int) -> tuple[dict[str, list[list[float]]], int]:
        """Cached passage vectors, embedding at most `budget` new documents per call.

        The budget exists so a first search after a bulk import cannot stall the
        read path; later searches pick up the remainder. A document's passages are
        embedded in one request and cached together - a partial set would break the
        index-to-passage mapping that lets a trace name the passage that matched.
        """
        if self.cache is None or self.embedder is None:
            raise RetrievalUnavailable("no embedder configured")
        vectors: dict[str, list[list[float]]] = {}
        missing: list[tuple[str, dict[str, Any]]] = []
        for key, document in documents.items():
            cached = self.cache.get(document["digest"])
            if cached:
                vectors[key] = cached
            else:
                missing.append((key, document))
        embedded = 0
        for key, document in missing:
            if embedded >= budget:
                break
            passages = self._passages(document)
            if not passages:
                continue
            vectors[key] = self.embedder.embed(passages, role="document")
            self.cache.put(document["digest"], vectors[key])
            embedded += 1
        return vectors, len(missing)

    def rank(self, query: str, documents: dict[str, dict[str, Any]], limit: int = 10,
             rerank_top: int = 20, embed_budget: int = 24) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Return ranked results with a trace of why each one ranked.

        The trace is the point: "not found" and "ranked 12th" are different
        problems, and without the trace you cannot tell a bad query from a bad
        corpus - which is what the unused-artifact review needs to know.
        """
        if not documents:
            return [], {"mode": "empty", "lexical": 0, "vector": 0}

        lexical_scores: dict[str, float] = {}
        distinctive_scores: dict[str, float] = {}
        lexical_ranking: list[str] = []
        if self.lexical:
            lexical = BM25().fit({key: document["fields"] for key, document in documents.items()})
            lexical_scores = lexical.score(query)
            distinctive_scores = lexical.distinctive(query)
            lexical_ranking = [key for key, _ in sorted(lexical_scores.items(), key=lambda item: -item[1])]

        vector_scores: dict[str, float] = {}
        best_passage: dict[str, int] = {}
        vector_ranking: list[str] = []
        mode = "lexical"
        note = ""
        try:
            vectors, pending = self._vectors(documents, embed_budget)
            query_vector = self.embedder.embed([query], role="query")[0]
            for key, passages in vectors.items():
                sims = [cosine(query_vector, vector) for vector in passages]
                if not sims:
                    continue
                top = max(range(len(sims)), key=lambda index: sims[index])
                vector_scores[key] = sims[top]
                best_passage[key] = top + 1
            vector_ranking = [key for key, _ in sorted(vector_scores.items(), key=lambda item: -item[1])
                              if vector_scores[key] > 0]
            mode = "hybrid" if len(vectors) == len(documents) else "hybrid-partial"
            if pending:
                note = f"{pending} artifact(s) not embedded yet"
        except RetrievalUnavailable as error:
            mode, note = "lexical", f"embeddings unavailable ({error})"

        # Gate before fusing, so a passed-over document cannot occupy a rank that
        # pushes a relevant one down.
        best_idf = max(distinctive_scores.values(), default=0.0)
        lexical_ranking = [key for key in lexical_ranking
                           if best_idf and distinctive_scores.get(key, 0.0) >= self.idf_ratio * best_idf]
        vector_ranking = [key for key in vector_ranking if vector_scores.get(key, 0.0) >= self.min_cosine]

        fused = rrf([lexical_ranking, vector_ranking], k=self.rrf_k, weights=self.weights)
        order = sorted(fused, key=lambda key: (-fused[key], key))

        reranked: dict[str, float] = {}
        if not isinstance(self.reranker, NoopReranker) and order:
            candidates = order[:rerank_top]
            scored = self.reranker.rerank(query, {key: documents[key]["rerank_text"] for key in candidates})
            if scored:
                reranked = scored
                order = sorted(order, key=lambda key: (-reranked.get(key, -1.0), -fused[key], key))
                mode = f"{mode}+rerank"

        lexical_position = {key: position for position, key in enumerate(lexical_ranking, start=1)}
        vector_position = {key: position for position, key in enumerate(vector_ranking, start=1)}
        results = []
        for key in order[:limit]:
            trace = {"rrf": round(fused.get(key, 0.0), 6)}
            if key in lexical_position:
                trace["lexical_rank"] = lexical_position[key]
            if key in vector_position:
                trace["vector_rank"] = vector_position[key]
            if key in reranked:
                trace["rerank"] = round(reranked[key], 3)
            if key in best_passage:
                trace["passage"] = f"{best_passage[key]}/{len(vectors.get(key) or [1])}"
            results.append({
                "key": key,
                "score": round(reranked.get(key, fused.get(key, 0.0)), 6),
                "why": trace,
                "bm25": round(lexical_scores.get(key, 0.0), 4),
                "cosine": round(vector_scores.get(key, 0.0), 4),
            })
        summary = {"mode": mode, "lexical": len(lexical_ranking), "vector": len(vector_ranking),
                   "documents": len(documents),
                   "gated_out": len(documents) - len(set(lexical_ranking) | set(vector_ranking))}
        if note:
            summary["note"] = note
        self.last_mode = mode
        self.cache.save() if self.cache is not None else None
        return results, summary
