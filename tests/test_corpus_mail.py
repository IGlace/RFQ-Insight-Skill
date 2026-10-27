import json, os
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
