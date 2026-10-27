from rfq import language
from rfq.followups import check_followup_answer


def test_german_prose_is_detected_and_english_is_not():
    assert language.foreign_share("Die Entwicklung der Komponenten ist nicht im Umfang und wird vom Kunden gestellt") > 0.25
    assert language.foreign_share("The customer will provide prototype hardware for the mule build in April") < 0.1


def test_bracketed_originals_and_designations_do_not_count():
    text = "Concept Freeze (Konzept-Freeze) follows VW 80000 and Werksnorm 123 in the Lastenheft (Lastenheft)"
    assert language.foreign_share(text) < 0.25


def test_short_fields_are_ignored():
    assert language.foreign_share("nicht verfügbar") == 0.0


def test_check_analysis_names_the_section():
    bad = {"answers": [{"id": 4, "answer": "| Application | Configuration |\n|---|---|\n| Fahrzeugprojekte im Rahmen ihrer Plattform und Baukastenausprägung | batterieelektrische Fahrzeuge |",
                        "deductions": [], "sources": []}]}
    problems = language.check_analysis(bad)
    assert problems and problems[0].startswith("Section 4: not English:")
    good = {"answers": [{"id": 4, "answer": "| Application | Configuration |\n|---|---|\n| Vehicle projects within the platform | battery-electric vehicles |", "deductions": [], "sources": []}]}
    assert language.check_analysis(good) == []


def test_fields_split_cells_paragraphs_and_items():
    text = "Intro line.\n\n| A | B |\n|---|:--:|\n| x | y |\n\n- first item\n- second item"
    assert language.fields(text) == ["Intro line.", "A", "B", "x", "y",
                                     "first item", "second item"]


def test_check_analysis_reads_deductions_and_caps_problems():
    german = "Die Entwicklung der Komponenten ist nicht im Umfang und wird vom Kunden gestellt"
    analysis = {"answers": [{"id": 2, "answer": "Fine English answer here.",
                             "deductions": [{"rule": "V3", "items": german, "basis": german}]}]}
    problems = language.check_analysis(analysis)
    assert len(problems) == 2 and all(p.startswith("Section 2: not English:") for p in problems)
    many = {"answers": [{"id": 1, "answer": "\n\n".join([german] * 30), "deductions": []}]}
    assert len(language.check_analysis(many)) == 10


def test_followup_answer_in_german_is_a_problem():
    german = "Die Entwicklung der Komponenten ist nicht im Umfang und wird vom Kunden gestellt"
    answer = {"id": 3, "answer": german, "sources": [], "not_found": False}
    problems = check_followup_answer(answer, {"filesContents": []}, 3)
    assert any(p.startswith("Follow-up: not English:") for p in problems)
    answer["answer"] = "The customer will provide prototype hardware for the mule build in April"
    assert not any("not English" in p for p in check_followup_answer(answer, {"filesContents": []}, 3))


def test_romance_sentences_with_short_articles_and_elisions_are_detected():
    sentences = [
        "Le fournisseur doit livrer les bancs d'essai avant la fin de l'année pour le client",
        "Le développement du logiciel est à la charge du fournisseur selon le cahier des charges",
        "Il fornitore deve consegnare i banchi prova entro la fine dell'anno al cliente",
        "Lo sviluppo del software è a carico del fornitore secondo il capitolato tecnico",
        "El proveedor debe entregar los bancos de prueba antes del final del año al cliente",
        "El desarrollo del software corre a cargo del proveedor según el pliego de condiciones",
    ]
    for sentence in sentences:
        assert language.foreign_share(sentence) > 0.25, sentence
    assert language.foreign_share(
        "The customer will provide the base engine, the die-cast housing and all test "
        "benches at its Graz site; AVL delivers the calibration dataset in Q3 2027") == 0.0


def test_file_names_are_not_prose():
    basis = "Lastenheft_für_die_Entwicklung_des_Batteriemanagementsystems_V2.3.pdf, Kapitel 4"
    assert language.foreign_share(basis) == 0.0
    analysis = {"answers": [{"id": 3, "answer": "Fine English answer here.",
                             "deductions": [{"rule": "V2", "items": "die", "basis": basis}]}]}
    assert language.check_analysis(analysis) == []
    assert language.foreign_share("See Anforderungen_an_die_Software_und_das_Steuergerät.docx section 3") == 0.0


def test_english_abbreviations_and_acronyms_do_not_count():
    assert language.foreign_share("Est. effort 120 h; est. cost covered by customer, est. start in May") <= 0.25
    assert language.foreign_share("MIT licence components and ALS sensor, AUS market variant only") <= 0.25


def test_words_that_are_also_english_are_not_function_words():
    for word in ("die", "para", "come", "con", "son", "hay", "sans", "tout"):
        assert not language.is_function_word(word), word
    assert language.foreign_share("Die casting tools come with a son set and hay test con rods") == 0.0
