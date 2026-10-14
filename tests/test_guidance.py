"""rfq.guidance + rfq.opportunity: the Guidance vocabularies, the Salesforce
account lookup (read-only against the shipped accounts.csv) and the
deterministic Opportunity Info slide."""

import json

import pytest

from helpers import sample_analysis, sample_opportunity, sample_plan
from rfq import guidance, opportunity
from rfq.guidance import INFO_NOT_AVAILABLE

NINGBO = "Aurobay (Ningbo) Intelligent Technology Co., Ltd."


# ----------------------------------------------------------- vocabularies
def test_vocabularies_come_from_the_shipped_workbook_in_order():
    assert guidance.vocabulary("project_types")[3] == (
        "SOP Project w/o CSM (up to SOP or partial SOP development)")
    assert guidance.vocabulary("technologies")[0] == "ICE & Mild Hybrid"
    assert guidance.vocabulary("industries")[0] == "Passenger Car"
    assert "Spark Ignited" in guidance.vocabulary("products")
    assert guidance.vocabulary("skills")[:2] == ["Functional Development", "Simulation"]
    raw = json.loads((guidance.GUIDANCE_DIR / "vocabularies.json").read_text(encoding="utf-8"))
    for kind in guidance.VOCABULARIES:
        names = guidance.vocabulary(kind)
        assert names == [item["name"] for item in raw[kind]]
        assert len(set(names)) == len(names)


def test_unknown_vocabulary_is_refused():
    with pytest.raises(ValueError, match="Unknown vocabulary"):
        guidance.vocabulary("colours")


def test_the_account_list_is_loaded_once_with_its_keys():
    data = guidance.load_guidance()
    assert len(data["accounts"]) > 20_000
    first = data["accounts"][0]
    assert set(first) >= {"name", "base", "site", "country", "kam_pte", "kam_company",
                          "index", "key", "display_name"}
    assert first["index"] == 0
    assert guidance.load_guidance() is data


# ------------------------------------------------------- name normalising
@pytest.mark.parametrize("text,folded", [
    ("Müller & Söhne AG", "muller and sohne ag"),
    ("  Xi'an  Motors ", "xi an motors"),
    ("Øresund-Straße 5", "oresund strasse 5"),
    ("", ""), (None, ""),
])
def test_fold(text, folded):
    assert guidance.fold(text) == folded


@pytest.mark.parametrize("name,key", [
    ("VINFAST Trading and Production JSC", "vinfast trading and production"),
    ("Aurobay (Ningbo) Intelligent Technology Co., Ltd.", "aurobay ningbo intelligent technology"),
    ("Robert Bosch GmbH", "robert bosch"),
    ("Volvo Car Corporation", "volvo car"),
    ("Hyundai Motor Company", "hyundai motor"),
    ("Siemens A.G.", "siemens"),
    ("Skoda Auto a.s.", "skoda auto"),
    ("Mercedes-Benz AG & Co. KG", "mercedes benz"),
    ("The Northwind Company", "northwind"),
    ("TBK Co., Ltd.", "tbk"),
    ("", ""),
])
def test_normalize_name_drops_legal_forms_only(name, key):
    assert guidance.normalize_name(name) == key


@pytest.mark.parametrize("site,cleaned", [
    ("Graz (inferred)", "Graz"),
    ("(assumed) Ningbo, Zhejiang (inferred) ", "Ningbo, Zhejiang"),
    ("Info not available", ""), ("N/A", ""), ("unknown", ""), ("", ""), (None, ""),
    ("Hauptstrasse 5, 8020 Graz, Austria", "Hauptstrasse 5, 8020 Graz, Austria"),
])
def test_clean_site(site, cleaned):
    assert guidance.clean_site(site) == cleaned


# -------------------------------------------------------- resolve_account
def test_exact_name_with_the_country_in_the_text_is_matched():
    result = guidance.resolve_account(
        NINGBO, "The customer, located in Ningbo, China, requests a quotation from AVL List GmbH, Graz, Austria.")
    assert result["status"] == "matched"
    assert result["tier"] == "exact"
    assert result["account_name"] == NINGBO
    assert result["kam_pte"] == "Hao Tong"
    assert result["customer"] == NINGBO and result["customer_site"] == ""
    assert result["candidates"] == [NINGBO]
    assert result["candidate_count"] == 1
    [detail] = result["candidate_details"]
    assert detail["reason"].startswith("Chosen: exact name match")
    assert '"China"' in detail["reason"]


def test_exact_name_without_its_country_in_the_text_is_ambiguous():
    result = guidance.resolve_account(NINGBO, "A calibration project for a passenger car.")
    assert result["status"] == "ambiguous"
    assert result["tier"] == "exact"
    assert result["account_name"] == INFO_NOT_AVAILABLE
    assert result["kam_pte"] == INFO_NOT_AVAILABLE
    [detail] = result["candidate_details"]
    assert "does not name its country" in detail["reason"]


def test_exact_name_with_another_country_in_the_text_is_ambiguous():
    result = guidance.resolve_account(NINGBO, "Deliveries go to the plant in Sweden.")
    assert result["status"] == "ambiguous"
    [detail] = result["candidate_details"]
    assert "Sweden" in detail["reason"] and "not named in the RFQ" in detail["reason"]


def test_avls_own_country_in_the_text_does_not_count():
    result = guidance.resolve_account(NINGBO, "To: AVL List GmbH, Hans-List-Platz 1, 8020 Graz, Austria.")
    assert result["status"] == "ambiguous"


def test_own_address_chooses_between_sites():
    result = guidance.resolve_account("Aurobay", "", site="Aurobay AB, 541 36 Skövde, Sweden")
    assert result["status"] == "matched"
    assert result["account_name"] == "Aurobay (Skövde)"
    assert result["kam_pte"] == "Grant Cairnie"


def test_a_nonexistent_customer_has_no_candidates():
    result = guidance.resolve_account("Zzyzx Quantum Widgets Ltd.", "Somewhere in Germany.")
    assert result["status"] == "none"
    assert result["tier"] == "none"
    assert result["candidates"] == [] and result["candidate_details"] == []
    assert result["candidate_count"] == 0
    assert result["account_name"] == INFO_NOT_AVAILABLE


def test_several_exact_name_sites_without_an_address_are_ambiguous():
    result = guidance.resolve_account("Aurobay", "An engine project.")
    assert result["status"] == "ambiguous"
    assert result["tier"] == "exact"
    assert result["candidate_count"] >= 2
    assert "Aurobay (Skövde)" in result["candidates"]
    assert all(d["reason"].startswith("Not chosen: several accounts share this name")
               for d in result["candidate_details"])


def test_a_partly_matching_name_is_never_chosen():
    result = guidance.resolve_account("Aurobay Sweden AB", "Skövde, Sweden.")
    assert result["status"] == "ambiguous"
    assert result["tier"] in ("tokens", "fuzzy", "contained")
    assert result["account_name"] == INFO_NOT_AVAILABLE
    assert all(d["reason"].startswith("Not chosen") for d in result["candidate_details"])


def test_avl_itself_is_never_the_customer():
    result = guidance.resolve_account("AVL List GmbH", "Graz, Austria.")
    assert result["status"] in ("ambiguous", "none")
    assert result["account_name"] == INFO_NOT_AVAILABLE
    if result["candidate_details"]:
        assert all(d["reason"] == "Not chosen: AVL is the supplier, not the customer."
                   for d in result["candidate_details"])


def test_search_accounts_lists_candidates_best_first():
    hits = guidance.search_accounts("Aurobay", country="Sweden")
    assert hits and all(h["country"] == "Sweden" for h in hits)
    assert hits[0]["match"] == "exact" and hits[0]["score"] == 1.0
    assert {"account_name", "site", "country", "kam_pte", "kam_company"} <= set(hits[0])
    assert guidance.search_accounts("Aurobay", site="Skövde")[0]["account_name"] == "Aurobay (Skövde)"


# ------------------------------------------------------ account_risk_line
@pytest.mark.parametrize("match,expected", [
    ({"status": "unreadable", "customer": "X"}, opportunity.UNREADABLE_ACCOUNT_RISK_LINE),
    ({"status": "none", "customer": "Zzyzx"}, 'No Salesforce account matches "Zzyzx".'),
    ({"status": "no_kam", "customer": "X", "account_name": "Aurobay (Gothenburg)"},
     'The Salesforce account "Aurobay (Gothenburg)" has no KAM (PTE) assigned.'),
    ({"status": "ambiguous", "tier": "tokens", "customer": "Aurobay Sweden"},
     'No exact Salesforce account match for "Aurobay Sweden"; close candidates are listed in the notes.'),
    ({"status": "ambiguous", "tier": "exact", "customer": "Aurobay",
      "candidates": ["Aurobay (Skövde)", "Aurobay (Gothenburg)"]},
     'Account Name (Site) and KAM (PTE) could not be matched to one Salesforce account '
     'for "Aurobay" (candidates: Aurobay (Skövde); Aurobay (Gothenburg)); confirm the account manually.'),
    ({"status": "matched", "customer": "X"}, None),
    (None, None),
])
def test_account_risk_line_per_status(match, expected):
    assert opportunity.account_risk_line(match) == expected


def test_ambiguous_risk_line_lists_three_candidates_and_counts_the_rest():
    match = {"status": "ambiguous", "tier": "exact", "customer": "Acme",
             "candidate_details": [
                 {"account_name": "Acme (A)", "kam_pte": "K1"},
                 {"account_name": "Acme (A)", "kam_pte": "K2"},
                 {"account_name": "Acme (B)", "kam_pte": "K3"},
                 {"account_name": "Acme (C)", "kam_pte": "K4"},
                 {"account_name": "Acme (D)", "kam_pte": "K5"}]}
    line = opportunity.account_risk_line(match)
    assert "candidates: Acme (A) (K1); Acme (B); Acme (C); and 1 more" in line
    assert line.startswith(opportunity.ACCOUNT_RISK_PREFIXES[0])


def test_every_risk_line_starts_with_a_known_prefix():
    for match in ({"status": "unreadable"}, {"status": "none", "customer": "X"},
                  {"status": "no_kam", "account_name": "Y"},
                  {"status": "ambiguous", "tier": "fuzzy", "customer": "X"},
                  {"status": "ambiguous", "tier": "exact", "customer": "X", "candidates": ["A"]}):
        assert opportunity.account_risk_line(match).startswith(opportunity.ACCOUNT_RISK_PREFIXES)


def test_add_and_remove_account_risk_on_section_11():
    analysis = sample_analysis()
    match = {"status": "none", "customer": "Zzyzx"}
    assert opportunity.add_account_risk(analysis, match) is True
    assert opportunity.add_account_risk(analysis, match) is False
    risks = next(a for a in analysis["answers"] if a["id"] == 11)
    assert risks["answer"].endswith('\n- No Salesforce account matches "Zzyzx".')
    assert opportunity.remove_account_risk(analysis) is True
    assert risks["answer"] == sample_analysis()["answers"][10]["answer"]
    assert opportunity.remove_account_risk(analysis) is False
    assert opportunity.add_account_risk(analysis, {"status": "matched"}) is False


def test_place_account_risk_owns_the_document_risks_panel():
    plan = sample_plan()
    panels = plan["questions"][10]["slides"]
    panels[1]["items"].append("No Salesforce account was found (model guess).")
    actions = opportunity.place_account_risk(plan, 'No Salesforce account matches "X".')
    assert actions == ["account risk line: replaced"]
    assert panels[1]["items"] == ["The BOM is not included.", 'No Salesforce account matches "X".']
    assert opportunity.place_account_risk(plan, None) == ["account risk line: removed"]
    assert panels[1]["items"] == ["The BOM is not included."]
    assert opportunity.place_account_risk(plan, None) == []


def test_place_account_risk_adds_a_panel_when_the_plan_has_none():
    plan = sample_plan()
    plan["questions"][10]["slides"] = plan["questions"][10]["slides"][:1]
    opportunity.place_account_risk(plan, "line")
    added = plan["questions"][10]["slides"][-1]
    assert added == {"layout": "panel", "title": "Risk Detection",
                     "heading": "Document Risks", "items": ["line"]}
    assert opportunity.place_account_risk({"questions": []}, "line") == []


# --------------------------------------------------- applying the lookup
def test_account_match_is_current_compares_customer_and_cleaned_site():
    info = {"customer": "Acme", "customer_site": "Graz (inferred)"}
    assert opportunity.account_match_is_current(info, {"customer": "Acme", "customer_site": "Graz"})
    assert not opportunity.account_match_is_current(info, {"customer": "Acme", "customer_site": "Wien"})
    assert not opportunity.account_match_is_current(info, {"customer": "Other", "customer_site": "Graz"})
    assert not opportunity.account_match_is_current(info, None)
    assert opportunity.account_match_is_current(
        {"customer": "Acme", "customer_site": INFO_NOT_AVAILABLE},
        {"customer": "Acme", "customer_site": ""})


def test_apply_account_match_fills_or_resets_the_two_fields():
    analysis = sample_analysis()
    analysis["opportunity"]["account_name"] = "model guess"
    match = {"customer": analysis["opportunity"]["customer"], "customer_site": "",
             "account_name": "Northwind (Hamburg)", "kam_pte": ""}
    applied = opportunity.apply_account_match(analysis, match)
    assert applied["opportunity"]["account_name"] == "Northwind (Hamburg)"
    assert applied["opportunity"]["kam_pte"] == INFO_NOT_AVAILABLE
    assert analysis["opportunity"]["account_name"] == "model guess"      # a copy
    reset = opportunity.apply_account_match(analysis, None)
    assert reset["opportunity"]["account_name"] == INFO_NOT_AVAILABLE
    assert reset["opportunity"]["kam_pte"] == INFO_NOT_AVAILABLE


def test_display_name_prefers_the_opportunity_name():
    assert opportunity.display_name(sample_opportunity(), "folder") == "Northwind – V6 Engine Calibration"
    assert opportunity.display_name({"opportunity_name": INFO_NOT_AVAILABLE}, "folder") == "folder"
    assert opportunity.display_name(None, "folder") == "folder"


# ------------------------------------------------- build_opportunity_slide
def test_opportunity_slide_rows_follow_the_client_order():
    slide = opportunity.build_opportunity_slide(sample_opportunity())
    assert slide["layout"] == "opportunity" and slide["title"] == "Opportunity Info"
    assert slide["columns"] == ["Opportunity Info", "Definition according to RFQ"]
    assert [row[0] for row in slide["rows"]] == [
        "Customer", "Customer contact", "Quotation due date", "Opportunity name",
        "Account Name (Site)", "KAM (PTE)", "Project type", "Lead product",
        "Technology", "Industry"]
    assert slide["rows"] == [
        ["Customer", "Northwind Motors GmbH"],
        ["Customer contact", "Jane Doe, Purchasing, jane.doe@example.com"],
        ["Quotation due date", "20 October 2026"],
        ["Opportunity name", "Northwind – V6 Engine Calibration"],
        ["Account Name (Site)", INFO_NOT_AVAILABLE],
        ["KAM (PTE)", INFO_NOT_AVAILABLE],
        ["Project type", "SOP Project w/o CSM (up to SOP or partial SOP development)"],
        ["Lead product", "Spark Ignited"],
        ["Technology", "ICE & Mild Hybrid"],
        ["Industry", "Passenger Car"]]
    assert "customer_site" not in json.dumps(slide)


def test_opportunity_slide_sorts_products_and_skills_by_percent():
    info = sample_opportunity()
    info["products"] = [{"name": "Battery", "percent": 30},
                        {"name": "Spark Ignited", "percent": 60},
                        {"name": "Calibration", "percent": 10}]
    info["skills"] = [{"name": "Design", "percent": 20},
                      {"name": "Calibration", "percent": 20},
                      {"name": "Project Management", "percent": 60}]
    slide = opportunity.build_opportunity_slide(info)
    assert slide["products"] == [["Spark Ignited", "60%"], ["Battery", "30%"], ["Calibration", "10%"]]
    # Equal shares keep the Guidance (workbook) order: Design before Calibration.
    assert slide["skills"] == [["Project Management", "60%"], ["Design", "20%"], ["Calibration", "20%"]]


def test_opportunity_slide_cleans_multi_line_values_and_tags():
    info = sample_opportunity()
    info["customer_contact"] = "Jane Doe (inferred)\nMax Muster, Engineering\n"
    info["quotation_due_date"] = ""
    slide = opportunity.build_opportunity_slide(info)
    rows = dict(slide["rows"])
    assert rows["Customer contact"] == "Jane Doe; Max Muster, Engineering"
    assert rows["Quotation due date"] == INFO_NOT_AVAILABLE


def test_fill_opportunity_slide_replaces_the_placeholder():
    plan, analysis = sample_plan(), sample_analysis()
    assert opportunity.fill_opportunity_slide(plan, analysis) == [
        "opportunity: slide built from the analysis"]
    assert plan["questions"][0]["slides"] == [
        opportunity.build_opportunity_slide(analysis["opportunity"])]
    assert opportunity.fill_opportunity_slide(sample_plan(), {"answers": []}) == []
