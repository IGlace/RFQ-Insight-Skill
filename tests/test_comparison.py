"""rfq/comparison.py: report acceptance, item diffs and the comparison
deck of two finished runs."""

import difflib
import json
import os
from pathlib import Path

import pytest

from conftest import SKILL_ROOT
from rfq import comparison
from rfq.schema import OPPORTUNITY, SCOPE, TIMING, TITLES

VOCAB = json.loads((Path(SKILL_ROOT) / "references" / "data" /
                    "vocabularies.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------- builders
def _opportunity(name: str, due: str = "20 October 2026") -> dict:
    product = VOCAB["products"][0]["name"]
    return {
        "customer": "Northwind Mobility", "customer_site": "Info not available",
        "customer_contact": "Dana Example", "quotation_due_date": due,
        "customer_short": "Northwind", "project_title": name,
        "opportunity_name": f"Northwind – {name}",
        "account_name": "Info not available", "kam_pte": "Info not available",
        "project_type": VOCAB["project_types"][0]["name"],
        "lead_product": product,
        "technology": VOCAB["technologies"][0]["name"],
        "industry": VOCAB["industries"][0]["name"],
        "products": [{"name": product, "percent": 100}],
        "skills": [{"name": VOCAB["skills"][0]["name"], "percent": 100}],
    }


def _bullets(number: int, *texts: str) -> list:
    return [{"layout": "bullets", "title": TITLES[number][0],
             "bullets": [{"text": t} for t in texts]}]


def _report(name: str, slides: dict | None = None, due: str = "20 October 2026",
            sections=range(1, 13)) -> dict:
    """A 12-section run report; `slides` overrides sections by number."""
    slides = slides or {}
    questions = []
    for n in sections:
        if n == OPPORTUNITY:
            own = [{"layout": "opportunity", "title": TITLES[n][0]}]
        else:
            own = slides.get(n) or _bullets(n, f"Point {n}.")
        questions.append({"number": n, "titleEn": TITLES[n][0],
                          "titleDe": TITLES[n][1], "slides": own})
    return {"run": {"projectName": name},
            "analysis": {"answers": [], "opportunity": _opportunity(name, due)},
            "slidePlan": {"projectName": name, "date": "2026-10-01",
                          "questions": questions}}


def _finished(root: Path, name: str, report: dict) -> Path:
    folder = root / name
    (folder / "output" / ".work").mkdir(parents=True)
    report_path = folder / "output" / "run.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    (folder / "output" / ".work" / "deliverables.json").write_text(json.dumps(
        {"pptx": str(folder / "output" / "run.pptx"), "report": str(report_path)}))
    return folder


def _diff(section: int, a: dict, b: dict):
    return comparison.diff_items(comparison.section_items(a, section),
                                 comparison.section_items(b, section),
                                 fuzzy=(section != OPPORTUNITY))


# ------------------------------------------------------------ acceptance
def test_check_report_accepts_a_current_report():
    comparison.check_report(_report("Cedar"))
    with_extra = _report("Cedar")
    questions = with_extra["slidePlan"]["questions"]
    questions.insert(11, {"number": 13, "titleEn": "Additional Information",
                          "titleDe": "Zusätzliche Informationen", "slides": []})
    comparison.check_report(with_extra)       # follow-up section is allowed


@pytest.mark.parametrize("make", [
    lambda: _report("Old", sections=range(1, 12)),          # 11 sections
    lambda: {**_report("Old"), "analysis": {"answers": []}},  # no opportunity
    lambda: {**_report("Old"), "slidePlan": {"questions": "none"}},
    lambda: "not a report",
])
def test_check_report_rejects_older_reports(make):
    with pytest.raises(comparison.ReportFormatError) as info:
        comparison.check_report(make())
    assert str(info.value) == comparison.OLD_FORMAT
    assert "older RFQ Insight version" in str(info.value)


def test_check_report_rejects_renamed_sections():
    report = _report("Old")
    report["slidePlan"]["questions"][1]["titleEn"] = "Summary"
    with pytest.raises(comparison.ReportFormatError, match="older RFQ Insight version"):
        comparison.check_report(report)


def test_load_report_names_the_folder(tmp_path):
    path = tmp_path / "run.json"
    path.write_text(json.dumps(_report("Old", sections=range(1, 12))), encoding="utf-8")
    with pytest.raises(comparison.ReportFormatError) as info:
        comparison.load_report(str(path), "Acme V6")
    assert str(info.value) == comparison.OLD_FORMAT_IN.format("Acme V6")
    assert "in Acme V6" in str(info.value)
    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(comparison.ReportFormatError, match="could not be read"):
        comparison.load_report(str(path), "Acme V6")


# ------------------------------------------------------------------ diffs
def test_diff_items_counts_unchanged_changed_added_and_removed():
    table = lambda rows: [{"layout": "table", "title": TITLES[3][0],  # noqa: E731
                           "columns": ["Item", "Value"], "rows": rows}]
    a = _report("A", {3: table([["Sensor modules", "four"], ["Supply voltage", "9 to 16 V"],
                                ["Connector", "M12"]])})
    b = _report("A", {3: table([["Sensor modules", "four"], ["Supply voltage", "9 to 18 V"],
                                ["Housing", "IP67"]])})
    counts, rows = _diff(3, a, b)
    assert counts == {"unchanged": 1, "changed": 1, "added": 1, "removed": 1}
    assert [(r["item"], r["change"]) for r in rows] == [
        ("Supply voltage", "Changed"), ("Connector", "Removed"), ("Housing", "Added")]
    changed = rows[0]
    assert changed["a"] == "Item: Supply voltage; Value: 9 to 16 V"
    assert changed["b"] == "Item: Supply voltage; Value: 9 to 18 V"
    assert rows[1]["b"] == "—" and rows[2]["a"] == "—"
    assert _diff(3, a, a) == ({"unchanged": 3, "changed": 0, "added": 0, "removed": 0}, [])


def test_opportunity_fields_are_compared_without_fuzzy_pairing():
    counts, rows = _diff(OPPORTUNITY, _report("Cedar"), _report("Cedar", due="27 October 2026"))
    assert counts["changed"] == 1 and counts["added"] == counts["removed"] == 0
    assert rows == [{"item": "Quotation due date", "a": "20 October 2026",
                     "b": "27 October 2026", "change": "Changed"}]
    counts, rows = _diff(OPPORTUNITY, _report("Cedar"), _report("Cedar"))
    assert counts["unchanged"] == len(comparison.OPPORTUNITY_FIELDS) + 2
    assert rows == []


def test_fuzzy_pairing_uses_the_similarity_threshold():
    assert comparison.SIMILARITY == 0.6
    near, far = "Bench readiness review", "Bench readines review"
    assert difflib.SequenceMatcher(None, near.lower(), far.lower()).ratio() >= 0.6
    assert difflib.SequenceMatcher(None, "alpha", "omega").ratio() < 0.6
    a = _report("A", {4: _bullets(4, near, "alpha")})
    b = _report("A", {4: _bullets(4, far, "omega")})
    counts, rows = _diff(4, a, b)
    assert counts == {"unchanged": 0, "changed": 1, "added": 1, "removed": 1}
    paired = rows[0]
    assert paired["change"] == "Changed" and paired["item"] == far
    assert paired["a"] == near and paired["b"] == far
    assert {(r["item"], r["change"]) for r in rows[1:]} == {
        ("alpha", "Removed"), ("omega", "Added")}
    # Without fuzzy pairing the renamed bullet is a removal plus an addition.
    counts, _rows = comparison.diff_items(comparison.section_items(a, 4),
                                          comparison.section_items(b, 4), fuzzy=False)
    assert counts == {"unchanged": 0, "changed": 0, "added": 2, "removed": 2}


def _ownership(rows: list, phases=("Bench Readiness", "Vehicle Check")) -> list:
    return [{"layout": "ownership", "title": TITLES[SCOPE][0],
             "columns": ["Scope of Work", *phases], "rows": rows}]


def test_ownership_cells_are_keyed_by_task_and_phase():
    report = _report("A", {SCOPE: _ownership([["Requirements review", "AVL", "Customer"],
                                              ["Shipping", "", "-"]])})
    items = comparison.section_items(report, SCOPE)
    assert comparison.OWNERSHIP_SEP == " × "
    assert set(items) == {"Requirements review × Bench Readiness",
                          "Requirements review × Vehicle Check",
                          "Shipping × Bench Readiness", "Shipping × Vehicle Check"}
    assert items["Requirements review × Bench Readiness"]["value"] == "AVL"
    assert items["Requirements review × Vehicle Check"]["value"] == "Customer"
    assert items["Shipping × Bench Readiness"]["value"] == comparison.NO_OWNER
    assert items["Shipping × Vehicle Check"]["value"] == comparison.NO_OWNER


def test_ownership_cells_pair_only_within_the_same_phase():
    # The same (slightly renamed) task in the SAME phase column: paired.
    a = _report("A", {SCOPE: _ownership([["Requirements review", "AVL"]],
                                        phases=("Bench Readiness",))})
    b = _report("A", {SCOPE: _ownership([["Requirement review", "Customer"]],
                                        phases=("Bench Readiness",))})
    counts, rows = _diff(SCOPE, a, b)
    assert counts == {"unchanged": 0, "changed": 1, "added": 0, "removed": 0}
    (renamed,) = rows
    assert renamed["item"] == "Requirement review × Bench Readiness"
    assert renamed["change"] == "Changed"
    assert renamed["a"] == "Requirements review × Bench Readiness (AVL)"
    assert renamed["b"] == "Requirement review × Bench Readiness (Customer)"

    # The same task names in DIFFERENT phase columns: never paired, even
    # though the whole keys would be similar enough on their own.
    c = _report("A", {SCOPE: _ownership([["Requirement review", "Customer"]],
                                        phases=("Vehicle Check",))})
    ka, kc = "Requirements review × Bench Readiness", "Requirement review × Vehicle Check"
    assert difflib.SequenceMatcher(None, ka.lower(), kc.lower()).ratio() >= comparison.SIMILARITY
    counts, rows = _diff(SCOPE, a, c)
    assert counts == {"unchanged": 0, "changed": 0, "added": 1, "removed": 1}
    assert {(r["item"], r["change"]) for r in rows} == {(ka, "Removed"), (kc, "Added")}


def test_owner_less_ownership_cells_are_never_added_or_removed_rows():
    a = _report("A", {SCOPE: _ownership([["Nothing here", "", "—"], ["Packing", "AVL", "-"]])})
    b = _report("A", {SCOPE: _ownership([["Zebra crossing", "-", ""]])})
    counts, rows = _diff(SCOPE, a, b)
    assert counts == {"unchanged": 0, "changed": 0, "added": 0, "removed": 1}
    assert [(r["item"], r["a"], r["change"]) for r in rows] == [
        ("Packing × Bench Readiness", "AVL", "Removed")]


def _timing(rows: list) -> list:
    return [{"layout": "timeline", "title": TITLES[TIMING][0],
             "steps": [{"label": r[0], "date": r[1], "desc": ""} for r in rows]},
            {"layout": "table", "title": TITLES[TIMING][0] + " — Milestone Table",
             "columns": ["Milestone", "Target timing", "Phase / Task"],
             "rows": rows}]


@pytest.mark.parametrize("before, after, label", [
    ("2026-11-02", "2026-11-05", "Changed (+3 days)"),
    ("2026-11-05", "2026-11-04", "Changed (-1 day)"),
    ("2026-11-02", "2026-11-09", "Changed (+1 week)"),
    ("2026-11-02", "2026-11-16", "Changed (+2 weeks)"),
    ("Nov 2026", "Jan 2027", "Changed (approximately +2 months)"),
    ("Q4 2026", "Q1 2027", "Changed (approximately +3 months)"),
])
def test_timing_changes_carry_the_date_shift(before, after, label):
    a = _report("A", {TIMING: _timing([["Review", before, "Review"]])})
    b = _report("A", {TIMING: _timing([["Review", after, "Review"]])})
    counts, rows = _diff(TIMING, a, b)
    assert counts["changed"] == 1
    (row,) = rows
    assert row["item"] == "Review" and row["change"] == label


def test_timing_changes_without_comparable_dates_are_plain_changes():
    a = _report("A", {TIMING: _timing([["Review", "2026-11-02", "Review"]])})
    b = _report("A", {TIMING: _timing([["Review", "after SOP", "Review"]])})
    (row,) = _diff(TIMING, a, b)[1]
    assert row["change"] == "Changed"
    assert comparison.exact_day_shift(
        __import__("datetime").date(2026, 11, 2),
        __import__("datetime").date(2026, 11, 2)) == "+0 days"
    assert comparison.format_shift(1.5) == "+1.5 months"
    assert comparison.format_shift(-1.0) == "-1 month"


# ---------------------------------------------------------------- compare
def test_run_compare_writes_the_comparison_json_and_deck(tmp_path):
    a = _finished(tmp_path, "Alpha RFQ", _report("Alpha", {4: _bullets(4, "Point A.")}))
    b = _finished(tmp_path, "Beta RFQ", _report("Beta", {4: _bullets(4, "Point B.")},
                                                 due="27 October 2026"))
    result = comparison.run_compare(str(a), str(b), today="2026-10-14")
    assert result["status"] == "done", result
    pptx = Path(result["pptx"])
    assert pptx.parent == a / "output"
    assert pptx.name == "RFQ Insight Comparison_Northwind – Alpha vs Northwind – Beta_14102026.pptx"
    assert pptx.read_bytes().startswith(b"PK")
    assert not list((b / "output").glob("*.pptx")), "folder B is never written"

    saved = json.loads((a / "output" / ".work" / "comparison.json").read_text(encoding="utf-8"))
    assert saved["date"] == "2026-10-14"
    assert saved["a"]["label"] == "Northwind – Alpha" and saved["a"]["column"] == "Northwind – Alpha"
    assert saved["b"]["label"] == "Northwind – Beta"
    assert [s["id"] for s in saved["sections"]] == list(range(1, 13))
    assert all(s["title"] == TITLES[s["id"]][0] for s in saved["sections"])
    by_id = {s["id"]: s for s in saved["sections"]}
    assert by_id[OPPORTUNITY]["counts"]["changed"] == 2        # name + due date
    assert by_id[4]["counts"] == {"unchanged": 0, "changed": 1, "added": 0, "removed": 0}
    assert by_id[5]["counts"] == {"unchanged": 1, "changed": 0, "added": 0, "removed": 0}

    # A second comparison on the same day never overwrites the first deck.
    again = comparison.run_compare(str(a), str(b), today="2026-10-14")
    assert Path(again["pptx"]).name.endswith("_14102026_2.pptx")
    assert Path(again["pptx"]).is_file() and pptx.is_file()


def test_comparison_basename_format():
    assert comparison.comparison_basename("Alpha", "Beta", "2026-10-06") == \
        "RFQ Insight Comparison_Alpha vs Beta_06102026"
    assert comparison.COMPARISON_PREFIX == "RFQ Insight Comparison_"


def test_run_compare_blocks_on_user_level_problems(tmp_path):
    a = _finished(tmp_path, "Alpha", _report("Alpha"))
    old = _finished(tmp_path, "Old", _report("Old", sections=range(1, 12)))
    assert comparison.run_compare(str(a), str(a)) == {
        "status": "blocked", "message": comparison.SAME_REPORT}
    result = comparison.run_compare(str(a), str(old))
    assert result == {"status": "blocked",
                      "message": comparison.OLD_FORMAT_IN.format("Old")}
    empty = tmp_path / "Empty"
    empty.mkdir()
    result = comparison.run_compare(str(a), str(empty))
    assert result["status"] == "blocked"
    assert result["message"] == ("No finished RFQ Insight run was found in Empty; "
                                 "run the analysis there first.")
    assert not (a / "output" / ".work" / "comparison.json").exists()
    assert not list((a / "output").glob("*.pptx"))
