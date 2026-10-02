"""The corpus the model actually reads, in the format the prompts describe.

The prompts do not merely prefer the `=== FILE: <name> ===` shape - they
instruct the model to navigate by it and to copy `evidence_files` names out
of it. Anything that changes it changes what the model is told.
"""

import json
import os
import re

import corpus_text as ct

SKILL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "plugins", "rfq-insight", "skills", "rfq-insight")
PROMPTS = os.path.join(SKILL, "references", "prompts")


def _files():
    return [
        {"filename": "SOR.docx", "extension": "docx", "path": "SOR.docx",
         "extracted_text": "The system shall deliver 450 Nm."},
        {"filename": "Annex A.pdf", "extension": "pdf",
         "path": os.path.join("annexes", "Annex A.pdf"),
         "extracted_text": "Quotation due 20.06.2026"},
    ]


def _corpus_folder(tmp_path, files=None):
    work = tmp_path / "Acme V6" / "output" / ".work"
    work.mkdir(parents=True)
    with open(work / "corpus.json", "w", encoding="utf-8") as fh:
        json.dump({"projectName": "Acme V6",
                   "filesContents": files if files is not None else _files()},
                  fh)
    return str(tmp_path / "Acme V6")


def test_each_file_becomes_a_delimited_block():
    text = ct.format_corpus(_files())
    assert "=== FILE: SOR.docx ===" in text
    assert "=== FILE: Annex A.pdf ===" in text
    assert "(type: docx; path: SOR.docx)" in text
    assert "The system shall deliver 450 Nm." in text
    assert "Quotation due 20.06.2026" in text


def test_the_header_matches_the_contract_the_prompt_states():
    """v12 line 30 tells the model the delimiter is a LINE of the form
    `=== FILE: <name> ===`, and line 101 says evidence_files names are
    copied exactly from it. A header that does not parse that way makes
    both instructions unfollowable."""
    text = ct.format_corpus(_files())
    headers = re.findall(r"(?m)^=== FILE: (.+) ===$", text)
    assert headers == ["SOR.docx", "Annex A.pdf"]
    assert headers == [f["filename"] for f in _files()]


def test_the_block_order_and_shape_are_exactly_the_container_app_s():
    """Ported verbatim from RFQ_Container_App pipeline._format_corpus:
    header line, meta line, then the text - blocks joined by a blank line."""
    text = ct.format_corpus(_files())
    assert text == (
        "=== FILE: SOR.docx ===\n"
        "(type: docx; path: SOR.docx)\n"
        "The system shall deliver 450 Nm.\n"
        "\n"
        "=== FILE: Annex A.pdf ===\n"
        f"(type: pdf; path: {os.path.join('annexes', 'Annex A.pdf')})\n"
        "Quotation due 20.06.2026")


def test_the_prompts_still_describe_the_format_this_script_emits():
    """The regression guard that matters: if someone edits the delimiter
    here or there, these two stop agreeing."""
    with open(os.path.join(PROMPTS, "RFQ_QA_Extraction_Prompt_v12.md"),
              encoding="utf-8") as fh:
        prompt = fh.read()
    sample = ct.format_corpus([{"filename": "SOR.docx", "extension": "docx",
                                "path": "SOR.docx", "extracted_text": "x"}])
    assert "=== FILE: <name> ===" in prompt
    assert sample.startswith("=== FILE: ")
    assert sample.splitlines()[0].endswith(" ===")


def test_an_empty_corpus_is_an_empty_string():
    assert ct.format_corpus([]) == ""


def test_cli_prints_the_blocks(tmp_path, capsys):
    folder = _corpus_folder(tmp_path)
    assert ct.main([folder]) == 0
    out = capsys.readouterr().out
    assert "=== FILE: SOR.docx ===" in out
    assert "The system shall deliver 450 Nm." in out


def test_cli_writes_a_file_when_asked(tmp_path):
    folder = _corpus_folder(tmp_path)
    out_path = str(tmp_path / "out" / "corpus.txt")
    assert ct.main([folder, "--out", out_path]) == 0
    with open(out_path, encoding="utf-8") as fh:
        assert fh.read() == ct.format_corpus(_files())


def test_cli_says_so_in_plain_language_when_there_is_no_corpus(tmp_path, capsys):
    folder = tmp_path / "Acme V6"
    folder.mkdir()
    assert ct.main([str(folder)]) == 2
    err = capsys.readouterr().err
    assert "corpus.json" not in err
    assert "Traceback" not in err


def test_a_merged_transcription_travels_inside_its_parent_block():
    """The reason evidence_files can still name the parent file: the
    picture's text lives in that file's extracted_text, so it lands inside
    that file's === FILE: === block."""
    files = [{"filename": "SOR.docx", "extension": "docx", "path": "SOR.docx",
              "extracted_text": "Intro.\n\n[BEGIN IMAGE TRANSCRIPTION "
                                "SOR.docx__img01]\nSOP Q3 2027.\n"
                                "[END IMAGE TRANSCRIPTION]"},
             {"filename": "Notes.txt", "extension": "txt", "path": "Notes.txt",
              "extracted_text": "Unrelated."}]
    text = ct.format_corpus(files)
    sor_block = text.split("=== FILE: Notes.txt ===")[0]
    assert "SOP Q3 2027." in sor_block


def test_long_lines_are_wrapped_below_the_file_reader_limit_without_losing_text():
    long_paragraph = " ".join(f"word{i}" for i in range(900))
    wide_row = "| " + " | ".join(["cell content " * 20] * 12) + " |"
    files = [{"filename": "SOR.docx", "extension": "docx", "path": "SOR.docx",
              "extracted_text": long_paragraph + "\n\n" + wide_row}]
    text = ct.format_corpus(files)
    assert max(len(line) for line in text.splitlines()) <= ct.MAX_LINE_CHARS
    # Only line breaks were added: joining on whitespace restores every token.
    assert " ".join(text.split()) == " ".join(
        ("=== FILE: SOR.docx === (type: docx; path: SOR.docx) "
         + long_paragraph + " " + wide_row).split())


def test_short_lines_are_untouched_by_wrapping():
    body = "short line\n| a | b |\n\nanother"
    assert ct.soft_wrap(body) == body


def test_a_single_overlong_token_is_still_cut_rather_than_kept_whole():
    assert max(len(l) for l in ct.soft_wrap("x" * 4000).splitlines()) <= ct.MAX_LINE_CHARS
