#!/usr/bin/env python3
"""Reduce an AVL-styled .pptx to its slide master, layouts and theme.

    python tools/make_template.py <source.pptx> <out.pptx>

The renderer opens the result instead of a blank presentation, so decks
inherit the AVL master. Everything a slide owns is removed: the slides, their
notes and relationships, the media only they used, the section list and
change history that name them, the thumbnail and the slide titles in
docProps/app.xml. Layout and master pictures (backgrounds, logo) stay.

The package is edited as text with `re` and `zipfile`; it is never parsed and
re-serialised, so namespaces and extension lists survive byte for byte.
"""

import argparse
import posixpath
import re
import sys
import zipfile

CONTENT_TYPES = "[Content_Types].xml"
PRESENTATION = "ppt/presentation.xml"
PRESENTATION_RELS = "ppt/_rels/presentation.xml.rels"
ROOT_RELS = "_rels/.rels"
APP_PROPS = "docProps/app.xml"
THUMBNAIL = "docProps/thumbnail.jpeg"

# Parts that belong to the source deck's content, not to its master.
DROP_PREFIXES = ("ppt/slides/", "ppt/notesSlides/", "ppt/changesInfos/", "[trash]/")
DROP_PARTS = {THUMBNAIL}

_REL = re.compile(r"<Relationship\b[^>]*?/>")
_OVERRIDE = re.compile(r"<Override\b[^>]*?/>")


def _attr(tag, name):
    match = re.search(r'\b%s="([^"]*)"' % name, tag)
    return match.group(1) if match else ""


def _dropped(name):
    return name in DROP_PARTS or name.startswith(DROP_PREFIXES)


def _resolve(source_part, target):
    """Absolute package path that `target` names from a .rels file's owner."""
    if target.startswith("/"):
        return target.lstrip("/")
    owner_dir = posixpath.dirname(posixpath.dirname(source_part))
    return posixpath.normpath(posixpath.join(owner_dir, target))


def _drop_relationships(xml, source_part):
    """Remove Relationship elements whose internal target is a dropped part."""
    def keep(match):
        tag = match.group(0)
        if _attr(tag, "TargetMode") == "External":
            return tag
        return "" if _dropped(_resolve(source_part, _attr(tag, "Target"))) else tag
    return _REL.sub(keep, xml)


def _strip_presentation(xml):
    xml = re.sub(r"<p:sldId\b[^>]*?/>", "", xml)
    # Sections list slide ids; with no slides the whole extension is stale.
    xml = re.sub(r"<p:ext\b[^>]*>\s*<p14:sectionLst\b.*?</p14:sectionLst>\s*</p:ext>",
                 "", xml, flags=re.S)
    return xml


def _strip_content_types(xml):
    def keep(match):
        part = _attr(match.group(0), "PartName").lstrip("/")
        return "" if _dropped(part) else match.group(0)
    return _OVERRIDE.sub(keep, xml)


def _strip_app_properties(xml):
    """Zero the slide statistics and forget the slide titles."""
    for tag in ("Slides", "Notes", "HiddenSlides", "Words", "Paragraphs", "MMClips"):
        xml = re.sub(r"<%s>\d+</%s>" % (tag, tag), "<%s>0</%s>" % (tag, tag), xml)
    xml = re.sub(r"<HeadingPairs>.*?</HeadingPairs>", "", xml, flags=re.S)
    xml = re.sub(r"<TitlesOfParts>.*?</TitlesOfParts>", "", xml, flags=re.S)
    return xml


def _referenced_media(parts):
    referenced = set()
    for name, data in parts.items():
        if not name.endswith(".rels"):
            continue
        for tag in _REL.findall(data.decode("utf-8")):
            if _attr(tag, "TargetMode") == "External":
                continue
            target = _resolve(name, _attr(tag, "Target"))
            if target.startswith("ppt/media/"):
                referenced.add(target)
    return referenced


def strip_to_master(src, out):
    """Write `out` as `src` without slides; return what was removed."""
    with zipfile.ZipFile(src) as zin:
        order = [i.filename for i in zin.infolist() if not i.filename.endswith("/")]
        parts = {name: zin.read(name) for name in order}

    slides_removed = sum(1 for n in parts
                         if re.fullmatch(r"ppt/slides/slide\d+\.xml", n))
    for name in [n for n in parts if _dropped(n)]:
        del parts[name]

    def edit(name, fn, *args):
        if name in parts:
            parts[name] = fn(parts[name].decode("utf-8"), *args).encode("utf-8")

    edit(PRESENTATION, _strip_presentation)
    edit(PRESENTATION_RELS, _drop_relationships, PRESENTATION_RELS)
    edit(ROOT_RELS, _drop_relationships, ROOT_RELS)
    edit(CONTENT_TYPES, _strip_content_types)
    edit(APP_PROPS, _strip_app_properties)

    keep_media = _referenced_media(parts)
    orphans = [n for n in parts if n.startswith("ppt/media/") and n not in keep_media]
    for name in orphans:
        del parts[name]

    names = [n for n in order if n in parts]
    names.sort(key=lambda n: n != CONTENT_TYPES)  # stable: only moves it first
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for name in names:
            zout.writestr(name, parts[name])
    return {"slides_removed": slides_removed, "media_removed": len(orphans)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("source", help="the styled .pptx to reduce")
    parser.add_argument("out", help="where to write the slide-free template")
    args = parser.parse_args(argv)
    result = strip_to_master(args.source, args.out)
    print("removed %(slides_removed)d slides and %(media_removed)d media files"
          % result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
