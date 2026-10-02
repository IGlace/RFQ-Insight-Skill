"""Claim harvesting and the effect of a verdict.

The first two tests are ported from
RFQ_Container_App/tests/test_insight_pipeline.py.
"""

import json
import os

import apply_verdicts as av
import extract_claims as ec


def _analysis(answers=None):
    return {"answers": answers or [
        {"id": 1, "answer": "Customer is Acme.", "confidence": "high"},
        {"id": 7, "answer": "Ownership split not found in the package.",
         "confidence": "high"},
        {"id": 9, "answer": "SOP is 2027-03-01 (inferred) from the 24-month "
                            "schedule.", "confidence": "medium"},
    ]}


# --------------------------------------------------------- harvesting
def test_extract_claims_finds_absences_and_derived():
    claims = ec.extract_claims(_analysis())
    kinds = {(c["section"], c["kind"]) for c in claims}
    assert (7, "absence") in kinds
    assert (9, "derived") in kinds
    assert not any(c["section"] == 1 for c in claims)


def test_extract_claims_carries_context_and_clean_text():
    claims = ec.extract_claims(_analysis())
    absence = next(c for c in claims if c["section"] == 7)
    assert absence["claim"] == "Ownership split not found in the package."
    assert "not found" in absence["context"]
    assert "*" not in absence["claim"] and "|" not in absence["claim"]


def test_derived_claim_needs_a_digit_not_just_the_tag():
    analysis = {"answers": [{"id": 5, "answer": "Approach is agile (inferred).",
                             "confidence": "high"}]}
    assert ec.extract_claims(analysis) == []


def test_at_most_three_claims_per_section():
    lines = "\n".join(f"Item {n}: not stated." for n in range(10))
    claims = ec.extract_claims({"answers": [{"id": 4, "answer": lines}]})
    assert len(claims) == 3


def test_overall_cap_is_respected():
    answers = [{"id": i, "answer": "\n".join(["not found"] * 3)}
               for i in range(1, 12)]
    claims = ec.extract_claims({"answers": answers}, max_claims=20)
    assert len(claims) == 20
    assert [c["id"] for c in claims] == list(range(1, 21))


# ------------------------------------------------------------ verdicts
def test_refuted_claim_caps_the_section_at_low():
    analysis = _analysis()
    claims = ec.extract_claims(analysis)
    target = next(c for c in claims if c["section"] == 7)
    verdicts = {"verdicts": [{"id": target["id"], "verdict": "refuted",
                              "evidence": "Annex B assigns calibration to AVL."}]}

    record = av.apply_verdicts(analysis, claims, verdicts)
    by_id = {a["id"]: a for a in analysis["answers"]}
    assert by_id[7]["confidence"] == "low"
    assert by_id[1]["confidence"] == "high"        # untouched
    assert record["refuted_sections"] == [7]
    assert record["status"] == "ok"


def test_the_answer_text_is_never_rewritten():
    analysis = _analysis()
    before = analysis["answers"][1]["answer"]
    claims = ec.extract_claims(analysis)
    target = next(c for c in claims if c["section"] == 7)
    av.apply_verdicts(analysis, claims,
                      {"verdicts": [{"id": target["id"], "verdict": "refuted",
                                     "evidence": "Annex B says otherwise."}]})
    assert analysis["answers"][1]["answer"] == before


def test_refutation_without_a_quote_is_rejected():
    """A false refutation is worse than a missed one - the verifier prompt's
    own bar, enforced deterministically here."""
    analysis = _analysis()
    claims = ec.extract_claims(analysis)
    target = next(c for c in claims if c["section"] == 7)
    record = av.apply_verdicts(analysis, claims,
                               {"verdicts": [{"id": target["id"],
                                              "verdict": "refuted",
                                              "evidence": "   "}]})
    by_id = {a["id"]: a for a in analysis["answers"]}
    assert by_id[7]["confidence"] == "high"
    assert record["refuted_sections"] == []
    assert record["rejected_verdicts"]
    assert "quote" in record["rejected_verdicts"][0]


def test_claim_with_no_verdict_is_marked_unchecked():
    analysis = _analysis()
    claims = ec.extract_claims(analysis)
    record = av.apply_verdicts(analysis, claims, {"verdicts": []})
    assert {c["verdict"] for c in record["claims"]} == {"unchecked"}
    assert record["refuted_sections"] == []


def test_no_claims_is_a_status_not_a_failure():
    record = av.apply_verdicts({"answers": []}, [], {"verdicts": []})
    assert record["status"] == "no_claims"


def test_mode_is_recorded_for_the_report():
    analysis = _analysis()
    claims = ec.extract_claims(analysis)
    record = av.apply_verdicts(analysis, claims, {"verdicts": []},
                               mode="in-thread")
    assert record["mode"] == "in-thread"


def test_applying_the_same_verdicts_twice_is_stable():
    analysis = _analysis()
    claims = ec.extract_claims(analysis)
    target = next(c for c in claims if c["section"] == 7)
    verdicts = {"verdicts": [{"id": target["id"], "verdict": "refuted",
                              "evidence": "Annex B assigns it to AVL."}]}
    first = av.apply_verdicts(analysis, claims, verdicts)
    second = av.apply_verdicts(analysis, claims, verdicts)
    assert first == second


# ----------------------------------------------------------------- CLI
def _work(tmp_path):
    work = tmp_path / "output" / ".work"
    work.mkdir(parents=True)
    return str(work)


def test_extract_claims_cli_writes_the_checkpoint(tmp_path):
    work = _work(tmp_path)
    with open(os.path.join(work, "analysis.json"), "w", encoding="utf-8") as fh:
        json.dump(_analysis(), fh)
    assert ec.main([str(tmp_path)]) == 0
    with open(os.path.join(work, "claims.json"), encoding="utf-8") as fh:
        assert len(json.load(fh)["claims"]) == 2


def test_apply_verdicts_cli_updates_both_checkpoints(tmp_path):
    work = _work(tmp_path)
    analysis = _analysis()
    claims = ec.extract_claims(analysis)
    target = next(c for c in claims if c["section"] == 7)
    for name, payload in (("analysis.json", analysis),
                          ("claims.json", {"claims": claims}),
                          ("verdicts.json", {"verdicts": [
                              {"id": target["id"], "verdict": "refuted",
                               "evidence": "Annex B assigns it to AVL."}]})):
        with open(os.path.join(work, name), "w", encoding="utf-8") as fh:
            json.dump(payload, fh)

    assert av.main([str(tmp_path)]) == 0
    with open(os.path.join(work, "analysis.json"), encoding="utf-8") as fh:
        by_id = {a["id"]: a for a in json.load(fh)["answers"]}
    assert by_id[7]["confidence"] == "low"
    with open(os.path.join(work, "verification.json"), encoding="utf-8") as fh:
        assert json.load(fh)["refuted_sections"] == [7]


def test_apply_verdicts_cli_survives_a_missing_verdicts_file(tmp_path):
    """The verify pass is never allowed to break the run."""
    work = _work(tmp_path)
    with open(os.path.join(work, "analysis.json"), "w", encoding="utf-8") as fh:
        json.dump(_analysis(), fh)
    with open(os.path.join(work, "claims.json"), "w", encoding="utf-8") as fh:
        json.dump({"claims": ec.extract_claims(_analysis())}, fh)

    assert av.main([str(tmp_path)]) == 0
    with open(os.path.join(work, "verification.json"), encoding="utf-8") as fh:
        assert json.load(fh)["status"] == "error"


def test_extract_claims_cli_says_what_is_missing_instead_of_crashing(
        tmp_path, capsys):
    """These scripts are run on a resume, where a checkpoint being absent
    is ordinary. A bare FileNotFoundError traceback is not an answer."""
    _work(tmp_path)
    assert ec.main([str(tmp_path)]) == 2
    err = capsys.readouterr().err
    assert "checkpoint is missing" in err
    assert "Traceback" not in err and "analysis.json" not in err


def test_apply_verdicts_cli_says_what_is_missing_instead_of_crashing(
        tmp_path, capsys):
    _work(tmp_path)
    assert av.main([str(tmp_path)]) == 2
    err = capsys.readouterr().err
    assert "checkpoint is missing" in err
    assert "Traceback" not in err
