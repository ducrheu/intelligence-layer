# Hybrid retrieval recipe

A working lexical + vector pipeline and the constants measured for it. Treat the numbers as
*starting points calibrated on one small corpus*, not defaults: re-run the harness before adopting
them elsewhere.

## Pipeline order

```
tokenize → BM25 (lexical ranking, per-field weights)
         → embeddings (passage vectors, cosine, best passage per document)
         → weighted reciprocal rank fusion
         → relevance gate (semantic OR lexical distinctiveness)
         → optional rerank on the fused head
         → result records carrying a trace
```

## Tokenisation

- Keep identifiers whole **and** contribute their parts: `pit-available-time-semantics` is one token
  plus `available`, `time`, …; `v1.1.0` must not decay into `v1 1 0`.
- Index CJK as character bigrams (`自动准入` → `自动`, `动准`, `准入`). It is the cheap standard trick
  that makes lexical search work at all on Chinese without shipping a segmentation model.
- No stemming, no stopword list: on a technical corpus the stopwords are usually the query.

## BM25

- `k1=1.5`, `b=0.75`; field weights as *term-frequency multipliers*: id 3.0, title 2.0, metadata
  name/tags 2.0, body 1.0. An id match must outrank a body mention.
- Also expose `distinctive(query)`: per document, the **highest idf among matched query tokens**.
  This is what makes a lexical gate safe for a corpus full of identifiers — a raw BM25 floor
  punishes short queries (`403`, `v2.0.1` carry little score mass), whereas matching one rare token
  is the real signal.

## Fusion

```
fused[key] = Σ_i w_i / (k + rank_i(key))
```

Measured on an 18-document fixture with 31 labelled queries: `k=60, w=[1,1]` scored 0.583 recall@1;
`k=10, w=[1.0, 0.25]` scored 0.750 on the embedder where configurations were still distinguishable,
and cost nothing on the strong one. Choose k and the weights on the setup that can still tell them
apart.

## Relevance gate

```
keep(document) = best_passage_cosine ≥ min_cosine
                 OR matched_idf ≥ idf_ratio × best_idf_for_this_query
```

- `min_cosine` absolute (bounded metric): 0.50 for bge-m3. Measured trade-off: 0.45 → recall@1
  1.000 with 0.375 of unrelated queries leaking hits; 0.50 → 0.917 / 0.000; 0.55 → 0.833 / 0.000.
  No gate at all → leak 1.000.
- `idf_ratio` relative (unbounded metric): 0.6. The relative form is what rescues short identifier
  queries on a small corpus after an absolute idf floor killed them.
- Apply the gate **before** fusing, so a passed-over document cannot occupy a rank that pushes a
  relevant one down.

## Passage splitting

`split_passages(text, target=600, hard_max=1400)`:

1. Split on blank lines into blocks; a block shorter than `target` is a piece.
2. A longer block is packed with whole sentences (split after `。！？；!?;` and newlines) up to
   `target`; only a sentence exceeding `hard_max` is hard-cut.
3. Merge undersized neighbours so many short paragraphs do not become many thin passages.

Determinism is load-bearing: cached vectors are mapped back to passages **by index**, so the same
text must always cut the same way. The splitter must not consult the model.

Measured: passages fixed content past the 2048-token embedding window (a fact planted 7000
characters in went from unreachable to found) and lifted overall recall@1 0.839 → 0.871, at the
cost of negative-query leak 0.000 → 0.125.

## Vector cache

```json
{"model": "bge-m3", "format": "passages-v1", "dimension": 1024,
 "vectors": {"<artifact digest>": [[...], [...]]}}
```

- Keyed by a digest of the document's *claim* (id, kind, scope, version, title, content, metadata
  minus any gateway-written annotation keys), so bookkeeping does not move the digest and
  invalidate evidence or vectors.
- A cache whose `model` or `format` differs is **dropped**, never reinterpreted: one vector per
  document would otherwise be read as a one-passage document.
- Prune digests for documents that no longer exist; embed at most N new documents per query so a
  first search after a bulk import cannot stall the read path.

## Harness layout

- Build a throwaway store, generate the fixture documents, run each mode in a fresh process
  (env-selected), print `config × recall@1/@5/MRR × negative-leak`, plus a per-query-class matrix
  so a regression names the class it broke.
- Keep negative queries in the corpus file next to the positives; a retriever that always returns k
  hits is worse than one that returns none.
- Modes: `lexical` (embeddings disabled), `vector` (lexical disabled), `hybrid`, `hybrid+rerank`.
  Do not print recall against a corpus that lacks the fixture answers — label that run a smoke check
  instead, or the 0.000 reads like a failure.

## Configuration

Defaults live in code with the measurement in a comment, and the same values are declared in the
service unit so live behaviour is visible and overridable without editing code, e.g.
`INTELLIGENCE_EMBED_MODEL`, `INTELLIGENCE_RRF_K`, `INTELLIGENCE_RRF_WEIGHTS`,
`INTELLIGENCE_MIN_COSINE`, `INTELLIGENCE_MIN_IDF_RATIO`, `INTELLIGENCE_PASSAGE_CHARS`,
`INTELLIGENCE_CHUNK`, `INTELLIGENCE_RERANK`, `INTELLIGENCE_EMBED_DISABLE`,
`INTELLIGENCE_LEXICAL_DISABLE`.

## Rerankers

- Local LLM-as-reranker (one generation per candidate) is a real option but costs latency and is
  not automatically better than RRF ordering; a cross-encoder API reads query and document
  together, which is the one thing RRF cannot do.
- Whichever is chosen must earn its place on a benchmark that can still discriminate. If a strong
  embedder has saturated the set, say the reranker is unproven rather than assuming it helps.
