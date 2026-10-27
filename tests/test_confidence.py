from rfq import confidence
from rfq.schema import RULES


def test_labels_are_plain_english():
    assert RULES["S8.1"].label == "{count} deliverable(s) implied by the scope but not listed in the RFQ"
    assert RULES["G3"].label == "{count} item(s) not stated in the RFQ, inferred from context"
    assert RULES["V1"].label == "contradicted by the independent check"
    assert RULES["V3"].label == "not found in the documents"
    for rule in RULES.values():
        assert "entailed" not in rule.label and "RASIC" not in rule.label


def test_deduction_line_carries_no_code():
    line = confidence.deduction_line(1, "S8.1", 8, "Result reports", "SOW 4.2")
    assert line == "8 deliverables implied by the scope but not listed in the RFQ: Result reports (SOW 4.2)"
    assert confidence.deduction_line(1, "G3", 1) == "1 item not stated in the RFQ, inferred from context"


def test_unscored_strips_codes_from_replayed_notes():
    old = "Confidence 6/10 (Medium)\n-2  S7.1  4 cells placed by inference: PM\nG3  1 inferred item: x"
    assert confidence.unscored(old) == "Confidence: Medium\n4 cells placed by inference: PM\n1 inferred item: x"
