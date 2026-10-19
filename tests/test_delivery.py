"""rfq.delivery: the deterministic tail that builds the deck, names the
files and replays a saved report."""

import copy
import datetime
import io
import json
import os
from pathlib import Path

import pytest

from helpers import (OPPORTUNITY_NAME, SOURCE_FILE, sample_analysis,
                     sample_corpus, sample_plan)
from rfq import confidence, delivery, workers
from rfq.opportunity import UNREADABLE_ACCOUNT_RISK_LINE, build_opportunity_slide
from rfq.schema import TITLES
from rfq.sources import ACCOUNT_LIST_SOURCE


# A real row of references/data/accounts.csv: the final gate only accepts an
# Account Name (Site) / KAM (PTE) pair the Guidance list carries.
ACCOUNT = "Aurobay (Ningbo) Intelligent Technology Co., Ltd."
KAM = "Hao Tong"
MATCH = {"status": "matched", "customer": ACCOUNT, "customer_site": "",
         "tier": "exact", "account_name": ACCOUNT, "kam_pte": KAM,
         "candidates": [ACCOUNT], "candidate_count": 1,
         "candidate_details": [{"account_name": ACCOUNT, "site": "",
                                "country": "China", "kam_pte": KAM,
                                "match": "exact",
                                "reason": "Chosen: exact name match."}]}


def _aurobay_analysis():
    analysis = sample_analysis()
    analysis["opportunity"]["customer"] = ACCOUNT
    return analysis


def _question(plan, number):
    return next(q for q in plan["questions"] if q["number"] == number)


@pytest.fixture(scope="module", autouse=True)
def fast_gradients():
    """The renderer paints its brand gradients pixel by pixel on every
    deck (several seconds each). They are pure functions of their
    arguments, so one real paint per shape is enough for a test module."""
    from rfq import renderer
    original = renderer._gradient_png
    cache = {}

    def cached(stops, w=1920, h=1080, vertical=False):
        key = (tuple(map(tuple, stops)), w, h, vertical)
        if key not in cache:
            cache[key] = original(stops, w, h, vertical).getvalue()
        return io.BytesIO(cache[key])

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(renderer, "_gradient_png", cached)
        yield


@pytest.fixture(scope="module")
def finalized(fast_gradients):
    """One finalize() for the read-only assertions below."""
    plan, deck, report = delivery.finalize(sample_corpus(), sample_analysis(), sample_plan())
    return plan, deck, report


# ---------------------------------------------------------------- finalize
def test_finalize_stamps_the_date_and_leaves_oppid_empty(finalized):
    plan, _, _ = finalized
    assert plan["date"] == datetime.date.today().isoformat()
    assert plan["oppId"] == ""
    assert plan["projectName"] == OPPORTUNITY_NAME


def test_finalize_attaches_confidence_per_question(finalized):
    plan, _, _ = finalized
    assert [q["confidence"] for q in plan["questions"]] == ["high"] * 12
    assert [q["score"] for q in plan["questions"]] == [10] * 12
    assert [q["deductions"] for q in plan["questions"]] == [[]] * 12


def test_finalize_scores_each_section_from_its_deductions():
    analysis = sample_analysis()
    analysis["answers"][6]["deductions"] = [
        {"rule": "S7.1", "count": 9, "items": "nine cells", "basis": "SOW 3"},
        {"rule": "V1", "count": 1, "items": '"Design | AVL"',
         "basis": 'quote: "Northwind designs."'},
        {"rule": "S7.3", "count": 1, "items": "test bench", "basis": ""}]
    analysis["answers"][6]["confidence"] = "high"     # legacy, ignored
    plan, _, _ = delivery.finalize(sample_corpus(), analysis, sample_plan())
    scope = _question(plan, 7)
    assert (scope["confidence"], scope["score"]) == ("low", 1)
    assert [(e["rule"], e["points"]) for e in scope["deductions"]] == [
        ("S7.1", 4), ("V1", 4), ("S7.3", 2)]
    assert scope["confidenceNotes"].startswith(
        "Confidence: Low\n"
        f"{confidence.BASIS_WORD['inferred']}\n"
        "S7.1  9 cells placed by inference: nine cells (SOW 3)\n"
        'V1  refuted by the reviewer: "Design | AVL" '
        '(quote: "Northwind designs.")\n'
        "S7.3  owner propagated across phases for a deliverable-bound "
        "task: test bench\n"
        f"{confidence.NO_CONTRADICTIONS}\n"
        "Check: no statements were selected for a second review.\n\n"
        "Sources:\n")
    assert _question(plan, 2)["confidence"] == "high"


# ------------------------------------------------- section 12 (Python)
PDF, XLSX, PPTX, SCAN = ("02_targets.pdf", "03_plan.xlsx", "04_deck.pptx",
                         "05_scan.docx")


def _source_corpus():
    """sample_corpus plus a PDF with an unreadable page, a workbook, a deck
    with an unreadable picture and one skipped file."""
    corpus = sample_corpus()

    def add(name, text):
        corpus["filesContents"].append({
            "filename": name, "path": f"annex/{name}",
            "extension": name.rsplit(".", 1)[1], "extracted_text": text})

    add(PDF, "--- Page 1 ---\nTargets\n\n--- Page 2 ---\n"
             "[[PAGE 2 could not be read]]\n\n--- Page 3 ---\nMore")
    add(XLSX, "--- Sheet: Plan ---\n| A |\n|---|\n| 1 |\n\n"
              "--- Sheet: Gates ---\n| B |\n|---|\n| 2 |")
    add(PPTX, "--- Slide 1 ---\nTitle: Plan\n\n--- Slide 2 ---\n"
              "[[PICTURE deck__img01 at slide 2 could not be read]]")
    corpus["extraction"]["skipped"] = [{
        "filename": SCAN, "path": SCAN, "reason": "password-protected",
        "detail": "PDFPasswordIncorrect"}]
    return corpus


def _source_analysis():
    """sample_analysis as the model writes it now (no section 12), with
    sections 3 and 9 also citing the PDF and section 9 the deck."""
    analysis = sample_analysis()
    analysis["answers"] = [a for a in analysis["answers"] if a["id"] != 12]
    analysis["answers"][8]["sources"] += [
        {"filename": PPTX, "locator": "slide 2"},
        {"filename": PDF, "locator": "p. 3"}]
    analysis["answers"][2]["sources"].append({"filename": PDF, "locator": "p. 1"})
    return analysis


SOURCE_TABLE = (
    "| File | Type | Read | Used by sections |\n"
    "| --- | --- | --- | --- |\n"
    f"| {SOURCE_FILE} | TXT | whole file | 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11 |\n"
    f"| {PDF} | PDF | partly: page 2 could not be read (pages 1-3) | 3, 9 |\n"
    f"| {XLSX} | XLSX | sheets: Plan, Gates | Not cited |\n"
    f"| {PPTX} | PPTX | partly: 1 picture could not be read (slides 1-2) | 9 |\n"
    f"| {SCAN} | DOCX | skipped: password-protected | Not cited |")


def test_build_source_material_lists_every_file():
    built = delivery.build_source_material(_source_corpus(), _source_analysis())
    assert built["id"] == 12 and built["not_found"] is False
    assert built["shown"] is None
    assert built["answer"] == SOURCE_TABLE
    # Partly read and skipped files are reported in the Read column only:
    # an evidence limit never costs points (client decision).
    assert built["deductions"] == []
    assert built["sources"] == [{"filename": name, "locator": ""}
                                for name in (SOURCE_FILE, PDF, XLSX, PPTX)]
    assert confidence.score(built["deductions"], 12) == 10


def test_build_source_material_without_problems_has_no_deductions():
    analysis = sample_analysis()
    built = delivery.build_source_material(sample_corpus(), analysis)
    assert built["deductions"] == []
    assert built["answer"].splitlines()[2] == (
        f"| {SOURCE_FILE} | TXT | whole file | 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11 |")
    # One page or slide reads in the singular; an uncited file says so.
    corpus = sample_corpus()
    corpus["filesContents"][0]["extracted_text"] = "--- Page 1 ---\nText"
    corpus["filesContents"][0]["extension"] = "pdf"
    analysis["answers"] = []
    assert delivery.build_source_material(corpus, analysis)["answer"].splitlines()[2] \
        == f"| {SOURCE_FILE} | PDF | page 1 | Not cited |"


def test_source_material_has_one_row_per_path():
    """A file listed twice is one row; two files that share a basename in
    different folders are two rows, each named by its path."""
    corpus = sample_corpus()
    corpus["filesContents"] = [
        {"filename": "Spec.pdf", "path": path, "extension": "pdf",
         "extracted_text": "--- Page 1 ---\nText"}
        for path in ("annex/Spec.pdf", "attachments/Spec.pdf", "annex/Spec.pdf")]
    corpus["filesContents"].append({"filename": "Plan.xlsx", "path": "Plan.xlsx",
                                    "extension": "xlsx",
                                    "extracted_text": "--- Sheet: Plan ---\nx"})
    corpus["extraction"]["skipped"] = [
        {"filename": "Plan.xlsx", "path": "Plan.xlsx", "reason": "duplicate"}]
    analysis = sample_analysis()
    analysis["answers"] = []
    rows = delivery.build_source_material(corpus, analysis)["answer"].splitlines()[2:]
    assert rows == ["| annex/Spec.pdf | PDF | page 1 | Not cited |",
                    "| attachments/Spec.pdf | PDF | page 1 | Not cited |",
                    "| Plan.xlsx | XLSX | sheet: Plan | Not cited |"]


def test_add_python_sections_replaces_an_old_section_12():
    analysis = sample_analysis()
    assert analysis["answers"][-1]["answer"] == f"- {SOURCE_FILE}"
    delivery.add_python_sections(analysis, sample_corpus())
    assert [a["id"] for a in analysis["answers"]] == list(range(1, 13))
    assert analysis["answers"][-1] == delivery.build_source_material(
        sample_corpus(), analysis)


def test_finalize_appends_the_built_section_12():
    plan, _, report = delivery.finalize(_source_corpus(), _source_analysis(),
                                        sample_plan())
    answers = report["analysis"]["answers"]
    assert [a["id"] for a in answers] == list(range(1, 13))
    assert answers[-1]["answer"] == SOURCE_TABLE
    sources = _question(plan, 12)
    # Section 12 is always High; the Read column says what was not read.
    assert (sources["confidence"], sources["score"]) == ("high", 10)
    assert sources["deductions"] == []
    assert sources["confidenceNotes"].startswith(
        "Confidence: High\n"
        f"{confidence.BASIS_WORD['extracted']}\n"
        "No deductions: every item is stated in the documents.\n"
        f"{confidence.NO_CONTRADICTIONS}\n"
        "Check: no statements were selected for a second review.\n\n"
        "Sources:\n")
    for name in (SOURCE_FILE, PDF, XLSX, PPTX):
        assert f"File: {name}" in sources["sourceDetails"]


def test_finalize_keeps_a_saved_section_12():
    _, _, report = delivery.finalize(sample_corpus(), sample_analysis(),
                                     sample_plan())
    assert report["analysis"]["answers"][-1]["answer"] == f"- {SOURCE_FILE}"


def test_the_report_analysis_carries_score_band_and_resolved_deductions():
    analysis = sample_analysis()
    analysis["answers"][6]["deductions"] = [
        {"rule": "S7.1", "count": 2, "items": "two cells", "basis": ""}]
    plan, _, report = delivery.finalize(sample_corpus(), analysis, sample_plan())
    answers = {a["id"]: a for a in report["analysis"]["answers"]}
    # 9 by the points, held at Medium: the cells were inferred.
    assert (answers[7]["score"], answers[7]["band"]) == (6, "medium")
    assert answers[7]["deductions"] == [
        {"rule": "S7.1", "count": 2, "items": "two cells", "basis": "",
         "points": 1, "line": "S7.1  2 cells placed by inference: two cells"}]
    assert answers[7]["deductions"] == _question(plan, 7)["deductions"]
    assert all((a["score"], a["band"], a["deductions"]) == (10, "high", [])
               for number, a in answers.items() if number != 7)
    assert analysis["answers"][6]["deductions"][0].keys() == {
        "rule", "count", "items", "basis"}, "the caller's analysis is untouched"


def test_finalize_attaches_sources_to_every_question(finalized):
    plan, _, _ = finalized
    for question in plan["questions"]:
        assert question["sourceLine"] == f"Source: {SOURCE_FILE}"
        assert question["sourceDetails"].startswith("Sources:\n\nFile: " + SOURCE_FILE)


def test_finalize_explains_the_confidence_in_the_notes(finalized):
    plan, _, _ = finalized
    for question in plan["questions"]:
        notes = question["confidenceNotes"]
        assert notes.startswith(
            f"Confidence: High\n{confidence.BASIS_WORD['extracted']}\n"
            f"{confidence.NO_DEDUCTIONS}\n")
        assert "/10" not in notes
        assert "\n\nSources:\n\nFile: " + SOURCE_FILE in notes
    assert "Account lookup (" in _question(plan, 1)["confidenceNotes"]
    assert "Account lookup (" not in _question(plan, 2)["confidenceNotes"]


def test_finalize_builds_the_opportunity_slide_from_the_analysis(finalized):
    plan, _, report = finalized
    slides = _question(plan, 1)["slides"]
    assert [slide["layout"] for slide in slides] == ["opportunity", "split"]
    expected = build_opportunity_slide(report["analysis"]["opportunity"])
    assert {k: slides[0][k] for k in ("layout", "title", "columns", "rows",
                                      "products", "skills")} == expected
    assert slides[0]["rows"][4] == ["Account Name (Site)", "Info not available"]
    assert slides[0]["rows"][5] == ["KAM (PTE)", "Info not available"]
    assert slides[1]["products"] == [["Spark Ignited", "100%"]]
    assert slides[1]["skills"] == [["Calibration", "70%"], ["Project Management", "30%"]]
    assert slides[1]["confidence"] == "low"


def test_finalize_without_a_lookup_adds_the_account_risk_line(finalized):
    plan, _, report = finalized
    panels = _question(plan, 11)["slides"]
    assert [s["heading"] for s in panels] == ["Project Risks", "Document Risks"]
    assert panels[1]["items"][-1] == UNREADABLE_ACCOUNT_RISK_LINE
    assert panels[0]["items"] == ["The A-Sample date is tight."]
    risks = next(a for a in report["analysis"]["answers"] if a["id"] == 11)
    assert risks["answer"].endswith("- " + UNREADABLE_ACCOUNT_RISK_LINE)
    assert "account risk line: replaced" in report["run"]["sanitizer"]


def test_finalize_applies_a_current_account_match():
    plan, _, report = delivery.finalize(sample_corpus(), _aurobay_analysis(), sample_plan(),
                                        account=MATCH)
    rows = dict(_question(plan, 1)["slides"][0]["rows"])
    assert rows["Customer"] == ACCOUNT
    assert rows["Account Name (Site)"] == ACCOUNT
    assert rows["KAM (PTE)"] == KAM
    assert report["analysis"]["opportunity"]["kam_pte"] == KAM
    assert _question(plan, 1)["sourceLine"] == f"Source: {SOURCE_FILE}; {ACCOUNT_LIST_SOURCE}"
    assert _question(plan, 1)["sourceDetails"].endswith("Reference: " + ACCOUNT_LIST_SOURCE)
    panels = _question(plan, 11)["slides"]
    assert panels[1]["items"] == ["The BOM is not included."]
    assert f"Result: {ACCOUNT}, KAM {KAM}." in _question(plan, 1)["confidenceNotes"]
    assert "account risk line: removed" not in report["run"]["sanitizer"]
    assert "account risk line: replaced" not in report["run"]["sanitizer"]


def test_a_matched_pair_that_is_not_a_guidance_row_is_refused():
    fake = dict(MATCH, customer="Northwind Motors GmbH", account_name="Northwind (Hamburg)",
                kam_pte="Max Muster")
    with pytest.raises(ValueError, match="not a Guidance row"):
        delivery.finalize(sample_corpus(), sample_analysis(), sample_plan(), account=fake)


def test_a_stale_account_match_is_not_applied():
    stale = dict(MATCH, customer="Someone Else AG")
    plan, _, _ = delivery.finalize(sample_corpus(), _aurobay_analysis(), sample_plan(),
                                   account=stale)
    rows = dict(_question(plan, 1)["slides"][0]["rows"])
    assert rows["Account Name (Site)"] == "Info not available"
    assert _question(plan, 11)["slides"][1]["items"][-1] == UNREADABLE_ACCOUNT_RISK_LINE


def test_the_models_own_account_remarks_are_replaced_on_the_slides():
    draft = sample_plan()
    _question(draft, 11)["slides"][1]["items"].append("Salesforce account not identified.")
    plan, _, _ = delivery.finalize(sample_corpus(), sample_analysis(), draft)
    items = _question(plan, 11)["slides"][1]["items"]
    assert items == ["The BOM is not included.", UNREADABLE_ACCOUNT_RISK_LINE]


def test_finalize_renders_a_real_pptx(finalized):
    _, deck, _ = finalized
    assert deck[:2] == b"PK"
    assert len(deck) > 20_000


def test_finalize_runs_the_sanitizer_and_records_what_it_did():
    draft = sample_plan()
    _question(draft, 5)["slides"][0]["title"] = "Something Else"
    _question(draft, 2)["slides"][0]["body"] = "Quotation due 20.06.2026 (inferred)."
    _question(draft, 12)["slides"][0]["bullets"] = [{"text": "SOW (assessment)"}]
    plan, _, report = delivery.finalize(sample_corpus(), sample_analysis(), draft)
    actions = report["run"]["sanitizer"]
    assert any("'Something Else' -> 'Collaboration Approach'" in a for a in actions)
    assert _question(plan, 5)["slides"][0]["title"] == "Collaboration Approach"
    # "(inferred)" stays beside the text it marks; other tags are stripped.
    assert _question(plan, 2)["slides"][0]["body"] == \
        "Quotation due 20.06.2026 (inferred)."
    bullet = _question(plan, 12)["slides"][0]["bullets"][0]
    assert bullet["text"] == "SOW"
    assert "(assessment)" not in json.dumps(report["slidePlan"])


def test_finalize_flags_inferred_bullets():
    draft = sample_plan()
    _question(draft, 12)["slides"][0]["bullets"] = [{"text": "Two annexes (inferred)"}]
    plan, _, _ = delivery.finalize(sample_corpus(), sample_analysis(), draft)
    bullet = _question(plan, 12)["slides"][0]["bullets"][0]
    # The tag stays in the text (the renderer draws it once, in amber).
    assert bullet["text"] == "Two annexes (inferred)" and bullet["inferred"] is True


def test_pictures_slides_are_stripped_from_the_deck():
    draft = sample_plan()
    _question(draft, 3)["slides"].append({
        "layout": "pictures", "title": "Product Pictures",
        "pictures": [{"imageId": "img1", "caption": "Engine", "source": "SOR p. 1"}]})
    plan, _, report = delivery.finalize(sample_corpus(), sample_analysis(), draft)
    assert [s["layout"] for s in _question(plan, 3)["slides"]] == ["table"]
    assert "pictures" not in json.dumps(plan)
    assert report["run"]["pictures"] == [] and report["run"]["pictures_skipped"] == []
    assert "pictures_unclassified" not in report["run"]


def test_finalize_does_not_mutate_its_inputs():
    corpus, analysis, draft = sample_corpus(), sample_analysis(), sample_plan()
    before = (copy.deepcopy(corpus), copy.deepcopy(analysis), copy.deepcopy(draft))
    delivery.finalize(corpus, analysis, draft)
    assert (corpus, analysis, draft) == before


def test_report_shape_matches_the_contract(finalized):
    plan, _, report = finalized
    run = report["run"]
    assert run["projectName"] == "Northwind RFQ"
    assert run["oppId"] == ""
    assert run["corpusFiles"] == [SOURCE_FILE]
    assert len(run["corpusRevision"]) == 64
    assert run["prompts"] == {"analysis": workers.PROMPTS["analysis"],
                              "slidePlan": workers.PROMPTS["slides"]}
    assert run["prompts"]["analysis"] == "RFQ_QA_Extraction_Prompt_v14.md"
    assert run["usage"] == {"mode": "in-session", "note": "not measured"}
    assert run["preprocess"][SOURCE_FILE]["removed_pct"] == 0.0
    assert run["extraction"]["parsed"] == 1
    assert "preprocess" not in run["extraction"]
    assert "execution" not in run and "sourceDowngrades" not in run
    assert "verification" not in report
    assert report["analysis"]["answers"][0]["answer"].startswith(
        "| Field | Value |\n|---|---|\n| Customer | Northwind Motors GmbH |")
    assert report["slidePlan"] == plan
    json.dumps(report)


def test_report_carries_verification_execution_and_downgrades():
    verification = {"status": "ok", "mode": "subagent", "claims": []}
    audit = {"stages": [{"host": "codex", "actual_model": None}]}
    plan, _, report = delivery.finalize(
        sample_corpus(), sample_analysis(), sample_plan(), verification=verification,
        execution=audit, downgrades=["Section 4: 01_statement_of_work.txt p. 7"])
    assert report["verification"] == verification
    assert report["run"]["execution"] == audit
    assert report["run"]["execution"] is not audit
    assert "01_statement_of_work.txt p. 7" in report["run"]["sourceDowngrades"]
    assert "01_statement_of_work.txt p. 7" in _question(plan, 4)["confidenceNotes"]


@pytest.mark.parametrize("draft", [
    "not a plan", {"questions": "x"}, {"questions": ["x"]},
    {"questions": [{"number": 1, "slides": "x"}]},
])
def test_finalize_refuses_a_malformed_plan_container(draft):
    with pytest.raises(ValueError, match="slide plan"):
        delivery.finalize(sample_corpus(), sample_analysis(), draft)


def test_finalize_refuses_a_plan_that_does_not_validate():
    draft = sample_plan()
    _question(draft, 3)["slides"][0] = {"layout": "table", "title": "X"}
    with pytest.raises(ValueError, match="does not validate"):
        delivery.finalize(sample_corpus(), sample_analysis(), draft)


def test_finalize_refuses_an_invalid_opportunity():
    analysis = sample_analysis()
    analysis["opportunity"]["products"] = [{"name": "Spark Ignited", "percent": 90}]
    with pytest.raises(ValueError, match="add up to 90"):
        delivery.finalize(sample_corpus(), analysis, sample_plan())
    with pytest.raises(ValueError, match="JSON object"):
        delivery.finalize(sample_corpus(), "nope", sample_plan())


# ------------------------------------------------------------- file names
def test_safe_filename_keeps_readable_names_and_drops_what_windows_forbids():
    assert delivery.safe_filename('Acme: V6 / "Phase 2" <x>?*|') == "Acme V6 Phase 2 x"
    assert delivery.safe_filename("Nord – Süd ") == "Nord – Süd"
    assert delivery.safe_filename("   ") == "RFQ"
    assert delivery.safe_filename("Name...") == "Name"
    long = delivery.safe_filename("a" * 200)
    assert len(long) == delivery.MAX_NAME


def test_deck_basename_follows_the_client_format():
    assert (delivery.deck_basename(OPPORTUNITY_NAME, "2026-10-14")
            == f"RFQ Insight_{OPPORTUNITY_NAME}_14102026")
    assert delivery.deck_basename("A/B", "2026-01-05") == "RFQ Insight_AB_05012026"


def test_deck_basename_truncates_a_long_name_against_the_output_folder():
    out_dir = "/" + "d" * 150
    name = "Northwind " + "word " * 40
    base = delivery.deck_basename(name, "2026-10-14", out_dir=out_dir)
    assert base.startswith("RFQ Insight_Northwind word")
    assert base.endswith("_14102026")
    assert len(out_dir) + 1 + len(base) + len(".pptx") + 4 <= delivery.MAX_PATH
    assert not base[len("RFQ Insight_"):-len("_14102026")].endswith(" ")


def test_truncate_at_word():
    assert delivery.truncate_at_word("one two three", 9) == "one two"
    assert delivery.truncate_at_word("one two three", 100) == "one two three"
    assert delivery.truncate_at_word("one two three", 0) == ""
    assert delivery.truncate_at_word("onetwothree", 5) == "onetw"


def test_deliverable_paths_follow_the_naming_contract(tmp_path):
    pptx, report = delivery.deliverable_paths(str(tmp_path), OPPORTUNITY_NAME, "2026-10-14")
    base = f"RFQ Insight_{OPPORTUNITY_NAME}_14102026"
    assert pptx == os.path.join(str(tmp_path), "output", base + ".pptx")
    assert report == os.path.join(str(tmp_path), "output", base + ".json")


@pytest.mark.parametrize("existing", [(".pptx",), (".json",), (".pptx", ".json")])
def test_deliverable_paths_never_overwrite_an_existing_pair(tmp_path, existing):
    out = tmp_path / "output"
    out.mkdir()
    base = f"RFQ Insight_{OPPORTUNITY_NAME}_14102026"
    for extension in existing:
        (out / (base + extension)).write_bytes(b"keep me")
    (out / (base + "_2.json")).write_bytes(b"keep this too")
    pptx, report = delivery.deliverable_paths(str(tmp_path), OPPORTUNITY_NAME, "2026-10-14")
    assert Path(pptx).name == base + "_3.pptx"
    assert Path(report).name == base + "_3.json"


def test_next_free_counts_from_two(tmp_path):
    assert delivery.next_free(str(tmp_path), "deck") == os.path.join(str(tmp_path), "deck")
    (tmp_path / "deck.pptx").write_bytes(b"")
    assert delivery.next_free(str(tmp_path), "deck") == os.path.join(str(tmp_path), "deck_2")


# ---------------------------------------------------------- write_outputs
def test_write_outputs_names_the_files_after_the_opportunity(finalized, tmp_path):
    _, deck, report = finalized
    pptx, path = delivery.write_outputs(str(tmp_path), sample_corpus(), deck, report)
    stamp = datetime.date.today().strftime("%d%m%Y")
    assert Path(pptx).name == f"RFQ Insight_{OPPORTUNITY_NAME}_{stamp}.pptx"
    assert Path(path).name == f"RFQ Insight_{OPPORTUNITY_NAME}_{stamp}.json"
    assert Path(pptx).read_bytes() == deck
    assert json.loads(Path(path).read_text(encoding="utf-8"))["run"]["projectName"] == "Northwind RFQ"
    saved = json.loads((tmp_path / "output" / ".work" / "deliverables.json").read_text())
    assert saved == {"pptx": pptx, "report": path}


def test_write_outputs_preserves_an_earlier_pair(finalized, tmp_path):
    _, deck, report = finalized
    first_pptx, first_report = delivery.write_outputs(str(tmp_path), sample_corpus(), deck, report)
    Path(first_pptx).write_bytes(b"manually edited presentation")
    second_pptx, second_report = delivery.write_outputs(str(tmp_path), sample_corpus(), deck, report)
    assert Path(first_pptx).read_bytes() == b"manually edited presentation"
    assert second_pptx.endswith("_2.pptx") and second_report.endswith("_2.json")
    assert Path(second_pptx).read_bytes().startswith(b"PK")
    saved = json.loads((tmp_path / "output" / ".work" / "deliverables.json").read_text())
    assert saved == {"pptx": second_pptx, "report": second_report}


def test_write_outputs_falls_back_to_the_project_name(finalized, tmp_path):
    _, deck, report = finalized
    report = copy.deepcopy(report)
    report["analysis"]["opportunity"] = None
    pptx, _ = delivery.write_outputs(str(tmp_path), sample_corpus(), deck, report)
    assert Path(pptx).name.startswith("RFQ Insight_Northwind RFQ_")


def test_write_outputs_creates_exclusively(finalized, tmp_path, monkeypatch):
    _, deck, report = finalized
    out = tmp_path / "output"
    out.mkdir()
    taken = out / "taken.pptx"
    taken.write_bytes(b"someone else's deck")
    monkeypatch.setattr(delivery, "deliverable_paths",
                        lambda *a, **k: (str(taken), str(out / "taken.json")))
    with pytest.raises(FileExistsError):
        delivery.write_outputs(str(tmp_path), sample_corpus(), deck, report)
    assert taken.read_bytes() == b"someone else's deck"
    assert not (out / "taken.json").exists()


# ------------------------------------------------------------ checkpoints
def test_load_checkpoints_needs_the_three_required_files(tmp_path):
    work = tmp_path / "output" / ".work"
    work.mkdir(parents=True)
    with pytest.raises(ValueError, match="checkpoint is missing"):
        delivery.load_checkpoints(str(tmp_path))
    for name, payload in (("corpus.json", sample_corpus()), ("analysis.json", sample_analysis()),
                          ("slide_plan.json", sample_plan())):
        (work / name).write_text(json.dumps(payload), encoding="utf-8")
    (work / "execution.json").write_text("broken", encoding="utf-8")
    (work / "account_match.json").write_text("broken", encoding="utf-8")
    loaded = delivery.load_checkpoints(str(tmp_path))
    assert loaded["draft"]["questions"][0]["number"] == 1
    assert loaded["execution"]["status"] == "error"
    assert loaded["account"] is None and loaded["verification"] is None
    assert loaded["images_dir"] == str(work / "images")


def test_the_slide_stage_parser_actions_reach_the_report(tmp_path):
    work = tmp_path / "output" / ".work"
    work.mkdir(parents=True)
    for name, payload in (("corpus.json", sample_corpus()), ("analysis.json", sample_analysis()),
                          ("slide_plan.json", sample_plan()),
                          ("plan_actions.json", ["Section 3: dropped text outside the table: x"])):
        (work / name).write_text(json.dumps(payload), encoding="utf-8")
    cp = delivery.load_checkpoints(str(tmp_path))
    plan, _, report = delivery.finalize(cp["corpus"], cp["analysis"], cp["draft"])
    assert report["run"]["sanitizer"][0] == "Section 3: dropped text outside the table: x"
    assert delivery.PLAN_ACTIONS_KEY not in plan and delivery.PLAN_ACTIONS_KEY not in report["slidePlan"]
    (work / "plan_actions.json").write_text("[]", encoding="utf-8")
    assert delivery.PLAN_ACTIONS_KEY not in delivery.load_checkpoints(str(tmp_path))["draft"]


# ----------------------------------------------------------------- replay
def test_render_report_replays_a_saved_report(finalized, tmp_path):
    _, _, report = finalized
    report_path = tmp_path / "output" / "report.json"
    report_path.parent.mkdir()
    report_path.write_text(json.dumps(report), encoding="utf-8")
    result = delivery.render_report(report_path)
    assert result["pptx"] == str(tmp_path / "output" / "report_preview.pptx")
    assert Path(result["pptx"]).read_bytes()[:2] == b"PK"
    assert result["sections"] == 12
    assert result["slides"] == 15          # one per section; Opportunity
                                           # Info, Timing and Risks two
    assert result["bytes"] == Path(result["pptx"]).stat().st_size


def test_render_report_accepts_an_explicit_output_and_a_bare_plan(finalized, tmp_path):
    plan, _, _ = finalized
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    out = tmp_path / "decks" / "preview.pptx"
    result = delivery.render_report(str(plan_path), str(out))
    assert result["pptx"] == str(out) and out.read_bytes()[:2] == b"PK"


def test_render_report_keeps_the_saved_sources_and_notes(finalized, tmp_path):
    _, _, report = finalized
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    plan = delivery.load_plan(str(report_path))
    saved = report["slidePlan"]
    for question, original in zip(plan["questions"], saved["questions"]):
        assert question["sourceLine"] == original["sourceLine"]
        assert question["confidenceNotes"] == original["confidenceNotes"]


def test_render_report_replays_a_scored_report_identically(tmp_path):
    analysis = sample_analysis()
    analysis["answers"][6]["deductions"] = [
        {"rule": "S7.1", "count": 9, "items": "nine cells", "basis": "SOW 3"}]
    _, _, report = delivery.finalize(_source_corpus(), analysis, sample_plan())
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    plan = delivery.load_plan(str(report_path))
    for question, original in zip(plan["questions"], report["slidePlan"]["questions"]):
        for key in ("confidence", "score", "deductions", "confidenceNotes"):
            assert question[key] == original[key], (question["number"], key)


def test_render_report_replays_a_pre_scoring_report_with_its_notes(finalized, tmp_path):
    """A report from before the scored confidence: its answers carry no
    deductions; the saved chips and notes are replayed, never re-scored."""
    _, _, report = finalized
    report = copy.deepcopy(report)
    for answer in report["analysis"]["answers"]:
        for key in ("deductions", "score", "band"):
            answer.pop(key, None)
    for question in report["slidePlan"]["questions"]:
        question["confidence"] = "medium"
        question.pop("score", None)
        question.pop("deductions", None)
        question["confidenceNotes"] = (f"Confidence: Medium\nWhy this rating: "
                                       f"section {question['number']}.")
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    plan = delivery.load_plan(str(report_path))
    for question, original in zip(plan["questions"], report["slidePlan"]["questions"]):
        assert question["confidence"] == "medium"
        assert question["confidenceNotes"] == original["confidenceNotes"]
        assert "score" not in question or question["score"] is None
    assert delivery.scored_analysis(report["analysis"]) is False
    assert delivery.scored_analysis(sample_analysis()) is True
    result = delivery.render_report(report_path)
    assert Path(result["pptx"]).read_bytes()[:2] == b"PK"


def test_load_plan_refuses_a_file_without_a_plan(tmp_path):
    path = tmp_path / "x.json"
    path.write_text('{"answers": []}', encoding="utf-8")
    with pytest.raises(ValueError, match="No slide plan"):
        delivery.load_plan(str(path))
