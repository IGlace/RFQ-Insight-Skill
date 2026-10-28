import json
import os
from msgfile import build_msg
from test_extractors import _minimal_pdf
from rfq import corpus as co, delivery

def test_mail_and_attachments_enter_the_corpus(tmp_path):
    folder = tmp_path / "RFQ"; folder.mkdir()
    build_msg(str(folder / "cover.msg"), subject="RFQ", sender=("D", "d@x.invalid"), to=("A", "a@x.invalid"),
              body="See attachment.", attachments=[("Appendix B.pdf", _minimal_pdf(["Appendix B"])), ("x.xyz", b"?")])
    c, _ = co.run_extraction(str(folder), "P")
    names = [f["filename"] for f in c["filesContents"]]
    assert names == ["cover.msg", "cover.msg › Appendix B.pdf"]
    assert c["filesContents"][1]["attachment_of"] == "cover.msg"
    assert c["filesContents"][1]["sha256"] == c["filesContents"][0]["sha256"]
    # An attachment of a type the run does not read is passed over like a
    # loose file of that type: listed, never blocking.
    assert c["extraction"]["skipped"] == []
    assert c["extraction"]["ignored"] == ["cover.msg › x.xyz"]
    assert os.path.isfile(folder / "output" / ".work" / "mail" / "cover" / "Appendix B.pdf")

def test_source_material_marks_attachments_under_their_mail_in_the_plan():
    from rfq import planning
    c = {"filesContents": [{"filename": "cover.msg", "path": "cover.msg", "extracted_text": "From: x"},
                           {"filename": "cover.msg › Appendix_B.pdf", "path": "cover.msg › Appendix_B.pdf", "extracted_text": "--- Page 1 ---\nx"},
                           {"filename": "cover.msg › fwd.msg", "path": "cover.msg › fwd.msg", "extracted_text": "From: y"},
                           {"filename": "cover.msg › fwd.msg › X.pdf", "path": "cover.msg › fwd.msg › X.pdf", "extracted_text": "--- Page 1 ---\ny"}],
         "extraction": {"skipped": []}}
    sm = delivery.build_source_material(c, {"answers": []})
    # The marker must survive the plan's cell stripping, which an indent of
    # spaces does not: the deck table is built from these rows.
    [table] = planning.typed_from_markdown(sm, 12, {})
    assert [row[0] for row in table["rows"]] == [
        "cover.msg", "\u21b3 Appendix_B.pdf", "\u21b3 fwd.msg", "\u21b3 \u21b3 X.pdf"]


def _mail(path, attachments, subject="RFQ"):
    os.makedirs(os.path.dirname(str(path)), exist_ok=True)
    build_msg(str(path), subject=subject, sender=("D", "d@x.invalid"), to=("A", "a@x.invalid"),
              body="See attachment.", attachments=attachments)


def test_attachments_do_not_make_the_package_look_changed(tmp_path):
    folder = tmp_path / "RFQ"; folder.mkdir()
    _mail(folder / "cover.msg", [("Appendix B.pdf", _minimal_pdf(["Appendix B"]))])
    c, _ = co.run_extraction(str(folder), "P")
    assert co.corpus_changes(str(folder), c) == {"added": [], "removed": [], "changed": []}
    _mail(folder / "cover.msg", [("Appendix B.pdf", _minimal_pdf(["Appendix B"]))], subject="RFQ v2")
    assert co.corpus_changes(str(folder), c) == {"added": [], "removed": [], "changed": ["cover.msg"]}


def _png(color):
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.effect_noise((600, 400), 80).convert("RGB").save(buf, "PNG")
    return buf.getvalue()


def test_colliding_mail_slugs_keep_attachment_images_apart(tmp_path, monkeypatch):
    from rfq import extractors
    folder = tmp_path / "RFQ"; folder.mkdir()
    _mail(folder / "a_b.msg", [("one.png", _png(1)), ("two.png", _png(2))])
    _mail(folder / "a" / "b.msg", [("three.png", _png(3)), ("four.png", _png(4))])
    keys, real = [], extractors.extract_file
    monkeypatch.setattr(extractors, "extract_file",
                        lambda path, key="": (keys.append(key), real(path, key))[1])
    c, raw = co.build_corpus(str(folder), "P")
    # Two mails and four attachments: six extractions, six identities.
    assert len(keys) == 6 and len(set(keys)) == 6
    ids = [r.image_id for r in raw]
    assert len(ids) == 4 and len(set(ids)) == 4


def test_unpack_folders_are_unique_and_cleared_on_rerun(tmp_path):
    folder = tmp_path / "RFQ"; folder.mkdir()
    pdf = _minimal_pdf(["x"])
    _mail(folder / "a_b.msg", [("p.pdf", pdf)])
    _mail(folder / "a_b_2.msg", [("p.pdf", pdf)])
    _mail(folder / "a" / "b.msg", [("p.pdf", pdf)])
    co.build_corpus(str(folder), "P")
    mail = folder / "output" / ".work" / "mail"
    dirs = sorted(d.name for d in mail.iterdir())
    assert len(dirs) == 3 and all((mail / d / "p.pdf").is_file() for d in dirs)
    # A rewritten mail leaves none of its old attachments behind.
    _mail(folder / "a_b.msg", [("q.pdf", pdf)])
    co.build_corpus(str(folder), "P")
    assert not (mail / "a_b" / "p.pdf").exists() and (mail / "a_b" / "q.pdf").is_file()


def test_a_mail_attached_as_a_file_is_read_one_level_deep(tmp_path):
    folder = tmp_path / "RFQ"; folder.mkdir()
    inner = tmp_path / "inner.msg"
    _mail(inner, [("Spec.pdf", _minimal_pdf(["Inner spec"]))], subject="Inner")
    _mail(folder / "cover.msg", [("fwd.msg", inner.read_bytes())])
    c, _ = co.build_corpus(str(folder), "P")
    assert [f["filename"] for f in c["filesContents"]] == [
        "cover.msg", "cover.msg › fwd.msg", "cover.msg › fwd.msg › Spec.pdf"]
    assert c["extraction"]["skipped"] == [] and c["extraction"]["ignored"] == []


def _pipeline_extract(folder, monkeypatch, tmp_path):
    from rfq import pipeline
    monkeypatch.setenv("RFQ_INSIGHT_HOME", str(tmp_path / "home"))
    return pipeline.advance(str(folder), "claude", until="extract")


def test_an_unsupported_attachment_does_not_block_the_run(tmp_path, monkeypatch):
    folder = tmp_path / "RFQ"; folder.mkdir()
    _mail(folder / "cover.msg", [("Spec.pdf", _minimal_pdf(["Scope"])),
                                 ("CAD_data.zip", b"PK\x03\x04junk"),
                                 ("housing.stp", b"ISO-10303-21;")])
    (folder / "loose.txt").write_text("Loose note", encoding="utf-8")
    assert _pipeline_extract(folder, monkeypatch, tmp_path) == {"status": "stopped", "stage": "extract"}
    c = json.loads((folder / "output" / ".work" / "corpus.json").read_text(encoding="utf-8"))
    assert c["extraction"]["skipped"] == []
    assert c["extraction"]["ignored"] == ["cover.msg › CAD_data.zip", "cover.msg › housing.stp"]
    lines = delivery.build_source_material(c, {"answers": []})["answer"].splitlines()[2:]
    rows = [[cell.strip() for cell in line.split("|")[1:-1]] for line in lines]
    assert [r[0] for r in rows] == ["cover.msg", "↳ Spec.pdf", "↳ CAD_data.zip",
                                    "↳ housing.stp", "loose.txt"]
    assert rows[2][1:3] == ["ZIP", "not read: unsupported file type"]
    # A resumed run does not read the folder again for an ignored attachment.
    assert _pipeline_extract(folder, monkeypatch, tmp_path) == {"status": "stopped", "stage": "extract"}


def test_a_forwarded_mail_and_its_pdf_reach_the_corpus(tmp_path):
    folder = tmp_path / "RFQ"; folder.mkdir()
    fwd = dict(subject="Original RFQ", sender=("E", "e@x.invalid"), to=("A", "a@x.invalid"),
               body="Inner note", attachments=[("Inner Spec.pdf", _minimal_pdf(["Inner scope"]))])
    _mail(folder / "cover.msg", [("Spec.pdf", _minimal_pdf(["Scope"])), ("Original RFQ", fwd)])
    c, _ = co.build_corpus(str(folder), "P")
    files = {f["filename"]: f for f in c["filesContents"]}
    assert list(files) == ["cover.msg", "cover.msg › Spec.pdf", "cover.msg › Original RFQ.msg",
                           "cover.msg › Original RFQ.msg › Inner Spec.pdf"]
    assert "Subject: Original RFQ" in files["cover.msg › Original RFQ.msg"]["extracted_text"]
    assert "Inner scope" in files["cover.msg › Original RFQ.msg › Inner Spec.pdf"]["extracted_text"]
    top = files["cover.msg"]["sha256"]
    assert all(f["sha256"] == top for f in files.values())
    assert files["cover.msg › Original RFQ.msg"]["attachment_of"] == "cover.msg"
    assert files["cover.msg › Original RFQ.msg › Inner Spec.pdf"]["attachment_of"] == \
        "cover.msg › Original RFQ.msg"
    assert files["cover.msg › Original RFQ.msg › Inner Spec.pdf"]["path"] == \
        "cover.msg › Original RFQ.msg › Inner Spec.pdf"
    assert c["extraction"]["skipped"] == [] and c["extraction"]["ignored"] == []
    assert co.corpus_changes(str(folder), c) == {"added": [], "removed": [], "changed": []}
    rows = [line.split("|")[1].strip() for line in
            delivery.build_source_material(c, {"answers": []})["answer"].splitlines()[2:]]
    assert rows == ["cover.msg", "↳ Spec.pdf", "↳ Original RFQ.msg", "↳ ↳ Inner Spec.pdf"]


def test_a_mail_nested_two_levels_deep_is_ignored(tmp_path):
    folder = tmp_path / "RFQ"; folder.mkdir()
    deep = dict(subject="Deep", sender=("F", "f@x.invalid"), to=("A", "a@x.invalid"), body="deep")
    fwd = dict(subject="Fwd", sender=("E", "e@x.invalid"), to=("A", "a@x.invalid"), body="fwd",
               attachments=[("deep", deep), ("drawing.dwg", b"AC1027")])
    _mail(folder / "cover.msg", [("fwd", fwd)])
    c, _ = co.build_corpus(str(folder), "P")
    assert [f["filename"] for f in c["filesContents"]] == ["cover.msg", "cover.msg › fwd.msg"]
    assert c["extraction"]["skipped"] == []
    assert c["extraction"]["ignored"] == ["cover.msg › fwd.msg › deep.msg",
                                          "cover.msg › fwd.msg › drawing.dwg"]
    rows = [[cell.strip() for cell in line.split("|")[1:-1]] for line in
            delivery.build_source_material(c, {"answers": []})["answer"].splitlines()[2:]]
    assert [r[0] for r in rows] == ["cover.msg", "↳ fwd.msg", "↳ ↳ deep.msg", "↳ ↳ drawing.dwg"]
    assert rows[2][1:3] == ["E-mail", "not read: nested e-mail"]


def test_a_broken_attachment_is_ignored_and_the_mail_is_still_read(tmp_path):
    from msgfile import build_msg
    folder = tmp_path / "RFQ"; folder.mkdir()
    build_msg(str(folder / "cover.msg"), subject="RFQ", sender=("D", "d@x.invalid"),
              to=("A", "a@x.invalid"), body="Body survives.",
              attachments=[("Spec.pdf", _minimal_pdf(["Scope"]))], broken=["gone.msg"])
    c, _ = co.build_corpus(str(folder), "P")
    assert [f["filename"] for f in c["filesContents"]] == ["cover.msg", "cover.msg › Spec.pdf"]
    assert "Body survives." in c["filesContents"][0]["extracted_text"]
    assert c["extraction"]["skipped"] == []
    assert c["extraction"]["ignored"] == ["cover.msg › (attachment could not be read)"]


def test_a_corrupt_supported_attachment_still_blocks(tmp_path):
    folder = tmp_path / "RFQ"; folder.mkdir()
    _mail(folder / "cover.msg", [("Spec.pdf", b"%PDF-1.4 broken")])
    c, _ = co.build_corpus(str(folder), "P")
    assert [s["filename"] for s in c["extraction"]["skipped"]] == ["cover.msg › Spec.pdf"]


def test_skipped_attachments_sit_under_their_mail_in_source_material():
    c = {"filesContents": [
            {"filename": "a.msg", "path": "a.msg", "extracted_text": "From: x"},
            {"filename": "a.msg › P.pdf", "path": "a.msg › P.pdf", "extracted_text": "--- Page 1 ---\nx"},
            {"filename": "b.msg", "path": "b.msg", "extracted_text": "From: y"}],
         "extraction": {"skipped": [
            {"filename": "a.msg › Q.pdf", "path": "a.msg › Q.pdf", "reason": "it is damaged"},
            {"filename": "z.docx", "path": "z.docx", "reason": "it is damaged"}],
            "ignored": ["a.msg › x.xyz", "y.xyz"]}}
    lines = delivery.build_source_material(c, {"answers": []})["answer"].splitlines()[2:]
    firsts = [l.split("|")[1].strip() for l in lines]
    assert firsts == ["a.msg", "\u21b3 P.pdf", "\u21b3 Q.pdf", "\u21b3 x.xyz", "b.msg", "z.docx"]
    assert "| E-mail |" in lines[0]
    assert "| skipped: it is damaged |" in lines[2]
    assert "| not read: unsupported file type |" in lines[3]


def test_an_unreadable_forwarded_mail_is_listed_and_does_not_block(tmp_path, monkeypatch):
    folder = tmp_path / "RFQ"; folder.mkdir()
    _mail(folder / "cover.msg", [("Spec.pdf", _minimal_pdf(["Scope"])),
                                 ("Fwd.msg", b"not an Outlook message at all")])
    assert _pipeline_extract(folder, monkeypatch, tmp_path) == {"status": "stopped", "stage": "extract"}
    c = json.loads((folder / "output" / ".work" / "corpus.json").read_text(encoding="utf-8"))
    assert [f["filename"] for f in c["filesContents"]] == ["cover.msg", "cover.msg › Spec.pdf"]
    assert c["extraction"]["skipped"] == []
    assert c["extraction"]["ignored"] == ["cover.msg › Fwd.msg (could not be read)"]
    rows = [[cell.strip() for cell in line.split("|")[1:-1]] for line in
            delivery.build_source_material(c, {"answers": []})["answer"].splitlines()[2:]]
    assert [r[0] for r in rows] == ["cover.msg", "↳ Spec.pdf", "↳ Fwd.msg"]
    assert rows[2][1:3] == ["E-mail", "not read: e-mail could not be read"]
    # A mail nested too deep keeps its own reason.
    assert delivery._not_read_reason("cover.msg › fwd.msg › deep.msg") == "nested e-mail"
