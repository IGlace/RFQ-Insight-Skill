"""Slide-plan schema, the markdown parser behind the deterministic plan
(planning.typed_from_markdown, CONTRACT §9) and the plan guards.

Ported from the old test_schema_sanitize.py: the sanitizer is now
rfq/planning.py (sanitize_plan) and the schemas are rfq/schema.py. The
preprocess test that sat here belongs with rfq/extractors.py.
"""

import pytest
from pydantic import ValidationError

from helpers import _ANSWERS, built_analysis, sample_corpus
from rfq import planning, schema
from rfq.planning import (_typed_answer_block, authoritative_risk_items,
                          clean_evidence_tags, plan_from_answers,
                          sanitize_plan, typed_from_markdown)
from rfq.validation import check_plan
from rfq.schema import (ADDITIONAL_INFO_ID, COLLABORATION, LoosePlanDraft,
                        OpportunityInfo, PercentItem,
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
    # "(inferred)" stays where the renderer draws it in amber; the other
    # tags never reach a slide.
    assert t["rows"][0][1] == "Passenger Car (inferred)"
    assert t["rows"][1][1] == "Hybrid"
    b = plan["questions"][0]["slides"][1]["bullets"][0]
    assert b == {"text": "Volume unknown (inferred)", "inferred": True}
    assert actions == ["tag stripped: Hybrid (stated)"]


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


# ------------------------------------------- markdown -> typed slides (§9)
def _ctx(**kw):
    return {"customer_short": "Northwind", "project_name": "V6 Engine Calibration",
            "spans": [], "actions": [], **kw}


def _parse(section, text, ctx=None, **answer):
    return typed_from_markdown({"answer": text, **answer}, section,
                               _ctx() if ctx is None else ctx)


def _written(slides):
    """The canonical markdown of a section's slides (round-trip rule)."""
    return "\n\n".join(block for slide in slides
                       if (block := _typed_answer_block(slide)))


def test_section_1_is_never_parsed():
    assert _parse(1, "anything at all") == [{"layout": "opportunity"}]


def test_section_2_is_one_prose_slide_with_one_paragraph_per_line():
    text = "First paragraph\nwrapped here.\n\nSecond paragraph."
    assert _parse(2, text) == [{"layout": "prose",
                                "body": "First paragraph wrapped here.\nSecond paragraph."}]
    assert _parse(2, _ANSWERS[2]) == [{"layout": "prose", "body": _ANSWERS[2]}]


def test_section_2_splits_above_300_words_at_the_middle_paragraph():
    paragraphs = [" ".join(["word"] * n) for n in (50, 60, 80, 60, 70)]
    slides = _parse(2, "\n\n".join(paragraphs))
    assert [s["layout"] for s in slides] == ["prose", "prose"]
    assert slides[0]["body"] == "\n".join(paragraphs[:3])   # 190 | 130
    assert slides[1]["body"] == "\n".join(paragraphs[3:])
    exactly = "\n\n".join(" ".join(["word"] * 100) for _ in range(3))
    assert len(_parse(2, exactly)) == 1, "300 words still fit one slide"
    assert len(_parse(2, " ".join(["word"] * 400))) == 1, "one paragraph cannot split"


@pytest.mark.parametrize("section", [3, 4, 8, 10])
def test_table_sections_parse_into_one_table(section):
    header, *_sep_rows = _ANSWERS[section].splitlines()
    (slide,) = _parse(section, _ANSWERS[section])
    assert slide["layout"] == "table"
    assert slide["columns"] == [c.strip() for c in header.strip("|").split("|")]
    assert len(slide["rows"]) == len(_ANSWERS[section].splitlines()) - 2


def test_the_inferred_tag_stays_in_the_cell_text():
    (slide,) = _parse(3, "| Item | Target |\n|:---|---:|\n| Power | 220 kW (inferred) |")
    assert slide["rows"] == [["Power", "220 kW (inferred)"]]


def test_section_5_collab_with_hub_dashed_roles_and_dependencies():
    text = ("Hub: Northwind\n\n| Party | Type | Role |\n|---|---|---|\n"
            "| Northwind | customer | Programme lead |\n| AVL | avl | Calibration |\n"
            "| Acme | supplier | Injectors (inferred) |\n\n"
            "Acme needs the injector targets\nfrom Northwind.")
    (slide,) = _parse(5, text)
    assert slide == {"layout": "collab", "hub": "Northwind", "parties": [
        {"name": "Northwind", "role": "Programme lead", "type": "customer", "dashed": False},
        {"name": "AVL", "role": "Calibration", "type": "avl", "dashed": False},
        {"name": "Acme", "role": "Injectors (inferred)", "type": "supplier", "dashed": True}],
        "callout": {"tag": "Dependencies",
                    "text": "Acme needs the injector targets from Northwind."}}


def test_section_5_hub_falls_back_to_the_customer_short_name():
    (slide,) = _parse(5, _ANSWERS[5].split("\n\n", 1)[1])
    assert slide["hub"] == "Northwind" and len(slide["parties"]) == 3


def test_a_dependencies_paragraph_too_long_for_the_callout_is_dropped():
    ctx = _ctx()
    long_text = " ".join(["dependency"] * 80)
    (slide,) = _parse(5, _ANSWERS[5] + "\n\n" + long_text, ctx)
    assert "callout" not in slide
    assert ctx["actions"] == [
        "Section 5: dropped the dependencies, too long for the callout: "
        + long_text[:60]]


def test_section_6_phases_referenced_callout_and_spans():
    text = ("| Phase | Definition | Scope | Hardware milestone | Span |\n"
            "|---|---|---|---|---|\n"
            "| Concept | Targets | in scope | no | January 2027 – June 2027 |\n"
            "| A-Sample | First build | in scope | yes | June 2027 – December 2028 (inferred) |\n"
            "| B-Sample | Second build | in scope |  | sometime |\n"
            "| Series | Volume | referenced only: separate future SOW | | |")
    ctx = _ctx()
    (slide,) = _parse(6, text, ctx)
    assert slide == {"layout": "phases", "phases": [
        {"name": "Concept", "desc": "Targets", "hw": False},
        {"name": "A-Sample", "desc": "First build", "hw": True},
        {"name": "B-Sample", "desc": "Second build"}],
        "callout": {"tag": "Referenced only", "text": "Series: separate future SOW"}}
    assert ctx["spans"] == [
        {"name": "Concept", "start": "January 2027", "end": "June 2027"},
        {"name": "A-Sample", "start": "June 2027", "end": "December 2028"}]


def test_section_6_without_an_in_scope_phase_is_the_whole_table():
    text = ("| Phase | Definition | Scope | Hardware milestone | Span |\n"
            "|---|---|---|---|---|\n| Series | Volume | referenced only: later | | |")
    (slide,) = _parse(6, text)
    assert slide["layout"] == "table" and slide["rows"][0][0] == "Series"


def test_section_7_ownership_takes_the_customer_short_name():
    (slide,) = _parse(7, _ANSWERS[7])
    assert slide == {"layout": "ownership", "customerAbbr": "Northwind",
                     "columns": ["Scope of Work", "Concept", "A-Sample"],
                     "rows": [["Design", "AVL", "Northwind"], ["Testing", "AVL", "AVL"]]}
    (slide,) = _parse(7, _ANSWERS[7], _ctx(customer_short=""))
    assert slide["customerAbbr"] == "Customer"


def test_section_7_owner_cells_take_their_canonical_spelling():
    """The gate accepts owners in any case (validation.owner_allowed); the
    parse writes them canonically so the fast path keeps the answer."""
    text = ("| Scope of Work | Concept | A-Sample |\n|---|---|---|\n"
            "| Design | avl | NORTHWIND |\n| Testing | joint | supplier |\n"
            "| Build | customer | — |")
    (slide,) = _parse(7, text)
    assert slide["rows"] == [["Design", "AVL", "Northwind"],
                             ["Testing", "Joint", "Supplier"],
                             ["Build", "Customer", "—"]]
    analysis = built_analysis()
    analysis["answers"][6]["answer"] = text
    plan, record = _plan(analysis)
    assert plan is not None and record["unparsable"] == []


def test_section_6_hardware_cells_starting_with_yes_or_no_map_to_a_flag():
    ctx = _ctx()
    text = ("| Phase | Definition | Scope | Hardware milestone | Span |\n"
            "|---|---|---|---|---|\n"
            "| Concept | Targets | in scope | Yes – X0 delivery | |\n"
            "| A-Sample | Build | in scope | No, desk study | |\n"
            "| B-Sample | Build | in scope | partly | |\n"
            "| C-Sample | Build | in scope | | |")
    (slide,) = _parse(6, text, ctx)
    assert [phase.get("hw") for phase in slide["phases"]] == [True, False, None, None]
    assert ctx["actions"] == ["Section 6: dropped the hardware milestone of "
                              "B-Sample, not yes or no: partly"]


TIMING_HEAD = "| Milestone | Target timing | Phase / Task |\n|---|---|---|\n"
SPANS = [{"name": "Concept", "start": "January 2027", "end": "June 2027"}]


def test_section_9_gantt_from_dated_rows_with_bars_from_the_spans():
    text = TIMING_HEAD + ("| Kick-off | January 2027 | Concept |\n"
                          "| Review | after kick-off | Concept |\n"
                          "| SOP | December 2028 | A-Sample |")
    chart, table = _parse(9, text, _ctx(spans=SPANS))
    assert chart == {"layout": "gantt", "bars": SPANS, "steps": [
        {"label": "Kick-off", "date": "January 2027", "desc": "Concept"},
        {"label": "SOP", "date": "December 2028", "desc": "A-Sample"}]}
    assert table == {"layout": "table",
                     "columns": ["Milestone", "Target timing", "Phase / Task"],
                     "rows": [["Kick-off", "January 2027", "Concept"],
                              ["Review", "after kick-off", "Concept"],
                              ["SOP", "December 2028", "A-Sample"]]}


def test_section_9_without_spans_or_with_too_many_bars_labels_the_project():
    chart, _table = _parse(9, _ANSWERS[9])
    assert chart["barLabel"] == "V6 Engine Calibration" and "bars" not in chart
    nine = [dict(SPANS[0], name=f"P{i}") for i in range(9)]
    chart, _table = _parse(9, _ANSWERS[9], _ctx(spans=nine))
    assert "bars" not in chart and chart["barLabel"] == "V6 Engine Calibration"


def test_section_9_takes_the_first_14_dated_rows():
    rows = "".join(f"| M{i} | {i + 1:02d}.03.2027 | T |\n" for i in range(16))
    chart, table = _parse(9, TIMING_HEAD + rows)
    assert len(chart["steps"]) == 14 and len(table["rows"]) == 16
    assert chart["steps"][-1]["label"] == "M13"


def test_section_9_with_fewer_than_two_dated_rows_is_a_timeline():
    text = TIMING_HEAD + "| Kick-off | January 2027 | Concept |\n| Review | after kick-off | Concept |"
    chart, _table = _parse(9, text)
    assert chart["layout"] == "timeline"
    assert [s["label"] for s in chart["steps"]] == ["Kick-off", "Review"]


def test_section_11_two_panels():
    assert _parse(11, _ANSWERS[11]) == [
        {"layout": "panel", "heading": "Project Risks", "items": ["The A-Sample date is tight."]},
        {"layout": "panel", "heading": "Document Risks", "items": ["The BOM is not included."]}]


def test_section_12_parses_the_python_built_table():
    analysis = built_analysis()
    (slide,) = _parse(12, analysis["answers"][-1]["answer"])
    assert slide["layout"] == "table"
    assert slide["columns"] == ["File", "Type", "Read", "Used by sections"]


def test_stray_lines_are_dropped_and_recorded():
    ctx = _ctx()
    text = "Note: the targets come from the SOW, chapter 4 and the annex tables.\n\n" \
        + _ANSWERS[3] + "\n\nSee also the appendix."
    (slide,) = _parse(3, text, ctx)
    assert len(slide["rows"]) == 2
    assert ctx["actions"] == [
        "Section 3: dropped text outside the table: "
        "Note: the targets come from the SOW, chapter 4 and the annex",
        "Section 3: dropped text outside the table: See also the appendix."]
    ctx = _ctx()
    _parse(11, "Intro.\n" + _ANSWERS[11], ctx)
    assert ctx["actions"] == ["Section 11: dropped text outside the risk lists: Intro."]
    ctx = _ctx()
    _parse(2, "- a bullet\n\nProse.", ctx)
    assert ctx["actions"] == ["Section 2: dropped text outside the paragraphs: - a bullet"]


def test_an_unparsable_section_records_no_action():
    ctx = _ctx()
    assert _parse(3, "Stray.\n| A | B |\n| 1 | 2 |", ctx) is None
    assert ctx["actions"] == []


@pytest.mark.parametrize("section, text", [
    (2, "## Heading only"),
    (3, "| A | B |\n| 1 | 2 |"),                              # no separator
    (3, "| A | B |\n|---|---|\n| 1 | 2 | 3 |"),                # ragged row
    (4, "| A |\n|---|\n| 1 |\n\n| B |\n|---|\n| 2 |"),         # two tables
    (8, "| A |\n|---|\n| 1 |\n|---|\n| 2 |"),                  # glued tables
    (10, "ISO 26262 for functional safety."),                 # no table
    (5, "| Party | Role |\n|---|---|\n| AVL | x |"),           # wrong header
    (5, "| Party | Type | Role |\n|---|---|---|\n| AVL | partner | x |"),
    (6, "| Phase | Definition |\n|---|---|\n| A | b |"),
    (6, "| Phase | Definition | Scope | Hardware milestone | Span |\n"
        "|---|---|---|---|---|\n| A | b | maybe | | |"),
    (7, "Design: AVL"),
    (9, "| Milestone | Date |\n|---|---|\n| SOP | 2028 |"),
    (11, "## Project Risks\n- One."),                          # group missing
    (11, "## Document Risks\n- One.\n## Project Risks\n- Two."),  # order
    (11, "## Project Risks\n\n## Document Risks\n- One."),     # empty group
    (11, "## Project Risks\n- One.\n## Other\n- x\n## Document Risks\n- Two."),
    (12, ""),
])
def test_unparsable_answers_give_none(section, text):
    assert _parse(section, text) is None


@pytest.mark.parametrize("section", [3, 4, 6, 8, 10])
def test_a_not_found_sentence_is_a_one_cell_table(section):
    (slide,) = _parse(section, "The RFQ states nothing on this.", not_found=True)
    assert slide == {"layout": "table", "columns": [TITLES[section][0]],
                     "rows": [["The RFQ states nothing on this."]]}
    assert _parse(section, "The RFQ states nothing on this.") is None


def test_a_not_found_timing_sentence_is_a_one_row_timeline_and_table():
    sentence = "The RFQ documents state no milestones or dates."
    chart, table = _parse(9, sentence, not_found=True)
    row = [sentence, "Info not available", ""]
    assert chart == {"layout": "timeline",
                     "steps": [{"label": sentence, "date": "Info not available",
                                "desc": ""}]}
    assert table == {"layout": "table",
                     "columns": ["Milestone", "Target timing", "Phase / Task"],
                     "rows": [row]}
    assert _parse(9, _written([chart, table]), not_found=True) == [chart, table]
    assert _parse(9, sentence) is None, "only a not_found answer"
    analysis = built_analysis()
    analysis["answers"][8].update(answer=sentence, not_found=True)
    plan, record = _plan(analysis)
    assert plan is not None and record["unparsable"] == []


ROUND_TRIP = {
    3: [_ANSWERS[3], "| P | V | C |\n|---|---|---|\n| Power | 220 kW (inferred) | peak |"],
    4: [_ANSWERS[4]],
    5: [_ANSWERS[5], "| Party | Type | Role |\n|---|---|---|\n| Northwind | customer | Lead |\n"
                     "| AVL | avl | Work (inferred) |\n\nAVL needs the targets."],
    6: [_ANSWERS[6], "| Phase | Definition | Scope | Hardware milestone | Span |\n"
                     "|---|---|---|---|---|\n| A | x | in scope | yes | |\n"
                     "| B: two | | referenced only: later; maybe | | |\n| C | | referenced only | | |",
        "| Phase | Definition | Scope | Hardware milestone | Span |\n"
        "|---|---|---|---|---|\n| S | v | referenced only: later | no | 2027 – 2028 |"],
    7: [_ANSWERS[7], "| Scope of Work | All phases |\n|---|---|\n| Design | Joint |"],
    8: [_ANSWERS[8]],
    9: [_ANSWERS[9], TIMING_HEAD + "| Kick-off | January 2027 | Concept |\n| Review | later | x |"],
    10: [_ANSWERS[10]],
    11: [_ANSWERS[11], "## Project Risks\n- A (inferred).\n- B.\n## Document Risks\n- No risk found."],
}


@pytest.mark.parametrize("section, text", [
    (section, text) for section, texts in ROUND_TRIP.items() for text in texts])
def test_round_trip_written_back_and_parsed_again_is_the_same(section, text):
    first = _parse(section, text, _ctx(spans=SPANS))
    assert first is not None
    again_ctx = _ctx(spans=SPANS)
    again = _parse(section, _written(first), again_ctx)
    assert again == first
    assert again_ctx["actions"] == [], "the written form has no stray line"


@pytest.mark.parametrize("section", [3, 6, 10])
def test_round_trip_of_a_not_found_sentence(section):
    first = _parse(section, "Nothing on this.", not_found=True)
    assert _parse(section, _written(first), not_found=True) == first


def test_round_trip_of_a_split_description():
    text = "\n\n".join(" ".join(["word"] * n) for n in (90, 90, 90, 90))
    first = _parse(2, text)
    assert len(first) == 2 and _parse(2, _written(first)) == first


# --------------------------------------------- the deterministic plan
def _plan(analysis=None):
    return plan_from_answers(sample_corpus(), analysis or built_analysis())


def test_the_sample_analysis_becomes_the_whole_plan():
    plan, record = _plan()
    assert record == {"parsed": list(range(2, 13)), "unparsable": [], "actions": []}
    layouts = {q["number"]: [s["layout"] for s in q["slides"]] for q in plan["questions"]}
    assert layouts == {1: ["opportunity"], 2: ["prose"], 3: ["table"], 4: ["table"],
                       5: ["collab"], 6: ["phases"], 7: ["ownership"], 8: ["table"],
                       9: ["gantt", "table"], 10: ["table"],
                       11: ["panel", "panel"], 12: ["table"]}
    timing = next(q for q in plan["questions"] if q["number"] == 9)
    assert [s["title"] for s in timing["slides"]] == ["Timing", "Timing — Milestone Table"]
    assert timing["slides"][0]["bars"] == [
        {"name": "Concept", "start": "January 2027", "end": "June 2027"},
        {"name": "A-Sample", "start": "June 2027", "end": "December 2028"}]
    risks = next(q for q in plan["questions"] if q["number"] == 11)
    assert [s["title"] for s in risks["slides"]] == ["Risk Detection"] * 2
    assert check_plan(plan) == []
    assert planning.deterministic_plan(sample_corpus(), built_analysis()) == plan


def test_the_parser_actions_come_with_the_plan():
    analysis = built_analysis()
    analysis["answers"][2]["answer"] += "\nA stray remark."
    plan, record = _plan(analysis)
    assert plan is not None
    assert record["actions"] == ["Section 3: dropped text outside the table: A stray remark."]


def test_one_unparsable_section_sends_the_whole_deck_to_the_worker():
    analysis = built_analysis()
    analysis["answers"][3]["answer"] = "Calibration: base and drivability."
    analysis["answers"][9]["answer"] = "| A | B |\n| 1 | 2 |"
    plan, record = _plan(analysis)
    assert plan is None and record["unparsable"] == [4, 10] and record["parsed"] == []


def test_a_model_section_12_or_a_missing_one_is_no_plan():
    analysis = built_analysis()
    analysis["answers"].pop()
    assert _plan(analysis) == (None, {"parsed": [], "unparsable": [12], "actions": []})


def test_a_cross_section_mismatch_names_its_section():
    analysis = built_analysis()
    analysis["answers"][6]["answer"] = ("| Scope of Work | Concept | B-Sample |\n|---|---|---|\n"
                                        "| Design | AVL | AVL |")
    assert _plan(analysis)[1]["unparsable"] == [7]
    analysis = built_analysis()
    analysis["answers"][8]["answer"] = TIMING_HEAD + (
        "| SOP | December 2028 | A |\n| Kick-off | January 2027 | B |")
    assert _plan(analysis)[1]["unparsable"] == [9], "milestones out of order"


def test_a_plan_shape_failure_names_its_section_or_the_plan(monkeypatch):
    """A parsed slide the plan schema refuses names its section in the
    record (slide_planning.json), never an empty list."""
    parse = planning.typed_from_markdown

    def broken(answer, section, context):
        slides = parse(answer, section, context)
        if section == 4:
            slides[0]["rows"] = [[3]]
        return slides

    monkeypatch.setattr(planning, "typed_from_markdown", broken)
    plan, record = _plan()
    assert plan is None and record["unparsable"] == [4]
    monkeypatch.setattr(planning, "typed_from_markdown", parse)
    corpus = dict(sample_corpus(), projectName=5)
    plan, record = plan_from_answers(corpus, built_analysis())
    assert plan is None and record["unparsable"] == ["plan"]


def test_no_in_scope_phase_means_one_all_phases_column():
    analysis = built_analysis()
    analysis["answers"][5]["answer"] = (
        "| Phase | Definition | Scope | Hardware milestone | Span |\n|---|---|---|---|---|\n"
        "| Concept | Targets | referenced only: separate SOW | | |")
    analysis["answers"][6]["answer"] = "| Scope of Work | All phases |\n|---|---|\n| Design | AVL |"
    plan, record = _plan(analysis)
    assert record["unparsable"] == []
    scope = next(q for q in plan["questions"] if q["number"] == 7)["slides"][0]
    assert scope["columns"] == ["Scope of Work", "All phases"]
    timing = next(q for q in plan["questions"] if q["number"] == 9)["slides"][0]
    assert timing["barLabel"] == "V6 Engine Calibration", "no in-scope span, no bar"


def test_section_11_is_parsed_without_the_application_account_line():
    analysis = built_analysis()
    analysis["answers"][10]["answer"] += '\n- No Salesforce account matches "Northwind".'
    plan, _record = _plan(analysis)
    documents = next(q for q in plan["questions"] if q["number"] == 11)["slides"][1]
    assert documents["items"] == ["The BOM is not included."]


def test_authoritative_risk_items_are_the_parsed_items_without_the_account_line():
    analysis = built_analysis()
    analysis["answers"][10]["answer"] = (
        "## Project Risks\n- Salesforce integration is in scope.\n\n"
        "## Document Risks\n- The BOM is not included.\n"
        '- No Salesforce account matches "Northwind".')
    assert authoritative_risk_items(analysis) == [
        "Salesforce integration is in scope.", "The BOM is not included."]
    analysis["answers"][10]["answer"] = "Prose only."
    assert authoritative_risk_items(analysis) == []
    assert authoritative_risk_items({"answers": []}) == []


# ---------------------------------------------- tags on the parsed plan
def test_the_sanitizer_keeps_inferred_where_the_renderer_draws_it():
    plan, _actions = sanitize_plan({"questions": [
        {"number": 3, "titleEn": "x", "titleDe": "x", "slides": [
            {"layout": "table", "title": "T (inferred)", "columns": ["A (inferred)"],
             "rows": [["220 kW (inferred) (stated)"]]},
            {"layout": "panel", "title": "R", "heading": "H",
             "items": ["Risk (inferred)"]},
            {"layout": "bullets", "title": "B",
             "bullets": [{"text": "Point (inferred)"}]},
            {"layout": "phases", "title": "P", "phases": [
                {"name": "Phase A (inferred)", "desc": "Build (inferred)"}]},
            {"layout": "collab", "title": "C", "parties": [
                {"name": "Acme (inferred)", "role": "Parts (inferred)", "dashed": True}]},
            {"layout": "gantt", "title": "G", "steps": [
                {"label": "SOP (inferred)", "date": "2028", "desc": ""}]},
            {"layout": "opportunity", "title": "O",
             "rows": [["Industry", "Passenger Car (inferred)"]]}]}]}, "")
    table, panel, bullets, phases, collab, gantt, opp = plan["questions"][0]["slides"]
    assert table["title"] == "T" and table["columns"] == ["A"]
    assert table["rows"] == [["220 kW (inferred)"]]
    assert panel["items"] == ["Risk (inferred)"]
    assert bullets["bullets"] == [{"text": "Point (inferred)", "inferred": True}]
    assert phases["phases"] == [{"name": "Phase A", "desc": "Build"}]
    assert collab["parties"][0]["name"] == "Acme" and collab["parties"][0]["role"] == "Parts"
    assert gantt["steps"][0]["label"] == "SOP"
    assert opp["rows"] == [["Industry", "Passenger Car"]]
    assert planning.tagged_strings(plan) == []


def test_tagged_strings_finds_what_the_sanitizer_would_strip():
    plan = {"questions": [{"number": 3, "titleEn": "x", "titleDe": "x", "slides": [
        {"layout": "table", "title": "T", "columns": ["A"],
         "rows": [["v (inferred)"], ["w (not found)"]]},
        {"layout": "phases", "title": "P", "phases": [{"name": "A (inferred)"}]}]}]}
    assert planning.tagged_strings(plan) == ["w (not found)", "A (inferred)"]


def test_plan_input_carries_no_free_text_confidence():
    payload = planning.build_plan_input(sample_corpus(), built_analysis())
    assert payload["answers"]
    assert all(set(a) == {"id", "title_en", "title_de", "answer"}
               for a in payload["answers"])
