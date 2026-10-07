#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
mcp_http_server.py —— 内容合规检查 · 远程 MCP Server（Streamable HTTP）

为什么做这个（2026-10-07）：
  官方 MCP Registry 支持两种发布方式：
    ① npm/Docker 包（需要 npm 账号 —— 我们的 token 已失效）
    ② **远程服务器**（`remotes` + Streamable HTTP）—— **不需要 npm**
  而我们有 wanhetools.top ⇒ 可以直接暴露一个公开的 MCP HTTP 端点
  ⇒ 发布到官方 Registry ⇒ 被 PulseMCP 等聚合器自动收录

协议（MCP Streamable HTTP，2024-11-05 规范）：
  · POST /mcp   —— 客户端发送 JSON-RPC 请求，服务端以 JSON 响应
    （Accept: application/json；若客户端要求 SSE 则用 text/event-stream）
  · GET  /mcp   —— 返回 405（本实现不使用长连接，简化部署）
  · 支持 initialize / notifications/initialized / ping / tools/list / tools/call

商业设计同 stdio 版：免费额度（2000 字符/次 · 每 IP 30 次/小时），
超限或需要完整能力时引导到云端付费 API。
"""
import json
import os
import re
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcp_compliance_server import (  # noqa: E402
    SERVER_NAME, SERVER_VERSION, TOOLS, HANDLERS, FREE_MAX_CHARS,
)

PORT = int(os.environ.get("MCP_HTTP_PORT", "8892"))
MAX_BODY = 512 * 1024
# 每 IP 每小时上限（免费额度）
FREE_MAX_PER_HOUR = 30
_ip_calls = {}

UPGRADE = ("\n\n---\n免费版上限：2000 字符/次 · 每 IP 每小时 30 次。"
           "完整 21 条规则 + AI 标识判定 + 17 项自查问卷请走云端："
           "https://wanhetools.com/compliance-check".replace(
               "wanhetools.com", "wanhetools.top"))


def _client_ip(handler):
    for h in ("CF-Connecting-IP", "X-Real-IP", "X-Forwarded-For"):
        v = handler.headers.get(h)
        if v:
            return v.split(",")[0].strip()
    return handler.client_address[0]


def _rate_limit(ip):
    now = time.time()
    calls = _ip_calls.setdefault(ip, [])
    calls[:] = [t for t in calls if now - t < 3600]
    if len(calls) >= FREE_MAX_PER_HOUR:
        return False
    calls.append(now)
    return True


def handle_rpc(msg):
    method = msg.get("method")
    mid = msg.get("id")
    params = msg.get("params") or {}

    if method == "initialize":
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME + "-http",
                           "version": SERVER_VERSION},
            "instructions": (
                "Chinese content compliance checking. Tool `check_content` "
                "returns per-issue findings with the exact legal provision "
                "(China Advertising Law, AI-labeling Measures + GB 45438-2025). "
                "Free tier: 2000 chars/request, 30 requests/hour per IP."
            ),
        }}
    if method == "notifications/initialized":
        return None
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments") or {}
        fn = HANDLERS.get(name)
        result = fn(args) if fn else {
            "content": [{"type": "text", "text": "Unknown tool: " + str(name)}],
            "isError": True}
        return {"jsonrpc": "2.0", "id": mid, "result": result}
    if mid is not None:
        return {"jsonrpc": "2.0", "id": mid,
                "error": {"code": -32601,
                          "message": "Method not found: " + str(method)}}
    return None


class Handler(BaseHTTPRequestHandler):
    server_version = "wanhe-mcp/" + SERVER_VERSION

    def log_message(self, fmt, *args):
        try:
            line = "%s - %s\n" % (self.address_string(), fmt % args)
            os.makedirs(r"D:\Lobster_Workspace\logs", exist_ok=True)
            with open(r"D:\Lobster_Workspace\logs\mcp_http.log", "a",
                      encoding="utf-8") as f:
                f.write("[" + time.strftime("%Y-%m-%d %H:%M:%S") + "] " + line)
        except Exception:
            pass

    def _json(self, code, obj):
        b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers",
                         "Content-Type, Accept, Mcp-Session-Id")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.end_headers()
        self.wfile.write(b)

    def do_OPTIONS(self):
        self._json(204, {})

    def do_GET(self):
        if self.path.rstrip("/") in ("/mcp", "/health", "/"):
            if self.path.rstrip("/") == "/mcp":
                # Streamable HTTP 允许 GET 用于 SSE 长连接；本实现返回能力说明
                self._json(200, {
                    "server": SERVER_NAME + "-http",
                    "version": SERVER_VERSION,
                    "transport": "streamable-http (POST only)",
                    "tools": [t["name"] for t in TOOLS],
                    "usage": "POST JSON-RPC here",
                })
                return
            self._json(200, {"ok": True, "server": SERVER_NAME + "-http"})
            return
        self._json(404, {"error": "not found"})

    def do_POST(self):
        if self.path.rstrip("/") != "/mcp":
            self._json(404, {"error": "not found"})
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0 or n > MAX_BODY:
                self._json(413, {"error": "bad content length"})
                return
            raw = self.rfile.read(n).decode("utf-8", "replace")
        except Exception as e:
            self._json(400, {"error": type(e).__name__})
            return

        ip = _client_ip(self)
        if not _rate_limit(ip):
            self._json(429, {
                "jsonrpc": "2.0", "id": None,
                "error": {"code": -32000,
                          "message": "Rate limit: 30 requests/hour per IP. " +
                                     UPGRADE}})
            return

        try:
            msg = json.loads(raw)
        except Exception:
            self._json(400, {"jsonrpc": "2.0", "id": None,
                             "error": {"code": -32700, "message": "Parse error"}})
            return

        # 支持批量（数组）
        if isinstance(msg, list):
            out = [handle_rpc(m) for m in msg]
            out = [o for o in out if o is not None]
            self._json(200, out)
            return

        resp = handle_rpc(msg)
        if resp is None:
            # 通知类消息：返回 202 Accepted（规范允许）
            self.send_response(202)
            self.send_header("Content-Length", "0")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            return
        self._json(200, resp)


if __name__ == "__main__":
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print("内容合规 MCP HTTP Server")
    print("  监听: http://127.0.0.1:" + str(PORT) + "/mcp")
    print("  工具: " + ", ".join(t["name"] for t in TOOLS))
    print("  免费额度: " + str(FREE_MAX_CHARS) + " 字符/次 · " +
          str(FREE_MAX_PER_HOUR) + " 次/小时/IP")
    srv.serve_forever()
