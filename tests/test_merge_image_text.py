"""Transcriptions go back exactly where the picture was."""

import json
import os

import merge_image_text as mit
from rfq.extractors import marker_for


def _work(tmp_path):
    work = tmp_path / "output" / ".work"
    (work / "image_text").mkdir(parents=True)
    return str(work)


def _corpus(text, filename="SOR.docx"):
    return {"projectName": "Demo", "oppId": "",
            "filesContents": [{"filename": filename, "extension": "docx",
                               "path": filename, "extracted_text": text}],
            "extraction": {"parsed": 1, "chars": len(text), "skipped": [],
                           "ignored": [], "images_flagged": [],
                           "images_filtered": [], "preprocess": {}}}


def _manifest(entries):
    return {"images": entries, "filtered": []}


def test_embedded_transcription_replaces_the_marker_in_place(tmp_path):
    work = _work(tmp_path)
    marker = marker_for("SOR.docx__img01")
    corpus = _corpus(f"Before the chart.\n\n{marker}\n\nAfter the chart.")
    manifest = _manifest([{"id": "SOR.docx__img01", "file": "x.png",
                           "source": "SOR.docx", "locator": "paragraph 4",
                           "kind": "embedded"}])

    merged = mit.merge(corpus, manifest,
                       {"SOR.docx__img01": "Gantt: SOP Q3 2027."})
    text = merged["filesContents"][0]["extracted_text"]

    assert marker not in text
    assert "Gantt: SOP Q3 2027." in text
    assert text.index("Before the chart.") < text.index("Gantt: SOP Q3 2027.")
    assert text.index("Gantt: SOP Q3 2027.") < text.index("After the chart.")
    assert merged["extraction"]["images_merged"] == ["SOR.docx__img01"]


def test_standalone_transcription_becomes_the_file_text(tmp_path):
    corpus = _corpus("", filename="timing_chart.png")
    corpus["filesContents"][0]["extension"] = "png"
    manifest = _manifest([{"id": "timing_chart.png__img01",
                           "file": "timing_chart.png__img01.png",
                           "source": "timing_chart.png",
                           "locator": "standalone", "kind": "standalone"}])

    merged = mit.merge(corpus, manifest,
                       {"timing_chart.png__img01": "Milestones: SOP Q3 2027."})
    assert "SOP Q3 2027." in merged["filesContents"][0]["extracted_text"]


def test_missing_transcription_leaves_an_honest_note(tmp_path):
    marker = marker_for("SOR.docx__img01")
    corpus = _corpus(f"Text.\n\n{marker}")
    manifest = _manifest([{"id": "SOR.docx__img01", "file": "x.png",
                           "source": "SOR.docx", "locator": "page 2",
                           "kind": "embedded"}])

    merged = mit.merge(corpus, manifest, {})
    text = merged["filesContents"][0]["extracted_text"]
    assert marker not in text
    assert "could not be read" in text
    assert merged["extraction"]["images_unread"] == ["SOR.docx__img01"]


def test_transcription_is_cleaned_like_any_extracted_text(tmp_path):
    marker = marker_for("SOR.docx__img01")
    corpus = _corpus(marker)
    manifest = _manifest([{"id": "SOR.docx__img01", "file": "x.png",
                           "source": "SOR.docx", "locator": "page 9",
                           "kind": "embedded"}])
    merged = mit.merge(corpus, manifest,
                       {"SOR.docx__img01": "Chart title\nPage 9 of 40\n25"})
    text = merged["filesContents"][0]["extracted_text"]
    assert "Chart title" in text
    assert "Page 9 of 40" not in text


def test_merging_twice_changes_nothing(tmp_path):
    marker = marker_for("SOR.docx__img01")
    corpus = _corpus(f"A\n\n{marker}\n\nB")
    manifest = _manifest([{"id": "SOR.docx__img01", "file": "x.png",
                           "source": "SOR.docx", "locator": "page 1",
                           "kind": "embedded"}])
    once = mit.merge(corpus, manifest, {"SOR.docx__img01": "Chart."})
    first = once["filesContents"][0]["extracted_text"]
    twice = mit.merge(once, manifest, {"SOR.docx__img01": "Chart."})
    assert twice["filesContents"][0]["extracted_text"] == first


def test_char_count_is_refreshed(tmp_path):
    marker = marker_for("SOR.docx__img01")
    corpus = _corpus(marker)
    manifest = _manifest([{"id": "SOR.docx__img01", "file": "x.png",
                           "source": "SOR.docx", "locator": "page 1",
                           "kind": "embedded"}])
    merged = mit.merge(corpus, manifest, {"SOR.docx__img01": "A" * 500})
    assert merged["extraction"]["chars"] == len(
        merged["filesContents"][0]["extracted_text"])


def test_read_transcriptions_finds_the_saved_files(tmp_path):
    work = _work(tmp_path)
    with open(mit.transcription_path(work, "SOR.docx__img01"), "w",
              encoding="utf-8") as fh:
        fh.write("  Gantt chart.  ")
    manifest = _manifest([
        {"id": "SOR.docx__img01", "file": "a.png", "source": "SOR.docx",
         "locator": "page 1", "kind": "embedded"},
        {"id": "SOR.docx__img02", "file": "b.png", "source": "SOR.docx",
         "locator": "page 2", "kind": "embedded"}])

    found, missing = mit.read_transcriptions(work, manifest)
    assert found == {"SOR.docx__img01": "Gantt chart."}
    assert missing == ["SOR.docx__img02"]


def test_each_of_two_same_named_files_gets_its_own_transcription():
    """annexes/Spec.pdf and attachments/Spec.pdf share a basename, and the
    corpus keys on basename. BOTH hold a picture - that is the case where
    getting it wrong puts one document's chart into the other, with full
    authority as corpus text and no warning.

    Resolving by marker is what keeps them apart, and the marker only
    separates them because the image id is built from the corpus-unique
    key (see extractors.image_key), not from the shared basename.
    """
    annex_marker = marker_for("annexes_Spec.pdf__img01")
    attach_marker = marker_for("attachments_Spec.pdf__img01")
    assert annex_marker != attach_marker
    corpus = {"projectName": "Demo", "oppId": "", "filesContents": [
        {"filename": "Spec.pdf", "path": "annexes/Spec.pdf",
         "extracted_text": f"Annex text.\n\n{annex_marker}"},
        {"filename": "Spec.pdf", "path": "attachments/Spec.pdf",
         "extracted_text": f"Attachment text.\n\n{attach_marker}"}],
        "extraction": {}}
    manifest = _manifest([
        {"id": "annexes_Spec.pdf__img01", "file": "annexes_Spec.pdf__img01.png",
         "source": "Spec.pdf", "locator": "page 2", "kind": "embedded"},
        {"id": "attachments_Spec.pdf__img01",
         "file": "attachments_Spec.pdf__img01.png",
         "source": "Spec.pdf", "locator": "page 5", "kind": "embedded"}])

    merged = mit.merge(corpus, manifest, {
        "annexes_Spec.pdf__img01": "Gantt: SOP Q3 2027.",
        "attachments_Spec.pdf__img01": "Wiring diagram, 12 V bus."})

    annex = merged["filesContents"][0]["extracted_text"]
    attach = merged["filesContents"][1]["extracted_text"]
    assert "SOP Q3 2027." in annex and "SOP Q3 2027." not in attach
    assert "12 V bus." in attach and "12 V bus." not in annex
    assert merged["extraction"]["images_merged"] == [
        "annexes_Spec.pdf__img01", "attachments_Spec.pdf__img01"]
    assert merged["extraction"]["images_unresolved"] == []


def test_image_with_no_matching_parent_is_recorded_not_dropped():
    corpus = _corpus("Some text with no marker at all.")
    manifest = _manifest([{"id": "Ghost.docx__img01", "file": "a.png",
                           "source": "Ghost.docx", "locator": "page 1",
                           "kind": "embedded"}])
    merged = mit.merge(corpus, manifest, {"Ghost.docx__img01": "Chart."})
    assert merged["extraction"]["images_unresolved"] == ["Ghost.docx__img01"]
    assert merged["extraction"]["images_merged"] == []


def test_second_pass_keeps_the_merge_history_and_records_nothing_new():
    marker = marker_for("SOR.docx__img01")
    corpus = _corpus(f"A\n\n{marker}\n\nB")
    manifest = _manifest([{"id": "SOR.docx__img01", "file": "x.png",
                           "source": "SOR.docx", "locator": "page 1",
                           "kind": "embedded"}])
    once = mit.merge(corpus, manifest, {"SOR.docx__img01": "Chart."})
    text_after_first = once["filesContents"][0]["extracted_text"]

    twice = mit.merge(once, manifest, {"SOR.docx__img01": "Chart."})
    assert twice["filesContents"][0]["extracted_text"] == text_after_first
    assert twice["extraction"]["images_merged"] == ["SOR.docx__img01"]
    assert twice["extraction"]["images_unresolved"] == []


def test_an_unread_picture_stays_unread_across_repeated_runs():
    """Run 1 replaces the marker with a note. Run 2 must recognise its own
    note and keep reporting the picture as unread - not reclassify it as
    one it could not match to a document."""
    marker = marker_for("SOR.docx__img01")
    corpus = _corpus(f"A\n\n{marker}\n\nB")
    manifest = _manifest([{"id": "SOR.docx__img01", "file": "x.png",
                           "source": "SOR.docx", "locator": "page 4",
                           "kind": "embedded"}])

    once = mit.merge(corpus, manifest, {})
    assert once["extraction"]["images_unread"] == ["SOR.docx__img01"]
    assert once["extraction"]["images_unresolved"] == []
    text_after_first = once["filesContents"][0]["extracted_text"]

    twice = mit.merge(once, manifest, {})
    assert twice["filesContents"][0]["extracted_text"] == text_after_first
    assert twice["extraction"]["images_unread"] == ["SOR.docx__img01"]
    assert twice["extraction"]["images_unresolved"] == []


def test_a_transcription_added_after_an_unread_run_still_merges():
    """The resume story: the picture was unreadable first time, someone
    supplied the text later. The note must give way to the transcription,
    in the same position the picture occupied."""
    marker = marker_for("SOR.docx__img01")
    corpus = _corpus(f"Intro paragraph.\n\n{marker}\n\nClosing paragraph.")
    manifest = _manifest([{"id": "SOR.docx__img01", "file": "x.png",
                           "source": "SOR.docx", "locator": "page 4",
                           "kind": "embedded"}])

    mit.merge(corpus, manifest, {})                       # unread first
    merged = mit.merge(corpus, manifest, {"SOR.docx__img01": "Gantt chart."})

    text = merged["filesContents"][0]["extracted_text"]
    assert "Gantt chart." in text
    assert "could not be read" not in text
    assert text.index("Intro paragraph.") < text.index("Gantt chart.")
    assert text.index("Gantt chart.") < text.index("Closing paragraph.")
    assert merged["extraction"]["images_merged"] == ["SOR.docx__img01"]
    assert merged["extraction"]["images_unread"] == []


def test_cli_rewrites_the_corpus_checkpoint(tmp_path):
    work = _work(tmp_path)
    marker = marker_for("SOR.docx__img01")
    with open(os.path.join(work, "corpus.json"), "w", encoding="utf-8") as fh:
        json.dump(_corpus(f"A\n\n{marker}"), fh)
    with open(os.path.join(work, "images.json"), "w", encoding="utf-8") as fh:
        json.dump(_manifest([{"id": "SOR.docx__img01", "file": "a.png",
                              "source": "SOR.docx", "locator": "page 1",
                              "kind": "embedded"}]), fh)
    with open(mit.transcription_path(work, "SOR.docx__img01"), "w",
              encoding="utf-8") as fh:
        fh.write("Gantt: SOP Q3 2027.")

    assert mit.main([str(tmp_path)]) == 0
    with open(os.path.join(work, "corpus.json"), encoding="utf-8") as fh:
        text = json.load(fh)["filesContents"][0]["extracted_text"]
    assert "SOP Q3 2027." in text and marker not in text


def test_two_loose_images_sharing_a_basename_each_get_their_own_text():
    """diagrams/chart.png and annexes/chart.png are different pictures. The
    corpus keys files on basename, so matching a standalone image's parent by
    name abandoned BOTH as ambiguous and discarded both transcriptions. The
    image id carries the path-derived key, which is unique.
    """
    from rfq.extractors import image_key

    corpus = {"projectName": "Demo", "oppId": "", "filesContents": [
        {"filename": "chart.png", "extension": "png",
         "path": "diagrams/chart.png", "extracted_text": ""},
        {"filename": "chart.png", "extension": "png",
         "path": "annexes/chart.png", "extracted_text": ""}],
        "extraction": {}}
    manifest = _manifest([
        {"id": image_key("diagrams/chart.png") + "__img01",
         "file": "a.png", "source": "chart.png",
         "locator": "standalone", "kind": "standalone"},
        {"id": image_key("annexes/chart.png") + "__img01",
         "file": "b.png", "source": "chart.png",
         "locator": "standalone", "kind": "standalone"},
    ])
    merged = mit.merge(corpus, manifest, {
        image_key("diagrams/chart.png") + "__img01": "Gantt: SOP Q3 2027.",
        image_key("annexes/chart.png") + "__img01": "Wiring layout.",
    })

    by_path = {f["path"]: f["extracted_text"]
               for f in merged["filesContents"]}
    assert "Gantt: SOP Q3 2027." in by_path["diagrams/chart.png"]
    assert "Wiring layout." in by_path["annexes/chart.png"]
    assert "Wiring layout." not in by_path["diagrams/chart.png"]
    assert merged["extraction"]["images_unresolved"] == []
    assert len(merged["extraction"]["images_merged"]) == 2
