"""Claim harvesting, the effect of a verdict, and the notes that explain a
confidence rating.

Ported from the old test_claims.py (extract_claims / apply_verdicts CLIs);
all of it now lives in rfq/verification.py.
"""

import json
import os

import pytest

from rfq import verification as vf
from rfq.opportunity import ACCOUNT_RISK_PREFIXES


def _analysis(answers=None):
    return {"answers": answers or [
        {"id": 1, "answer": "Customer is Acme.", "confidence": "high"},
        {"id": 7, "answer": "Ownership split not found in the package.",
         "confidence": "high", "confidence_reason": "The SOR names no owner."},
        {"id": 9, "answer": "SOP is 2027-03-01 (inferred) from the 24-month "
                            "schedule.", "confidence": "medium"},
    ]}


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
])
def test_every_absence_marker_qualifies(line):
    found = vf.check_candidates({"id": 4, "answer": line})
    assert found == [("absence", line)]


def test_derived_claim_needs_a_digit_not_just_the_tag():
    analysis = {"answers": [{"id": 5, "answer": "Approach is agile (inferred).",
                             "confidence": "high"}]}
    assert vf.extract_claims(analysis) == []
    assert vf.check_candidates(analysis["answers"][0]) == []


def test_candidates_are_cleaned_of_bullets_and_table_bars():
    found = vf.check_candidates({"id": 4, "answer": "- **Warranty**: not stated | x"})
    assert found == [("absence", "Warranty: not stated  x")]


def test_at_most_three_claims_per_section():
    lines = "\n".join(f"Item {n}: not stated." for n in range(10))
    answer = {"id": 4, "answer": lines}
    assert len(vf.check_candidates(answer)) == 10     # before the cap
    claims = vf.extract_claims({"answers": [answer]})
    assert len(claims) == vf.MAX_PER_SECTION == 3


def test_overall_cap_is_respected():
    answers = [{"id": i, "answer": "\n".join(["not found"] * 3)}
               for i in range(1, 12)]
    claims = vf.extract_claims({"answers": answers}, max_claims=20)
    assert len(claims) == 20
    assert [c["id"] for c in claims] == list(range(1, 21))


def test_the_default_overall_cap_is_twenty():
    answers = [{"id": i, "answer": "\n".join(["not found"] * 3)}
               for i in range(1, 13)]
    assert len(vf.extract_claims({"answers": answers})) == 20


def test_account_lines_in_opportunity_info_are_never_absence_claims():
    """The application fills Account Name (Site) and KAM (PTE); the model's
    "Info not available" there is a formatting artefact."""
    answer = {"id": 1, "answer": (
        "Customer: Acme\n"
        "- Account Name (Site): Info not available\n"
        "- KAM (PTE): Info not available\n"
        "Customer contact: Info not available")}
    found = vf.check_candidates(answer)
    assert found == [("absence", "Customer contact: Info not available")]


def test_account_lines_outside_section_one_still_count():
    answer = {"id": 4, "answer": "- KAM (PTE): Info not available"}
    assert len(vf.check_candidates(answer)) == 1


def test_the_account_risk_line_in_risk_detection_is_skipped():
    line = ACCOUNT_RISK_PREFIXES[0] + " so the account is not found."
    answer = {"id": 11, "answer": f"- Schedule is tight.\n- {line}\n- Cost not stated."}
    found = vf.check_candidates(answer)
    assert found == [("absence", "Cost not stated.")]


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


def test_large_claim_sets_split_into_sixes():
    assert vf.PARTITION_THRESHOLD == 8 and vf.PARTITION_SIZE == 6
    parts = vf.partition_claims(_claims(8))
    assert [len(p) for p in parts] == [6, 2]
    parts = vf.partition_claims(_claims(20))
    assert [len(p) for p in parts] == [6, 6, 6, 2]
    assert [c["id"] for p in parts for c in p] == list(range(1, 21))


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
def test_refuted_claim_caps_the_section_at_low():
    analysis = _analysis()
    claims = vf.extract_claims(analysis)
    target = next(c for c in claims if c["section"] == 7)
    verdicts = {"verdicts": [{"id": target["id"], "verdict": "refuted",
                              "evidence": "Annex B assigns calibration to AVL."}]}

    record = vf.apply_verdicts(analysis, claims, verdicts)
    by_id = {a["id"]: a for a in analysis["answers"]}
    assert by_id[7]["confidence"] == "low"
    assert by_id[1]["confidence"] == "high"        # untouched
    assert record["refuted_sections"] == [7]
    assert record["status"] == "ok"


def test_the_lowered_reason_names_the_contradiction_and_the_old_rating():
    analysis = _analysis()
    claims = vf.extract_claims(analysis)
    target = next(c for c in claims if c["section"] == 7)
    vf.apply_verdicts(analysis, claims, {"verdicts": [
        {"id": target["id"], "verdict": "refuted",
         "evidence": "Annex B assigns calibration to AVL."}]})
    reason = analysis["answers"][1]["confidence_reason"]
    assert reason.startswith(vf.LOWERED_NOTE.split("{")[0])
    assert "Ownership split not found in the package." in reason
    assert "Annex B assigns calibration to AVL." in reason
    assert "The analysis had rated this section high: The SOR names no owner." in reason


def test_the_answer_text_is_never_rewritten():
    analysis = _analysis()
    before = analysis["answers"][1]["answer"]
    claims = vf.extract_claims(analysis)
    target = next(c for c in claims if c["section"] == 7)
    vf.apply_verdicts(analysis, claims,
                      {"verdicts": [{"id": target["id"], "verdict": "refuted",
                                     "evidence": "Annex B says otherwise."}]})
    assert analysis["answers"][1]["answer"] == before


def test_refutation_without_a_quote_is_rejected():
    """A false refutation is worse than a missed one."""
    analysis = _analysis()
    claims = vf.extract_claims(analysis)
    target = next(c for c in claims if c["section"] == 7)
    record = vf.apply_verdicts(analysis, claims,
                               {"verdicts": [{"id": target["id"],
                                              "verdict": "refuted",
                                              "evidence": "   "}]})
    by_id = {a["id"]: a for a in analysis["answers"]}
    assert by_id[7]["confidence"] == "high"
    assert record["refuted_sections"] == []
    assert record["rejected_verdicts"]
    assert "quote" in record["rejected_verdicts"][0]
    assert [c["verdict"] for c in record["claims"]
            if c["id"] == target["id"]] == ["unchecked"]


def test_an_ambiguous_verdict_never_lowers_the_rating():
    analysis = _analysis()
    claims = vf.extract_claims(analysis)
    target = next(c for c in claims if c["section"] == 7)
    record = vf.apply_verdicts(analysis, claims, {"verdicts": [
        {"id": target["id"], "verdict": "ambiguous",
         "evidence": "Annex B mentions calibration without an owner."}]})
    by_id = {a["id"]: a for a in analysis["answers"]}
    assert by_id[7]["confidence"] == "high"
    assert by_id[7]["confidence_reason"] == "The SOR names no owner."
    assert record["refuted_sections"] == []
    assert record["rejected_verdicts"] == []
    assert [c["verdict"] for c in record["claims"]
            if c["id"] == target["id"]] == ["ambiguous"]


def test_an_ambiguous_verdict_without_evidence_is_unchecked():
    analysis = _analysis()
    claims = vf.extract_claims(analysis)
    target = next(c for c in claims if c["section"] == 7)
    record = vf.apply_verdicts(analysis, claims, {"verdicts": [
        {"id": target["id"], "verdict": "ambiguous", "evidence": ""}]})
    assert record["rejected_verdicts"]
    assert [c["verdict"] for c in record["claims"]
            if c["id"] == target["id"]] == ["unchecked"]


def test_a_confirmed_claim_leaves_everything_alone():
    analysis = _analysis()
    claims = vf.extract_claims(analysis)
    record = vf.apply_verdicts(analysis, claims, {"verdicts": [
        {"id": c["id"], "verdict": "confirmed", "evidence": "quote"}
        for c in claims]})
    assert {c["verdict"] for c in record["claims"]} == {"confirmed"}
    assert [a["confidence"] for a in analysis["answers"]] == [
        "high", "high", "medium"]


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
    target = next(c for c in claims if c["section"] == 7)
    verdicts = {"verdicts": [{"id": target["id"], "verdict": "refuted",
                              "evidence": "Annex B assigns it to AVL."}]}
    first = vf.apply_verdicts(analysis, claims, verdicts)
    reason_first = analysis["answers"][1]["confidence_reason"]
    second = vf.apply_verdicts(analysis, claims, verdicts)
    assert first == second
    assert analysis["answers"][1]["confidence_reason"] == reason_first
    assert reason_first.count("Lowered to low") == 1          # never nests


def test_model_rating_reads_back_through_a_lowered_reason():
    answer = {"confidence": "low", "confidence_reason":
              "Lowered to low by the independent check: x. "
              "The analysis had rated this section medium: partly inferred."}
    assert vf.model_rating(answer) == ("medium", "partly inferred.")
    assert vf.model_rating({"confidence": "high", "confidence_reason": " r "}) == (
        "high", "r")


def test_many_contradictions_are_cut_to_three_and_counted():
    answer = {"confidence": "high", "confidence_reason": "r"}
    reason = vf.lowered_reason(answer, [(f"c{i}", f"q{i}") for i in range(5)])
    assert reason.count("(quote:") == vf.MAX_LISTED == 3
    assert "and 2 more statement(s)" in reason


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
    assert record["status"] == "ok" and record["refuted_sections"] == [7]
    with open(os.path.join(work, "analysis.json"), encoding="utf-8") as fh:
        by_id = {a["id"]: a for a in json.load(fh)["answers"]}
    assert by_id[7]["confidence"] == "low"
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
    assert text.startswith("Check: 2 statements reviewed by a separate reviewer: "
                           "1 confirmed, 1 contradicted by the documents.")
    assert "1 statements were not checked (no usable result)." in text
    assert "2 additional statements were not checked" in text
    assert vf.CHECK_SCOPE in text
    assert "Statements checked:" in text
    assert '- B not found.\n  Result: contradicted by the documents. Source text: "q2"' in text
    assert "No source quote was recorded." in text


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


def test_confidence_notes_have_the_documented_shape():
    text = vf.confidence_notes("high", "Direct support in the SOR.",
                               vf.NO_CHECK, "Sources: SOR.docx p. 3")
    assert text == ("CONFIDENCE: HIGH\n\n"
                    "Reason:\nDirect support in the SOR.\n\n"
                    f"{vf.NO_CHECK}\n\n"
                    "Sources: SOR.docx p. 3")


def test_confidence_notes_fill_in_a_missing_reason_and_drop_the_details():
    check = vf.check_summary(4, _verification([
        {"section": 4, "claim": "A not found.", "verdict": "confirmed",
         "evidence": "q"}]))
    text = vf.confidence_notes("medium", "", check)
    assert "No reason was recorded for this rating." in text
    assert "Statements checked:" not in text
    assert text.startswith("CONFIDENCE: MEDIUM")


def test_confidence_notes_strip_the_historical_rating_sentence():
    reason = ("Lowered to low by the independent check: x. "
              "The analysis had rated this section high: fine.")
    text = vf.confidence_notes("low", reason, vf.NO_CHECK)
    assert "The analysis had rated" not in text
    assert "Lowered to low" in text


def test_attach_confidence_notes_writes_one_block_per_rated_section():
    analysis = _analysis()
    plan = {"questions": [
        {"number": 1, "confidence": "high"},
        {"number": 7, "confidence": "high"},
        {"number": 9},                                  # unrated: skipped
    ]}
    actions = vf.attach_confidence_notes(plan, analysis, None)
    assert actions == ["confidence notes: 2 sections"]
    assert plan["questions"][0]["confidenceNotes"].startswith("CONFIDENCE: HIGH")
    assert vf.CHECK_FAILED in plan["questions"][1]["confidenceNotes"]
    assert "confidenceNotes" not in plan["questions"][2]


def test_answer_evidence_notes_list_inferences_and_absences():
    text = vf.answer_evidence_notes({"id": 9, "answer":
        "SOP is 2027 (inferred) from the plan.\nWarranty not stated."})
    assert "Estimates or assumptions:" in text
    assert "- SOP is 2027 (inferred) from the plan." in text
    assert "Information reported as missing:" in text
    assert "- Warranty not stated." in text
    assert vf.answer_evidence_notes({"id": 2, "answer": "Plain fact."}) == ""
