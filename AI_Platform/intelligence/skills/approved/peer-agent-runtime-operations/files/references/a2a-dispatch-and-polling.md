# A2A dispatch: bearer, envelopes, polling

The working sequence for sending a task to a peer agent runtime over A2A JSON-RPC
and reading the result. Architecture rules live in the parent SKILL.md; this file is
the protocol depth.

`a2a-governed-read` covers the read-only side of the same binding and is the better
skill to consult for artifact extraction shapes and the trust boundary.

## Sequence

1. **Fetch the agent card** if you do not already know the peer's URL and binding:
   `GET http://127.0.0.1:<port>/.well-known/agent-card.json` (a plain `GET /` on some
   peers returns a health document instead).
2. **Dispatch with a bearer token.** No header — no service:

```bash
TOKEN=$(grep -oP '(?<=<PEER>_TOKEN=).*' ~/<peer-home>/env/<caller>.env | head -1 | tr -d '"'"'" \r\n')
curl -s -o /tmp/task.json -w '%{http_code}\n' --max-time 60 \
  -X POST http://127.0.0.1:<port>/a2a/v1 \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"jsonrpc":"2.0","id":"dispatch-1","method":"message/send",
       "params":{"message":{"role":"user","messageId":"dispatch-1",
       "parts":[{"kind":"text","text":"<task contract>"}]}}}'
```

   Never echo the token; report its length if you must show it was read.
3. **Read the task id** from `result.task.id` (and keep `contextId` for correlation).
4. **Poll if it is not finished**:

```bash
curl -s -X POST http://127.0.0.1:<port>/a2a/v1 \
  -H 'Content-Type: application/json' -H "Authorization: Bearer $TOKEN" \
  -d "{\"jsonrpc\":\"2.0\",\"id\":\"get-1\",\"method\":\"tasks/get\",\"params\":{\"id\":\"$TID\"}}"
```

   Terminal states: `TASK_STATE_COMPLETED`, `TASK_STATE_FAILED`, `TASK_STATE_CANCELED`,
   `TASK_STATE_REJECTED`. Short tasks can complete inside the dispatch call itself, so
   poll once and check before looping. A generous per-poll timeout matters more than a
   tight interval: an agent turn takes tens of seconds.

## Reading the result

- Success text lives in `result.task.artifacts[*].parts[*].text`, then
  `result.task.status.message.parts[*].text`.
- **A failed task explains itself**: the reason is in
  `result.task.status.message.parts[*].text`, written for a human, usually naming the
  exact configuration change needed. Read it before forming a hypothesis, and quote
  it to the operator rather than paraphrasing a guess.
- A completed task with no artifact text is an empty answer, not a call failure.

## Writing the task contract

The peer agent receives only your message text. Put all of this in it:

```text
【目标】 one sentence, verifiable
【必须做的事】 the constraints that matter (which tool, which path, which identity)
【验收】 what the reply must contain for the task to count as done
【格式】 output shape and a length ceiling
```

Ask for evidence in the reply (the file it read, the command it ran). Then check it —
a worker's self-report is a claim, and the cheap way to falsify it is one `ls`, one
`curl`, or one read of the governed artifact it says it filed.

## Failure modes and what they mean

| symptom | meaning |
|---|---|
| `401` | missing/invalid bearer |
| connection refused / `000` | peer gateway not up yet after a restart — poll the port, then retry |
| HTTP 200, task `FAILED`, message about routing | peer-side config: that channel/account has no owning agent |
| HTTP 200, task `FAILED`, message about provider auth | peer-side config: that agent has no model credential |
| task stays non-terminal for minutes | the agent turn is long; poll, do not re-dispatch (re-dispatching duplicates the work) |
| state reads `unknown` | your poll envelope is wrong, not the task |
