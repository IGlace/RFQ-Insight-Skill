"""Slide-plan schema and the deterministic plan guards.

Ported from the old test_schema_sanitize.py: the sanitizer is now
rfq/planning.py (sanitize_plan) and the schemas are rfq/schema.py. The
preprocess test that sat here belongs with rfq/extractors.py.
"""

import pytest
from pydantic import ValidationError

from rfq import schema
from rfq.planning import clean_evidence_tags, sanitize_plan
from rfq.schema import (ADDITIONAL_INFO_ID, COLLABORATION, LoosePlanDraft,
                        OpportunityInfo, PercentItem, PresentationContent,
                        RISKS, SCOPE, SECTION_IDS, SlidePlan, TITLES,
                        section_number_errors, tighten_plan)


# ---------------------------------------------------------------- fixtures
def _question(number, slides=None):
    en, de = TITLES[number]
    return {"number": number, "titleEn": en, "titleDe": de,
            "slides": slides or [{"layout": "bullets", "title": en,
                                  "bullets": [{"text": f"Point {number}"}]}]}


def _canonical_plan(overrides=None, date="2026-07-23"):
    """All 12 canonical sections in deck order; `overrides` replaces the
    slides of the named sections."""
    overrides = overrides or {}
    plan = {"projectName": "Demo", "date": date,
            "questions": [_question(n, overrides.get(n)) for n in SECTION_IDS]}
    return plan


def test_the_fixture_is_the_full_canonical_deck():
    assert len(TITLES) == 12
    assert SECTION_IDS == tuple(range(1, 13))
    assert TITLES[SCOPE][0] == "Scope of Work and Responsibilities"
    assert SCOPE == 7
    SlidePlan.model_validate(_canonical_plan())


# ------------------------------------------------------------------- schema
def test_tighten_plan_strips_unused_fields():
    loose = LoosePlanDraft.model_validate({
        "projectName": "Demo",
        "questions": [{"number": n, "titleEn": TITLES[n][0], "titleDe": "x",
                       "slides": [{"layout": "bullets", "title": TITLES[n][0],
                                   "bullets": [{"text": "x",
                                                "inferred": False}]}]}
                      for n in SECTION_IDS],
    }).model_dump()
    plan = tighten_plan(loose)
    assert "rows" not in plan["questions"][0]["slides"][0]   # None fields gone
    plan["date"] = "2026-07-23"
    SlidePlan.model_validate(plan)                            # strict union OK


def test_slide_plan_requires_every_section_once_in_canonical_order():
    plan = _canonical_plan()
    plan["questions"] = plan["questions"][1:] + plan["questions"][:1]
    with pytest.raises(ValidationError, match="canonical order"):
        SlidePlan.model_validate(plan)

    short = _canonical_plan()
    short["questions"].pop()
    with pytest.raises(ValidationError):
        SlidePlan.model_validate(short)

    doubled = _canonical_plan()
    doubled["questions"].append(_question(7))
    with pytest.raises(ValidationError, match="Duplicate"):
        SlidePlan.model_validate(doubled)


def test_additional_information_is_allowed_only_before_source_material():
    plan = _canonical_plan()
    extra = {"number": ADDITIONAL_INFO_ID, "titleEn": "Additional Information",
             "titleDe": "Zusätzliche Informationen",
             "slides": [{"layout": "panel", "title": "Additional Information",
                         "heading": "Follow-up", "items": ["Answer."]}]}
    plan["questions"].insert(11, extra)                 # before 12
    SlidePlan.model_validate(plan)

    plan["questions"].append(plan["questions"].pop(11))  # after 12
    with pytest.raises(ValidationError):
        SlidePlan.model_validate(plan)


def test_section_number_errors_cover_type_duplicates_and_order():
    assert section_number_errors(list(SECTION_IDS)) == []
    assert section_number_errors(["1", *SECTION_IDS[1:]]) == [
        "Section numbers must be integers."]
    assert section_number_errors([True, *SECTION_IDS[1:]]) == [
        "Section numbers must be integers."]
    assert "Duplicate section number(s): 7" in section_number_errors(
        [*SECTION_IDS, 7])[0]
    assert section_number_errors(list(reversed(SECTION_IDS))) == [
        "Sections must appear once each in the canonical order."]
    with_extra = list(SECTION_IDS[:-1]) + [ADDITIONAL_INFO_ID, 12]
    assert section_number_errors(with_extra, allow_additional=True) == []
    assert section_number_errors(with_extra) and "Additional" not in \
        section_number_errors(with_extra)[0]
    assert "Additional Information may appear before Source Material" in \
        section_number_errors([*SECTION_IDS, ADDITIONAL_INFO_ID],
                              allow_additional=True)[0]


def test_section_numbers_must_be_strict_integers_in_the_plan():
    plan = _canonical_plan()
    plan["questions"][0]["number"] = 1.0
    with pytest.raises(ValidationError):
        SlidePlan.model_validate(plan)


def test_presentation_content_accepts_a_typed_phases_slide():
    content = PresentationContent.model_validate({"slides": [
        {"layout": "phases", "phases": [{"name": "Concept", "hw": False}]}]})
    assert content.slides[0].phases[0].hw is False
    assert content.slides[0].layout == "phases"


def test_presentation_content_rejects_a_string_where_a_bool_belongs():
    """LooseSlide would coerce hw="false" to True-ish; the strict pass on
    the raw input is what stops malformed typed data slipping through."""
    with pytest.raises(ValidationError):
        PresentationContent.model_validate({"slides": [
            {"layout": "phases",
             "phases": [{"name": "Concept", "hw": "false"}]}]})
    with pytest.raises(ValidationError):
        PresentationContent.model_validate({"slides": [
            {"layout": "collab",
             "parties": [{"name": "AVL", "dashed": "true"}]}]})


def test_presentation_content_rejects_an_unknown_layout_or_stray_field():
    with pytest.raises(ValidationError):
        PresentationContent.model_validate({"slides": [
            {"layout": "mystery", "title": "x"}]})
    with pytest.raises(ValidationError):
        PresentationContent.model_validate({"slides": [
            {"layout": "bullets", "bullets": [{"text": "x"}], "extra": 1}]})


def test_presentation_content_drops_none_fields_before_the_strict_check():
    content = PresentationContent.model_validate({"slides": [
        {"layout": "table", "columns": ["A"], "rows": [["1"]],
         "bullets": None, "callout": None}]})
    assert content.slides[0].columns == ["A"]


def test_opportunity_info_carries_percent_lists_and_app_defaults():
    info = OpportunityInfo.model_validate({
        "customer": "Acme", "customer_contact": "J. Doe",
        "quotation_due_date": "20.06.2026", "customer_short": "Acme",
        "project_title": "V6", "opportunity_name": "Acme – V6",
        "project_type": "Development", "lead_product": "Engine",
        "technology": "ICE", "industry": "Passenger Car",
        "products": [{"name": "Engine", "percent": 60},
                     {"name": "Testing", "percent": 40}],
        "skills": [{"name": "Design", "percent": 100}]})
    assert info.account_name == "Info not available"
    assert info.kam_pte == "Info not available"
    assert info.customer_site == "Info not available"
    assert info.products[0] == PercentItem(name="Engine", percent=60)


def test_percent_items_and_opportunity_info_are_strict():
    with pytest.raises(ValidationError):
        PercentItem.model_validate({"name": "Engine", "percent": "sixty"})
    with pytest.raises(ValidationError):
        PercentItem.model_validate({"name": "Engine", "percent": 60, "x": 1})
    with pytest.raises(ValidationError):
        OpportunityInfo.model_validate({"customer": "Acme"})      # incomplete


# ---------------------------------------------------------------- sanitizer
def _sanitized(overrides, corpus="", analysis=""):
    return sanitize_plan(_canonical_plan(overrides), corpus, analysis)


def test_sanitize_plan_guards():
    corpus = "The HLP shows A1 Sample [Dyno] and the Concept and A-sample phases."
    plan, actions = _sanitized({
        6: [{"layout": "phases", "title": "Development Phases",
             "phases": [{"name": "Concept", "desc": "", "hw": False},
                        {"name": "A1 Sample", "desc": "", "hw": True},
                        {"name": "A2 Sample", "desc": "", "hw": True}],
             "callout": None}],
        7: [{"layout": "ownership",
             "title": "Scope of Work and Responsibilities",
             "customerAbbr": "MAL",
             "columns": ["Task", "Concept", "A-Sample"],
             "rows": [["Design", "AVL", "AVL"],
                      ["Combustion definition", "Excluded", "Excluded"]],
             "callout": None}],
    }, corpus)
    phases = plan["questions"][5]["slides"][0]
    assert [p["name"] for p in phases["phases"]] == ["Concept", "A1 Sample"]
    assert "A2 Sample" in phases["callout"]["text"]          # disclosed
    own = plan["questions"][6]["slides"][0]
    assert own["rows"] == [["Design", "AVL", "AVL"]]
    assert "Combustion definition" in own["callout"]["text"]
    assert len(actions) == 2


def test_sanitizer_normalizes_na_cells_and_keeps_rows():
    """'n/a' means phase-not-applicable: the row STAYS in the matrix as a
    blank cell, never exiled to the callout."""
    plan, actions = _sanitized({
        7: [{"layout": "ownership",
             "title": "Scope of Work and Responsibilities",
             "customerAbbr": "MAL",
             "columns": ["Task", "Concept", "A-Sample"],
             "rows": [["Concept CAD", "AVL", "n/a"],
                      ["Detailed design", "N/A", "AVL"],
                      ["Release", "not applicable", "MAL"]],
             "callout": None}]})
    sl = plan["questions"][6]["slides"][0]
    assert sl["rows"] == [["Concept CAD", "AVL", "—"],
                          ["Detailed design", "—", "AVL"],
                          ["Release", "—", "MAL"]]
    assert not sl.get("callout")                       # nothing exiled
    assert sum("normalized" in a for a in actions) == 3


def test_the_sanitizer_leaves_joint_and_blank_cells_alone():
    plan, actions = _sanitized({
        7: [{"layout": "ownership",
             "title": "Scope of Work and Responsibilities",
             "customerAbbr": "MAL",
             "columns": ["Task", "Concept", "A-Sample"],
             "rows": [["Design", "Joint", "—"], ["PM", "-", "Supplier"]]}]})
    assert plan["questions"][6]["slides"][0]["rows"] == [
        ["Design", "Joint", "—"], ["PM", "-", "Supplier"]]
    assert not [a for a in actions if a.startswith("ownership:")]


def test_the_sanitizer_never_empties_the_matrix():
    """When EVERY row would move out, nothing moves: a callout is no
    substitute for the whole table."""
    plan, actions = _sanitized({
        7: [{"layout": "ownership",
             "title": "Scope of Work and Responsibilities",
             "columns": ["Task", "Concept"],
             "rows": [["Design", "TBD"], ["PM", "Excluded"]]}]})
    sl = plan["questions"][6]["slides"][0]
    assert [r[0] for r in sl["rows"]] == ["Design", "PM"]
    assert not sl.get("callout")


def test_sanitizer_fixes_the_client_confirmed_slide_titles():
    """Client-confirmed exceptions to the "<titleEn> — <suffix>" format: the
    Collaboration Approach diagram is "Collaboration Approach", and BOTH
    Risk Detection panels are "Risk Detection"."""
    plan, actions = _sanitized({
        COLLABORATION: [
            {"layout": "collab",
             "title": "Collaboration Approach — Collaboration Model",
             "hub": "VHE30TD", "callout": None,
             "parties": [{"name": "VF", "role": "OEM", "type": "customer"},
                         {"name": "AVL", "role": "Development", "type": "avl"}]}],
        RISKS: [
            {"layout": "panel", "title": "Risk Detection",
             "heading": "Project Risks", "items": ["Schedule is tight"],
             "callout": None},
            {"layout": "panel", "title": "Risk Detection — Document Risks",
             "heading": "Document Risks", "items": ["SOR contradicts"],
             "callout": None}]})
    id5 = plan["questions"][COLLABORATION - 1]
    id11 = plan["questions"][RISKS - 1]
    assert [sl["title"] for sl in id5["slides"]] == ["Collaboration Approach"]
    assert [sl["title"] for sl in id11["slides"]] == [
        "Risk Detection", "Risk Detection"]
    assert [sl["heading"] for sl in id11["slides"]] == [
        "Project Risks", "Document Risks"]                  # groups still told
    assert sum(a.startswith("title:") for a in actions) == 2


def test_a_collab_or_panel_slide_outside_its_section_keeps_its_title():
    plan, actions = _sanitized({
        4: [{"layout": "table", "title": "Application Approach",
             "columns": ["Variant", "Powertrain"], "rows": [["V1", "BEV"]]},
            {"layout": "collab",
             "title": "Application Approach — Collaboration Model",
             "hub": "X", "parties": [{"name": "AVL", "type": "avl"}]}]})
    assert [sl["title"] for sl in plan["questions"][3]["slides"]] == [
        "Application Approach", "Application Approach — Collaboration Model"]
    assert not [a for a in actions if a.startswith("title:")]


def test_sanitizer_scrubs_literal_tags():
    plan, actions = _sanitized({
        1: [{"layout": "table", "title": "Opportunity Info",
             "columns": ["Field", "Value"],
             "rows": [["Industry", "Passenger Car (inferred)"],
                      ["Technology", "Hybrid (stated)"]]},
            {"layout": "bullets", "title": "Opportunity Info — Notes",
             "bullets": [{"text": "Volume unknown (inferred)",
                          "inferred": False}], "callout": None}]})
    t = plan["questions"][0]["slides"][0]
    assert t["rows"][0][1] == "Passenger Car" and t["rows"][1][1] == "Hybrid"
    b = plan["questions"][0]["slides"][1]["bullets"][0]
    assert b["inferred"] is True and "(inferred)" not in b["text"]
    assert any("tag stripped" in a for a in actions)


@pytest.mark.parametrize("raw, clean", [
    ("Passenger Car (inferred)", "Passenger Car"),
    ("Hybrid (STATED)", "Hybrid"),
    ("Volume (not found) unknown", "Volume unknown"),
    ("Two (assessment)  spaces (analysis)", "Two spaces"),
    ("Untouched", "Untouched"),
])
def test_clean_evidence_tags(raw, clean):
    assert clean_evidence_tags(raw) == clean


def test_ownership_stage_column_not_treated_as_owner():
    plan, actions = _sanitized({
        7: [{"layout": "ownership",
             "title": "Scope of Work and Responsibilities",
             "customerAbbr": "VF",
             "columns": ["Scope of Work", "Phases", "Owner"],
             "rows": [["Design", "All", "AVL"],
                      ["Testing", "A/B/C", "VF"],
                      ["Procurement", "TBD", "TBD"]]}]})
    sl = plan["questions"][6]["slides"][0]
    # stage values survive; only the TBD OWNER row moves to the callout
    assert ["Design", "All", "AVL"] in sl["rows"]
    assert not any(r[0] == "Procurement" for r in sl["rows"])
    assert "Procurement" in sl["callout"]["text"]


def test_the_ownership_audit_warns_about_uniform_rows_without_touching_them():
    plan, actions = _sanitized({
        7: [{"layout": "ownership",
             "title": "Scope of Work and Responsibilities",
             "columns": ["Task", "P1", "P2", "P3"],
             "rows": [["Design", "AVL", "AVL", "AVL"],
                      ["Testing", "AVL", "Customer", "—"]]}]})
    assert plan["questions"][6]["slides"][0]["rows"][0] == [
        "Design", "AVL", "AVL", "AVL"]
    assert any(a.startswith("ownership-audit: 1/2") for a in actions)


def test_a_sanitized_canonical_plan_still_validates():
    plan, _ = _sanitized({
        7: [{"layout": "ownership",
             "title": "Scope of Work and Responsibilities",
             "customerAbbr": "MAL",
             "columns": ["Task", "Concept"],
             "rows": [["Design", "AVL"], ["Release", "n/a"]]}]})
    SlidePlan.model_validate(plan)


# ------------------------------------------- phase traceability
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


def _phase_plan(phases):
    return _canonical_plan({6: [{"layout": "phases",
                                 "title": "Development Phases",
                                 "phases": [{"name": n, "desc": ""}
                                            for n in phases],
                                 "callout": None}]})


def _kept_phases(plan):
    return [p["name"] for p in plan["questions"][5]["slides"][0]["phases"]]


def test_shortened_phase_names_survive():
    """The slide-plan stage may condense long client phase names; every
    grounded phase stays on the diagram."""
    names = ["Technical Route Feasibility", "Design & Temp-Field Freeze",
             "Structural CAE", "X0 Thermo-Dev Testing",
             "First Durability Verification"]
    plan, actions = sanitize_plan(_phase_plan(names), CORPUS, ANSWER_6)
    assert _kept_phases(plan) == names
    assert not [a for a in actions if a.startswith("phases")]


def test_invented_phase_names_still_drop():
    names = ["Technical Route Feasibility", "A2 Sample",
             "Industrialisation Ramp-Up"]
    plan, actions = sanitize_plan(_phase_plan(names), CORPUS, ANSWER_6)
    assert _kept_phases(plan) == ["Technical Route Feasibility"]
    assert any("A2 Sample" in a for a in actions)


def test_answer_text_backs_phases_missing_from_garbled_corpus():
    plan, actions = sanitize_plan(
        _phase_plan(["Temperature-Field CAE Freeze"]), "unrelated corpus text",
        ANSWER_6)
    assert _kept_phases(plan) == ["Temperature-Field CAE Freeze"]


def test_a_phase_is_traceable_when_most_of_its_tokens_are():
    """The fuzzy tier passes at 55% of distinctive tokens: three hits out of
    five is enough, two out of five is not."""
    corpus = "the concept phase; alpha beta gamma words only"
    plan, _ = sanitize_plan(_phase_plan(
        ["Alpha Beta Gamma Delta Epsilon", "Concept"]), corpus)
    assert _kept_phases(plan) == ["Alpha Beta Gamma Delta Epsilon", "Concept"]
    plan, _ = sanitize_plan(_phase_plan(
        ["Alpha Beta Delta Epsilon Zeta", "Concept"]), corpus)
    assert _kept_phases(plan) == ["Concept"]


def test_more_than_forty_percent_unverifiable_of_five_phases_are_kept():
    """A diagram of five or more phases that would lose over 40% keeps
    them all and says so, rather than showing 2 of 5 (client feedback)."""
    names = ["Technical Route Feasibility", "Structural CAE",
             "Invented One", "Invented Two", "Invented Three"]
    plan, actions = sanitize_plan(_phase_plan(names), CORPUS, ANSWER_6)
    assert _kept_phases(plan) == ["Technical Route Feasibility",
                                  "Structural CAE", "Invented One",
                                  "Invented Two", "Invented Three"]
    assert not plan["questions"][5]["slides"][0].get("callout")
    assert any("kept 3 unverifiable phases" in a for a in actions)


def test_the_keep_rule_needs_five_phases():
    """Four phases losing two (50%) still drop them: the rule only applies
    to diagrams of five or more."""
    names = ["Technical Route Feasibility", "Structural CAE",
             "Invented One", "Invented Two"]
    plan, actions = sanitize_plan(_phase_plan(names), CORPUS, ANSWER_6)
    assert _kept_phases(plan) == ["Technical Route Feasibility", "Structural CAE"]
    assert "Invented One" in plan["questions"][5]["slides"][0]["callout"]["text"]


def test_the_diagram_is_never_emptied():
    plan, actions = sanitize_plan(_phase_plan(["Invented One"]), CORPUS)
    assert _kept_phases(plan) == ["Invented One"]
    assert not [a for a in actions if a.startswith("phases")]


def test_without_any_source_text_phases_are_left_alone():
    plan, actions = sanitize_plan(_phase_plan(["Anything Goes"]), "")
    assert _kept_phases(plan) == ["Anything Goes"]
    assert not [a for a in actions if a.startswith("phases")]
