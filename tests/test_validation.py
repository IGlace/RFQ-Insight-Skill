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


P5_CORPUS = ("Der Lieferant liefert. Die Konzeptphase endet mit dem Konzept-Freeze. "
             "Kunde: Cedar AG. Projekt 2026. Partner: Müller GmbH.")


def _parties(*names):
    rows = "".join(f"| {n} | supplier | builds |\n" for n in names)
    return {"answer": "| Party | Type | Role |\n|---|---|---|\n" + rows}


def test_a_degenerate_bracketed_original_does_not_make_a_party_faithful():
    names = ["Phantom Systems GmbH (Lieferant)", "Ghost Corp (2026)", "Ghost Two (Der)",
             "Ghost Three (Der Lieferant)", "Mueller Ltd (Müller GmbH)"]
    missed = [name for name, _ in v._party_names(_parties(*names), P5_CORPUS, "Cedar")]
    assert missed == names[:4]


def test_a_degenerate_bracketed_original_does_not_make_a_phase_faithful():
    corpus_norm = v._norm(P5_CORPUS)
    assert v._phase_ok("Concept Freeze (Konzept-Freeze)", corpus_norm)
    for name in ["Invented Phase (Die)", "Invented Phase (2026)", "Invented Phase (dem)",
                 "Invented Phase (endet mit)", "Invented Phase (Konzeptpha)"]:
        assert not v._phase_ok(name, corpus_norm), name


def test_function_words_are_exposed_for_the_faithfulness_gate():
    from rfq import language
    assert language.is_function_word("Der") and language.is_function_word("mit")
    assert not language.is_function_word("Lieferant") and not language.is_function_word("Freeze")


def test_a_party_original_made_only_of_role_words_is_not_a_name():
    assert not v._name_like("Sous-traitant", party=True)
    assert not v._name_like("Lieferant", party=True)
    assert v._name_like("Lieferant", party=False)
    assert v._name_like("Kraftfahrt-Bundesamt", party=True)
