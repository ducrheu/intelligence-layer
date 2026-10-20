# Retrieval quality: making the store findable, and proving it

Companion to rule 12. Read before changing a retriever, adding content, or
switching an embedding model - and run the harness before and after, because every
constant below came from a measurement and two of them were wrong when copied from
their usual defaults.

## Shape of the retriever

Lexical (BM25) + dense embeddings -> **rank-based** fusion -> relevance floor ->
optional rerank.

Fuse by rank, not by score: BM25's scores are unbounded and cosine's live in
[-1,1], so there is no honest way onto one scale without per-corpus tuning.
Reciprocal rank fusion (`sum(weight / (k + rank))`) only needs the orderings to be
comparable, which they are.

The two halves fail in opposite directions, which is the entire argument for
keeping both: identifiers (`pit-available-time-semantics`), version strings
(`v2.0.1`) and codes (`403`) are where dense retrieval is weakest, and a query
that is a paraphrase of the answer is where lexical fails.

Start with stdlib only and brute-force cosine over cached vectors. At hundreds of
chunks that beats the round trip to a vector store and avoids a new dependency in
an always-on service; revisit when the corpus reaches thousands of chunks.

## Constants that must be measured, not inherited

| constant | ship value | the measurement behind it |
|---|---|---|
| embedding model | multilingual, local (`bge-m3`) | same queries, vector-only recall@1: English-first small model 0.312 vs multilingual 0.958. Corpus language decides this, nothing else. |
| fusion `k` | 10 | the textbook 60 pools deep rankings of thousands of documents; on a corpus of dozens it flattens the fusion (recall@1 0.583 at 60 vs 0.750 at 10) |
| half weights | lexical 1.0, dense 0.25 | lexical carries precision, dense adds recall; down-weighting dense lifted recall@1 0.500 -> 0.750 with a weak embedder and cost nothing with a strong one |
| relevance floor, dense | absolute cosine | cosine is bounded, so the number transfers between corpus sizes |
| relevance floor, lexical | relative: matched idf >= ~0.6x the best matched idf for that query | idf is not bounded - a token in one of five documents has far less idf than one in one of eighteen - so an absolute idf floor silently encodes corpus size and starts rejecting short identifier queries as the store grows |
| chunking | on, passages a few hundred chars | the embedding model has a token window and the client truncates, so tail content is invisible to the dense half; long documents also dilute to a single mediocre vector |
| reranker | off until it earns its latency | a cross-encoder can separate "mentions it" from "is about it", but a reranker judged on a saturated benchmark is unproven |

Make every constant an environment knob *and* surface the live values in the
service definition (the unit file, not just code defaults) so behaviour is
inspectable without reading the source.

## The relevance floor is a policy choice, so state it

Without a floor the dense half gives *any* query a positive similarity, so an
unrelated question returns its top k confident-looking records and the zero-result
signal dies (which then breaks rule 11, because "nobody read it" can no longer be
told apart from "the asker used different words").

| floor | recall@1 | share of unrelated queries that still return hits |
|---|---|---|
| 0.45 | 1.000 | 0.375 |
| 0.50 | 0.917 | 0.000 |
| 0.55 | 0.833 | 0.000 |

Shipping 0.50 is an operator-facing judgement: silently withholding a governance
rule costs more than an agent reading one irrelevant record. Say which side was
picked and why, and keep the knob visible.

## Harness design

Score four things, never one: recall@1, recall@5, MRR, and **negative leak** (the
share of queries with no correct answer that still return hits). A retriever that
always returns k hits scores 1.000 on leak and is worse than one that admits it
found nothing.

Include, in the fixture corpus: distractors that share vocabulary but not intent,
identifiers and version strings and codes, paraphrase-only answers, cross-language
queries, one long broad document, and a document long enough that its answer sits
past the embedder's truncation point.

Keep a live-corpus mode as a **smoke check, not a metric**: labelled queries belong
to the synthetic corpus, so live recall is always ~0 and printing it invites
misreading. Use it to see which artifact a real query actually lands on.

## Traps

- **Don't tune on a saturated set.** Pick the constant where configurations still
differ, then verify the value costs nothing where they do not.
- **A change that shows no effect means inspect the fixture.** A broad-document
  fixture built from the same sentences as the specific documents wins
  legitimately and measures nothing.
- **Negative results are results.** Long broad documents beating specific ones for
  specific queries is a corpus-shape problem; passage-level scoring did *not* fix
  it in measurement, so do not ship the intuition as a fix. What chunking did fix,
  measurably, is the truncation blind spot - which only the lexical half could see
  before.
- **A gate can kill your own probe.** After adding a relevance floor, a query that
  matched weakly returns nothing and looks like a visibility verdict; assert on
  terms the corpus contains lexically.
- **Passage splitting must be deterministic** and the vector cache keyed by the
  artifact's content digest, with a format tag: cached vectors are mapped back to
  passages by index, so a changed splitter or a changed digest silently attributes
  a vector to the wrong passage, and a model swap must invalidate the whole cache
  rather than mixing two vector spaces.
- **Keep a projection of "what the author claims" for digests.** The store's own
  annotations (verdicts, status, timestamps) must stay outside it, or recording a
  decision invalidates the evidence that justified it.
- **Never re-derive a ranking or verdict in a second code path.** Tools ask the
  service; they do not import its policy functions and re-run them with less
  context.
