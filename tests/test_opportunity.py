from rfq import opportunity, validation
from rfq.guidance import INFO_NOT_AVAILABLE, vocabulary


def _info():
    product = vocabulary("products")[0]
    skill = vocabulary("skills")[0]
    return {"customer": "Acme", "customer_contact": INFO_NOT_AVAILABLE,
            "quotation_due_date": INFO_NOT_AVAILABLE,
            "opportunity_name": "Acme" + validation.OPPORTUNITY_SEP + "Pack",
            "account_name": INFO_NOT_AVAILABLE, "kam_pte": INFO_NOT_AVAILABLE,
            "project_type": vocabulary("project_types")[0],
            "lead_product": product,
            "technology": vocabulary("technologies")[0],
            "industry": vocabulary("industries")[0],
            "products": [{"name": product, "percent": 100}],
            "skills": [{"name": skill, "percent": 100}]}


def _plan(second_header):
    split = opportunity.build_split_slide(_info())
    split["confidence"] = "Low"
    split["columns"] = ["Products (%)", second_header]
    return {"questions": [{"number": validation.OPPORTUNITY, "slides": [
        opportunity.build_opportunity_slide(_info()), split]}]}


def test_percentage_tables_use_the_short_header():
    assert opportunity.PRODUCTS_COLUMNS == ["Products (%)", "Definition"]
    assert opportunity.SKILLS_COLUMNS == ["Skills (%)", "Definition"]
    assert opportunity.MAIN_COLUMNS == ["Opportunity Info", "Definition according to RFQ"]


def test_stored_reports_with_the_old_header_still_validate():
    assert validation.LEGACY_DEFINITION_HEADER == "Definition according to RFQ"
    for header in ("Definition", validation.LEGACY_DEFINITION_HEADER):
        assert validation.check_final_opportunity(None, _plan(header)) == []
