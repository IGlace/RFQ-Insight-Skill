"""Figures: what earns a visual read, how workers' outputs are certified, and
how transcriptions go back exactly where the picture was.

Ported from the old test_images.py (rfq.images) and test_merge_image_text.py
(merge_image_text CLI); both now live in rfq/figures.py.
"""

import io
import json
import os
from pathlib import Path

import pytest

from rfq import figures as fg
from rfq import pipeline
from rfq.extractors import RawImage, image_key, marker_for


def _noise_png(w, h):
    """An incompressible PNG, so byte size tracks pixel size honestly."""
    from PIL import Image
    buf = io.BytesIO()
    Image.frombytes("RGB", (w, h), os.urandom(w * h * 3)).save(buf, format="PNG")
    return buf.getvalue()


def _flat_png(w, h, colour=(240, 240, 240)):
    """A big picture that compresses to almost nothing - the shape of a real
    chart or block diagram, which _noise_png deliberately is not."""
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), colour).save(buf, format="PNG")
    return buf.getvalue()


def _img(source, ordinal, data, locator="paragraph 1"):
    return RawImage(source, ordinal, data, ".png", locator)


# ================================================================ filtering
def test_big_embedded_image_is_kept():
    kept, dropped = fg.filter_images([_img("SOR.docx", 1, _noise_png(300, 300))])
    assert [i.image_id for i in kept] == ["SOR.docx__img01"]
    assert dropped == []


def test_small_image_is_dropped_as_furniture():
    kept, dropped = fg.filter_images([_img("SOR.docx", 1, _noise_png(32, 32))])
    assert kept == []
    assert dropped[0]["reason"] == "too_small"
    assert dropped[0]["id"] == "SOR.docx__img01"


def test_a_big_picture_that_compresses_small_is_kept():
    """A 600x400 chart is 240 000 pixels - six times the floor - and still
    lands under the byte floor, because flat fills and few colours compress
    to almost nothing. Testing either dimension alone threw it away."""
    blob = _flat_png(600, 400)
    assert len(blob) < fg.MIN_IMAGE_BYTES        # the trap the fixture sets
    kept, dropped = fg.filter_images([_img("SOR.docx", 1, blob)])
    assert [i.image_id for i in kept] == ["SOR.docx__img01"]
    assert dropped == []


def test_a_picture_small_in_both_ways_is_still_furniture():
    """The AND must not turn the filter off: an icon fails both tests."""
    blob = _flat_png(24, 24)
    assert len(blob) < fg.MIN_IMAGE_BYTES
    kept, dropped = fg.filter_images([_img("SOR.docx", 1, blob)])
    assert kept == []
    assert dropped[0]["reason"] == "too_small"


def test_image_repeating_three_times_is_chrome_after_the_first():
    """Page furniture is read ONCE per document, not never: a real package
    put its only telephone number inside the letterhead strip repeated on
    every page."""
    blob = _noise_png(300, 300)
    kept, dropped = fg.filter_images(
        [_img("SOR.docx", n, blob, f"page {n}") for n in (1, 2, 3)])
    assert [i.image_id for i in kept] == ["SOR.docx__img01"]
    assert {d["reason"] for d in dropped} == {"chrome"}
    assert len(dropped) == 2
    assert "3 times" in dropped[0]["detail"]


def test_second_identical_image_is_a_duplicate():
    blob = _noise_png(300, 300)
    kept, dropped = fg.filter_images([_img("SOR.docx", 1, blob),
                                      _img("SOR.docx", 2, blob)])
    assert [i.image_id for i in kept] == ["SOR.docx__img01"]
    assert [d["reason"] for d in dropped] == ["duplicate"]


def test_the_cap_limits_how_many_are_flagged():
    imgs = [_img("SOR.docx", n, _noise_png(300, 300)) for n in range(1, 6)]
    kept, dropped = fg.filter_images(imgs, max_flagged=2)
    assert len(kept) == 2
    assert [d["reason"] for d in dropped] == ["cap_reached"] * 3


def test_the_default_cap_is_ninety():
    assert fg.MAX_FLAGGED_IMAGES == 90


def test_the_cap_is_shared_across_documents_not_consumed_by_the_first():
    """A long annex must not eat the whole budget: slots go round-robin
    across documents, original order kept within each."""
    imgs = ([_img("A.docx", n, _noise_png(300, 300)) for n in range(1, 5)]
            + [_img("B.docx", n, _noise_png(300, 300)) for n in range(1, 3)])
    kept, dropped = fg.filter_images(imgs, max_flagged=4)
    assert [i.image_id for i in kept] == [
        "A.docx__img01", "B.docx__img01", "A.docx__img02", "B.docx__img02"]
    assert sorted(d["id"] for d in dropped) == ["A.docx__img03", "A.docx__img04"]


def test_standalone_image_bypasses_the_size_filter():
    """A .png in the RFQ folder IS the content - a small one still counts."""
    kept, dropped = fg.filter_images(
        [_img("timing_chart.png", 1, _noise_png(32, 32), "standalone")])
    assert [i.image_id for i in kept] == ["timing_chart.png__img01"]
    assert dropped == []


def test_standalone_image_still_respects_the_cap():
    imgs = [_img(f"c{n}.png", 1, _noise_png(300, 300), "standalone")
            for n in range(4)]
    kept, dropped = fg.filter_images(imgs, max_flagged=2)
    assert len(kept) == 2 and len(dropped) == 2


def test_unreadable_bytes_are_dropped_not_crashed():
    kept, dropped = fg.filter_images([_img("SOR.docx", 1, b"not an image")])
    assert kept == []
    assert dropped[0]["reason"] == "unreadable"


def test_a_standalone_copy_does_not_make_an_embedded_chart_chrome():
    blob = _noise_png(300, 300)
    imgs = [_img("SOR.docx", 1, blob, "page 1"),
            _img("SOR.docx", 2, blob, "page 9"),
            _img("chart.png", 1, blob, "standalone")]
    kept, dropped = fg.filter_images(imgs)
    assert "chrome" not in {d["reason"] for d in dropped}
    assert "SOR.docx__img01" in [i.image_id for i in kept]


def test_three_embedded_copies_are_still_chrome_with_a_standalone_present():
    blob = _noise_png(300, 300)
    imgs = [_img("SOR.docx", n, blob, f"page {n}") for n in (1, 2, 3)]
    imgs.append(_img("chart.png", 1, blob, "standalone"))
    kept, dropped = fg.filter_images(imgs)
    assert {d["reason"] for d in dropped} == {"chrome"}
    assert len(dropped) == 2
    assert [i.image_id for i in kept] == ["SOR.docx__img01", "chart.png__img01"]


def test_the_plain_language_reason_travels_with_the_record():
    kept, dropped = fg.filter_images([_img("SOR.docx", 1, _noise_png(24, 24))])
    assert dropped[0]["reason"] == "too_small"
    assert dropped[0]["explanation"] == fg.REASONS["too_small"]
    assert "logo" in dropped[0]["explanation"]


def test_every_emitted_reason_has_a_plain_language_explanation():
    blob = _noise_png(300, 300)
    imgs = ([_img("A.docx", 1, _noise_png(32, 32))]
            + [_img("B.docx", n, blob, f"page {n}") for n in (1, 2, 3)]
            + [_img("C.docx", 1, b"junk")]
            + [_img("D.docx", n, _noise_png(300, 300)) for n in (1, 2, 3)])
    _, dropped = fg.filter_images(imgs, max_flagged=1)
    assert {d["reason"] for d in dropped} <= set(fg.REASONS)
    for d in dropped:
        assert fg.REASONS[d["reason"]]


def test_a_presized_figure_is_not_re_judged_on_pixel_count():
    """A PDF figure crop was already measured against its area on the page."""
    tiny = _noise_png(30, 30)          # small in bytes AND pixels
    presized = RawImage("Seismic.pdf", 1, tiny, ".png", "page 1",
                        "Seismic.pdf", True)
    kept, dropped = fg.filter_images([presized])
    assert [i.image_id for i in kept] == ["Seismic.pdf__img01"]
    assert dropped == []


def test_an_ordinary_small_embedded_image_is_still_furniture():
    kept, dropped = fg.filter_images(
        [_img("SOR.docx", 1, _noise_png(30, 30))])
    assert kept == []
    assert dropped[0]["reason"] == "too_small"


def test_a_presized_figure_is_still_de_duplicated():
    """The size exemption for PDF crops must cover the SIZE test only."""
    blob = _noise_png(300, 300)
    imgs = [RawImage("Doc.pdf", n, blob, ".png", f"page {n}", "Doc.pdf", True)
            for n in (1, 2)]
    kept, dropped = fg.filter_images(imgs)
    assert [i.image_id for i in kept] == ["Doc.pdf__img01"]
    assert [d["reason"] for d in dropped] == ["duplicate"]


# ============================================================ write_images
def test_write_images_saves_files_and_builds_the_manifest(tmp_path):
    blob = _noise_png(300, 300)
    kept = [_img("SOR.docx", 1, blob),
            _img("timing_chart.png", 1, blob, "standalone")]
    dropped = [{"id": "SOR.docx__img02", "source": "SOR.docx",
                "locator": "page 2", "reason": "too_small", "detail": ""}]
    out = str(tmp_path / "images")
    manifest = fg.write_images(kept, dropped, out)

    assert os.path.exists(os.path.join(out, "SOR.docx__img01.png"))
    assert os.path.exists(os.path.join(out, "timing_chart.png__img01.png"))
    assert [e["id"] for e in manifest["images"]] == [
        "SOR.docx__img01", "timing_chart.png__img01"]
    assert manifest["images"][0]["kind"] == "embedded"
    assert manifest["images"][1]["kind"] == "standalone"
    assert manifest["filtered"] == dropped
    json.dumps(manifest)        # must be serialisable as written


def test_write_images_records_the_sha256_of_the_saved_bytes(tmp_path):
    """The manifest identity is what every later stage certifies against."""
    blob = _noise_png(300, 300)
    out = str(tmp_path / "images")
    manifest = fg.write_images([_img("SOR.docx", 1, blob)], [], out)
    entry = manifest["images"][0]
    assert entry["sha256"] == fg.image_digest(blob)
    assert fg.image_identity(entry, out)["sha256"] == entry["sha256"]


def test_image_identity_rejects_a_filename_that_is_not_local(tmp_path):
    for bad in ("../x.png", "a/b.png", "", ".", "C:x.png"):
        with pytest.raises(ValueError):
            fg.image_identity({"file": bad}, str(tmp_path))


def test_identity_matches_needs_every_field():
    full = {"file": "a.png", "source": "S", "locator": "page 1", "sha256": "x"}
    assert fg.identity_matches(full, dict(full))
    assert not fg.identity_matches({k: v for k, v in full.items()
                                    if k != "sha256"}, full)
    assert not fg.identity_matches(full, {**full, "sha256": "y"})
    assert not fg.identity_matches(None, full)


# ========================================================= balanced batches
def _manifest_on_disk(tmp_path, sizes):
    """Write one noise PNG per (id, side) and return (entries, images_dir)."""
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    entries = []
    for image_id, side in sizes:
        data = _noise_png(side, side)
        (images_dir / f"{image_id}.png").write_bytes(data)
        entries.append({"id": image_id, "file": f"{image_id}.png",
                        "source": "SOR.docx", "locator": "page 1",
                        "sha256": fg.image_digest(data)})
    return entries, str(images_dir)


def test_the_pipeline_sends_six_pictures_per_figure_worker():
    assert pipeline.FIGURE_BATCH == 6


def test_batches_are_bounded_by_the_batch_size_and_cover_every_id(tmp_path):
    ids = [f"SOR.docx__img{n:02d}" for n in range(1, 15)]
    entries, images_dir = _manifest_on_disk(tmp_path, [(i, 20) for i in ids])
    batches = fg.balanced_figure_batches(entries, ids, images_dir,
                                         pipeline.FIGURE_BATCH)
    assert len(batches) == 3
    assert all(len(b) <= pipeline.FIGURE_BATCH for b in batches)
    assert sorted(i for b in batches for i in b) == sorted(ids)


def test_batches_spread_the_big_pictures_apart(tmp_path):
    """Pixel load is balanced: the two heavy pictures land in different
    batches instead of both in the first."""
    sizes = [("big_a", 120), ("big_b", 120), ("s1", 10), ("s2", 10)]
    entries, images_dir = _manifest_on_disk(tmp_path, sizes)
    batches = fg.balanced_figure_batches(entries, [s[0] for s in sizes],
                                         images_dir, 2)
    homes = {i: n for n, b in enumerate(batches) for i in b}
    assert homes["big_a"] != homes["big_b"]


def test_batches_are_reproducible_for_the_same_manifest(tmp_path):
    ids = [f"img{n}" for n in range(7)]
    entries, images_dir = _manifest_on_disk(tmp_path, [(i, 10) for i in ids])
    first = fg.balanced_figure_batches(entries, ids, images_dir, 3)
    second = fg.balanced_figure_batches(entries, list(reversed(ids)),
                                        images_dir, 3)
    assert first == second


def test_no_ids_means_no_batches(tmp_path):
    assert fg.balanced_figure_batches([], [], str(tmp_path), 6) == []


def test_batch_size_must_be_an_integer_between_one_and_the_cap(tmp_path):
    entries, images_dir = _manifest_on_disk(tmp_path, [("a", 10)])
    for bad in (0, 91, True, 2.0, "6"):
        with pytest.raises(ValueError):
            fg.balanced_figure_batches(entries, ["a"], images_dir, bad)


def test_duplicate_or_unknown_ids_are_refused(tmp_path):
    entries, images_dir = _manifest_on_disk(tmp_path, [("a", 10)])
    with pytest.raises(ValueError):
        fg.balanced_figure_batches(entries, ["a", "a"], images_dir, 6)
    with pytest.raises(ValueError):
        fg.balanced_figure_batches(entries, ["ghost"], images_dir, 6)


def test_the_no_text_marker_is_what_a_blank_picture_reads_as():
    assert fg.NO_TEXT_MARKER == "[No text in this picture]"
    assert fg.NO_TEXT_MARKER.strip()        # never mistaken for "unread"


# ================================================== worker output receipts
def _work(tmp_path):
    work = tmp_path / "output" / ".work"
    (work / "image_text").mkdir(parents=True)
    (work / "images").mkdir()
    return str(work)


def _manifest_entry(work, image_id, data, source="SOR.docx", locator="page 1",
                    kind="embedded"):
    """Save the bytes and append the manifest entry (as write_images does)."""
    name = f"{image_id}.png"
    with open(os.path.join(work, "images", name), "wb") as fh:
        fh.write(data)
    entry = {"id": image_id, "file": name, "source": source,
             "locator": locator, "kind": kind, "sha256": fg.image_digest(data)}
    path = os.path.join(work, "images.json")
    manifest = {"images": [], "filtered": []}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            manifest = json.load(fh)
    manifest["images"].append(entry)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh)
    return entry


def _worker_outputs(work, image_id, text="Gantt chart."):
    """What a figure worker writes: the transcription, nothing else."""
    fg.figure_output(work, image_id).write_text(text, encoding="utf-8")


def _receipt(work, image_id):
    """What the app writes when it dispatches a worker for this picture."""
    with open(os.path.join(work, "images.json"), encoding="utf-8") as fh:
        entry = next(e for e in json.load(fh)["images"] if e["id"] == image_id)
    identity = fg.image_identity(entry, os.path.join(work, "images"))
    path = os.path.join(work, "figure_requests.json")
    receipts = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            receipts = json.load(fh)
    receipts[image_id] = identity
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(receipts, fh)


def _certified(work, image_id, data=None, text="Gantt chart.", **entry_kw):
    """A picture the worker has read and the app has accepted."""
    _manifest_entry(work, image_id, data or _noise_png(300, 300), **entry_kw)
    _worker_outputs(work, image_id, text)
    _receipt(work, image_id)
    assert fg.accept_figure_outputs(work, [image_id]) == [image_id]


def test_a_worker_output_is_not_reusable_until_the_app_accepts_it(tmp_path):
    work = _work(tmp_path)
    _manifest_entry(work, "SOR.docx__img01", _noise_png(300, 300))
    _worker_outputs(work, "SOR.docx__img01")
    assert not fg.figure_reusable(work, "SOR.docx__img01")
    _receipt(work, "SOR.docx__img01")
    assert fg.accept_figure_outputs(work, ["SOR.docx__img01"]) == ["SOR.docx__img01"]
    assert fg.figure_reusable(work, "SOR.docx__img01")
    assert fg.figure_metadata(work, "SOR.docx__img01").is_file()


def test_accepting_consumes_the_receipt(tmp_path):
    work = _work(tmp_path)
    _certified(work, "SOR.docx__img01")
    with open(os.path.join(work, "figure_requests.json"), encoding="utf-8") as fh:
        assert json.load(fh) == {}
    # A second acceptance has no receipt to certify against.
    assert fg.accept_figure_outputs(work, ["SOR.docx__img01"]) == []
    assert fg.figure_reusable(work, "SOR.docx__img01")      # still certified


def test_outputs_without_a_receipt_are_never_accepted(tmp_path):
    work = _work(tmp_path)
    _manifest_entry(work, "SOR.docx__img01", _noise_png(300, 300))
    _worker_outputs(work, "SOR.docx__img01")
    assert fg.accept_figure_outputs(work, ["SOR.docx__img01"]) == []
    assert not fg.figure_reusable(work, "SOR.docx__img01")


def test_an_empty_transcription_is_not_accepted(tmp_path):
    work = _work(tmp_path)
    _manifest_entry(work, "SOR.docx__img01", _noise_png(300, 300))
    _worker_outputs(work, "SOR.docx__img01", text="   ")
    _receipt(work, "SOR.docx__img01")
    assert fg.accept_figure_outputs(work, ["SOR.docx__img01"]) == []


def test_the_transcription_alone_is_a_complete_figure_output(tmp_path):
    """One output per picture: the .txt. No classification file is asked
    for, written or needed for the result to be accepted and reused."""
    work = _work(tmp_path)
    assert fg.figure_output(work, "SOR.docx__img01") == (
        Path(work) / "image_text" / "SOR.docx__img01.txt")
    _certified(work, "SOR.docx__img01")
    assert fg.figure_reusable(work, "SOR.docx__img01")
    assert sorted(p.name for p in (Path(work) / "image_text").iterdir()) == [
        "SOR.docx__img01.meta.json", "SOR.docx__img01.txt"]
    assert not hasattr(fg, "figure_outputs")
    assert not hasattr(fg, "load_classification")
    assert not hasattr(fg, "apply_classifications")


def test_a_figure_set_parses_the_manifest_once_and_hashes_each_image_once(
        tmp_path, monkeypatch):
    work = _work(tmp_path)
    ids = [f"SOR.docx__img{i:02d}" for i in range(1, 5)]
    for image_id in ids:
        _certified(work, image_id, locator=f"page {image_id[-1]}")
    hashed, parsed = [], []
    digest, read = fg.image_digest, fg._read_json
    monkeypatch.setattr(fg, "image_digest",
                        lambda data: hashed.append(1) or digest(data))
    monkeypatch.setattr(fg, "_read_json", lambda path: parsed.append(
        Path(path).name) or read(path))
    figs = fg.FigureSet(work)
    for _ in range(3):
        assert all(fg.figure_reusable(work, i, figs) for i in ids)
        assert fg.accept_figure_outputs(work, ids, figs) == []
    assert len(hashed) == len(ids)
    assert parsed.count("images.json") == 1
    found, missing = fg.read_transcriptions(work, figs.manifest, figs)
    assert sorted(found) == ids and missing == []
    assert len(hashed) == len(ids)


def test_a_receipt_for_different_bytes_does_not_certify(tmp_path):
    """The image changed between dispatch and return: the worker read
    something else, so its output is not evidence for this picture."""
    work = _work(tmp_path)
    _manifest_entry(work, "SOR.docx__img01", _noise_png(300, 300))
    _worker_outputs(work, "SOR.docx__img01")
    _receipt(work, "SOR.docx__img01")
    with open(os.path.join(work, "images", "SOR.docx__img01.png"), "wb") as fh:
        fh.write(_noise_png(301, 301))
    assert fg.accept_figure_outputs(work, ["SOR.docx__img01"]) == []


def test_a_certified_output_stops_being_reusable_when_the_image_changes(tmp_path):
    work = _work(tmp_path)
    _certified(work, "SOR.docx__img01")
    with open(os.path.join(work, "images", "SOR.docx__img01.png"), "wb") as fh:
        fh.write(_noise_png(301, 301))
    assert not fg.figure_reusable(work, "SOR.docx__img01")


def test_invalidating_requests_ends_all_outstanding_receipts(tmp_path):
    work = _work(tmp_path)
    _manifest_entry(work, "SOR.docx__img01", _noise_png(300, 300))
    _worker_outputs(work, "SOR.docx__img01")
    _receipt(work, "SOR.docx__img01")
    fg.invalidate_figure_requests(work)
    assert fg.accept_figure_outputs(work, ["SOR.docx__img01"]) == []


def test_figure_outputs_and_metadata_use_plain_local_names(tmp_path):
    work = _work(tmp_path)
    for bad in ("../x", "a/b", "", "."):
        with pytest.raises(ValueError):
            fg.figure_output(work, bad)
        with pytest.raises(ValueError):
            fg.figure_metadata(work, bad)


def test_read_transcriptions_finds_only_certified_files(tmp_path):
    work = _work(tmp_path)
    _certified(work, "SOR.docx__img01", text="  Gantt chart.  ")
    _manifest_entry(work, "SOR.docx__img02", _noise_png(300, 300),
                    locator="page 2")
    _worker_outputs(work, "SOR.docx__img02", text="Uncertified.")
    with open(os.path.join(work, "images.json"), encoding="utf-8") as fh:
        manifest = json.load(fh)

    found, missing = fg.read_transcriptions(work, manifest)
    assert found == {"SOR.docx__img01": "Gantt chart."}
    assert missing == ["SOR.docx__img02"]


# ==================================================================== merge
def _corpus(text, filename="SOR.docx"):
    return {"projectName": "Demo", "oppId": "",
            "filesContents": [{"filename": filename, "extension": "docx",
                               "path": filename, "extracted_text": text}],
            "extraction": {"parsed": 1, "chars": len(text), "skipped": [],
                           "ignored": [], "images_flagged": [],
                           "images_filtered": [], "preprocess": {}}}


def _manifest(entries):
    return {"images": entries, "filtered": []}


def _embedded(image_id, locator="page 1", source="SOR.docx"):
    return {"id": image_id, "file": "x.png", "source": source,
            "locator": locator, "kind": "embedded"}


def test_the_transcription_block_and_unread_note_have_the_documented_shape():
    assert fg.transcription_block("SOR.docx__img01", "Text.") == (
        "[BEGIN IMAGE TRANSCRIPTION SOR.docx__img01]\nText.\n"
        "[END IMAGE TRANSCRIPTION]")
    assert fg.unread_note("SOR.docx__img01", "page 4") == (
        "[[PICTURE SOR.docx__img01 at page 4 could not be read]]")


def test_embedded_transcription_replaces_the_marker_in_place():
    marker = marker_for("SOR.docx__img01")
    corpus = _corpus(f"Before the chart.\n\n{marker}\n\nAfter the chart.")
    manifest = _manifest([_embedded("SOR.docx__img01", "paragraph 4")])

    merged = fg.merge(corpus, manifest, {"SOR.docx__img01": "Gantt: SOP Q3 2027."})
    text = merged["filesContents"][0]["extracted_text"]

    assert marker not in text
    assert "[BEGIN IMAGE TRANSCRIPTION SOR.docx__img01]" in text
    assert "Gantt: SOP Q3 2027." in text
    assert text.index("Before the chart.") < text.index("Gantt: SOP Q3 2027.")
    assert text.index("Gantt: SOP Q3 2027.") < text.index("After the chart.")
    assert merged["extraction"]["images_merged"] == ["SOR.docx__img01"]


def test_standalone_transcription_becomes_the_file_text():
    corpus = _corpus("", filename="timing_chart.png")
    corpus["filesContents"][0]["extension"] = "png"
    manifest = _manifest([{"id": "timing_chart.png__img01",
                           "file": "timing_chart.png__img01.png",
                           "source": "timing_chart.png",
                           "locator": "standalone", "kind": "standalone"}])

    merged = fg.merge(corpus, manifest,
                      {"timing_chart.png__img01": "Milestones: SOP Q3 2027."})
    assert "SOP Q3 2027." in merged["filesContents"][0]["extracted_text"]
    assert merged["extraction"]["images_merged"] == ["timing_chart.png__img01"]


def test_an_unread_standalone_picture_gets_the_note_as_its_text():
    corpus = _corpus("", filename="timing_chart.png")
    manifest = _manifest([{"id": "timing_chart.png__img01", "file": "a.png",
                           "source": "timing_chart.png",
                           "locator": "standalone", "kind": "standalone"}])
    merged = fg.merge(corpus, manifest, {})
    assert merged["filesContents"][0]["extracted_text"] == fg.unread_note(
        "timing_chart.png__img01", "standalone")
    assert merged["extraction"]["images_unread"] == ["timing_chart.png__img01"]


def test_missing_transcription_leaves_an_honest_note():
    marker = marker_for("SOR.docx__img01")
    corpus = _corpus(f"Text.\n\n{marker}")
    manifest = _manifest([_embedded("SOR.docx__img01", "page 2")])

    merged = fg.merge(corpus, manifest, {})
    text = merged["filesContents"][0]["extracted_text"]
    assert marker not in text
    assert "[[PICTURE SOR.docx__img01 at page 2 could not be read]]" in text
    assert merged["extraction"]["images_unread"] == ["SOR.docx__img01"]


def test_transcription_is_cleaned_like_any_extracted_text():
    marker = marker_for("SOR.docx__img01")
    corpus = _corpus(marker)
    manifest = _manifest([_embedded("SOR.docx__img01", "page 9")])
    merged = fg.merge(corpus, manifest,
                      {"SOR.docx__img01": "Chart title\nPage 9 of 40\n25"})
    text = merged["filesContents"][0]["extracted_text"]
    assert "Chart title" in text
    assert "Page 9 of 40" not in text


def test_merging_twice_changes_nothing():
    marker = marker_for("SOR.docx__img01")
    corpus = _corpus(f"A\n\n{marker}\n\nB")
    manifest = _manifest([_embedded("SOR.docx__img01")])
    once = fg.merge(corpus, manifest, {"SOR.docx__img01": "Chart."})
    first = once["filesContents"][0]["extracted_text"]
    twice = fg.merge(once, manifest, {"SOR.docx__img01": "Chart."})
    assert twice["filesContents"][0]["extracted_text"] == first
    assert twice["extraction"]["images_merged"] == ["SOR.docx__img01"]
    assert twice["extraction"]["images_unresolved"] == []


def test_char_count_is_refreshed():
    marker = marker_for("SOR.docx__img01")
    corpus = _corpus(marker)
    manifest = _manifest([_embedded("SOR.docx__img01")])
    merged = fg.merge(corpus, manifest, {"SOR.docx__img01": "A" * 500})
    assert merged["extraction"]["chars"] == len(
        merged["filesContents"][0]["extracted_text"])


def test_each_of_two_same_named_files_gets_its_own_transcription():
    """annexes/Spec.pdf and attachments/Spec.pdf share a basename; the
    marker carries the path-derived id, which keeps them apart."""
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
        _embedded("annexes_Spec.pdf__img01", "page 2", "Spec.pdf"),
        _embedded("attachments_Spec.pdf__img01", "page 5", "Spec.pdf")])

    merged = fg.merge(corpus, manifest, {
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
    manifest = _manifest([_embedded("Ghost.docx__img01", "page 1", "Ghost.docx")])
    merged = fg.merge(corpus, manifest, {"Ghost.docx__img01": "Chart."})
    assert merged["extraction"]["images_unresolved"] == ["Ghost.docx__img01"]
    assert merged["extraction"]["images_merged"] == []


def test_a_standalone_image_with_no_parent_entry_is_unresolved():
    corpus = _corpus("Unrelated.")
    manifest = _manifest([{"id": "ghost.png__img01", "file": "a.png",
                           "source": "ghost.png", "locator": "standalone",
                           "kind": "standalone"}])
    merged = fg.merge(corpus, manifest, {"ghost.png__img01": "Text."})
    assert merged["extraction"]["images_unresolved"] == ["ghost.png__img01"]


def test_an_unread_picture_stays_unread_across_repeated_runs():
    """Run 2 must recognise its own note and keep reporting the picture as
    unread, not reclassify it as one it could not match to a document."""
    marker = marker_for("SOR.docx__img01")
    corpus = _corpus(f"A\n\n{marker}\n\nB")
    manifest = _manifest([_embedded("SOR.docx__img01", "page 4")])

    once = fg.merge(corpus, manifest, {})
    assert once["extraction"]["images_unread"] == ["SOR.docx__img01"]
    assert once["extraction"]["images_unresolved"] == []
    text_after_first = once["filesContents"][0]["extracted_text"]

    twice = fg.merge(once, manifest, {})
    assert twice["filesContents"][0]["extracted_text"] == text_after_first
    assert twice["extraction"]["images_unread"] == ["SOR.docx__img01"]
    assert twice["extraction"]["images_unresolved"] == []


def test_a_transcription_added_after_an_unread_run_still_merges():
    marker = marker_for("SOR.docx__img01")
    corpus = _corpus(f"Intro paragraph.\n\n{marker}\n\nClosing paragraph.")
    manifest = _manifest([_embedded("SOR.docx__img01", "page 4")])

    fg.merge(corpus, manifest, {})                       # unread first
    merged = fg.merge(corpus, manifest, {"SOR.docx__img01": "Gantt chart."})

    text = merged["filesContents"][0]["extracted_text"]
    assert "Gantt chart." in text
    assert "could not be read" not in text
    assert text.index("Intro paragraph.") < text.index("Gantt chart.")
    assert text.index("Gantt chart.") < text.index("Closing paragraph.")
    assert merged["extraction"]["images_merged"] == ["SOR.docx__img01"]
    assert merged["extraction"]["images_unread"] == []


def test_two_loose_images_sharing_a_basename_each_get_their_own_text():
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
    merged = fg.merge(corpus, manifest, {
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


def test_run_merge_rewrites_the_corpus_checkpoint(tmp_path):
    work = _work(tmp_path)
    marker = marker_for("SOR.docx__img01")
    with open(os.path.join(work, "corpus.json"), "w", encoding="utf-8") as fh:
        json.dump(_corpus(f"A\n\n{marker}"), fh)
    _certified(work, "SOR.docx__img01", text="Gantt: SOP Q3 2027.")

    result = fg.run_merge(str(tmp_path))
    assert result["added"] == 1 and result["missing"] == []
    assert result["record"]["images_merged"] == ["SOR.docx__img01"]
    with open(os.path.join(work, "corpus.json"), encoding="utf-8") as fh:
        text = json.load(fh)["filesContents"][0]["extracted_text"]
    assert "SOP Q3 2027." in text and marker not in text
    # Nothing is classified any more: the manifest keeps its own fields.
    with open(os.path.join(work, "images.json"), encoding="utf-8") as fh:
        manifest = json.load(fh)
    assert "unclassified" not in manifest
    assert set(manifest["images"][0]) == {"id", "file", "source", "locator",
                                          "kind", "sha256"}


def test_run_merge_reports_uncertified_pictures_as_missing(tmp_path):
    work = _work(tmp_path)
    marker = marker_for("SOR.docx__img01")
    with open(os.path.join(work, "corpus.json"), "w", encoding="utf-8") as fh:
        json.dump(_corpus(f"A\n\n{marker}"), fh)
    _manifest_entry(work, "SOR.docx__img01", _noise_png(300, 300))
    _worker_outputs(work, "SOR.docx__img01")        # never accepted

    result = fg.run_merge(str(tmp_path))
    assert result["added"] == 0
    assert result["missing"] == ["SOR.docx__img01"]
    assert result["record"]["images_unread"] == ["SOR.docx__img01"]


def test_run_merge_is_none_before_extraction(tmp_path):
    assert fg.run_merge(str(tmp_path)) is None
