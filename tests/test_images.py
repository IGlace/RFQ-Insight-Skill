"""Image filtering: what earns a visual read, and what is page furniture."""

import io
import json
import os

from rfq import images as im
from rfq.extractors import RawImage


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


def test_big_embedded_image_is_kept():
    kept, dropped = im.filter_images([_img("SOR.docx", 1, _noise_png(300, 300))])
    assert [i.image_id for i in kept] == ["SOR.docx__img01"]
    assert dropped == []


def test_small_image_is_dropped_as_furniture():
    kept, dropped = im.filter_images([_img("SOR.docx", 1, _noise_png(32, 32))])
    assert kept == []
    assert dropped[0]["reason"] == "too_small"
    assert dropped[0]["id"] == "SOR.docx__img01"


def test_a_big_picture_that_compresses_small_is_kept():
    """A 600x400 chart is 240 000 pixels - six times the floor - and still
    lands under the byte floor, because flat fills and few colours compress
    to almost nothing. Testing either dimension alone threw it away."""
    blob = _flat_png(600, 400)
    assert len(blob) < im.MIN_IMAGE_BYTES        # the trap the fixture sets
    kept, dropped = im.filter_images([_img("SOR.docx", 1, blob)])
    assert [i.image_id for i in kept] == ["SOR.docx__img01"]
    assert dropped == []


def test_a_picture_small_in_both_ways_is_still_furniture():
    """The AND must not turn the filter off: an icon fails both tests."""
    blob = _flat_png(24, 24)
    assert len(blob) < im.MIN_IMAGE_BYTES
    kept, dropped = im.filter_images([_img("SOR.docx", 1, blob)])
    assert kept == []
    assert dropped[0]["reason"] == "too_small"


def test_image_repeating_three_times_is_chrome_after_the_first():
    """Page furniture is read ONCE per document, not never.

    Changed deliberately after a real package put its only telephone number
    and the engineering firm's name inside the letterhead strip repeated on
    every page: that is chrome by definition and also where contact details
    live. Dropping every copy lost the contact; keeping the first costs one
    visual read.
    """
    blob = _noise_png(300, 300)
    kept, dropped = im.filter_images(
        [_img("SOR.docx", n, blob, f"page {n}") for n in (1, 2, 3)])
    assert [i.image_id for i in kept] == ["SOR.docx__img01"]
    assert {d["reason"] for d in dropped} == {"chrome"}
    assert len(dropped) == 2
    assert "3 times" in dropped[0]["detail"]


def test_second_identical_image_is_a_duplicate():
    blob = _noise_png(300, 300)
    kept, dropped = im.filter_images([_img("SOR.docx", 1, blob),
                                      _img("SOR.docx", 2, blob)])
    assert [i.image_id for i in kept] == ["SOR.docx__img01"]
    assert [d["reason"] for d in dropped] == ["duplicate"]


def test_the_cap_limits_how_many_are_flagged():
    imgs = [_img("SOR.docx", n, _noise_png(300, 300)) for n in range(1, 6)]
    kept, dropped = im.filter_images(imgs, max_flagged=2)
    assert len(kept) == 2
    assert [d["reason"] for d in dropped] == ["cap_reached"] * 3


def test_standalone_image_bypasses_the_size_filter():
    """A .png in the RFQ folder IS the content - a small one still counts."""
    kept, dropped = im.filter_images(
        [_img("timing_chart.png", 1, _noise_png(32, 32), "standalone")])
    assert [i.image_id for i in kept] == ["timing_chart.png__img01"]
    assert dropped == []


def test_standalone_image_still_respects_the_cap():
    imgs = [_img(f"c{n}.png", 1, _noise_png(300, 300), "standalone")
            for n in range(4)]
    kept, dropped = im.filter_images(imgs, max_flagged=2)
    assert len(kept) == 2 and len(dropped) == 2


def test_unreadable_bytes_are_dropped_not_crashed():
    kept, dropped = im.filter_images([_img("SOR.docx", 1, b"not an image")])
    assert kept == []
    assert dropped[0]["reason"] == "unreadable"


def test_a_standalone_copy_does_not_make_an_embedded_chart_chrome():
    """A .png the user dropped in the folder is one whole input, not a
    repeat of anything. Counting it toward the repeat threshold let two
    copies of a chart plus one loose file throw the chart away."""
    blob = _noise_png(300, 300)
    imgs = [_img("SOR.docx", 1, blob, "page 1"),
            _img("SOR.docx", 2, blob, "page 9"),
            _img("chart.png", 1, blob, "standalone")]
    kept, dropped = im.filter_images(imgs)
    assert "chrome" not in {d["reason"] for d in dropped}
    assert "SOR.docx__img01" in [i.image_id for i in kept]


def test_three_embedded_copies_are_still_chrome_with_a_standalone_present():
    """The other side: excluding standalone files must not disable the
    repeat check for the pictures it is meant to catch."""
    blob = _noise_png(300, 300)
    imgs = [_img("SOR.docx", n, blob, f"page {n}") for n in (1, 2, 3)]
    imgs.append(_img("chart.png", 1, blob, "standalone"))
    kept, dropped = im.filter_images(imgs)
    # The first embedded copy is read once; copies 2 and 3 are chrome. The
    # standalone file is its own input and is never counted as a repeat.
    assert {d["reason"] for d in dropped} == {"chrome"}
    assert len(dropped) == 2
    assert [i.image_id for i in kept] == ["SOR.docx__img01", "chart.png__img01"]


def test_the_plain_language_reason_travels_with_the_record():
    """The run report carried raw keys like 'too_small'; the sentence
    explaining them lived only in the test suite."""
    kept, dropped = im.filter_images([_img("SOR.docx", 1, _noise_png(24, 24))])
    assert dropped[0]["reason"] == "too_small"
    assert dropped[0]["explanation"] == im.REASONS["too_small"]
    assert "logo" in dropped[0]["explanation"]


def test_every_emitted_reason_has_a_plain_language_explanation():
    blob = _noise_png(300, 300)
    imgs = ([_img("A.docx", 1, _noise_png(32, 32))]
            + [_img("B.docx", n, blob, f"page {n}") for n in (1, 2, 3)]
            + [_img("C.docx", 1, b"junk")]
            + [_img("D.docx", n, _noise_png(300, 300)) for n in (1, 2, 3)])
    _, dropped = im.filter_images(imgs, max_flagged=1)
    assert {d["reason"] for d in dropped} <= set(im.REASONS)
    for d in dropped:
        assert im.REASONS[d["reason"]]


def test_write_images_saves_files_and_builds_the_manifest(tmp_path):
    blob = _noise_png(300, 300)
    kept = [_img("SOR.docx", 1, blob),
            _img("timing_chart.png", 1, blob, "standalone")]
    dropped = [{"id": "SOR.docx__img02", "source": "SOR.docx",
                "locator": "page 2", "reason": "too_small", "detail": ""}]
    out = str(tmp_path / "images")
    manifest = im.write_images(kept, dropped, out)

    assert os.path.exists(os.path.join(out, "SOR.docx__img01.png"))
    assert os.path.exists(os.path.join(out, "timing_chart.png__img01.png"))
    assert [e["id"] for e in manifest["images"]] == [
        "SOR.docx__img01", "timing_chart.png__img01"]
    assert manifest["images"][0]["kind"] == "embedded"
    assert manifest["images"][1]["kind"] == "standalone"
    assert manifest["filtered"] == dropped
    json.dumps(manifest)        # must be serialisable as written


def test_a_presized_figure_is_not_re_judged_on_pixel_count():
    """A PDF figure crop has already been measured against its area on the
    page, which is the meaningful test. Re-measuring it in pixels discards
    exactly what the page-area floor was lowered to catch: one line of text
    rendered as a picture — a real package showed its standard version as a
    72x17 point image reading "ASCE 7-22" over text saying "ASCE 7-16".
    """
    tiny = _noise_png(30, 30)          # small in bytes AND pixels
    presized = RawImage("Seismic.pdf", 1, tiny, ".png", "page 1",
                        "Seismic.pdf", True)
    kept, dropped = im.filter_images([presized])
    assert [i.image_id for i in kept] == ["Seismic.pdf__img01"]
    assert dropped == []


def test_an_ordinary_small_embedded_image_is_still_furniture():
    """The exemption must not disable the filter for images that were never
    measured against a page — an icon inside a .docx has no page area."""
    kept, dropped = im.filter_images(
        [_img("SOR.docx", 1, _noise_png(30, 30))])
    assert kept == []
    assert dropped[0]["reason"] == "too_small"


def test_a_presized_figure_is_still_de_duplicated():
    """The size exemption for PDF crops must cover the SIZE test only.

    Exempting them from the whole block left PDF figures never
    de-duplicated: one real package flagged 60 figures of which 19 were
    repeat renders of two logos, each costing a visual read and a slot of
    the flagged cap.
    """
    blob = _noise_png(300, 300)
    imgs = [RawImage("Doc.pdf", n, blob, ".png", f"page {n}", "Doc.pdf", True)
            for n in (1, 2)]
    kept, dropped = im.filter_images(imgs)
    assert [i.image_id for i in kept] == ["Doc.pdf__img01"]
    assert [d["reason"] for d in dropped] == ["duplicate"]
