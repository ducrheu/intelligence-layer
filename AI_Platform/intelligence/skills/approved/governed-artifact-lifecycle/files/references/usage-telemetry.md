# Usage telemetry: making an artifact store falsifiable

Admission evidence proves an artifact was allowed in. Nothing in it proves the
artifact was worth having, so a store with only admission records can never be
falsified - it accumulates, and "nobody ever used this" stays invisible until
someone audits by hand. The external finding that motivates this: the bottleneck
in knowledge and skill bases is not writing but *invocation*. Even strong setups
fail to trigger the right record, and flat retrieval degrades once a few dozen
records coexist, so selection is harder than storage.

## Three signals, deliberately separate

| signal | how it is recorded | what it means |
|---|---|---|
| strong: an explicit fetch | append-only event per successful retrieval, carrying id, kind, status, actor, timestamp, and how it was obtained | the whole record was read |
| weak: appearing in a result set | one aggregated counter per record, in a small file | the record was findable, not that it was read |
| void: a query that found nothing | one aggregated counter keyed by the query text | the asker's words and the corpus's words did not meet |

Rules that keep the two honest:

- **Never merge them into one number.** The weak signal alone would retire
  records that are found constantly but not yet read; the strong signal alone
  hides a findability failure, which looks identical to being useless.
- **A search must not rewrite what it finds.** Count the weak signal in one
  aggregate write per search, never one write per hit: per-hit counting is write
  amplification across the very artifacts being served.
- **Only successful reads count.** A refused or failed read is not usage - an
  artifact nobody may read is not one anybody used.
- **Keep the event stream content-free.** It is forwarded to other agents, so it
  carries identity, status, kind and time, and none of the record's body.
- **Record the queries that return nothing.** The losses are the more actionable
  half: a query that finds nothing while candidates exist names a vocabulary gap or
  a missing record, and it is invisible in every metric that counts only successes.
  This requires the retriever to be able to return nothing at all - a search that
  always answers with k hits destroys the signal while looking healthier.

## Flags, never deletions

Derive per-artifact review flags from the two signals: never-used, surfaced-only
(found but never read, or hits far exceeding reads), and past-review-horizon (the
validity horizon set at admission). An automatically admitted record that nobody
has read earns a stronger flag, because it never passed a human at all.

Flags summon a human; they do not act. "Unused" has three causes - wrong,
unfindable, or simply too new - that no counter can tell apart, so automatic
retirement would delete the premature along with the bad. This is the same
principle as reuse-driven review in knowledge-management practice: being read is
what makes a record worth reviewing, so a record that nothing reads is a question
to answer, not a verdict to apply.

**Demotion is the exception that keeps the rule.** When the operator sets a zero-demand horizon, a
record past it may step back to `experimental`: body kept, actor and reason written onto the
artifact, one transition from returning, and no `deprecated` and no deletion. That is reversible
enough to be automatic, unlike retirement. Two consequences to wire in with it. A demoted record
leaves the read surface *and* the review flags, or every weekly report re-raises the same item
forever. And a record already `superseded_by` a finished one is provenance, not a to-do - its zero
read count is expected, so flagging it trains the operator to ignore the flag.

## When the instrument writes the signal

Counters and event streams cannot tell a reader from a measurement. Two failures follow, and both
look like a healthy store:

- **A measurement becomes usage.** A live-corpus benchmark fetches records through the normal read
  path, so its probes emit `used` events and bump surfacing counters exactly like a person. One
  suite run wrote 315 lifecycle events into the live stream; one 31-query benchmark kept the
  "nobody is reading this" alarm silent for a week. Give read-only tools an explicit telemetry
  suppression switch, have those tools set it themselves, and keep the audit chain exempt - the
  governance record of who did what is never optional.
- **The alarm counts a proxy.** A consumption check written against *search calls* is satisfied by
  benchmarks and by empty searches; write it against successful fetches, and state the threshold in
the message so a silent week is legible. Compare stored stamps as UTC: parsing a `Z` stamp into a
naive datetime and comparing it with local now shifts the window by the UTC offset and quietly
excludes the boundary hours.

Verification for both, cheap and decisive: record the event-file line count, run the measurement,
re-read it. Suppressed: unchanged. Unsuppressed: a handful of new `used` rows naming fixture ids.


**A fourth cause, and the only one about the instrument rather than the record:
the counting window closed before the record existed.** The aggregate file carries
its own last-write timestamp, and it moves only when a retrieval is recorded, so
once reading stops, every record admitted afterwards is structurally unable to have
a read count and is flagged never-used on arrival. Measured on a 23-record store:
reads stopped, the counter froze, and every artifact approved since collected
`never-used, auto-admitted-unverified`; one live search moved the timestamp
immediately. Compare the counter's last-write time against each record's admission
date, and report the post-freeze records as *not yet eligible* rather than unused.
A frozen counter and a store nobody reads look identical in the table, and which
one it is decides between "the corpus is bad" and "the loop is not running" - so
do one counted probe and watch whether the timestamp moves before reporting either.

## Wiring it up

1. A retrieval path that counts only successful reads and writes nothing else.
2. A read-only report that prints per-artifact reads, surfacing, and flags -
   with a machine-readable mode and an "only what needs attention, silent when
   nothing" mode.
3. A script-only scheduled job that runs the report's silent mode, so an idle
   period costs no model call and sends no message.
4. The review horizon that admission required is what the report enforces; an
   admission without a horizon can never be revisited.

Read the resulting table as a diagnosis, not a scoreboard: a corpus where nearly
everything is flagged says the problem is retrieval and triggering, not content
volume - which is the opposite of the instinct to write more artifacts. Count the
store's actions per day to tell the two loops apart: writes (submit, validate,
approve) continuing while the retrieval call has sat at flat zero for weeks is a
corpus that is fed but never consulted - a workflow gap, and one no threshold change
fixes. Look at the
recorded empty queries before commissioning new content: a miss usually means the
asker's words and the corpus's words differ, and rewriting a title or its tags costs
less than writing another artifact nobody will find.
