"""Minimal alphaXiv MCP client (streamable HTTP, JSON-RPC).

Auth: the cloud environment's network secret adds `Authorization: Bearer <key>` for
api.alphaxiv.org, so no key appears here. Locally, set ALPHAXIV_API_KEY instead.

We only use get_hot_feed, which does NOT consume alphaXiv assistant quota.
Usage:  python pipeline/alphaxiv.py hot [--limit 200]
"""
import argparse
import json
import os
import sys
import urllib.request

URL = "https://api.alphaxiv.org/mcp/v1"
UA = "ai-updated-digest/0.1"


class AlphaXiv:
    def __init__(self):
        self.sid = None
        self.headers = {
            "User-Agent": UA,
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        key = os.environ.get("ALPHAXIV_API_KEY")
        if key:
            self.headers["Authorization"] = f"Bearer {key}"
        self._id = 0
        self._rpc("initialize", {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "ai-updated-digest", "version": "0.1"},
        })
        self._rpc("notifications/initialized", None, notify=True)

    def _rpc(self, method, params, notify=False):
        body = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            body["params"] = params
        if not notify:
            self._id += 1
            body["id"] = self._id
        h = dict(self.headers)
        if self.sid:
            h["Mcp-Session-Id"] = self.sid
        req = urllib.request.Request(URL, json.dumps(body).encode(), h)
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                self.sid = r.headers.get("Mcp-Session-Id") or self.sid
                raw = r.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if notify:
                return None
            raise RuntimeError(f"alphaXiv {method}: HTTP {e.code} {e.read()[:200]!r}")
        if notify or not raw.strip():
            return None
        if "data:" in raw[:200]:
            raw = "\n".join(l[5:].strip() for l in raw.splitlines() if l.startswith("data:"))
        msg = json.loads(raw)
        if "error" in msg:
            raise RuntimeError(f"alphaXiv {method}: {msg['error']}")
        return msg["result"]

    def call(self, tool, **args):
        res = self._rpc("tools/call", {"name": tool, "arguments": args})
        text = "".join(c.get("text", "") for c in res.get("content", []))
        if res.get("isError"):
            raise RuntimeError(f"alphaXiv tool {tool} error: {text[:300]}")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    def hot_feed(self, limit=200):
        """Ordered list of universal paper ids from the Hot feed (free, no quota)."""
        return [p["universal_paper_id"] for p in self.call("get_hot_feed", limit=limit)["papers"]]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["hot"])
    ap.add_argument("--limit", type=int, default=200)
    a = ap.parse_args()
    ids = AlphaXiv().hot_feed(a.limit)
    json.dump(ids, sys.stdout, indent=0)
    print()
