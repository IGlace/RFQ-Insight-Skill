import importlib.util
import os
import re
import zipfile

from pptx import Presentation
from pptx.util import Inches

from conftest import REPO_ROOT, SKILL_ROOT

TEMPLATE = os.path.join(SKILL_ROOT, "assets", "avl_template.pptx")


def _load_builder():
    path = os.path.join(REPO_ROOT, "tools", "make_template.py")
    spec = importlib.util.spec_from_file_location("make_template", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_template_is_a_master_without_slides():
    prs = Presentation(TEMPLATE)
    assert len(prs.slides) == 0
    assert abs(prs.slide_width / 914400 - 13.333) < 0.01
    assert abs(prs.slide_height / 914400 - 7.5) < 0.01
    names = [l.name for l in prs.slide_layouts]
    assert "Only Title" in names
    assert any(n.startswith("1_Title_") for n in names)
    assert any(n.startswith("Final Slide") for n in names)


def test_template_carries_no_slide_parts_or_large_media():
    with zipfile.ZipFile(TEMPLATE) as z:
        names = z.namelist()
        assert not [n for n in names if n.startswith("ppt/slides/")]
        assert all(z.getinfo(n).file_size <= 1_000_000
                   for n in names if n.startswith("ppt/media/"))


def test_template_leaks_nothing_from_the_source_slides():
    with zipfile.ZipFile(TEMPLATE) as z:
        names = z.namelist()
        assert names[0] == "[Content_Types].xml"
        assert not [n for n in names if n.startswith(("ppt/notesSlides/", "[trash]/",
                                                       "ppt/changesInfos/"))]
        assert "docProps/thumbnail.jpeg" not in names
        text = {n: z.read(n).decode("utf-8", "ignore") for n in names
                if n.endswith((".xml", ".rels"))}
    assert not [n for n, t in text.items() if re.search(r"slides/slide\d+\.xml", t)]
    assert not [n for n, t in text.items() if "notesSlide" in t or "thumbnail" in t]
    assert "<p14:sectionLst" not in text["ppt/presentation.xml"]
    assert "Folientitel" not in text["docProps/app.xml"]
    assert "<Slides>0</Slides>" in text["docProps/app.xml"]


def test_every_media_part_is_referenced_by_a_remaining_part():
    with zipfile.ZipFile(TEMPLATE) as z:
        media = {n for n in z.namelist() if n.startswith("ppt/media/")}
        referenced = set()
        for n in z.namelist():
            if n.endswith(".rels"):
                for target in re.findall(r'Target="\.\./media/([^"]+)"',
                                         z.read(n).decode("utf-8")):
                    referenced.add("ppt/media/" + target)
    assert media and media == referenced


def test_strip_to_master_drops_slides_notes_and_orphan_media(tmp_path):
    builder = _load_builder()
    picture = tmp_path / "pic.png"
    # smallest valid PNG: 1x1 pixel
    picture.write_bytes(bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000d49444154789c6360f8cfc000000301010018dd8db00000000049454e44ae426082"))
    src = tmp_path / "src.pptx"
    prs = Presentation()
    for i in range(3):
        slide = prs.slides.add_slide(prs.slide_layouts[5])
        slide.shapes.title.text = "Customer secret %d" % i
        slide.shapes.add_picture(str(picture), Inches(1), Inches(1))
        slide.notes_slide.notes_text_frame.text = "private note"
    prs.save(src)
    with zipfile.ZipFile(src) as z:
        assert any(n.startswith("ppt/notesSlides/") for n in z.namelist())
        assert any(n.startswith("ppt/media/") for n in z.namelist())

    out = tmp_path / "out.pptx"
    result = builder.strip_to_master(str(src), str(out))

    assert result["slides_removed"] == 3
    assert result["media_removed"] >= 1
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        assert names[0] == "[Content_Types].xml"
        assert not [n for n in names if n.startswith(("ppt/slides/", "ppt/notesSlides/"))]
        assert not [n for n in names if n.startswith("ppt/media/")]
        blob = b"".join(z.read(n) for n in names)
        assert b"Customer secret" not in blob and b"private note" not in blob
        assert b"/ppt/slides/" not in z.read("[Content_Types].xml")
    reopened = Presentation(out)
    assert len(reopened.slides) == 0
    assert len(reopened.slide_layouts) == len(prs.slide_layouts)
