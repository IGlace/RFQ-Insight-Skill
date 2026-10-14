"""Claim harvesting per section mode, verdicts as V1/V2 deductions, and
the notes that explain a section's score.

All of it lives in rfq/verification.py; the score itself is
rfq/confidence.py's.
"""

import json
import os

import pytest

from rfq import confidence
from rfq import verification as vf
from rfq.opportunity import ACCOUNT_RISK_PREFIXES


def _analysis(answers=None):
    return {"answers": answers or [
        {"id": 1, "answer": "Customer is Acme.", "deductions": []},
        {"id": 7, "answer": "Ownership split not found in the package.",
         "deductions": [{"rule": "S7.3", "count": 1,
                         "items": "test bench", "basis": ""}]},
        {"id": 9, "answer": "SOP is 2027-03-01 (inferred) from the 24-month "
                            "schedule.", "deductions": []},
    ]}


def _kinds(answer):
    return [kind for kind, _ in vf.check_candidates(answer)]


# ============================================================== harvesting
def test_extract_claims_finds_absences_and_derived():
    claims = vf.extract_claims(_analysis())
    kinds = {(c["section"], c["kind"]) for c in claims}
    assert (7, "absence") in kinds
    assert (9, "derived") in kinds
    assert not any(c["section"] == 1 for c in claims)


def test_extract_claims_carries_context_and_clean_text():
    claims = vf.extract_claims(_analysis())
    absence = next(c for c in claims if c["section"] == 7)
    assert absence["claim"] == "Ownership split not found in the package."
    assert "not found" in absence["context"]
    assert "*" not in absence["claim"] and "|" not in absence["claim"]


def test_claim_ids_are_consecutive_from_one():
    claims = vf.extract_claims(_analysis())
    assert [c["id"] for c in claims] == list(range(1, len(claims) + 1))


@pytest.mark.parametrize("line", [
    "Ownership split not found in the package.",
    "Account: Info not available.",
    "Warranty terms not stated.",
    "Parties: AVL, Acme; no further parties named.",
    "Concept: No definition in the RFQ.",
])
def test_every_absence_marker_qualifies(line):
    found = vf.check_candidates({"id": 4, "answer": line})
    assert found == [("absence", line)]


def test_candidates_are_cleaned_of_bullets_and_table_bars():
    found = vf.check_candidates({"id": 4, "answer": "- **Warranty**: not stated | x"})
    assert found == [("absence", "Warranty: not stated  x")]


# -------------------------------------------------- extracted sections 3-10
_TARGETS = ("| Item | Target |\n|---|---|\n"
            "| **Power** | 220 kW |\n"
            "| Torque | 400 Nm |\n"
            "| Emissions | Euro 7 |\n"
            "| Speed | 6500 rpm |\n"
            "| Mass | 180 kg |\n"
            "| Volume | 2.0 l |\n"
            "| Noise | 80 dB (inferred) |\n"
            "| Warranty | not stated |")


def test_an_extracted_table_gives_absences_inferred_rows_and_four_stated_rows():
    found = vf.check_candidates({"id": 3, "answer": _TARGETS})
    # Header and separator rows are skipped; cells are joined with " | ".
    stated = [claim for kind, claim in found if kind == "stated"]
    assert len(stated) == vf.MAX_STATED == 4
    assert stated == ["Power | 220 kW", "Torque | 400 Nm",
                      "Emissions | Euro 7", "Speed | 6500 rpm"]
    assert ("derived", "Noise | 80 dB (inferred)") in found
    assert ("absence", "Warranty | not stated") in found
    assert len(found) == 6


def test_a_stated_row_needs_a_digit_or_a_standard_designation():
    answer = {"id": 10, "answer": "| Standard | Scope |\n|---|---|\n"
              "| ISO 26262 | Functional safety |\n"
              "| Customer EMC spec | Radiated emissions |\n"
              "| Supplier quality manual | Audits |"}
    assert vf.check_candidates(answer) == [
        ("stated", "ISO 26262 | Functional safety")]


def test_an_inferred_line_in_an_extracted_section_needs_no_digit():
    answer = {"id": 5, "answer": "- Approach is agile (inferred)."}
    assert vf.check_candidates(answer) == [
        ("derived", "Approach is agile (inferred).")]


def test_stated_bullets_count_but_plain_text_does_not():
    answer = {"id": 8, "answer": "Twelve deliverables apply in 2027.\n"
              "- D1 calibration data set\n- Test reports"}
    assert vf.check_candidates(answer) == [("stated", "D1 calibration data set")]


def test_an_inferred_row_is_never_a_stated_claim():
    answer = {"id": 9, "answer": "| Milestone | Target timing | Phase / Task |\n"
              "|---|---|---|\n| SOP | 2028 (inferred) | A-Sample |"}
    assert _kinds(answer) == ["derived"]


# ------------------------------------------- analysed sections and section 1
def test_description_sentences_are_stated_claims_up_to_four():
    answer = {"id": 2, "answer": (
        "Northwind requests calibration of a V6 engine. The scope runs to "
        "SOP in 2028.\n\nAVL leads the base calibration. Acme supplies the "
        "injectors. The volume is not stated. Testing uses two dynos.")}
    assert vf.check_candidates(answer) == [
        ("stated", "Northwind requests calibration of a V6 engine."),
        ("stated", "The scope runs to SOP in 2028."),
        ("stated", "AVL leads the base calibration."),
        ("stated", "Acme supplies the injectors."),
        ("absence", "The volume is not stated."),
    ]


def test_every_risk_item_is_a_trigger_claim():
    answer = {"id": 11, "answer": (
        "## Project Risks\n- The A-Sample date is tight.\n"
        "- Penalties apply per day of delay.\n\n"
        "## Document Risks\n- The BOM is not included.\n"
        "- Cost not stated.")}
    assert vf.check_candidates(answer) == [
        ("trigger", "The A-Sample date is tight."),
        ("trigger", "Penalties apply per day of delay."),
        ("trigger", "The BOM is not included."),
        ("absence", "Cost not stated."),
    ]


def test_an_empty_risk_group_has_no_trigger_to_check():
    answer = {"id": 11, "answer": (
        "## Project Risks\n- Penalties apply per day of delay.\n\n"
        "## Document Risks\n- No document risk was found in the documents.")}
    assert vf.check_candidates(answer) == [
        ("trigger", "Penalties apply per day of delay.")]


def test_the_account_risk_line_in_risk_detection_is_skipped():
    line = ACCOUNT_RISK_PREFIXES[0] + " so the account is not found."
    answer = {"id": 11, "answer": f"- Schedule is tight.\n- {line}\n- Cost not stated."}
    found = vf.check_candidates(answer)
    assert found == [("trigger", "Schedule is tight."), ("absence", "Cost not stated.")]


def test_opportunity_info_gives_absences_and_inferred_values_only():
    answer = {"id": 1, "answer": (
        "| Field | Value |\n|---|---|\n"
        "| Customer | Acme |\n"
        "| Quotation due date | 20 October 2026 |\n"
        "| Customer contact | Info not available |\n"
        "| Project type | SOP Project (inferred) |\n"
        "| Lead product | Spark Ignited 100% (inferred) |")}
    assert vf.check_candidates(answer) == [
        ("absence", "Customer contact | Info not available"),
        ("derived", "Lead product | Spark Ignited 100% (inferred)"),
    ]


def test_account_lines_in_opportunity_info_are_never_absence_claims():
    """The application fills Account Name (Site) and KAM (PTE); the model's
    "Info not available" there is a formatting artefact."""
    answer = {"id": 1, "answer": (
        "Customer: Acme\n"
        "- Account Name (Site): Info not available\n"
        "- KAM (PTE): Info not available\n"
        "| Account Name (Site) | Info not available |\n"
        "Customer contact: Info not available")}
    found = vf.check_candidates(answer)
    assert found == [("absence", "Customer contact: Info not available")]


def test_account_lines_outside_section_one_still_count():
    answer = {"id": 4, "answer": "- KAM (PTE): Info not available"}
    assert len(vf.check_candidates(answer)) == 1


def test_source_material_is_never_harvested():
    answer = {"id": 12, "answer": "| File | Read |\n|---|---|\n"
              "| sow.pdf | 12 pages |\n| scan.pdf | not found |"}
    assert vf.check_candidates(answer) == []


# ------------------------------------------------------------------- caps
def test_at_most_six_claims_per_section_marked_ones_first():
    lines = "\n".join(f"- Value {n}: {n} kW" for n in range(4))
    lines += "\n" + "\n".join(f"Item {n}: not stated." for n in range(4))
    answer = {"id": 4, "answer": lines}
    assert len(vf.check_candidates(answer)) == 8     # before the cap
    claims = vf.extract_claims({"answers": [answer]})
    assert len(claims) == vf.MAX_PER_SECTION == 6
    # The four absences are kept, two stated rows fill up; answer order.
    assert [c["kind"] for c in claims] == ["stated"] * 2 + ["absence"] * 4
    assert [c["claim"] for c in claims[:2]] == ["Value 0: 0 kW", "Value 1: 1 kW"]


def test_overall_cap_is_respected():
    answers = [{"id": i, "answer": "\n".join(["not found"] * 6)}
               for i in range(1, 12)]
    claims = vf.extract_claims({"answers": answers}, max_claims=20)
    assert len(claims) == 20
    assert [c["id"] for c in claims] == list(range(1, 21))


def test_the_default_overall_cap_is_forty_eight():
    answers = [{"id": i, "answer": "\n".join(["not found"] * 6)}
               for i in range(1, 12)]
    assert vf.MAX_CLAIMS == 48
    assert len(vf.extract_claims({"answers": answers})) == 48


def test_write_claims_writes_the_checkpoint(tmp_path):
    work = _work(tmp_path)
    with open(os.path.join(work, "analysis.json"), "w", encoding="utf-8") as fh:
        json.dump(_analysis(), fh)
    claims = vf.write_claims(str(tmp_path))
    assert len(claims) == 2
    with open(os.path.join(work, "claims.json"), encoding="utf-8") as fh:
        assert json.load(fh) == {"claims": claims}


def test_write_claims_raises_when_the_analysis_is_missing(tmp_path):
    _work(tmp_path)
    with pytest.raises(FileNotFoundError):
        vf.write_claims(str(tmp_path))


# ============================================================== partitions
def _claims(n):
    return [{"id": i, "section": 4, "kind": "absence", "claim": f"c{i}",
             "context": ""} for i in range(1, n + 1)]


def test_small_claim_sets_are_one_partition():
    for n in range(1, vf.PARTITION_THRESHOLD):
        assert vf.partition_claims(_claims(n)) == [_claims(n)]


def test_large_claim_sets_split_into_eights():
    assert vf.PARTITION_THRESHOLD == 8 and vf.PARTITION_SIZE == 8
    assert [len(p) for p in vf.partition_claims(_claims(8))] == [8]
    parts = vf.partition_claims(_claims(20))
    assert [len(p) for p in parts] == [8, 8, 4]
    assert [c["id"] for p in parts for c in p] == list(range(1, 21))


def test_a_full_run_needs_at_most_six_partitions():
    parts = vf.partition_claims(_claims(vf.MAX_CLAIMS))
    assert [len(p) for p in parts] == [8] * 6


def test_no_claims_means_no_partitions():
    assert vf.partition_claims([]) == []


def test_claims_identity_is_stable_across_key_order():
    a = [{"id": 1, "claim": "x", "section": 4}]
    b = [{"section": 4, "claim": "x", "id": 1}]
    assert vf.claims_identity(a) == vf.claims_identity(b)
    assert vf.claims_identity(a) != vf.claims_identity([{"id": 2}])


# ========================================================== check_verdicts
def test_a_complete_well_formed_verdict_set_has_no_problems():
    payload = {"verdicts": [
        {"id": 1, "verdict": "confirmed", "evidence": "q"},
        {"id": 2, "verdict": "refuted", "evidence": "q"},
        {"id": 3, "verdict": "ambiguous", "evidence": ""}]}
    assert vf.check_verdicts(payload, [1, 2, 3]) == []


def test_check_verdicts_names_each_problem():
    problems = vf.check_verdicts({"verdicts": [
        {"id": 1, "verdict": "confirmed", "evidence": "q"},
        {"id": 1, "verdict": "maybe", "evidence": 3},
        {"id": 9, "verdict": "confirmed"},
        {"id": "2", "verdict": "confirmed"},
        "junk"]}, [1, 2, 3])
    text = " ".join(problems)
    assert "Duplicate verdict id: 1" in text
    assert "Claim 1 has an invalid verdict" in text
    assert "Claim 1 evidence must be a string" in text
    assert "Unexpected verdict id: 9" in text
    assert "must be an integer" in text
    assert "must be an object" in text
    assert "Missing verdict ids: [2, 3]" in text


def test_check_verdicts_rejects_a_non_list_payload():
    assert vf.check_verdicts({"verdicts": {}}, [1])
    assert vf.check_verdicts([], [1])
    assert vf.check_verdicts(None, [1])


# ================================================================ verdicts
def _by_id(analysis):
    return {a["id"]: a for a in analysis["answers"]}


def _section_7_claim(claims):
    return next(c for c in claims if c["section"] == 7)


def test_a_refuted_claim_becomes_a_v1_deduction():
    analysis = _analysis()
    claims = vf.extract_claims(analysis)
    target = _section_7_claim(claims)
    verdicts = {"verdicts": [{"id": target["id"], "verdict": "refuted",
                              "evidence": "Annex B assigns calibration to AVL."}]}

    record = vf.apply_verdicts(analysis, claims, verdicts)
    by_id = _by_id(analysis)
    assert by_id[7]["deductions"] == [
        {"rule": "S7.3", "count": 1, "items": "test bench", "basis": ""},
        {"rule": "V1", "count": 1,
         "items": '"Ownership split not found in the package."',
         "basis": 'quote: "Annex B assigns calibration to AVL."'}]
    assert by_id[1]["deductions"] == []           # untouched
    assert "confidence" not in by_id[7]           # no rating is written
    # A refuted absence is no contradicted value: not a refuted section.
    assert record["refuted_sections"] == []
    assert record["status"] == "ok"


def test_an_ambiguous_claim_becomes_a_v2_deduction():
    analysis = _analysis()
    claims = vf.extract_claims(analysis)
    target = _section_7_claim(claims)
    record = vf.apply_verdicts(analysis, claims, {"verdicts": [
        {"id": target["id"], "verdict": "ambiguous",
         "evidence": "Annex B mentions calibration without an owner."}]})
    assert _by_id(analysis)[7]["deductions"][-1] == {
        "rule": "V2", "count": 1,
        "items": '"Ownership split not found in the package."',
        "basis": 'quote: "Annex B mentions calibration without an owner."'}
    assert record["refuted_sections"] == []
    assert record["rejected_verdicts"] == []
    assert [c["verdict"] for c in record["claims"]
            if c["id"] == target["id"]] == ["ambiguous"]


def test_a_refuted_stated_value_in_an_extracted_section_is_a_refuted_section():
    analysis = {"answers": [
        {"id": 2, "answer": "Northwind builds engines.", "deductions": []},
        {"id": 3, "answer": "| Item | Target |\n|---|---|\n| Power | 220 kW |",
         "deductions": []}]}
    claims = vf.extract_claims(analysis)
    assert [(c["section"], c["kind"]) for c in claims] == [
        (2, "stated"), (3, "stated")]
    record = vf.apply_verdicts(analysis, claims, {"verdicts": [
        {"id": 1, "verdict": "refuted", "evidence": "Northwind sells cars."},
        {"id": 2, "verdict": "refuted", "evidence": "Peak power 180 kW."}]})
    assert record["refuted_sections"] == [3]       # section 2 is analysed
    assert [e["rule"] for a in analysis["answers"]
            for e in a["deductions"]] == ["V1", "V1"]


def test_v1_and_v2_entries_are_priced_by_the_catalogue():
    analysis = _analysis()
    analysis["answers"][1]["answer"] = "\n".join(
        f"Item {n} not stated." for n in range(4))
    analysis["answers"][1]["deductions"] = []
    claims = vf.extract_claims(analysis)
    vf.apply_verdicts(analysis, claims, {"verdicts": [
        {"id": c["id"], "verdict": verdict, "evidence": "q"}
        for c, verdict in zip(claims, ("refuted", "refuted", "refuted",
                                       "ambiguous"))]})
    resolved, score, band = vf.section_confidence(7, _by_id(analysis)[7])
    assert [e["points"] for e in resolved] == [4, 4, 0, 2]   # V1 cap 8
    assert (score, band) == (1, "low")


def test_the_answer_text_is_never_rewritten():
    analysis = _analysis()
    before = analysis["answers"][1]["answer"]
    claims = vf.extract_claims(analysis)
    target = _section_7_claim(claims)
    vf.apply_verdicts(analysis, claims,
                      {"verdicts": [{"id": target["id"], "verdict": "refuted",
                                     "evidence": "Annex B says otherwise."}]})
    assert analysis["answers"][1]["answer"] == before


def test_refutation_without_a_quote_is_rejected():
    """A false refutation is worse than a missed one."""
    analysis = _analysis()
    claims = vf.extract_claims(analysis)
    target = _section_7_claim(claims)
    record = vf.apply_verdicts(analysis, claims,
                               {"verdicts": [{"id": target["id"],
                                              "verdict": "refuted",
                                              "evidence": "   "}]})
    assert [e["rule"] for e in _by_id(analysis)[7]["deductions"]] == ["S7.3"]
    assert record["refuted_sections"] == []
    assert record["rejected_verdicts"]
    assert "quote" in record["rejected_verdicts"][0]
    assert [c["verdict"] for c in record["claims"]
            if c["id"] == target["id"]] == ["unchecked"]


def test_an_ambiguous_verdict_without_evidence_is_unchecked():
    analysis = _analysis()
    claims = vf.extract_claims(analysis)
    target = _section_7_claim(claims)
    record = vf.apply_verdicts(analysis, claims, {"verdicts": [
        {"id": target["id"], "verdict": "ambiguous", "evidence": ""}]})
    assert record["rejected_verdicts"]
    assert [c["verdict"] for c in record["claims"]
            if c["id"] == target["id"]] == ["unchecked"]
    assert [e["rule"] for e in _by_id(analysis)[7]["deductions"]] == ["S7.3"]


def test_a_confirmed_claim_adds_no_deduction():
    analysis = _analysis()
    claims = vf.extract_claims(analysis)
    record = vf.apply_verdicts(analysis, claims, {"verdicts": [
        {"id": c["id"], "verdict": "confirmed", "evidence": "quote"}
        for c in claims]})
    assert {c["verdict"] for c in record["claims"]} == {"confirmed"}
    assert [[e["rule"] for e in a["deductions"]]
            for a in analysis["answers"]] == [[], ["S7.3"], []]


def test_claim_with_no_verdict_is_marked_unchecked():
    analysis = _analysis()
    claims = vf.extract_claims(analysis)
    record = vf.apply_verdicts(analysis, claims, {"verdicts": []})
    assert {c["verdict"] for c in record["claims"]} == {"unchecked"}
    assert record["refuted_sections"] == []


def test_no_claims_is_a_status_not_a_failure():
    record = vf.apply_verdicts({"answers": []}, [], {"verdicts": []})
    assert record["status"] == "no_claims"


def test_mode_is_recorded_for_the_report():
    analysis = _analysis()
    claims = vf.extract_claims(analysis)
    record = vf.apply_verdicts(analysis, claims, {"verdicts": []},
                               mode="in-thread")
    assert record["mode"] == "in-thread"
    assert vf.apply_verdicts(analysis, claims, {"verdicts": []})["mode"] == "subagent"


def test_applying_the_same_verdicts_twice_is_stable():
    analysis = _analysis()
    claims = vf.extract_claims(analysis)
    target = _section_7_claim(claims)
    verdicts = {"verdicts": [{"id": target["id"], "verdict": "refuted",
                              "evidence": "Annex B assigns it to AVL."}]}
    first = vf.apply_verdicts(analysis, claims, verdicts)
    deductions_first = json.dumps(analysis, sort_keys=True)
    second = vf.apply_verdicts(analysis, claims, verdicts)
    assert first == second
    assert json.dumps(analysis, sort_keys=True) == deductions_first
    assert [e["rule"] for e in _by_id(analysis)[7]["deductions"]] == ["S7.3", "V1"]


def test_new_verdicts_replace_the_earlier_ones_and_keep_other_runner_codes():
    analysis = _analysis()
    analysis["answers"][1]["deductions"].append(
        {"rule": "V3", "count": 1, "items": "AVL", "basis": "sow.txt"})
    claims = vf.extract_claims(analysis)
    target = _section_7_claim(claims)
    vf.apply_verdicts(analysis, claims, {"verdicts": [
        {"id": target["id"], "verdict": "refuted", "evidence": "q"}]})
    vf.apply_verdicts(analysis, claims, {"verdicts": [
        {"id": target["id"], "verdict": "confirmed", "evidence": "q"}]})
    assert [e["rule"] for e in _by_id(analysis)[7]["deductions"]] == ["S7.3", "V3"]


def test_the_retired_rating_helpers_are_gone():
    for name in ("LOWERED_NOTE", "CONTRADICTED", "RATED_BEFORE",
                 "_RATED_BEFORE", "model_rating", "lowered_reason",
                 "RATING_GUIDE", "PICTURE_NOTES", "answer_evidence_notes",
                 "CHECK_SCOPE"):
        assert not hasattr(vf, name), name


# ================================================================ run_apply
def _work(tmp_path):
    work = tmp_path / "output" / ".work"
    work.mkdir(parents=True)
    return str(work)


def test_run_apply_updates_both_checkpoints(tmp_path):
    work = _work(tmp_path)
    analysis = _analysis()
    claims = vf.extract_claims(analysis)
    target = next(c for c in claims if c["section"] == 7)
    for name, payload in (("analysis.json", analysis),
                          ("claims.json", {"claims": claims}),
                          ("verdicts.json", {"verdicts": [
                              {"id": target["id"], "verdict": "refuted",
                               "evidence": "Annex B assigns it to AVL."}]})):
        with open(os.path.join(work, name), "w", encoding="utf-8") as fh:
            json.dump(payload, fh)

    record = vf.run_apply(str(tmp_path))
    assert record["status"] == "ok" and record["claims"][0]["verdict"] == "refuted"
    with open(os.path.join(work, "analysis.json"), encoding="utf-8") as fh:
        by_id = {a["id"]: a for a in json.load(fh)["answers"]}
    assert [e["rule"] for e in by_id[7]["deductions"]] == ["S7.3", "V1"]
    with open(os.path.join(work, "verification.json"), encoding="utf-8") as fh:
        assert json.load(fh) == record


def test_run_apply_survives_a_missing_verdicts_file(tmp_path):
    """The verify pass is never allowed to break the run."""
    work = _work(tmp_path)
    with open(os.path.join(work, "analysis.json"), "w", encoding="utf-8") as fh:
        json.dump(_analysis(), fh)
    with open(os.path.join(work, "claims.json"), "w", encoding="utf-8") as fh:
        json.dump({"claims": vf.extract_claims(_analysis())}, fh)

    record = vf.run_apply(str(tmp_path), mode="in-thread")
    assert record["status"] == "error" and record["mode"] == "in-thread"
    assert "FileNotFoundError" in record["error"]
    with open(os.path.join(work, "verification.json"), encoding="utf-8") as fh:
        assert json.load(fh)["status"] == "error"


def test_run_apply_raises_when_a_checkpoint_is_missing(tmp_path):
    _work(tmp_path)
    with pytest.raises(FileNotFoundError):
        vf.run_apply(str(tmp_path))


# ====================================================== notes for the deck
def _verification(claims, mode="subagent", status="ok"):
    return {"status": status, "mode": mode, "claims": claims,
            "refuted_sections": [], "rejected_verdicts": []}


def test_check_summary_without_a_record_depends_on_whether_anything_qualified():
    assert vf.check_summary(4, None, 0) == vf.NO_CHECK
    assert vf.check_summary(4, None, 2) == vf.CHECK_FAILED


def test_check_summary_reports_a_failed_check():
    assert vf.check_summary(4, _verification([], status="error"), 1) == vf.CHECK_FAILED


def test_check_summary_counts_the_verdicts_for_the_section():
    record = _verification([
        {"section": 4, "claim": "A not found.", "verdict": "confirmed",
         "evidence": "q1"},
        {"section": 4, "claim": "B not found.", "verdict": "refuted",
         "evidence": "q2"},
        {"section": 4, "claim": "C not found.", "verdict": "unchecked",
         "evidence": ""},
        {"section": 9, "claim": "other", "verdict": "confirmed", "evidence": "q"}])
    text = vf.check_summary(4, record, 5)
    assert text == (
        "Check: 2 statements reviewed by a separate reviewer: 1 confirmed, "
        "1 contradicted by the documents. 1 statements were not checked "
        "(no usable result). " + vf._not_rechecked(2))
    assert "\n" not in text                     # one line


def test_check_summary_tells_an_in_thread_review_from_an_independent_one():
    claims = [{"section": 4, "claim": "A not found.", "verdict": "confirmed",
               "evidence": "q"}]
    assert "not an independent review" in vf.check_summary(
        4, _verification(claims, mode="in-thread"))
    assert "by a separate reviewer" in vf.check_summary(
        4, _verification(claims, mode="isolated"))
    assert "independence was not recorded" in vf.check_summary(
        4, _verification(claims, mode="replay"))


def test_check_summary_for_a_section_with_no_claims_in_the_record():
    record = _verification([{"section": 9, "claim": "x", "verdict": "confirmed",
                             "evidence": "q"}])
    assert vf.check_summary(4, record, 0) == vf.NO_CHECK
    assert vf.check_summary(4, record, 3) == "Check: " + vf._not_rechecked(3)


_SOURCES = "Sources:\n\nFile: sow.pdf\nPage: 3"


def _six_confirmed(section):
    return _verification([{"section": section, "claim": f"c{n}",
                           "verdict": "confirmed", "evidence": "q"}
                          for n in range(6)])


def test_confidence_notes_for_a_section_with_two_deductions():
    answer = {"id": 7, "answer": "", "not_found": False,
              "shown": {"found": 16, "shown": 13},
              "deductions": [
                  {"rule": "S7.1", "count": 4,
                   "items": "PM, design review, cooling jacket, failure handling",
                   "basis": "Technical Agreement 3.3.2 gives no phase for them"},
                  {"rule": "S7.2", "count": 2,
                   "items": "test bench setup, calibration sign-off",
                   "basis": "Table 2 lists Aurobay and Party B as R"}]}
    check = vf.check_summary(7, _six_confirmed(7), 6)
    assert vf.confidence_notes(7, answer, check, _SOURCES) == (
        "Confidence 6/10 (Medium)\n"
        "-2  S7.1  4 cells placed by inference: PM, design review, cooling "
        "jacket, failure handling (Technical Agreement 3.3.2 gives no phase "
        "for them)\n"
        "-2  S7.2  2 RASIC conflicts resolved to one executing party: test "
        "bench setup, calibration sign-off (Table 2 lists Aurobay and Party B "
        "as R)\n"
        "Check: 6 statements reviewed by a separate reviewer: 6 confirmed.\n"
        "Shown: 13 of 16 rows.\n"
        "\n"
        "Sources:\n\nFile: sow.pdf\nPage: 3")


def test_confidence_notes_for_a_clean_section():
    answer = {"id": 4, "answer": "", "deductions": []}
    assert vf.confidence_notes(4, answer, vf.NO_CHECK, _SOURCES) == (
        "Confidence 10/10 (High)\n"
        f"{confidence.NO_DEDUCTIONS}\n"
        f"{vf.NO_CHECK}\n\n{_SOURCES}")
    absent = {"id": 4, "answer": "Info not available", "not_found": True}
    assert vf.confidence_notes(4, absent, vf.NO_CHECK).splitlines()[1] == \
        confidence.NO_DEDUCTIONS_ABSENT


def test_an_entry_past_its_cap_is_left_out_of_the_notes():
    answer = {"id": 7, "answer": "", "deductions": [
        {"rule": "S7.3", "count": 1, "items": "a", "basis": ""},
        {"rule": "S7.3", "count": 1, "items": "b", "basis": ""}]}
    lines = vf.confidence_notes(7, answer, vf.NO_CHECK).splitlines()
    assert lines == ["Confidence 8/10 (High)", "-2  S7.3  owner propagated "
                     "across phases for a deliverable-bound task: a",
                     vf.NO_CHECK]


def test_attach_confidence_notes_sets_band_score_and_deductions():
    analysis = _analysis()
    claims = vf.extract_claims(analysis)
    target = _section_7_claim(claims)
    record = vf.apply_verdicts(analysis, claims, {"verdicts": [
        {"id": target["id"], "verdict": "refuted", "evidence": "Annex B."}]})
    plan = {"questions": [
        {"number": 1, "sourceDetails": _SOURCES},
        {"number": 7},
        {"number": 12},                                  # no answer: skipped
    ]}
    actions = vf.attach_confidence_notes(plan, analysis, record)
    assert actions == ["confidence notes: 2 sections"]
    first, seventh, twelfth = plan["questions"]
    assert (first["confidence"], first["score"], first["deductions"]) == (
        "high", 10, [])
    assert first["confidenceNotes"] == (
        f"Confidence 10/10 (High)\n{confidence.NO_DEDUCTIONS}\n"
        f"{vf.NO_CHECK}\n\n{_SOURCES}")
    assert (seventh["confidence"], seventh["score"]) == ("medium", 4)
    assert [(e["rule"], e["points"]) for e in seventh["deductions"]] == [
        ("S7.3", 2), ("V1", 4)]
    assert seventh["confidenceNotes"] == (
        "Confidence 4/10 (Medium)\n"
        "-2  S7.3  owner propagated across phases for a deliverable-bound "
        "task: test bench\n"
        '-4  V1  refuted by the reviewer: "Ownership split not found in the '
        'package." (quote: "Annex B.")\n'
        "Check: 1 statements reviewed by a separate reviewer: "
        "1 contradicted by the documents.")
    assert twelfth == {"number": 12}


def test_attach_confidence_notes_without_a_check_record():
    plan = {"questions": [{"number": 9}]}
    vf.attach_confidence_notes(plan, _analysis(), None)
    assert vf.CHECK_FAILED in plan["questions"][0]["confidenceNotes"]


def test_attach_confidence_notes_explains_the_account_lookup_in_section_one():
    match = {"status": "none", "customer": "Acme", "customer_site": ""}
    plan = {"questions": [{"number": 1}, {"number": 9}]}
    vf.attach_confidence_notes(plan, _analysis(), None, match)
    first, ninth = (q["confidenceNotes"] for q in plan["questions"])
    assert "\n\nAccount lookup (Salesforce account list" in first
    assert "Account lookup" not in ninth
