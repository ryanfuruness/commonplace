"""End-to-end over real HTTP: MCP client -> uvicorn -> auth -> tools -> SQLite."""

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import anyio
import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

ROOT = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    db = tmp_path_factory.mktemp("cp") / "cp.db"
    port = _free_port()
    env = {**os.environ, "COMMONPLACE_DB": str(db), "COMMONPLACE_OWNER_TOKEN": "owner-token-123",
           "COMMONPLACE_OWNER_NAME": "ryan", "PORT": str(port), "HOST": "127.0.0.1"}
    log = open(db.parent / "server.log", "w")
    proc = subprocess.Popen([sys.executable, "-m", "commonplace"], cwd=ROOT, env=env,
                            stdout=log, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            if httpx.get(base + "/healthz").status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.1)
    member = subprocess.run([sys.executable, "-m", "commonplace.admin", "--db", str(db), "add-contributor", "sam"],
                            cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip().splitlines()[-1]
    yield base, "owner-token-123", member
    proc.terminate()
    proc.wait(5)
    log.close()
    text = (db.parent / "server.log").read_text()
    assert "owner-token-123" not in text and "key=[redacted]" in text


async def _call(url, headers, name, args):
    async with httpx.AsyncClient(headers=headers, timeout=30) as http:
        async with streamable_http_client(url, http_client=http) as (r, w, _):
            async with ClientSession(r, w) as s:
                await s.initialize()
                res = await s.call_tool(name, args)
    text = res.content[0].text if res.content else ""
    return res.isError, (json.loads(text) if not res.isError else text)


def call(base, token, name, args, via="header"):
    if via == "header":
        return anyio.run(_call, base + "/mcp", {"Authorization": f"Bearer {token}"}, name, args)
    return anyio.run(_call, base + f"/mcp?key={token}", {}, name, args)


def test_rejects_without_token(server):
    base, _, _ = server
    r = httpx.post(base + "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                   headers={"Accept": "application/json, text/event-stream"})
    assert r.status_code == 401


def test_full_loop(server):
    base, owner, member = server
    err, out = call(base, member, "commons_stats", {})
    assert not err and out["you"] == {"name": "sam", "role": "member"}

    body = ("## Approach\nStart from the installed base of the systems the product replaces.\n\n"
            "## Traps\nAnalyst totals double-count adjacent categories.\n\n## Human corrections\n"
            "The stakeholder wanted ranges with named assumptions.\n\n## Evidence\nAccepted after one revision.\n")
    err, e = call(base, member, "contribute", {"title": "Installed-base market sizing", "summary": "Bottom-up "
                  "sizing when public data is thin.", "kind": "methodology", "task": "market sizing",
                  "domain": "enterprise AI, GCC", "body": body, "human_approved": True, "human_steered": True})
    assert not err, e
    err, res = call(base, owner, "search", {"query": "size an enterprise software market bottom-up"}, via="query")
    assert not err and res["results"][0]["id"] == e["id"]

    err, rep = call(base, owner, "report_use", {"entry_id": e["id"], "task": "market sizing", "outcome": "success",
                                                "human_signal": "accepted", "domain": "govtech, KSA"})
    assert not err and rep["quality"]["reports"] == 1

    err, msg = call(base, member, "curation_queue", {})
    assert err and "curator" in msg
    err, q = call(base, owner, "curation_queue", {})
    assert not err and "promotion_candidates" in q

    err, msg = call(base, member, "contribute", {"title": "x", "summary": "y", "kind": "methodology",
                                                 "task": "t", "body": body + "\nemail me at a.b@c.com"})
    assert err and "email" in msg


def test_web_view(server):
    base, owner, _ = server
    assert httpx.get(base + "/").status_code == 401
    with httpx.Client(base_url=base, follow_redirects=True) as c:
        r = c.get(f"/?key={owner}")
        assert r.status_code == 200 and "Commonplace" in r.text
        assert "default-src 'none'" in r.headers["content-security-policy"]
        assert c.get("/").status_code == 200  # cookie set


def test_transport_hardening(server):
    base, owner, _ = server
    hdrs = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    # The browser cookie never authenticates MCP calls.
    r = httpx.post(base + "/mcp", json=body, headers={**hdrs, "Cookie": f"cp_key={owner}"})
    assert r.status_code == 401
    # A malformed unrelated cookie does not break the web view.
    r = httpx.get(base + "/", headers={"Cookie": f'{{"a":1}}=1; cp_key={owner}'})
    assert r.status_code == 200
    # Oversized requests are refused before reaching a tool.
    r = httpx.post(base + f"/mcp?key={owner}", content=b"x" * (300 * 1024), headers=hdrs)
    assert r.status_code == 413
    r = httpx.post(base + f"/mcp?key={owner}", content=iter([b"x" * 65536] * 5), headers=hdrs)  # chunked
    assert r.status_code == 413
    # Nomination decisions need a same-origin browser session, not a token.
    r = httpx.post(base + "/entry/x/decision", data={"decision": "approve"},
                   headers={"Authorization": f"Bearer {owner}", "Origin": base})
    assert r.status_code == 403
    r = httpx.post(base + "/entry/x/decision", data={"decision": "approve"},
                   headers={"Cookie": f"cp_key={owner}", "Origin": "https://evil.example"})
    assert r.status_code == 403
