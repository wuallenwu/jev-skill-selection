"""Tiny OpenAI-compatible chat server for keyless end-to-end tests of the harness.

Turn 1: cat the first listed skill's SKILL.md (exercises skill injection + skills_opened parsing).
Later turns: declare the task complete (terminus-2 asks to confirm, so this repeats).
"""
import json, re, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOC = re.compile(r"<location>([^<]+/SKILL\.md)</location>")


def reply(messages: list[dict]) -> str:
    text = "\n".join(str(m.get("content")) for m in messages)
    if sum(m.get("role") == "assistant" for m in messages) == 0:
        loc = LOC.search(text)
        cmd = f"cat {loc.group(1)} | head -5\n" if loc else "ls /app/skills 2>&1 | head\n"
        return json.dumps({"analysis": "mock", "plan": "open a skill", "commands": [{"keystrokes": cmd, "duration": 0.5}], "task_complete": False})
    return json.dumps({"analysis": "mock", "plan": "done", "commands": [], "task_complete": True})


class H(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        msgs = body.get("messages", [])
        content = reply(msgs)
        n_in = sum(len(str(m.get("content"))) for m in msgs) // 4
        out = {"id": "mock", "object": "chat.completion", "created": int(time.time()), "model": body.get("model", "mock"),
               "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
               "usage": {"prompt_tokens": n_in, "completion_tokens": len(content) // 4, "total_tokens": n_in + len(content) // 4}}
        data = json.dumps(out).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(data))); self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


def serve(port: int = 8765) -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
