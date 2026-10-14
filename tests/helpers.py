"""Shared fixtures for the RFQ Insight test-suite: one valid analysis and
one valid slide-plan draft, as the two model stages would hand them over.

Both builders return fresh dicts on every call, so a test may mutate what
it gets without affecting another one. The names are invented
(Northwind is the customer, Acme the supplier)."""

from rfq.schema import TITLES

SOURCE_FILE = "01_statement_of_work.txt"
CUSTOMER = "Northwind Motors GmbH"
CUSTOMER_SHORT = "Northwind"
PROJECT_TITLE = "V6 Engine Calibration"
OPPORTUNITY_NAME = f"{CUSTOMER_SHORT} – {PROJECT_TITLE}"      # en dash

_ANSWERS = {
    1: "Customer: Northwind Motors GmbH. Quotation due 20 October 2026.",
    2: "Northwind requests calibration of a V6 spark-ignited engine for a "
       "passenger car platform, from concept to SOP.",
    3: "| Item | Target |\n| --- | --- |\n| Power | 220 kW |\n| Emissions | Euro 7 |",
    4: "| Topic | Approach |\n| --- | --- |\n| Calibration | Base and drivability |",
    5: "Northwind leads the programme; AVL calibrates; Acme supplies injectors.",
    6: "| Phase | Scope |\n| --- | --- |\n| Concept | Targets |\n| A-Sample | First build |",
    7: "| Task | Concept | A-Sample |\n| --- | --- | --- |\n| Design | AVL | Northwind |",
    8: "- Calibration data sets\n- Test reports",
    9: "Kick-off January 2027, A-Sample June 2027, SOP December 2028.",
    10: "| Standard | Scope |\n| --- | --- |\n| ISO 26262 | Functional safety |",
    11: "Project Risks:\n- The A-Sample date is tight.\nDocument Risks:\n"
        "- The BOM is not included.",
    12: "- 01_statement_of_work.txt",
}

_TLDR = {
    1: "Northwind asks for a V6 calibration quote by 20 October 2026.",
    2: "A V6 spark-ignited engine calibration up to SOP.",
    3: "Power 220 kW and Euro 7 emissions are the targets.",
    4: "Base calibration followed by drivability work.",
    5: "Northwind leads, AVL calibrates, Acme supplies injectors.",
    6: "Concept and A-Sample phases are planned.",
    7: "AVL designs in the concept phase; Northwind in A-Sample.",
    8: "Calibration data sets and test reports are deliverable.",
    9: "Kick-off in January 2027 and SOP in December 2028.",
    10: "ISO 26262 applies.",
    11: "The A-Sample date is tight and the BOM is missing.",
    12: "One statement of work was provided.",
}


def sample_opportunity():
    """A valid `opportunity` object in Guidance vocabulary."""
    return {
        "customer": CUSTOMER,
        "customer_site": "Info not available",
        "customer_contact": "Jane Doe, Purchasing, jane.doe@example.com",
        "quotation_due_date": "20 October 2026",
        "customer_short": CUSTOMER_SHORT,
        "project_title": PROJECT_TITLE,
        "opportunity_name": OPPORTUNITY_NAME,
        "account_name": "Info not available",
        "kam_pte": "Info not available",
        "project_type": "SOP Project w/o CSM (up to SOP or partial SOP development)",
        "lead_product": "Spark Ignited",
        "technology": "ICE & Mild Hybrid",
        "industry": "Passenger Car",
        "products": [{"name": "Spark Ignited", "percent": 100}],
        "skills": [{"name": "Calibration", "percent": 70},
                   {"name": "Project Management", "percent": 30}],
    }


def sample_analysis():
    """A valid 12-section AnalysisResult dict (ids 1-12 in TITLES order)."""
    answers = []
    for number in TITLES:
        answers.append({
            "id": number,
            "answer": _ANSWERS[number],
            "tldr": _TLDR[number],
            "not_found": False,
            "confidence": "high",
            "confidence_reason": (
                f"Section {number} is stated directly in the statement of "
                f"work; nothing had to be inferred from other documents."),
            "sources": [{"filename": SOURCE_FILE, "locator": ""}],
        })
    return {"answers": answers, "opportunity": sample_opportunity()}


def _question(number, slides):
    return {"number": number, "titleEn": TITLES[number][0],
            "titleDe": TITLES[number][1], "slides": slides}


def _table(number, columns, rows):
    return {"layout": "table", "title": TITLES[number][0],
            "columns": columns, "rows": rows}


def sample_plan():
    """A LoosePlanDraft dict that satisfies validation.check_plan."""
    return {"projectName": OPPORTUNITY_NAME, "questions": [
        _question(1, [{"layout": "opportunity", "title": "Opportunity Info"}]),
        _question(2, [{"layout": "prose", "title": TITLES[2][0],
                       "body": _ANSWERS[2]}]),
        _question(3, [_table(3, ["Item", "Target"],
                             [["Power", "220 kW"], ["Emissions", "Euro 7"]])]),
        _question(4, [_table(4, ["Topic", "Approach"],
                             [["Calibration", "Base and drivability"]])]),
        _question(5, [{"layout": "collab", "title": TITLES[5][0],
                       "hub": "Northwind",
                       "parties": [
                           {"name": "Northwind", "role": "Customer",
                            "type": "customer"},
                           {"name": "AVL", "role": "Calibration", "type": "avl"},
                           {"name": "Acme", "role": "Injector supplier",
                            "type": "supplier"}]}]),
        _question(6, [{"layout": "phases", "title": TITLES[6][0],
                       "phases": [{"name": "Concept", "desc": "Targets"},
                                  {"name": "A-Sample", "desc": "First build"}]}]),
        _question(7, [{"layout": "ownership", "title": TITLES[7][0],
                       "customerAbbr": "Northwind",
                       "columns": ["Scope of Work", "Concept", "A-Sample"],
                       "rows": [["Design", "AVL", "Northwind"],
                                ["Testing", "AVL", "AVL"]]}]),
        _question(8, [_table(8, ["Deliverable", "Format"],
                             [["Calibration data sets", "Files"],
                              ["Test reports", "PDF"]])]),
        _question(9, [{"layout": "gantt", "title": TITLES[9][0],
                       "steps": [
                           {"label": "Kick-off", "date": "Jan 2027",
                            "desc": "Project start"},
                           {"label": "A-Sample", "date": "Jun 2027",
                            "desc": "First build"},
                           {"label": "SOP", "date": "Dec 2028",
                            "desc": "Start of production"}],
                       "barLabel": "V6 calibration"},
                      _table(9, ["Milestone", "Date"],
                             [["Kick-off", "Jan 2027"], ["A-Sample", "Jun 2027"],
                              ["SOP", "Dec 2028"]])]),
        _question(10, [_table(10, ["Standard", "Scope"],
                              [["ISO 26262", "Functional safety"]])]),
        _question(11, [{"layout": "panel", "title": "Risk Detection",
                        "heading": "Project Risks",
                        "items": ["The A-Sample date is tight."]},
                       {"layout": "panel", "title": "Risk Detection",
                        "heading": "Document Risks",
                        "items": ["The BOM is not included."]}]),
        _question(12, [{"layout": "bullets", "title": TITLES[12][0],
                        "bullets": [{"text": SOURCE_FILE}]}]),
    ]}


def sample_corpus(text="Concept and A-Sample phases apply. ISO 26262."):
    """A one-file corpus whose only file is the one sample_analysis cites."""
    return {"projectName": "Northwind RFQ", "oppId": "",
            "filesContents": [{"filename": SOURCE_FILE, "path": SOURCE_FILE,
                               "extension": "txt", "extracted_text": text}],
            "extraction": {"parsed": 1, "chars": len(text), "skipped": [],
                           "ignored": [], "images_flagged": [],
                           "images_filtered": [],
                           "preprocess": {SOURCE_FILE: {
                               "chars_before": len(text),
                               "chars_after": len(text),
                               "removed_pct": 0.0}}}}
