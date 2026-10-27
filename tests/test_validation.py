from rfq import validation as v

CORPUS = {"filesContents": [{"filename": "sow.txt", "extracted_text": "Phase Konzept-Freeze ends in Q2. Partner: Müller GmbH."}]}


def _answer(section, text):
    return {"answers": [{"id": section, "answer": text, "not_found": False, "shown": None, "deductions": [], "sources": []}]}


def test_phase_name_with_bracketed_original_is_faithful():
    table = "| Phase | Definition | Scope | Hardware milestone | Span |\n|---|---|---|---|---|\n| Concept Freeze (Konzept-Freeze) | x | in scope | | |"
    assert v.faithfulness_misses(_answer(6, table), CORPUS).get(6, []) == []


def test_phase_name_without_corpus_support_still_misses():
    table = "| Phase | Definition | Scope | Hardware milestone | Span |\n|---|---|---|---|---|\n| Concept Freeze (Konzeptfreigabe) | x | in scope | | |"
    assert v.faithfulness_misses(_answer(6, table), CORPUS)[6] == ["Concept Freeze (Konzeptfreigabe)"]


def test_party_name_with_bracketed_original_is_faithful():
    table = "| Party | Type | Role |\n|---|---|---|\n| Mueller Ltd (Müller GmbH) | supplier | parts |"
    assert v.faithfulness_misses(_answer(5, table), CORPUS).get(5, []) == []


def test_party_name_without_corpus_support_still_misses():
    table = "| Party | Type | Role |\n|---|---|---|\n| Mueller Ltd (Meier AG) | supplier | parts |"
    assert v.faithfulness_misses(_answer(5, table), CORPUS)[5] == ["Mueller Ltd (Meier AG)"]


def test_with_original_splits_the_last_bracket_group():
    assert v._with_original("Concept Freeze (Konzept-Freeze)") == ("Concept Freeze", "Konzept-Freeze")
    assert v._with_original("Gate (A) (Tor A)") == ("Gate (A)", "Tor A")
    assert v._with_original("Concept Freeze") == ("Concept Freeze", None)


def test_with_original_never_treats_inferred_as_an_original():
    assert v._with_original("Concept Freeze (inferred)") == ("Concept Freeze (inferred)", None)
    assert v._with_original("Concept Freeze (Inferred)") == ("Concept Freeze (Inferred)", None)
