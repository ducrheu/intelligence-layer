# Hybrid Retrieval: design, measurement, and the constants that bite

Where it lives: `AI_Platform/intelligence/gateway/retrieval.py` (BM25 + embeddings +
weighted RRF + relevance gate + optional reranker), constructed by
`gateway/service.py::_build_retriever`. Stdlib only - no numpy, no vector store:
at this corpus size brute-force cosine over cached vectors beats a round trip to a
vector database, and the gateway runs under the system python.

## Two invariants that outrank quality

1. **Filter, then rank.** Permission/status/scope filtering happens in the service
   (`_search_documents`) before the retriever sees anything. The retriever is handed
   exactly what the caller may read, so no score, trace or count can leak the
   existence of a candidate to a reader without candidate scope. Never move a filter
   into the ranking layer.
2. **Degrade, never fail.** If the embedder is unreachable the search still returns
   BM25 results with `mode: lexical` and a note. A knowledge base that stops
   answering because a model server restarted is worse than one that answers with
   lexical matches and says so.

## Procedure: measure before touching a constant

1. Run the harness: `python3 /mnt/d/OpenClaw/tools/intelligence-retrieval-eval.py
   --corpus synthetic --modes lexical,vector,hybrid` (add `hybrid+rerank` to price a
   reranker). It builds a labelled synthetic corpus - themes, distractor documents
   that share vocabulary with the right answer, identifiers, version strings, error
   codes, Chinese and English paraphrases of the same thing - plus negative queries
   that must return nothing.
2. Read `recall@1`, `recall@5`, `MRR` **and** `neg-leak` together. neg-leak is the
   share of unrelated queries that still return hits. Optimising recall alone is how
   you get a retriever that always answers, confidently and uselessly.
3. Sweep the knob through the environment, cheapest first:
   `INTELLIGENCE_EMBED_MODEL`, `INTELLIGENCE_RRF_K`, `INTELLIGENCE_RRF_WEIGHTS`,
   `INTELLIGENCE_MIN_COSINE`, `INTELLIGENCE_MIN_IDF_RATIO`.
4. Tune where differences are still visible. A benchmark that returns 1.000 for
   every configuration has stopped measuring anything - add a harder tier or more
   negative queries instead of tuning on a saturated set, then re-check that the
   chosen values do not cost anything on the strong configuration.
5. `--corpus live` is a smoke check, not a metric: the labelled queries belong to
   the synthetic corpus, so recall against the real store is meaningless. Use it to
   confirm short and identifier queries still resolve and that unrelated ones do not.
   **A benchmark is a measurement, not a reader.** In `live` mode it fetches through the
   normal read path, so it emits `used` events and bumps surfacing counters exactly like a
   person; one such run kept the "nobody is reading this" alarm silent for a week. Set the
   telemetry-suppression switch in the harness itself (this install:
   `INTELLIGENCE_TELEMETRY_SUPPRESS=1`), and verify it by recording the event-file line
   count around a run.

Two traps that decide whether a result means anything. When a change makes no
difference, **inspect the fixture before the hypothesis**: a "long broad document"
fixture originally built from the same sentences as the specific documents wins
legitimately and measures nothing about the change under test - and getting no
difference is a result to report, not a reason to ship the intuition. When a hit
exposes a better reading of a query than the label did, **accept both answers and
record why** instead of editing the expectation into passing; the label was the
finding.

**Where the live values come from: read the construction site, never the signature.**
`Retriever.__init__` in `retrieval.py` carries *library* defaults (`rrf_k=60`,
`min_cosine=0.55`) that are **not** in force here. The values that run are set where the
retriever is built, `gateway/service.py::_build_retriever`, each one an env override with a
measured default: `INTELLIGENCE_EMBED_MODEL=bge-m3`, `INTELLIGENCE_RRF_K=10`,
`INTELLIGENCE_RRF_WEIGHTS=1.0,0.25`, `INTELLIGENCE_MIN_COSINE=0.50`,
`INTELLIGENCE_MIN_IDF_RATIO=0.6`, `INTELLIGENCE_CHUNK=1`,
`INTELLIGENCE_PASSAGE_CHARS=600`, `INTELLIGENCE_RERANK=none`.
**The `systemd` unit is not where they live on this install** - `systemctl --user show -p
Environment` carries only the state dir and the legacy-names switch, so an absent variable
there proves nothing about the value in force. This is the same shape as the auto-admission
mode, whose authority is a file in the store rather than the process environment: when a
setting can be declared in three places (signature default, construction-site default, unit
environment), grep the construction site before quoting any number or debugging any
behaviour.

## Constants that assume a scale (each of these was wrong when copied)

- **RRF `k`.** The paper's `k=60` pools rankings thousands of documents deep. On a
  corpus of dozens, every candidate lands inside the top 20 of both retrievers, the
  `1/(k+rank)` terms flatten out, and fusion degenerates into counting votes - it
  scored *worse* than lexical alone. Use ~10 here and re-measure when the corpus
  grows an order of magnitude.
- **Fusion weights.** Rank-based fusion treats both retrievers as equally
  trustworthy. When one is measurably weaker on this corpus, declare it:
  `INTELLIGENCE_RRF_WEIGHTS=1.0,0.25` (lexical carries precision, the vector half
  carries recall).
- **A lexical gate on raw BM25 score or absolute idf.** idf is unbounded and shrinks
  as a corpus grows, so a floor calibrated on one corpus size silently kills short
  queries (`403`, `v2.0.1`, `pit`) on another. Gate on *relative* distinctiveness:
  matched idf >= ratio x the best idf available for that query in this corpus.
- **A vector gate on cosine is safe to make absolute** because cosine is bounded, so
  a threshold transfers across corpus sizes. Measured separation on this corpus:
  relevant pairs 0.40-0.79, unrelated 0.13-0.60, overlapping - so the floor is the
  recall-vs-leak dial (0.45 -> recall 1.000 / leak 0.375; 0.50 -> 0.917 / 0.000;
  0.55 -> 0.833 / 0.000). Default 0.50. State the trade-off next to the constant;
  picking a point on that curve is a policy choice, not a technical one.
- **A gate is not optional.** "Rank everything and return the top k" makes every
  query look answered: dense vectors are positively similar to almost anything. That
  hands an agent confident-looking irrelevant context *and* buries the zero-result
  signal, which is the most actionable thing this knowledge base emits.

## Chunking (passages)

`split_passages` cuts `title + content` into passages of ~600 chars (hard cap 1400):
whole sentences are packed up to the target and only a sentence that cannot fit the
cap is fragmented; short paragraphs merge. Every passage gets its own vector, an
artifact scores on its **best** passage, and the trace names it
(`why.passage: "3/5"`).

- **The split must be deterministic.** Cached vectors are mapped back to passages by
  *index*, so a splitter that varies between calls attributes a vector to the wrong
  passage. Nothing ambient (model, clock, query) may enter the split.
- **The cache carries a format tag (`passages-v1`).** A cache written in the older
  one-vector-per-document shape is dropped rather than reinterpreted as a
  single-passage document; bump the tag whenever the splitting changes.
- **A document's passages are embedded in one request and cached together**, so a
  partial set can never break the index-to-passage mapping.
- The vector half now sees the tail of a long artifact at all. The lexical half
  already could - which is why it scored 1.00 on the past-the-window fixture in both
  configurations, and why chunking read as "no gain" to anyone looking only at that
  number: it removes an asymmetry, it does not add a capability BM25 lacked.

## Embedding model choice is a language question

`nomic-embed-text` is English-first: alone it scored recall@1 0.312 on a
Chinese-language corpus where `bge-m3` scored 0.958, same queries, same pipeline.
Pick the embedder for the corpus language and verify it with the harness rather
than by reputation; a local model was sufficient here, so no external API was
needed. Watch the task-prefix contract - `search_document:` / `search_query:` are
part of nomic's documented usage, while bge-m3 takes none - and derive the prefix
from the model family instead of hardcoding it at a call site.

Vectors are cached in `qa/embeddings.json`, keyed by the artifact digest
(`attestation.artifact_digest`), so an edit re-embeds automatically and an
unchanged artifact never pays twice; changing the model discards the whole cache,
because mixing two models' vectors in one similarity computation produces
silence-free nonsense. Embed at most a bounded number of new documents per search so
a bulk import cannot stall the read path.

## Reranking

Implemented and off by default: `INTELLIGENCE_RERANK=ollama` scores candidates with
a local model, `=http` posts to a Jina/Cohere-style `/rerank`. Keep it off until the
harness discriminates - a reranker costs a generation per candidate and has to beat
the fused order on a set where the fused order is not already perfect.

**An identical score across two modes is a switch that never engaged, not a finding.** A
`hybrid+rerank` run reproduced `hybrid` to three decimals, because the unit sets
`INTELLIGENCE_RERANK=none` and the requested mode never reached the retriever. Before
reporting "reranking adds nothing here", assert which configuration actually ran - print the
mode from the harness output or the retriever's own trace, and check the construction-site
default as above. The same reading applies in reverse: "no gain" from a feature nobody turned
on is the most expensive sentence in a tuning report, because it closes the question.

## Known gaps

- **Chunking fixed the context window, not the broad-document problem - measured, do
  not re-litigate.** Passage-level scoring (now shipped) closes the blind spot where
  an artifact larger than the embedder's window was embedded as its opening only,
  leaving BM25 the sole path to its tail: an answer planted past the truncation point
  went from unfindable to found (0.00 -> 1.00 on that query class), recall@1 rose
  0.839 -> 0.871, MRR 0.887 -> 0.903, at a cost of neg-leak 0.000 -> 0.125. What it
  did **not** do is stop a long, broad document from winning specific queries: once
  the fixture was made genuinely generic (naming themes without containing the
  answers), chunked and unchunked scored identically, and on the live store the broad
  document's winning *passage* is a real passage about the topic - the question is
  answered, not lost. It is a corpus-shape problem. The untested options are the
  cross-encoder reranker and specificity weighting; neither has a measurement behind
  it, so neither is enabled.
- Search surfacing and retrieval are counted separately in `qa/usage.json`; a record
  that is only ever found, never read, shows up in the review flags and should be
  diagnosed as a findability question rather than a content one.
- **A multilingual embedder does not make the corpus cross-lingual.** Measured on the same
  labelled set: `cross-lingual` recall@1 stayed 0.00 for both lexical and hybrid, and
  English paraphrases went 0.00 -> 0.67 only once the vector half was on. A corpus written in
  one language answers asks in that language; treat an English question against a Chinese
  store as a miss to be routed around (ask in the corpus's language), not as a retriever
  defect to tune away.

## Tests

Unit tests run lexical-only: every test module that constructs a gateway sets
`os.environ.setdefault("INTELLIGENCE_EMBED_DISABLE", "1")` before it does. Tests must
not depend on whether a model server happens to be running on the machine, and
`test_retrieval.py` covers the mechanical half (tokenisation, BM25, fusion weights,
cache invalidation on digest and on model swap, degradation, the embed budget) plus
the security half (a candidate must not be counted, ranked or hinted at for a reader
without candidate scope).
