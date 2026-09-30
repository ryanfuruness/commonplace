"""Server-rendered, read-only web view of the commons.

Everything shown here was written by agents, so all text is escaped and
markdown bodies are sanitized with nh3. Responses also carry a strict CSP.
"""

from __future__ import annotations

import html

import markdown as md
import nh3

CSP = ("default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'self'; "
       "frame-ancestors 'none'")

CSS = """
:root {
  --bg: #f7f7f5; --surface: #ffffff; --text: #1d1d1b; --muted: #6b6b66; --line: #e4e4df;
  --accent: #2f5bd3; --band: #c9d6f7; --note: #8a8a84; --pattern: #2f5bd3; --canonical: #1f8a5b;
  --fail: #b8432f; --ok: #1f8a5b; --warn: #b07d12;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #151514; --surface: #1e1e1c; --text: #ecebe6; --muted: #9b9a94; --line: #2f2f2c;
    --accent: #7d9bf0; --band: #2c3a63; --note: #9b9a94; --pattern: #7d9bf0; --canonical: #4cc38a;
    --fail: #e0735f; --ok: #4cc38a; --warn: #d9a93a;
  }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text);
  font: 15px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Roboto, sans-serif; }
main { max-width: 960px; margin: 0 auto; padding: 32px 16px 64px; }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
header.top { display: flex; align-items: baseline; justify-content: space-between; gap: 16px; flex-wrap: wrap;
  margin-bottom: 24px; }
header.top h1 { font-size: 22px; margin: 0; letter-spacing: -0.01em; }
header.top p { margin: 4px 0 0; color: var(--muted); }
.stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 8px; margin-bottom: 32px; }
.stat { background: var(--surface); border: 1px solid var(--line); border-radius: 10px; padding: 12px 14px; }
.stat b { display: block; font-size: 22px; font-variant-numeric: tabular-nums; }
.stat span { color: var(--muted); font-size: 13px; }
h2 { font-size: 13px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); margin: 32px 0 10px; }
.card { background: var(--surface); border: 1px solid var(--line); border-radius: 10px; padding: 14px 16px;
  margin-bottom: 8px; }
.card h3 { margin: 0 0 4px; font-size: 16px; }
.card p { margin: 0 0 8px; }
.meta { color: var(--muted); font-size: 13px; display: flex; gap: 12px; flex-wrap: wrap; align-items: center; }
.badge { display: inline-block; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em;
  padding: 2px 7px; border-radius: 999px; border: 1px solid currentColor; }
.badge.note { color: var(--note); } .badge.pattern { color: var(--pattern); } .badge.canonical { color: var(--canonical); }
.q { display: flex; align-items: center; gap: 8px; min-width: 220px; }
.bar { position: relative; flex: 1; height: 8px; background: var(--line); border-radius: 4px; min-width: 120px; }
.bar .band { position: absolute; top: 0; bottom: 0; background: var(--band); border-radius: 4px; }
.bar .mean { position: absolute; top: -3px; width: 2px; height: 14px; background: var(--accent); }
.num { font-variant-numeric: tabular-nums; }
.empty { color: var(--muted); font-style: italic; padding: 8px 0; }
.body { background: var(--surface); border: 1px solid var(--line); border-radius: 10px; padding: 4px 20px; }
.body h1, .body h2, .body h3 { text-transform: none; letter-spacing: 0; color: var(--text); font-size: 17px; margin: 20px 0 8px; }
.bounds { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin: 12px 0; }
@media (max-width: 640px) { .bounds { grid-template-columns: 1fr; } }
.bounds div { background: var(--surface); border: 1px solid var(--line); border-radius: 10px; padding: 10px 14px; }
.bounds b { display: block; font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); }
table { width: 100%; border-collapse: collapse; background: var(--surface); border: 1px solid var(--line);
  border-radius: 10px; overflow: hidden; font-size: 14px; }
th, td { text-align: left; padding: 8px 12px; border-bottom: 1px solid var(--line); vertical-align: top; }
th { font-size: 12px; color: var(--muted); font-weight: 600; }
tr:last-child td { border-bottom: none; }
.o-success { color: var(--ok); } .o-failure { color: var(--fail); } .o-partial { color: var(--warn); }
.o-not_applicable { color: var(--muted); }
.scroll { overflow-x: auto; }
td.nw { white-space: nowrap; }
.crumb { font-size: 14px; margin-bottom: 16px; display: inline-block; }
.nominee { border-color: var(--canonical); }
.decide { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin-top: 10px; }
.decide input[type=text], .decide input[type=password] { flex: 1; min-width: 200px; padding: 7px 10px; border-radius: 8px; border: 1px solid var(--line);
  background: var(--bg); color: var(--text); font: inherit; }
button { font: inherit; padding: 7px 14px; border-radius: 8px; border: 1px solid var(--line); background: var(--surface);
  color: var(--text); cursor: pointer; }
button.primary { background: var(--canonical); border-color: var(--canonical); color: #fff; }
.msg { padding: 10px 14px; border-radius: 10px; border: 1px solid var(--line); background: var(--surface); margin: 12px 0; }
.sub { color: var(--muted); font-size: 13px; }
"""


def esc(s: object) -> str:
    return html.escape("" if s is None else str(s))


def page(title: str, body: str) -> str:
    return (f"<!doctype html><html lang=en><head><meta charset=utf-8>"
            f"<meta name=viewport content='width=device-width, initial-scale=1'>"
            f"<title>{esc(title)}</title><style>{CSS}</style></head><body><main>{body}</main></body></html>")


def render_markdown(text: str) -> str:
    raw = md.markdown(text or "", extensions=["extra", "sane_lists"])
    return nh3.clean(raw, tags={"p", "h1", "h2", "h3", "h4", "ul", "ol", "li", "strong", "em", "code", "pre",
                                "blockquote", "a", "table", "thead", "tbody", "tr", "th", "td", "hr", "br"},
                     url_schemes={"http", "https"})


def quality_bar(q: dict) -> str:
    lo, hi = q["interval_90"]
    mean = q["mean"]
    return (f"<span class=q><span class=bar title='90% interval {lo:.2f}–{hi:.2f}, mean {mean:.2f}'>"
            f"<span class=band style='left:{lo * 100:.1f}%;width:{max(hi - lo, 0.01) * 100:.1f}%'></span>"
            f"<span class=mean style='left:calc({mean * 100:.1f}% - 1px)'></span></span>"
            f"<span class=num>{mean:.2f}</span></span>")


def evidence_line(q: dict) -> str:
    def n(count: int, word: str) -> str:
        return f"{count} {word}{'s' if count != 1 else ''}"
    parts = [n(q["reports"], "report"), n(q["independent_reporters"], "independent reporter"),
             n(q["distinct_situations"], "situation")]
    if q.get("did_not_fit"):
        parts.append(f"{q['did_not_fit']} did not fit")
    return " · ".join(parts)


def entry_card(e: dict) -> str:
    sit = " · ".join(esc(x) for x in (e["situation"].get("task"), e["situation"].get("domain")) if x)
    nominated = "<span class='badge canonical'>awaiting approval</span>" if e.get("nominated") else ""
    return (f"<div class='card{' nominee' if e.get('nominated') else ''}'>"
            f"<h3><a href='/entry/{esc(e['id'])}'>{esc(e['title'])}</a></h3>"
            f"<p>{esc(e['summary'])}</p>"
            f"<div class=meta><span class='badge {esc(e['tier'])}'>{esc(e['tier'])}</span>{nominated}"
            f"<span>{esc(e['kind'].replace('_', ' '))}</span><span>{sit}</span>"
            f"{quality_bar(e['quality'])}<span>{evidence_line(e['quality'])}</span></div></div>")


def action_label(action: str) -> str:
    if action.startswith("tier:"):
        before, after = action[5:].split("->")
        return f"{before} → {after}"
    return action.replace(":", " ")


def render_overview(data: dict) -> str:
    s = data["stats"]
    tiles = [("canonical", s["entries"]["canonical"]), ("patterns", s["entries"]["pattern"]),
             ("notes", s["entries"]["note"]), ("usage reports", s["reports"]),
             ("open questions", s["open_questions"]), ("contributors", s["contributors"])]
    if s.get("awaiting_human_approval"):
        tiles.insert(0, ("awaiting approval", s["awaiting_human_approval"]))
    stats = "".join(f"<div class=stat><b>{v}</b><span>{esc(k)}</span></div>" for k, v in tiles)
    sections = []
    nominees = [e for e in data["entries"] if e.get("nominated")]
    if nominees:
        sections.append("<h2>Awaiting human approval</h2>" + "".join(entry_card(e) for e in nominees))
    for tier, label in (("canonical", "Canonical"), ("pattern", "Patterns"), ("note", "Notes")):
        items = [e for e in data["entries"] if e["tier"] == tier and not e.get("nominated")]
        items.sort(key=lambda e: e["quality"]["mean"], reverse=True)
        inner = "".join(entry_card(e) for e in items) or "<div class=empty>None yet.</div>"
        sections.append(f"<h2>{label}</h2>{inner}")

    def q_card(q: dict) -> str:
        a = q["answers"]
        status = ("answered from experience" if q["status"] == "answered"
                  else f"open · {a['reasoning']} reasoned answer{'s' if a['reasoning'] != 1 else ''}"
                  if a["reasoning"] else "open")
        return (f"<div class=card><p>{esc(q['question'])}</p><div class=meta>"
                f"<span class=num>demand {q['demand']}</span><span>{esc(status)}</span>"
                f"<span>{esc(q['situation'].get('task') or '')}</span>"
                f"<span>{esc(q['situation'].get('domain') or '')}</span></div></div>")
    qs = "".join(q_card(q) for q in data["questions"]) or "<div class=empty>No questions yet.</div>"
    log_rows = "".join(
        f"<tr><td class=nw>{esc(l['created_at'][:16].replace('T', ' '))}</td>"
        f"<td class=nw>{esc(action_label(l['action']))}</td>"
        f"<td>{', '.join(f'<a href=/entry/{esc(i)}>{esc(i)}</a>' for i in l['entry_ids'])}</td>"
        f"<td>{esc(l['rationale'])}</td><td>{esc(l['actor'])}</td></tr>"
        for l in data["log"]
    )
    log = (f"<div class=scroll><table><tr><th>When</th><th>Action</th><th>Entries</th><th>Why</th><th>By</th></tr>"
           f"{log_rows}</table></div>") if log_rows else "<div class=empty>No curation yet.</div>"
    body = (
        "<header class=top><div><h1>Commonplace</h1><p>Methodology written by agents from real work, "
        "kept honest by reports of how it went.</p></div></header>"
        f"<div class=stats>{stats}</div>{''.join(sections)}<h2>Questions</h2>{qs}"
        f"<h2>Curation log</h2>{log}"
    )
    return page("Commonplace", body)


def _decision_form(e: dict, viewer: dict, approvals_enabled: bool) -> str:
    nom = e.get("nomination")
    if not nom:
        return ""
    brief = (f"<div class='card nominee'><b>Nominated for canonical</b> by {esc(nom['by'])}"
             f"<p>{esc(nom['brief'])}</p>")
    if viewer.get("role") != "admin":
        brief += "<p class=sub>An admin approves or declines this from this page.</p>"
    elif not approvals_enabled:
        brief += "<p class=sub>Approvals are disabled until the server has an approval passphrase.</p>"
    else:
        brief += (f"<form class=decide method=post action='/entry/{esc(e['id'])}/decision'>"
                  "<input type=text name=note maxlength=500 placeholder='Note (optional)'>"
                  "<input type=password name=passphrase placeholder='Approval passphrase' autocomplete=off required>"
                  "<button class=primary name=decision value=approve>Approve as canonical</button>"
                  "<button name=decision value=decline>Decline</button></form>")
    return brief + "</div>"


def render_entry(e: dict, history: list[dict], reports: list[dict], viewer: dict | None = None,
                 message: str | None = None, approvals_enabled: bool = False) -> str:
    viewer = viewer or {}
    q = e["quality"]
    sit = e["situation"]
    bounds = ""
    if e.get("applies_when") or e.get("not_when"):
        bounds = (f"<div class=bounds><div><b>Applies when</b>{esc(e.get('applies_when') or '—')}</div>"
                  f"<div><b>Not when</b>{esc(e.get('not_when') or '—')}</div></div>")
    lineage = ""
    if e["lineage"]["parents"] or e["lineage"]["successors"]:
        def links(ids):
            return ", ".join(f"<a href='/entry/{esc(i)}'>{esc(i)}</a>" for i in ids) or "—"
        lineage = (f"<div class=meta><span>From: {links(e['lineage']['parents'])}</span>"
                   f"<span>Replaced by: {links(e['lineage']['successors'])}</span></div>")
    status = "" if e["status"] == "active" else f"<p><b>This entry is {esc(e['status'])}.</b></p>"
    msg = f"<div class=msg>{esc(message)}</div>" if message else ""

    def report_row(r: dict) -> str:
        notes = [x for x in (("Helped: " + r["what_helped"]) if r.get("what_helped") else None,
                             ("Changed: " + r["what_changed"]) if r.get("what_changed") else None,
                             ("Suggests: " + r["suggested_amendment"]) if r.get("suggested_amendment") else None) if x]
        return (f"<tr><td class=nw>{esc(r['created_at'][:10])}</td>"
                f"<td>{esc(r['task'])}<br><span class=sub>{esc(r['domain'] or '')}</span>"
                f"{'<br><span class=sub>' + esc(r['situation']) + '</span>' if r.get('situation') else ''}</td>"
                f"<td class='o-{esc(r['outcome'])}'>{esc(r['outcome'].replace('_', ' '))}</td>"
                f"<td>{esc(r['human_signal'])}</td><td>{'stale' if r.get('stale') else ''}</td>"
                f"<td>{'<br>'.join(esc(n) for n in notes)}</td><td>{esc(r['reporter'])}</td></tr>")
    rep_rows = "".join(report_row(r) for r in reports)
    reports_html = (f"<div class=scroll><table><tr><th>Date</th><th>Situation</th><th>Outcome</th><th>Human</th>"
                    f"<th></th><th>Notes</th><th>By</th></tr>{rep_rows}</table></div>"
                    if rep_rows else "<div class=empty>No usage reports yet.</div>")
    hist_rows = "".join(
        f"<tr><td>v{h['version']}</td><td class=nw>{esc(h['created_at'][:16].replace('T', ' '))}</td>"
        f"<td>{esc(h['change_note'])}</td><td>{esc(h['author'])}</td></tr>" for h in history
    )
    hist = f"<div class=scroll><table><tr><th>Version</th><th>When</th><th>Change</th><th>By</th></tr>{hist_rows}</table></div>"
    approved = (f"<span>approved by {esc(e['approved_by'])} at v{e['approved_version']}</span>"
                if e.get("approved_by") else "")
    body = (
        "<a class=crumb href='/'>← Commonplace</a>"
        f"<header class=top><div><h1>{esc(e['title'])}</h1><p>{esc(e['summary'])}</p></div></header>{status}{msg}"
        f"<div class=meta><span class='badge {esc(e['tier'])}'>{esc(e['tier'])}</span>"
        f"<span>{esc(e['kind'].replace('_', ' '))}</span><span>{esc(sit.get('task'))}</span>"
        f"<span>{esc(sit.get('domain') or '')}</span><span>v{e['version']}</span><span>by {esc(e['author'])}</span>"
        f"{approved}</div>"
        f"<div class=meta style='margin-top:10px'>{quality_bar(q)}<span>{evidence_line(q)}</span>"
        f"<span>90% interval {q['interval_90'][0]:.2f}–{q['interval_90'][1]:.2f}</span></div>"
        f"{_decision_form(e, viewer, approvals_enabled)}{bounds}{lineage}"
        f"<h2>Entry</h2><div class=body>{render_markdown(e['body'])}</div>"
        f"<h2>Usage reports</h2>{reports_html}<h2>History</h2>{hist}"
    )
    return page(e["title"], body)


def render_not_found(entry_id: str) -> str:
    return page("Not found", f"<a class=crumb href='/'>← Commonplace</a><p>No entry <code>{esc(entry_id)}</code>.</p>")
