import random

import pytest

from commonplace import store
from commonplace.db import connect
from commonplace.lint import LintError
from commonplace.scoring import Thresholds, ReportView, compute_quality, report_weights

BODY = """## Approach
Size the market bottom-up from the installed base of target systems, not top-down from analyst totals.

## Non-obvious moves
Government tender portals are a better demand signal than analyst reports in this region.

## Traps
Startup databases are sparse here; do not treat missing data as absence of competitors.

## Human corrections
The stakeholder wanted a range with explicit assumptions, not a single point estimate.

## Evidence
Accepted by the stakeholder after one revision.
"""

T = Thresholds(pattern_n_eff=3, pattern_low=0.5, pattern_situations=2, pattern_reporters=2,
               canonical_n_eff=6, canonical_low=0.6, canonical_situations=3, canonical_reporters=2)


@pytest.fixture
def env():
    conn = connect(":memory:")
    people = {}
    for name, role in (("ada", "member"), ("ben", "member"), ("cy", "member"), ("cur", "curator"), ("own", "admin")):
        tok = store.add_contributor(conn, name, role)
        people[name] = store.contributor_for_token(conn, tok)
    return conn, people


def contribute(conn, who, **kw):
    args = dict(title="Bottom-up market sizing from installed base", summary="Size enterprise markets bottom-up "
                "when public data is sparse.", kind="methodology", task="market sizing", domain="enterprise AI, GCC",
                body=BODY, human_steered=True, human_approved=True)
    args.update(kw)
    return store.contribute(conn, who, **args)


def test_contribute_and_search(env):
    conn, p = env
    e = contribute(conn, p["ada"])
    assert e["tier"] == "note" and e["warnings"] == []
    res = store.search(conn, "market sizing for enterprise AI in the Gulf", rng=random.Random(0))
    assert res["results"][0]["id"] == e["id"]
    assert res["results"][0]["quality"]["reports"] == 0
    assert store.search(conn, "watercolor painting technique")["results"] == []


def test_lint_rejects_leaks(env):
    conn, p = env
    with pytest.raises(LintError):
        contribute(conn, p["ada"], body=BODY + "\nContact jane.doe@acme.com for the data.")
    with pytest.raises(LintError):
        contribute(conn, p["ada"], body=BODY + "\napi_key = sk-abcdefghijklmnopqrstuvwxyz123456")
    with pytest.raises(LintError):
        contribute(conn, p["ada"], body="too short")
    with pytest.raises(ValueError):
        contribute(conn, p["ada"], kind="vibes")


def test_missing_sections_warn(env):
    conn, p = env
    e = contribute(conn, p["ada"], body="## Approach\n" + "Do the thing carefully. " * 20)
    assert any("traps" in w for w in e["warnings"])


def test_report_rules(env):
    conn, p = env
    e = contribute(conn, p["ada"])
    with pytest.raises(ValueError):
        store.report_use(conn, p["ben"], entry_id=e["id"], task="market sizing", outcome="success",
                         human_signal="rejected")
    r = store.report_use(conn, p["ben"], entry_id=e["id"], task="market sizing", outcome="not_applicable")
    assert r["quality"]["reports"] == 0 and r["quality"]["did_not_fit"] == 1


def test_weights():
    base = dict(task="t", domain="d")
    views = [
        ReportView(reporter="a", outcome="success", human_signal="accepted", created_at="1", **base),
        ReportView(reporter="a", outcome="success", human_signal="accepted", created_at="2", **base),
        ReportView(reporter="a", outcome="success", human_signal="accepted", created_at="3", **base),
        ReportView(reporter="b", outcome="success", human_signal="none", created_at="4", **base),
        ReportView(reporter="c", outcome="failure", human_signal="accepted", created_at="5", stale=True, **base),
        ReportView(reporter="a", outcome="success", human_signal="accepted", created_at="6", task="t",
                   domain="another setting"),
    ]
    w = report_weights(views)
    assert w == [1.0, 0.5, 0.25, 0.5, 0.5, 1.0]
    q = compute_quality(views)
    assert q.alpha == pytest.approx(1 + 3.25) and q.beta == pytest.approx(1 + 0.5)
    assert q.reporters == 3 and q.situations == 2


def test_promotion_path(env):
    conn, p = env
    e = contribute(conn, p["ada"])
    eid = e["id"]
    with pytest.raises(ValueError, match="Not eligible"):
        store.set_tier(conn, p["cur"], T, entry_id=eid, tier="pattern", rationale="looks good")
    with pytest.raises(ValueError, match="one tier at a time"):
        store.set_tier(conn, p["cur"], T, entry_id=eid, tier="canonical", rationale="x")
    for who, dom in (("ben", "enterprise AI, GCC"), ("cy", "govtech, KSA"), ("ben", "fintech, UAE"),
                     ("cy", "health AI, Qatar")):
        store.report_use(conn, p[who], entry_id=eid, task="market sizing", domain=dom, outcome="success",
                         human_signal="accepted")
    q = store.curation_queue(conn, T)
    assert [c["id"] for c in q["promotion_candidates"]] == [eid]
    store.set_tier(conn, p["cur"], T, entry_id=eid, tier="pattern", rationale="4 accepted uses")
    for i in range(6):
        store.report_use(conn, p[("ben", "cy")[i % 2]], entry_id=eid, task="market sizing",
                         domain=f"sector {i}", outcome="success", human_signal="accepted")
    out = store.set_tier(conn, p["cur"], T, entry_id=eid, tier="canonical", rationale="proven")
    assert out["nominated"] and store.get_entry(conn, eid)["tier"] == "pattern"
    assert store.curation_queue(conn, T)["awaiting_human_approval"][0]["id"] == eid
    with pytest.raises(store.Forbidden):
        store.decide_nomination(conn, p["cur"], T, entry_id=eid, approve=True)
    store.decide_nomination(conn, p["own"], T, entry_id=eid, approve=True, note="read it")
    got = store.get_entry(conn, eid)
    assert got["tier"] == "canonical" and got["approved_by"] == "own" and got["nomination"] is None

    # A boundary edit is not material, so evidence stands, but any change lapses canonical approval.
    before = got["quality"]["evidence"]
    r = store.revise_entry(conn, p["cur"], entry_id=eid, not_when="consumer products", change_note="boundary")
    assert not r["material"] and "note" in r
    got = store.get_entry(conn, eid)
    assert got["quality"]["evidence"] == before
    assert got["tier"] == "pattern" and got["approved_by"] is None
    # A body change is material: earlier reports go stale.
    r = store.revise_entry(conn, p["cur"], entry_id=eid, body=BODY + "\nNew step.\n", change_note="new step",
                           material=True)
    assert r["material"]
    assert store.get_entry(conn, eid)["quality"]["evidence"] == pytest.approx(before / 2)


def test_author_cannot_promote_alone(env):
    conn, p = env
    eid = contribute(conn, p["ada"])["id"]
    for i in range(6):
        store.report_use(conn, p["ada"], entry_id=eid, task="market sizing", domain=f"region{i}",
                         outcome="success", human_signal="accepted")
    q = store.get_entry(conn, eid)["quality"]
    assert q["independent_reporters"] == 0
    assert store.curation_queue(conn, T)["promotion_candidates"] == []
    personal = Thresholds(pattern_reporters=0, canonical_reporters=0)
    assert store.curation_queue(conn, personal)["promotion_candidates"][0]["id"] == eid


def test_split_carries_evidence(env):
    conn, p = env
    eid = contribute(conn, p["ada"])["id"]
    good, bad = [], []
    for who, dom in (("ben", "B2B enterprise, GCC"), ("cy", "B2B logistics, KSA"), ("ben", "B2B health, UAE")):
        good.append(store.report_use(conn, p[who], entry_id=eid, task="market sizing", domain=dom,
                                     outcome="success", human_signal="accepted")["recorded"])
    for who, dom in (("cy", "consumer apps, Egypt"), ("ben", "consumer marketplace, Morocco")):
        bad.append(store.report_use(conn, p[who], entry_id=eid, task="market sizing", domain=dom,
                                    outcome="failure", human_signal="rejected",
                                    what_changed="no install-base data for consumers")["recorded"])
    na = store.report_use(conn, p["cy"], entry_id=eid, task="pricing", outcome="not_applicable")["recorded"]
    q = store.curation_queue(conn, T)
    cand = q["split_candidates"][0]
    assert cand["id"] == eid and cand["dividing_term"] in ("consumer", "b2b")
    assert q["amendments"][0]["id"] == eid
    child = lambda title, rids, aw: {"title": title, "summary": "Sizing approach for " + title, "body": BODY,
                                     "applies_when": aw, "report_ids": rids}
    with pytest.raises(ValueError, match="Unassigned"):
        store.split_entry(conn, p["cur"], entry_id=eid, rationale="by buyer type",
                          children=[child("B2B enterprise sizing", good, "B2B"),
                                    child("Consumer sizing caution", bad, "consumer")])
    out = store.split_entry(conn, p["cur"], entry_id=eid, rationale="works for B2B, fails for consumer",
                            children=[child("B2B enterprise sizing", good + [na], "B2B enterprise"),
                                      child("Consumer sizing caution", bad, "consumer apps")])
    b2b, cons = out["children"]
    assert b2b["quality"]["mean"] > 0.7 and cons["quality"]["mean"] < 0.3
    assert b2b["quality"]["did_not_fit"] == 1
    assert store.get_entry(conn, eid)["status"] == "split"
    assert all(r["id"] != eid for r in store.search(conn, "market sizing")["results"])
    assert store.curation_queue(conn, T)["duplicate_candidates"] == []  # siblings are not duplicates
    with pytest.raises(ValueError, match="split"):
        store.report_use(conn, p["ben"], entry_id=eid, task="market sizing", outcome="success")


def test_merge_and_revise(env):
    conn, p = env
    a = contribute(conn, p["ada"])["id"]
    b = contribute(conn, p["ben"], title="Bottom-up market sizing using installed base")["id"]
    assert any(set(d["ids"]) == {a, b} for d in store.curation_queue(conn, T)["duplicate_candidates"])
    r = store.report_use(conn, p["cy"], entry_id=a, task="market sizing", outcome="partial",
                         suggested_amendment="Add a sanity check against top-down totals.")["recorded"]
    rev = store.revise_entry(conn, p["cur"], entry_id=a, body=BODY + "\nSanity-check against top-down totals.\n",
                             change_note="added sanity check", processed_report_ids=[r])
    assert rev["version"] == 2
    assert store.curation_queue(conn, T)["amendments"] == []
    m = store.merge_entries(conn, p["cur"], entry_ids=[a, b], title="Bottom-up market sizing", summary="Merged.",
                            body=BODY, rationale="duplicates")
    assert m["quality"]["reports"] == 1
    assert store.get_entry(conn, a)["lineage"]["successors"] == [m["id"]]


def test_questions_flow(env):
    conn, p = env
    q = store.ask(conn, p["ada"], question="How do you estimate sovereign AI procurement budgets in the GCC?",
                  task="market sizing", domain="public sector AI, GCC")
    again = store.ask(conn, p["ben"], question="x" * 20, same_as=q["id"])
    assert again["demand"] == 2
    res = store.search(conn, "sovereign AI procurement budget GCC")
    assert res["related_questions"][0]["id"] == q["id"]
    store.answer(conn, p["ben"], question_id=q["id"], basis="reasoning",
                 body="Probably scale announced national budgets by the software share of IT spend.")
    assert store.open_questions(conn)["questions"][0]["id"] == q["id"]  # a guess does not settle it
    store.answer(conn, p["cy"], question_id=q["id"], basis="experience",
                 body="Tender portals list awarded contracts; sum those over three years as a floor.")
    assert store.open_questions(conn)["questions"] == []
    assert store.search(conn, "sovereign AI procurement budget")["related_questions"][0]["status"] == "answered"
    assert store.ask(conn, p["ben"], question="", same_as=q["id"])["answers"][0]["basis"] == "experience"
    assert store.curation_queue(conn, T)["answers_to_convert"][0]["question_id"] == q["id"]
    e = contribute(conn, p["cur"], title="Sovereign AI budget estimation from tenders", answers_question=q["id"])
    assert store.curation_queue(conn, T)["answers_to_convert"] == []
    answers = store.get_question(conn, q["id"])["answers"]
    assert answers[0]["basis"] == "experience" and answers[0]["entry_id"] == e["id"]


def test_report_update(env):
    conn, p = env
    eid = contribute(conn, p["ada"])["id"]
    r = store.report_use(conn, p["ben"], entry_id=eid, task="market sizing", outcome="success")
    assert "update_report_id" in r["note"]
    assert r["quality"]["evidence"] == 0.5
    u = store.report_use(conn, p["ben"], update_report_id=r["recorded"], outcome="partial", human_signal="corrected",
                         what_changed="human wanted ranges")
    assert u["quality"]["evidence"] == 1.0 and u["quality"]["reports"] == 1
    with pytest.raises(store.NotFound):
        store.report_use(conn, p["cy"], update_report_id=r["recorded"], outcome="failure")


def test_search_details(env):
    conn, p = env
    cafe = contribute(conn, p["ada"], title="Café retail footfall estimation", kind="source_intel",
                      body="## Sources\n" + "Use municipal permit data for footfall. " * 8 + "\n## Evidence\nWorked.")
    arabic = contribute(conn, p["ada"], title="تقدير حجم السوق للبرمجيات المؤسسية",
                        summary="تقدير من القاعدة المركبة", task="تقدير حجم السوق")
    assert store.search(conn, "cafe footfall")["results"][0]["id"] == cafe["id"]
    assert store.search(conn, "café")["results"][0]["id"] == cafe["id"]
    assert store.search(conn, "المؤسسية")["results"][0]["id"] == arabic["id"]
    for i in range(31):
        contribute(conn, p["ben"], title=f"Market sizing variant {i}")
    got = store.search(conn, "market sizing footfall", kinds=["source_intel"])["results"]
    assert [r["id"] for r in got] == [cafe["id"]]
    with pytest.raises(ValueError, match="Unknown kinds"):
        store.search(conn, "x", kinds=["vibes"])
    # Text in not_when does not make an entry more relevant.
    a = contribute(conn, p["cy"], title="Channel checks for hardware demand", task="demand estimation")["id"]
    b = contribute(conn, p["cy"], title="Channel checks for hardware demand", task="demand estimation",
                   not_when="wearables and smartwatches")["id"]
    rel = {r["id"]: r["relevance"] for r in store.search(conn, "wearables smartwatches channel checks",
                                                        limit=15)["results"]}
    assert rel[b] <= rel[a]


def test_limits_and_retire(env):
    conn, p = env
    with pytest.raises(ValueError, match="limit"):
        contribute(conn, p["ada"], applies_when="word " * 500)
    with pytest.raises(ValueError, match="required"):
        store.revise_entry(conn, p["cur"], entry_id=contribute(conn, p["ada"])["id"], title="", change_note="x")
    eid = contribute(conn, p["ada"])["id"]
    conn.execute("UPDATE entries SET tier = 'pattern' WHERE id = ?", (eid,))
    store.retire_entry(conn, p["cur"], entry_id=eid, rationale="contained instructions to agents", purge_content=True)
    with pytest.raises(ValueError, match="retired"):
        store.export_skill(conn, eid)
    assert "Approach" not in store.get_entry(conn, eid)["body"]


def test_export_skill(env):
    conn, p = env
    eid = contribute(conn, p["ada"], applies_when="public data is sparse", not_when="consumer markets")["id"]
    with pytest.raises(ValueError):
        store.export_skill(conn, eid)
    conn.execute("UPDATE entries SET tier = 'pattern' WHERE id = ?", (eid,))
    out = store.export_skill(conn, eid)
    assert out["skill_md"].startswith("---\nname: bottom-up-market-sizing-from-installed-base\n")
    assert "Not for consumer markets." in out["skill_md"]


def test_roles(env):
    conn, p = env
    with pytest.raises(store.Forbidden):
        store.require_role(p["ada"], "curator")
    store.require_role(p["cur"], "curator")


def test_second_review_fixes(env):
    conn, p = env
    # Updating a report keeps fields that were not sent, and redacted reports are frozen.
    eid = contribute(conn, p["ada"])["id"]
    rid = store.report_use(conn, p["ben"], entry_id=eid, task="market sizing", domain="enterprise, GCC",
                           outcome="success", human_signal="accepted")["recorded"]
    u = store.report_use(conn, p["ben"], update_report_id=rid, suggested_amendment="Add a sanity check.")
    assert u["quality"]["evidence"] == 1.0
    store.redact_report(conn, p["cur"], report_id=rid, rationale="named a client")
    with pytest.raises(ValueError, match="redacted"):
        store.report_use(conn, p["ben"], update_report_id=rid, what_changed="put it back")

    # Merging cannot turn an author's self-reports into independent ones.
    a = contribute(conn, p["ada"], title="Sizing from procurement records")["id"]
    b = contribute(conn, p["ben"], title="Sizing from procurement data")["id"]
    for i in range(4):
        store.report_use(conn, p["ben"], entry_id=b, task="market sizing", domain=f"sector{i}",
                         outcome="success", human_signal="accepted")
    m = store.merge_entries(conn, p["cur"], entry_ids=[a, b], title="Sizing from procurement records",
                            summary="Merged.", body=BODY, rationale="same approach")
    assert m["quality"]["independent_reporters"] == 0

    # Duplicates are found in a crowded topic and among entries built on the same parent.
    base = contribute(conn, p["ada"], title="Channel checks for hardware demand", task="demand estimation")["id"]
    x = contribute(conn, p["ben"], title="Channel checks for hardware demand in retail",
                   task="demand estimation", based_on=[base])["id"]
    y = contribute(conn, p["cy"], title="Channel checks for hardware demand in retail",
                   task="demand estimation", based_on=[base])["id"]
    for i in range(80):
        contribute(conn, p["cy"], title=f"Bottom-up market sizing from installed base variant{i}")
    active = conn.execute("SELECT * FROM entries WHERE status = 'active'").fetchall()
    pairs = {frozenset(d["ids"]) for d in store._duplicate_pairs(active)}
    assert frozenset((x, y)) in pairs
    assert len(pairs) > 1000  # the 80 near-identical sizing entries all pair up

    # Purge removes every field, and ids never carried the title in the first place.
    leak = contribute(conn, p["ada"], title="Sizing for Acme Corp entry into KSA", task="market sizing Acme")["id"]
    assert "acme" not in leak
    store.report_use(conn, p["ben"], entry_id=leak, task="sizing for Acme board", outcome="success",
                     situation="Acme board pack")
    store.retire_entry(conn, p["cur"], entry_id=leak, rationale="client name", purge_content=True)
    dump = "\n".join(str(tuple(r)) for t in ("entries", "entry_versions", "reports")
                     for r in conn.execute(f"SELECT * FROM {t}"))
    assert "Acme" not in dump

    # A contribution that answers a question is recorded as an experience answer.
    q = store.ask(conn, p["ada"], question="How should consumer app markets be sized without install data?")
    e = contribute(conn, p["cy"], title="Consumer sizing from usage panels", answers_question=q["id"])
    ans = store.get_question(conn, q["id"])
    assert ans["status"] == "answered" and ans["answers"][0]["basis"] == "experience"
    assert ans["answers"][0]["entry_id"] == e["id"]
