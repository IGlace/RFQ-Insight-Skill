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
    assert names == ["cover.msg", "cover.msg › Appendix_B.pdf"]
    assert c["filesContents"][1]["attachment_of"] == "cover.msg"
    assert c["filesContents"][1]["sha256"] == c["filesContents"][0]["sha256"]
    assert [s["reason"] for s in c["extraction"]["skipped"]] == ["unsupported file type"]
    assert os.path.isfile(folder / "output" / ".work" / "mail" / "cover" / "Appendix_B.pdf")

def test_source_material_indents_attachments_under_their_mail():
    c = {"filesContents": [{"filename": "cover.msg", "path": "cover.msg", "extracted_text": "From: x"},
                           {"filename": "cover.msg › Appendix_B.pdf", "path": "cover.msg › Appendix_B.pdf", "extracted_text": "--- Page 1 ---\nx"}],
         "extraction": {"skipped": []}}
    rows = delivery.build_source_material(c, {"answers": []})["answer"]
    assert "| cover.msg |" in rows and "|   Appendix_B.pdf |" in rows


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


def test_an_attached_mail_is_skipped_as_nested(tmp_path):
    folder = tmp_path / "RFQ"; folder.mkdir()
    inner = tmp_path / "inner.msg"
    _mail(inner, [])
    _mail(folder / "cover.msg", [("fwd.msg", inner.read_bytes())])
    c, _ = co.build_corpus(str(folder), "P")
    assert [f["filename"] for f in c["filesContents"]] == ["cover.msg"]
    assert [s["reason"] for s in c["extraction"]["skipped"]] == ["nested e-mail"]


def test_skipped_attachments_sit_under_their_mail_in_source_material():
    c = {"filesContents": [
            {"filename": "a.msg", "path": "a.msg", "extracted_text": "From: x"},
            {"filename": "a.msg › P.pdf", "path": "a.msg › P.pdf", "extracted_text": "--- Page 1 ---\nx"},
            {"filename": "b.msg", "path": "b.msg", "extracted_text": "From: y"}],
         "extraction": {"skipped": [
            {"filename": "a.msg › x.xyz", "path": "a.msg › x.xyz", "reason": "unsupported file type"},
            {"filename": "z.docx", "path": "z.docx", "reason": "it is damaged"}]}}
    lines = delivery.build_source_material(c, {"answers": []})["answer"].splitlines()[2:]
    firsts = [l.split("|")[1].rstrip() for l in lines]
    assert firsts == [" a.msg", "   P.pdf", "   x.xyz", " b.msg", " z.docx"]
    assert "| E-mail |" in lines[0]
