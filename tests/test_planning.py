from rfq import planning


def _parties(table_rows):
    segments = [("table", ["Party", "Type", "Role"], table_rows)]
    return planning._collaboration(segments, {}, [])[0]["parties"]


def test_whole_role_inferred_moves_the_tag_to_the_name():
    [p] = _parties([["AVL", "avl", "Engineering partner for module design (inferred)"]])
    assert p["name_inferred"] is True
    assert p["role"] == "Engineering partner for module design"
    assert "dashed" not in p


def test_partial_inference_keeps_the_tag_in_the_role():
    [p] = _parties([["AVL", "avl", "Design owner. Supplies test benches (inferred). Reports monthly."]])
    assert p["name_inferred"] is False
    assert "(inferred)" in p["role"]


def test_tag_in_the_party_cell_marks_the_name_and_leaves_it_untagged():
    [p] = _parties([["AVL (inferred)", "avl", "Engineering partner"]])
    assert p["name_inferred"] is True
    assert p["name"] == "AVL"
    assert p["role"] == "Engineering partner"


def test_sentence_boundary_before_a_trailing_tag_keeps_the_role():
    [p] = _parties([["AVL", "avl", "Design owner. Supplies test benches (inferred)"]])
    assert p["name_inferred"] is False
    assert p["role"] == "Design owner. Supplies test benches (inferred)"


def test_uninferred_party_is_plain():
    [p] = _parties([["AVL", "avl", "Engineering partner"]])
    assert p == {"name": "AVL", "role": "Engineering partner", "type": "avl",
                 "name_inferred": False}


def test_inferred_marker_survives_a_write_and_parse_round_trip():
    answer = {"answer": "Hub: NW\n\n| Party | Type | Role |\n| --- | --- | --- |\n"
                        "| Acme | supplier | Makes cells (inferred) |\n"
                        "| AVL | avl | Design owner. Supplies benches (inferred). Reports monthly. |"}
    first = planning.typed_from_markdown(answer, planning.COLLABORATION, {})
    [slide] = first
    assert [p["name_inferred"] for p in slide["parties"]] == [True, False]
    written = planning._typed_answer_block(slide)
    second = planning.typed_from_markdown({"answer": written}, planning.COLLABORATION, {})
    assert second == first
    acme = second[0]["parties"][0]
    assert (acme["name"], acme["role"]) == ("Acme", "Makes cells")
    assert acme["name_inferred"] is True
