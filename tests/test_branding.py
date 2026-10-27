import json, os
from rfq import branding

def test_long_date_is_day_month_year():
    assert branding.long_date("2026-10-23") == "23 October 2026"
    assert branding.long_date("junk") == "junk"

def test_identity_order_argument_env_config_fallback(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps({"author": "C. Config", "department": "LBP"}))
    env = {"RFQ_INSIGHT_AUTHOR": "E. Env"}
    got = branding.resolve_identity(None, None, env=env, home=str(tmp_path))
    assert got == {"author": "E. Env", "department": "LBP", "fallback": False}
    got = branding.resolve_identity("A. Arg", None, env=env, home=str(tmp_path))
    assert got["author"] == "A. Arg"
    got = branding.resolve_identity(None, None, env={}, home=str(tmp_path / "missing"))
    assert got["department"] == "RFQ Insight" and got["fallback"] is True and got["author"]

def test_footer_text_matches_the_master_shape():
    assert branding.footer_text("K. Petinger", "LBP", "2026-10-23") == "K. Petinger | LBP | 23 October 2026 |"

def test_set_footer_writes_the_master_box():
    prs = branding.load_template()
    branding.set_footer(prs, "K. Petinger", "LBP", "2026-10-23")
    box = next(s for s in prs.slide_masters[0].shapes if s.name == "footer_ProjectInfo")
    assert box.text_frame.text == "K. Petinger | LBP | 23 October 2026 |"
    assert box.text_frame.paragraphs[0].runs[0].font.name == "Verdana"
