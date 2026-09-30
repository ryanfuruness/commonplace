"""Run a small illustrative commons end to end over real MCP, then serve it.

Three agents contribute, search, apply and report; one asks a question that
another answers from experience; then a curator pass merges a duplicate,
splits an entry whose reports diverge by situation, folds in an amendment,
promotes an entry and turns the answer into an entry. All content is invented
for illustration.

    python demo/seed_demo.py            # seed, print the web URL, keep serving
    python demo/seed_demo.py --no-serve # seed and exit (used in CI)
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import anyio
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from commonplace import store  # noqa: E402
from commonplace.db import connect  # noqa: E402

SIZING_BODY = """## Approach
Size bottom-up from the installed base of the systems the product would replace, counted from public procurement records, then cross-check against top-down analyst totals. The bottom-up figure anchors the range; the top-down figure only flags an order-of-magnitude error.

## Non-obvious moves
Awarded public tenders were a better demand signal than analyst reports, which extrapolated from other regions.

## Traps
Global startup databases showed almost no competitors. That was a coverage gap, not an open market.

## Human corrections
The stakeholder rejected a point estimate and asked for a range with each assumption named, because the figure was going to a board that would challenge assumptions one by one.

## Evidence
Accepted after one revision; the assumption table was reused in the board material.
"""

DUP_BODY = """## Approach
Count the installed base of incumbent systems in the target segment and multiply by expected replacement value; compare with analyst totals only as a sanity check.

## Traps
Analyst totals double-count adjacent categories, which inflates top-down estimates.

## Human corrections
The human asked for the assumptions to be listed next to the number so the range could be defended.

## Evidence
Accepted without revision.
"""

SOURCES_BODY = """## Sources
For competitor mapping in emerging markets, regional startup databases and local accelerator portfolios were far more complete than global databases, which missed most companies founded in the last three years. Government tender portals listed which vendors actually won deals.

## Evidence
Found three times as many relevant competitors as the global database; the human confirmed the list against their own knowledge.
"""

WINLOSS_BODY = """## Approach
Before designing pricing, synthesize win/loss notes by the buyer's stated alternative rather than by deal size. The alternative the buyer compared against sets the price anchor more than the product's own cost structure.

## Traps
Sales notes over-attribute losses to price. Read the notes for what the buyer did instead.

## Human corrections
The human asked to separate procurement-led deals from champion-led deals, because procurement anchors on the lowest bid while champions anchor on the cost of the problem.

## Evidence
Accepted; the segmentation changed the proposed price tiers.
"""

TENDER_BODY = """## Approach
Estimate public-sector AI budgets from awarded tenders over the last three years as a floor, then scale by the share of AI spend that goes through framework agreements rather than open tenders, which you can estimate from the ratio of framework to open awards in adjacent IT categories.

## Traps
Announced national AI budgets are multi-year envelopes that include infrastructure; treating them as annual software spend overstates the market several times over.

## Evidence
Used in one sizing exercise; the human accepted the floor-plus-framework range.
"""


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class Agent:
    def __init__(self, base: str, token: str, name: str):
        self.url, self.token, self.name = base + "/mcp", token, name

    def __call__(self, tool: str, **args):
        return anyio.run(self._call, tool, args)

    async def _call(self, tool, args):
        async with httpx.AsyncClient(headers={"Authorization": f"Bearer {self.token}"}, timeout=30) as http:
            async with streamable_http_client(self.url, http_client=http) as (r, w, _):
                async with ClientSession(r, w) as s:
                    await s.initialize()
                    res = await s.call_tool(tool, args)
        text = res.content[0].text if res.content else ""
        if res.isError:
            raise RuntimeError(f"{self.name} {tool}: {text}")
        return json.loads(text)


def seed(base: str, tokens: dict[str, str]) -> None:
    ada, ben, cy = (Agent(base, tokens[n], n) for n in ("ada", "ben", "cy"))
    curator = Agent(base, tokens["ryan"], "ryan")

    def say(msg):
        print(f"  {msg}")

    print("Practitioners")
    sizing = ada("contribute", title="Installed-base market sizing for enterprise software in data-sparse markets",
                 summary="Bottom-up sizing from procurement records when public market data is thin.",
                 kind="methodology", task="market sizing", domain="enterprise software, GCC",
                 situation="Series B platform company entering a regional enterprise market",
                 body=SIZING_BODY, human_steered=True, human_approved=True,
                 applies_when="public market data is sparse or extrapolated from other regions")["id"]
    say(f"ada contributed {sizing}")
    dup = ben("contribute", title="Bottom-up enterprise market sizing from installed base",
              summary="Size enterprise markets from the installed base of incumbent systems.",
              kind="methodology", task="market sizing", domain="enterprise software, Europe",
              body=DUP_BODY, human_approved=True)["id"]
    say(f"ben contributed {dup} (a near-duplicate)")
    sources = ben("contribute", title="Regional startup databases for competitor mapping in emerging markets",
                  summary="Regional databases and tender portals beat global startup databases for recent companies.",
                  kind="source_intel", task="competitor mapping", domain="emerging markets",
                  body=SOURCES_BODY, human_approved=True)["id"]
    winloss = cy("contribute", title="Win/loss synthesis by buyer alternative before pricing",
                 summary="Group win/loss notes by what the buyer compared against; it sets the price anchor.",
                 kind="methodology", task="pricing research", domain="B2B software",
                 body=WINLOSS_BODY, human_steered=True, human_approved=True)["id"]
    say(f"ben contributed {sources}; cy contributed {winloss}")

    hits = cy("search", query="size a B2B software market with little public data")["results"]
    say(f"cy searched: top result {hits[0]['id']} ({hits[0]['tier']})")
    for agent, domain, outcome, signal, changed in (
        (cy, "govtech software, KSA", "success", "accepted", None),
        (ben, "industrial IoT, UAE", "success", "accepted", None),
        (ada, "healthcare IT, Qatar", "success", "corrected", "Added a sensitivity table at the human's request"),
        (cy, "consumer fintech app, Egypt", "failure", "rejected", "No installed base exists for consumer apps"),
        (ben, "consumer marketplace, Morocco", "failure", "rejected", "Procurement records do not cover consumers"),
    ):
        agent("report_use", entry_id=sizing, task="market sizing", domain=domain, outcome=outcome,
              human_signal=signal, what_changed=changed)
    for agent, domain in ((ada, "enterprise software, KSA"), (cy, "logistics software, Oman")):
        agent("report_use", entry_id=dup, task="market sizing", domain=domain, outcome="success",
              human_signal="accepted")
    for agent, domain in ((ada, "climate tech, Kenya"), (cy, "fintech, Pakistan"), (ada, "edtech, Indonesia")):
        agent("report_use", entry_id=sources, task="competitor mapping", domain=domain, outcome="success",
              human_signal="accepted")
    ada("report_use", entry_id=winloss, task="pricing research", domain="B2B software, public sector",
        outcome="partial", human_signal="corrected",
        suggested_amendment="Public-sector deals are almost all procurement-led; say so, and anchor on "
                            "framework-agreement rates instead of champion value.")
    say("agents filed 11 usage reports")

    q = ada("ask", question="How should public-sector AI software budgets be estimated when announced national "
                            "AI budgets mix infrastructure and multi-year envelopes?",
            task="market sizing", domain="public sector AI, GCC")["id"]
    ben("ask", question="Same need: estimating public-sector AI budgets.", same_as=q)
    cy("answer", question_id=q, basis="experience",
       body="Treat awarded tenders over three years as a floor and scale by the framework-agreement share. "
            "National budget announcements overstated annual software spend several times over.")
    say(f"ada asked {q}, ben registered the same need, cy answered from experience")

    print("Curator")
    queue = curator("curation_queue")
    say("queue: " + ", ".join(f"{k}={len(v)}" for k, v in queue.items() if isinstance(v, list)))

    merged = curator("merge_entries", entry_ids=[sizing, dup],
                     title="Installed-base market sizing for enterprise software in data-sparse markets",
                     summary="Bottom-up sizing from procurement records and installed base when public data is thin.",
                     body=SIZING_BODY, task="market sizing", domain="enterprise software",
                     rationale="Same approach for the same kind of situation; combined their evidence.")["id"]
    say(f"merged duplicates into {merged}")

    full = curator("get_entry", entry_id=merged)
    queue = curator("curation_queue")
    pending = {a["id"]: a for a in queue["amendments"]}
    cand = next(c for c in queue["split_candidates"] if c["id"] == merged)
    say(f"split candidate {merged}: reports mentioning {cand['dividing_term']!r} succeed "
        f"{cand['with_term']['success_rate']:.0%}, others {cand['without_term']['success_rate']:.0%}")
    consumer, enterprise = cand["with_term"]["report_ids"], cand["without_term"]["report_ids"]
    split = curator("split_entry", entry_id=merged, rationale=(
        "Reports diverge by buyer type: every enterprise use succeeded, both consumer uses failed because "
        "no installed base or procurement record exists for consumers."), children=[
        {"title": "Installed-base market sizing for enterprise software in data-sparse markets",
         "summary": full["summary"], "body": SIZING_BODY, "task": "market sizing", "domain": "enterprise software",
         "applies_when": "buyers are organizations with procurement records and incumbent systems",
         "not_when": "consumer products, where no installed base or procurement record exists",
         "report_ids": enterprise},
        {"title": "Consumer market sizing: installed-base methods do not transfer",
         "summary": "Why procurement-based bottom-up sizing fails for consumer products, and what to check first.",
         "body": ("## Trap\nInstalled-base and procurement-record sizing assumes organizational buyers. For "
                  "consumer products there is no installed base to count and no procurement trail, so the method "
                  "produces an empty or arbitrary floor.\n\n## Avoid\nConfirm the buyer is an organization before "
                  "using installed-base methods. For consumer products, start from usage panels or app-store "
                  "proxies instead.\n\n## Evidence\nTwo consumer uses of the enterprise method were rejected.\n"),
         "task": "market sizing", "domain": "consumer products",
         "applies_when": "sizing a consumer product market", "report_ids": consumer},
    ])
    b2b = split["children"][0]["id"]
    say(f"split {merged} into {b2b} and {split['children'][1]['id']}")

    wl = pending[winloss]
    curator("revise_entry", entry_id=winloss, processed_report_ids=[r["id"] for r in wl["pending_reports"]],
            body=WINLOSS_BODY.replace("## Evidence", "In public-sector deals nearly every sale is procurement-led; "
                                      "anchor on framework-agreement rates rather than champion value.\n\n## Evidence"),
            not_when="the buyer is a public-sector body buying through framework agreements, unless adapted as above",
            change_note="Folded in a corrected public-sector use: procurement-led deals need a different anchor.")
    say(f"revised {winloss} with a public-sector amendment")

    for cand in curator("curation_queue")["promotion_candidates"]:
        curator("set_tier", entry_id=cand["id"], tier=cand["to"],
                rationale=f"Meets {cand['to']} thresholds with evidence from distinct situations and contributors.")
        say(f"promoted {cand['id']} to {cand['to']}")

    curator("contribute", title="Public-sector AI budget estimation from awarded tenders",
            summary="Estimate public-sector AI software spend from tenders plus framework share, not announced budgets.",
            kind="methodology", task="market sizing", domain="public sector AI", body=TENDER_BODY,
            answers_question=q, human_approved=True)
    say("turned cy's experience-based answer into an entry")

    stats = curator("commons_stats")
    say(f"final: {stats['entries']}, {stats['reports']} reports, {stats['reports_awaiting_curation']} awaiting curation")
    skill = curator("export_skill", entry_id=b2b)
    say(f"exported {b2b} as skill '{skill['name']}'")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-serve", action="store_true")
    ap.add_argument("--port", type=int, default=0)
    args = ap.parse_args()

    db = os.path.join(tempfile.mkdtemp(), "demo.db")
    os.environ["COMMONPLACE_DB"] = db
    conn = connect(db)
    tokens = {name: store.add_contributor(conn, name, role)
              for name, role in (("ryan", "admin"), ("ada", "member"), ("ben", "member"), ("cy", "member"))}
    conn.close()

    port = args.port or free_port()
    env = {**os.environ, "COMMONPLACE_DB": db, "PORT": str(port), "HOST": "127.0.0.1",
           "CP_CANONICAL_REPORTERS": "2"}
    proc = subprocess.Popen([sys.executable, "-m", "commonplace"], cwd=ROOT, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                if httpx.get(base + "/healthz").status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.1)
        seed(base, tokens)
        print(f"\nWeb view: {base}/?key={tokens['ryan']}")
        if not args.no_serve:
            print("Serving; Ctrl-C to stop.")
            proc.wait()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
