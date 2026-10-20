# A2A send + poll helper: Hermes -> OpenClaw main.
#
#   python3 a2a_send.py <message-file> [--timeout 360]
#
# Why this exists: message/send is cut off server-side at ~120s and returns
# TASK_STATE_WORKING, not a client timeout. So: send, then poll tasks/get until
# the task reaches a terminal state. The reply text lives at
# result.task.artifacts[*].parts[*].text -- res.get("task") on the envelope
# itself returns an empty string.
#
# Appends every exchange to transcript.jsonl next to this script.
import json
import pathlib
import sys
import time
import urllib.request
import uuid

HERE = pathlib.Path(__file__).resolve().parent
BASE = "http://127.0.0.1:18789/a2a/v1"          # OpenClaw gateway, A2A binding
ENVFILE = pathlib.Path.home() / ".openclaw/env/a2a-hermes.env"


def token():
    for line in ENVFILE.read_text().splitlines():
        if line.startswith("A2A_HERMES_TOKEN="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("no A2A token in " + str(ENVFILE))


def rpc(method, params, tok, timeout=60):
    body = json.dumps({"jsonrpc": "2.0", "id": str(uuid.uuid4()),
                       "method": method, "params": params}).encode()
    req = urllib.request.Request(BASE, data=body, headers={
        "Content-Type": "application/json",
        "Authorization": "Bearer " + tok,
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def unwrap(res):
    res = res.get("result", res)
    return res.get("task", res)


def reply_text(res):
    task = unwrap(res)
    out = [p["text"] for a in (task.get("artifacts") or [])
           for p in a.get("parts", []) if p.get("text")]
    if not out:
        msg = (task.get("status") or {}).get("message") or {}
        out = [p["text"] for p in msg.get("parts", []) if p.get("text")]
    return "\n".join(out)


TERMINAL = {"TASK_STATE_COMPLETED", "TASK_STATE_FAILED",
            "TASK_STATE_CANCELED", "TASK_STATE_REJECTED"}


def main():
    mfile = sys.argv[1]
    timeout = int(sys.argv[sys.argv.index("--timeout") + 1]) if "--timeout" in sys.argv else 240
    text = pathlib.Path(mfile).read_text()
    tok = token()
    t0 = time.time()
    res = rpc("message/send", {"message": {
        "role": "user", "messageId": str(uuid.uuid4()),
        "parts": [{"kind": "text", "text": text}]}}, tok, timeout)
    task = unwrap(res)
    tid, state = task.get("id"), (task.get("status") or {}).get("state")
    reply = reply_text(res)
    deadline = t0 + timeout
    while not reply and state not in TERMINAL and time.time() < deadline:
        time.sleep(20)
        task = unwrap(rpc("tasks/get", {"id": tid}, tok))
        state = (task.get("status") or {}).get("state")
        reply = reply_text({"task": task})
    out = {"task_id": tid, "state": state,
           "elapsed": round(time.time() - t0, 1), "reply": reply}
    if not reply:
        out["raw"] = json.dumps(res, ensure_ascii=False)[:1500]
    print(json.dumps(out, ensure_ascii=False, indent=2))
    with open(HERE / "transcript.jsonl", "a") as f:
        f.write(json.dumps({"ts": time.strftime("%F %T"), "sent": text,
                            "state": state, "reply": reply}, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
