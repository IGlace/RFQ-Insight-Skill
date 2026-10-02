"""Ported schema / sanitizer / preprocess tests.

From RFQ_Container_App/tests/test_insight_pipeline.py - the half that covers
the deterministic modules the skill carries over. The llm.py and
run_insight() tests are dropped with the components they cover; the claim
and size-guard tests moved to test_claims.py and test_validate.py.
"""

from rfq.preprocess import clean_extracted_text
from rfq.sanitize import sanitize_plan
from rfq.schema import LoosePlanDraft, SlidePlan, tighten_plan


# --------------------------------------------------------------- preprocess
def test_preprocess_removes_page_furniture():
    text = ("Real content line about the V12 engine.\n"
            "Mclaren RESTRICTED\nConfidential\nPage 3 of 12\n25\n"
            "Info not available\nInfo not available\nSupplier\nSupplier\n")
    cleaned = clean_extracted_text(text)
    assert "Real content line" in cleaned
    assert "RESTRICTED" not in cleaned and "Confidential" not in cleaned
    assert "Page 3" not in cleaned
    # repeated CONTENT lines must survive (no repeated-line heuristic)
    assert cleaned.count("Info not available") == 2
    assert cleaned.count("Supplier") == 2


# ------------------------------------------------------------------- schema
def test_tighten_plan_strips_unused_fields():
    loose = LoosePlanDraft.model_validate({
        "projectName": "Demo",
        "questions": [{"number": 1, "titleEn": "Timing", "titleDe": "x",
                       "slides": [{"layout": "bullets", "title": "Timing",
                                   "bullets": [{"text": "x",
                                                "inferred": False}]}]}],
    }).model_dump()
    plan = tighten_plan(loose)
    assert "rows" not in plan["questions"][0]["slides"][0]   # None fields gone
    plan["date"] = "2026-07-23"
    SlidePlan.model_validate(plan)                            # strict union OK


# ---------------------------------------------------------------- sanitizer
def test_sanitize_plan_guards():
    corpus = "The HLP shows A1 Sample [Dyno] and the Concept and A-sample phases."
    plan = {"projectName": "X", "date": "2026-07-23", "questions": [
        {"number": 6, "titleEn": "Development Phases", "titleDe": "x",
         "slides": [{"layout": "phases", "title": "Development Phases",
                     "phases": [{"name": "Concept", "desc": "", "hw": False},
                                {"name": "A1 Sample", "desc": "", "hw": True},
                                {"name": "A2 Sample", "desc": "", "hw": True}],
                     "callout": None}]},
        {"number": 7, "titleEn": "Scope of Work and Responsibilities",
         "titleDe": "x",
         "slides": [{"layout": "ownership",
                     "title": "Scope of Work and Responsibilities",
                     "customerAbbr": "MAL",
                     "columns": ["Task", "Concept", "A-Sample"],
                     "rows": [["Design", "AVL", "AVL"],
                              ["Combustion definition", "Excluded", "Excluded"]],
                     "callout": None}]},
    ]}
    plan, actions = sanitize_plan(plan, corpus)
    phases = plan["questions"][0]["slides"][0]
    assert [p["name"] for p in phases["phases"]] == ["Concept", "A1 Sample"]
    assert "A2 Sample" in phases["callout"]["text"]          # disclosed
    own = plan["questions"][1]["slides"][0]
    assert own["rows"] == [["Design", "AVL", "AVL"]]
    assert "Combustion definition" in own["callout"]["text"]
    assert len(actions) == 2


def test_sanitizer_normalizes_na_cells_and_keeps_rows():
    """Regression: 'n/a' means phase-not-applicable — the row must STAY in
    the matrix as a blank cell, never be exiled to the callout (this gutted
    a real MAL Scope-of-Work slide to 4 of 16 rows)."""
    plan = {"projectName": "X", "date": "2026-07-23", "questions": [
        {"number": 7, "titleEn": "Scope of Work and Responsibilities",
         "titleDe": "x",
         "slides": [{"layout": "ownership",
                     "title": "Scope of Work and Responsibilities",
                     "customerAbbr": "MAL",
                     "columns": ["Task", "Concept", "A-Sample"],
                     "rows": [["Concept CAD", "AVL", "n/a"],
                              ["Detailed design", "N/A", "AVL"],
                              ["Release", "not applicable", "MAL"]],
                     "callout": None}]},
    ]}
    plan, actions = sanitize_plan(plan, "")
    sl = plan["questions"][0]["slides"][0]
    assert sl["rows"] == [["Concept CAD", "AVL", "—"],
                          ["Detailed design", "—", "AVL"],
                          ["Release", "—", "MAL"]]
    assert not sl.get("callout")                       # nothing exiled
    assert sum("normalized" in a for a in actions) == 3


def test_sanitizer_fixes_the_client_confirmed_slide_titles():
    """Client-confirmed exceptions to the "<titleEn> — <suffix>" format: id 5's
    diagram is "Collaboration Approach", and BOTH id-11 panels are titled
    "Risk Detection" (the heading, not the title, names the risk group)."""
    plan = {"projectName": "X", "date": "2026-07-23", "questions": [
        {"number": 5, "titleEn": "Application Approach", "titleDe": "x",
         "slides": [{"layout": "table", "title": "Application Approach",
                     "columns": ["Variant", "Powertrain"],
                     "rows": [["V1", "BEV"]]},
                    {"layout": "collab",
                     "title": "Application Approach — Collaboration Model",
                     "hub": "VHE30TD", "callout": None,
                     "parties": [{"name": "VF", "role": "OEM",
                                  "type": "customer"},
                                 {"name": "AVL", "role": "Development",
                                  "type": "avl"}]}]},
        {"number": 11, "titleEn": "Risk Detection", "titleDe": "x",
         "slides": [{"layout": "panel", "title": "Risk Detection",
                     "heading": "Project Risks", "items": ["Schedule is tight"],
                     "callout": None},
                    {"layout": "panel",
                     "title": "Risk Detection — Document Risks",
                     "heading": "Document Risks", "items": ["SOR contradicts"],
                     "callout": None}]},
    ]}
    plan, actions = sanitize_plan(plan, "")
    id5, id11 = plan["questions"]
    assert [sl["title"] for sl in id5["slides"]] == [
        "Application Approach", "Collaboration Approach"]   # table untouched
    assert [sl["title"] for sl in id11["slides"]] == [
        "Risk Detection", "Risk Detection"]
    assert [sl["heading"] for sl in id11["slides"]] == [
        "Project Risks", "Document Risks"]                  # groups still told
    assert sum(a.startswith("title:") for a in actions) == 2


def test_sanitizer_scrubs_literal_tags():
    plan = {"projectName": "X", "date": "2026-07-23", "questions": [
        {"number": 1, "titleEn": "Commercial Info", "titleDe": "x",
         "slides": [{"layout": "table", "title": "Commercial Info",
                     "columns": ["Field", "Value"],
                     "rows": [["Industry", "Passenger Car (inferred)"],
                              ["Technology", "Hybrid (stated)"]]},
                    {"layout": "bullets", "title": "Commercial Info — Notes",
                     "bullets": [{"text": "Volume unknown (inferred)",
                                  "inferred": False}], "callout": None}]},
    ]}
    plan, actions = sanitize_plan(plan, "")
    t = plan["questions"][0]["slides"][0]
    assert t["rows"][0][1] == "Passenger Car" and t["rows"][1][1] == "Hybrid"
    b = plan["questions"][0]["slides"][1]["bullets"][0]
    assert b["inferred"] is True and "(inferred)" not in b["text"]
    assert any("tag stripped" in a for a in actions)


def test_ownership_stage_column_not_treated_as_owner():
    plan = {"projectName": "X", "date": "2026-07-23", "questions": [
        {"number": 7, "titleEn": "Scope of Work and Responsibilities",
         "titleDe": "x", "confidence": "high",
         "slides": [{"layout": "ownership",
                     "title": "Scope of Work and Responsibilities",
                     "customerAbbr": "VF",
                     "columns": ["Scope of Work", "Phases", "Owner"],
                     "rows": [["Design", "All", "AVL"],
                              ["Testing", "A/B/C", "VF"],
                              ["Procurement", "TBD", "TBD"]]}]},
    ]}
    plan, actions = sanitize_plan(plan, "")
    sl = plan["questions"][0]["slides"][0]
    # stage values survive; only the TBD OWNER row moves to the callout
    assert ["Design", "All", "AVL"] in sl["rows"]
    assert not any(r[0] == "Procurement" for r in sl["rows"])
    assert "Procurement" in sl["callout"]["text"]


# ------------------------------------------- phase traceability
# Shortened-but-grounded phase names survive, invented ones are still
# dropped (client feedback: the Northwind deck showed 2 of 5 phases because
# the old verbatim check dropped legitimate labels).
CORPUS = """
Phase 1: Technical route feasibility assessment. Complete a one-dimensional
thermodynamic simulation analysis report. Acceptance is subject to approval.
Phase 2: Combustion system, cooling and lubrication design, and temperature
field CAE analysis freeze.
Phase 3: Complete Structural CAE analysis and deliver 3D simulation reports.
Phase 4: X0 prototype thermodynamic development testing.
Phase 5: Complete the first round of durability test verification of the
prototype.
"""

ANSWER_6 = """
| Phase 1 – Technical route feasibility assessment | in scope |
| Phase 2 – Combustion / cooling-lubrication design & temperature-field CAE
freeze | in scope |
| Phase 4 – X0 prototype thermodynamic development testing | in scope |
"""


def _plan(phases):
    return {"projectName": "Demo", "date": "2026-08-03", "questions": [
        {"number": 6, "titleEn": "Development Phases",
         "titleDe": "Entwicklungsphasen",
         "slides": [{"layout": "phases", "title": "Development Phases",
                     "phases": [{"name": n, "desc": ""} for n in phases],
                     "callout": None}]}]}


def test_shortened_phase_names_survive():
    """The slide-plan stage may condense long client phase names — every
    grounded phase stays on the diagram (Northwind regression: 5 -> 2)."""
    names = ["Technical Route Feasibility", "Design & Temp-Field Freeze",
             "Structural CAE", "X0 Thermo-Dev Testing",
             "First Durability Verification"]
    plan, actions = sanitize_plan(_plan(names), CORPUS, ANSWER_6)
    kept = [p["name"] for p in plan["questions"][0]["slides"][0]["phases"]]
    assert kept == names
    assert not [a for a in actions if a.startswith("phases")]


def test_invented_phase_names_still_drop():
    names = ["Technical Route Feasibility", "A2 Sample",
             "Industrialisation Ramp-Up"]
    plan, actions = sanitize_plan(_plan(names), CORPUS, ANSWER_6)
    kept = [p["name"] for p in plan["questions"][0]["slides"][0]["phases"]]
    assert kept == ["Technical Route Feasibility"]
    assert any("A2 Sample" in a for a in actions)


def test_answer_text_backs_phases_missing_from_garbled_corpus():
    """When the corpus extraction garbled a chart, the stage-1 answer is a
    legitimate second trace source."""
    plan, actions = sanitize_plan(
        _plan(["Temperature-Field CAE Freeze"]), "unrelated corpus text",
        ANSWER_6)
    kept = [p["name"] for p in plan["questions"][0]["slides"][0]["phases"]]
    assert kept == ["Temperature-Field CAE Freeze"]
