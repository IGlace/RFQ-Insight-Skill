"""Native per-format text extraction.

Replaces the Power Automate OCR path: every file type is parsed with the
library that understands it, so text arrives structured instead of
flattened. The single biggest quality lever here is TABLES - they come out
as real markdown pipe tables, which is the shape the analysis prompt is
told to produce. The prompt's garbled-table reconstruction protocol stays
in place as a safety net.

Images cannot be read here. They are unpacked to bytes, given a stable id
and an inline marker at the position they occurred, and handed upward for a
vision pass (see images.py and merge_image_text.py). Putting the
transcription back at its original position keeps the surrounding context
and keeps `evidence_files` naming the parent file.

An image id is `<key>__imgNN`, where `key` identifies the CORPUS ENTRY the
picture came from - not its filename. Everything downstream (the file on
disk, the marker in the text, the transcription filename, the merge) keys
on that id, so it has to be unique across the whole corpus. See image_key.
"""

import io
import os
from dataclasses import dataclass, field

SUPPORTED_EXTENSIONS = {".docx", ".pptx", ".xlsx", ".pdf", ".csv", ".txt",
                        ".png", ".jpg", ".jpeg"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}

# Carried over from the Power Automate corpus contract so the per-file
# metadata keys in corpus.json stay recognisable.
CATEGORY = {
    ".pdf": "pdf", ".png": "image", ".jpg": "image", ".jpeg": "image",
    ".docx": "office_doc", ".pptx": "office_slide", ".xlsx": "office_sheet",
    ".csv": "text_csv", ".txt": "text_plain",
}
METHOD = {
    ".pdf": "pdfplumber", ".docx": "python-docx", ".pptx": "python-pptx",
    ".xlsx": "openpyxl", ".csv": "raw_text", ".txt": "raw_text",
    ".png": "vision", ".jpg": "vision", ".jpeg": "vision",
}

_ENCODINGS = ("utf-8-sig", "utf-8", "cp1252", "latin-1")


class UnreadableFile(Exception):
    """A file we support but could not read.

    `reason` is shown to the user and is always plain language. `detail`
    carries the technical cause for the run report and is never surfaced to
    a salesperson. The spec requires both audiences be served separately;
    one string cannot do it.
    """

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


def image_key(rel_path: str) -> str:
    """A readable, filesystem-safe identity for one corpus entry.

    Image ids have to be unique across the CORPUS, not across a folder.
    Two files can share a basename in different subfolders
    (annexes/Spec.docx and attachments/Spec.docx), and an id built from the
    basename alone would give both documents the same id: one image's bytes
    would overwrite the other's on disk, and the merge would hand one
    document a verbatim transcription of a chart it does not contain.

    The path relative to the RFQ folder is unique by construction. Slugging
    it keeps the id usable as a filename and still readable in a message to
    the user - a file at the top of the folder keeps its plain name.
    """
    import re
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", rel_path or "")
    return slug.strip("_") or "file"


@dataclass
class RawImage:
    """One image pulled out of a document, before filtering."""
    source: str              # parent filename, e.g. "SOR.docx"
    ordinal: int             # 1-based within the parent
    data: bytes
    ext: str                 # ".png", ".jpeg", ...
    locator: str = ""        # "paragraph 47" / "slide 3" / "page 12" / "standalone"
    key: str = ""            # corpus-unique identity; defaults to `source`
    presized: bool = False   # producer already applied a size judgement

    def __post_init__(self):
        # `source` stays the DISPLAY name - it is what the user is shown and
        # what `evidence_files` names. `key` is the identity. They differ
        # only when two corpus entries share a basename.
        if not self.key:
            self.key = self.source

    @property
    def image_id(self) -> str:
        return f"{self.key}__img{self.ordinal:02d}"


@dataclass
class Extracted:
    text: str
    images: list = field(default_factory=list)


class _ImageCollector:
    def __init__(self, source: str, key: str = ""):
        self.source = source
        self.key = key or source
        self.images: list = []

    def add(self, data: bytes, ext: str, locator: str,
            presized: bool = False) -> RawImage:
        img = RawImage(self.source, len(self.images) + 1, data,
                       (ext or ".png").lower(), locator, self.key, presized)
        self.images.append(img)
        return img


def marker_for(image_id: str) -> str:
    """The placeholder left where an image was, replaced by its
    transcription in merge_image_text.py."""
    return f"[[EMBEDDED IMAGE {image_id} — transcription pending]]"


def _why(exc: Exception) -> tuple:
    """(reason for the user, detail for the run report)."""
    detail = f"{type(exc).__name__}: {exc}"
    text = detail.lower()
    if "password" in text or "encrypt" in text:
        return "password-protected", detail
    if "permission" in text or "being used by another" in text:
        return "locked by another program", detail
    if ("not a zip" in text or "badzipfile" in text
            or "file is not a" in text or "no such" in text
            or "cannot be opened" in text or "package not found" in text):
        # "package not found" also fires when the file has vanished between
        # the folder scan and the open. Same advice either way: the file the
        # name points at is not a usable document.
        return "corrupt, or not really the file type its name says", detail
    return "I couldn't open it", detail


def _docx_row_cells(row) -> list:
    """One value per grid position, with a merged cell's text appearing only
    in the first position it spans.

    python-docx returns the same underlying <tc> for every position a merged
    cell covers, so reading .text per position would repeat the value across
    the span and widen the table with phantom data.
    """
    seen, cells = set(), []
    for cell in row.cells:
        key = id(cell._tc)
        if key in seen:
            cells.append("")
        else:
            seen.add(key)
            cells.append(cell.text)
    return cells


def _pptx_row_cells(row) -> list:
    """Same rule as the docx helper: a spanned cell contributes once."""
    return ["" if getattr(cell, "is_spanned", False) else cell.text
            for cell in row.cells]


def rows_to_markdown(rows) -> str:
    """Render table rows as a markdown pipe table. Row 0 is the header.

    Empty rows are dropped, ragged rows padded, embedded newlines collapsed
    and literal pipes escaped, so one cell can never break the table shape.
    """
    import re
    cleaned = []
    for row in rows:
        cells = [re.sub(r"\s+", " ", str("" if c is None else c)).strip()
                 .replace("|", "\\|") for c in row]
        if any(cells):
            cleaned.append(cells)
    if not cleaned:
        return ""
    width = max(len(r) for r in cleaned)
    cleaned = [r + [""] * (width - len(r)) for r in cleaned]
    header, body = cleaned[0], cleaned[1:]
    out = ["| " + " | ".join(header) + " |",
           "| " + " | ".join(["---"] * width) + " |"]
    out.extend("| " + " | ".join(r) + " |" for r in body)
    return "\n".join(out)


# ------------------------------------------------------------------- docx
def extract_docx(path: str, key: str = "") -> Extracted:
    """Paragraphs in document order, tables as pipe tables, and every
    embedded picture unpacked with a marker where it occurred."""
    import docx
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    try:
        document = docx.Document(path)
    except Exception as exc:
        raise UnreadableFile(*_why(exc)) from exc

    blip_tag, embed_attr = qn("a:blip"), qn("r:embed")
    collector = _ImageCollector(os.path.basename(path), key)
    parts: list = []
    para_no = 0

    for child in document.element.body.iterchildren():
        tag = child.tag.split("}")[-1]
        if tag == "p":
            para_no += 1
            for blip in child.iter(blip_tag):
                rid = blip.get(embed_attr)
                related = (document.part.related_parts.get(rid)
                           if rid else None)
                if related is None:
                    continue
                img = collector.add(
                    related.blob,
                    os.path.splitext(str(related.partname))[1],
                    f"paragraph {para_no}")
                parts.append(marker_for(img.image_id))
            text = Paragraph(child, document).text.strip()
            if text:
                parts.append(text)
        elif tag == "tbl":
            table = Table(child, document)
            md = rows_to_markdown([_docx_row_cells(r) for r in table.rows])
            if md:
                parts.append(md)

    return Extracted("\n\n".join(parts), collector.images)


# ------------------------------------------------------------------- pptx
def extract_pptx(path: str, key: str = "") -> Extracted:
    """Per slide: title, body text, tables as pipe tables, speaker notes."""
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    try:
        prs = Presentation(path)
    except Exception as exc:
        raise UnreadableFile(*_why(exc)) from exc

    collector = _ImageCollector(os.path.basename(path), key)
    parts: list = []

    for n, slide in enumerate(prs.slides, start=1):
        chunk = [f"--- Slide {n} ---"]
        title_shape = slide.shapes.title
        title = title_shape.text.strip() if title_shape is not None else ""
        if title:
            chunk.append(f"Title: {title}")
        for shape in slide.shapes:
            if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                img = collector.add(shape.image.blob,
                                    "." + str(shape.image.ext).lstrip("."),
                                    f"slide {n}")
                chunk.append(marker_for(img.image_id))
                continue
            if shape.has_table:
                md = rows_to_markdown([_pptx_row_cells(r)
                                       for r in shape.table.rows])
                if md:
                    chunk.append(md)
                continue
            if shape.has_text_frame:
                text = shape.text_frame.text.strip()
                if text and text != title:
                    chunk.append(text)
        if slide.has_notes_slide:
            notes = slide.notes_slide.notes_text_frame.text.strip()
            if notes:
                chunk.append(f"Speaker notes: {notes}")
        parts.append("\n".join(chunk))

    return Extracted("\n\n".join(parts), collector.images)


# ------------------------------------------------------------------- xlsx
def extract_xlsx(path: str, key: str = "") -> Extracted:
    """Per sheet: header + rows as a pipe table, empty rows skipped."""
    from openpyxl import load_workbook

    try:
        wb = load_workbook(path, data_only=True, read_only=True)
    except Exception as exc:
        raise UnreadableFile(*_why(exc)) from exc

    parts: list = []
    try:
        for ws in wb.worksheets:
            rows = []
            for row in ws.iter_rows(values_only=True):
                cells = ["" if v is None else str(v) for v in row]
                if any(c.strip() for c in cells):
                    rows.append(cells)
            md = rows_to_markdown(rows)
            if md:
                parts.append(f"--- Sheet: {ws.title} ---\n{md}")
    except Exception as exc:
        raise UnreadableFile(*_why(exc)) from exc
    finally:
        wb.close()

    return Extracted("\n\n".join(parts), [])


# -------------------------------------------------------------------- pdf
# Render density for anything handed to the visual pass. 300 dpi is the
# long-standing floor for reading text off a scan, and these renders exist
# to be read: at 150 dpi the annotation text on a dense process-flow diagram
# is illegible, so the figure gets flagged, comes back transcribed as
# unreadable, and the flagging achieves nothing for exactly the figures
# worth the most. Measured on a real package: a module PFD whose equipment
# tags and stack ratings were unreadable at 150 and plain at 300.
RENDER_DPI = 300


def _page_png(page) -> bytes:
    """Render a page to PNG so a scanned page can be read visually."""
    buf = io.BytesIO()
    page.to_image(resolution=RENDER_DPI).original.save(buf, format="PNG")
    return buf.getvalue()


# A figure embedded in a text-bearing PDF page has to be worth a visual read
# before we cut it out. Expressed in PDF points (72 per inch), so this is
# about 0.8 x 0.14 inches — the size of a single line of small text.
#
# Deliberately set at LABEL size, not chart size, and the cost of that is
# accepted. Two findings from a real package drove it down here. Its only
# telephone number and the engineering firm's name sat inside a 188 x 42
# point letterhead strip. Worse, its seismic sheet rendered the standard's
# version as a 72 x 17 point PICTURE reading "ASCE 7-22" over a text layer
# that still said "ASCE 7-16" — a version number is exactly the identifier
# the analysis prompt requires be reproduced exactly, and a chart-sized
# floor silently reported the wrong one.
#
# This flags several times more figures per package than a chart-sized floor
# would. That is the intended trade: the knowledge pack names letterheads,
# signature blocks and footers as the first places contact details hide, and
# a missed contact or a wrong standard version is a reported error, while an
# extra transcription is only time.
MIN_PDF_IMAGE_POINTS = 60 * 10


def _page_region_png(page, bbox) -> bytes:
    """Render one region of a page to PNG.

    Cropping and rendering rather than pulling the embedded stream out: PDF
    images arrive in several encodings (DCTDecode, FlateDecode, CCITT) and
    some carry no standalone container, so reconstructing bytes per encoding
    is far more fragile than asking the renderer for the pixels.
    """
    x0, top, x1, bottom = bbox
    x0 = max(x0, page.bbox[0])
    top = max(top, page.bbox[1])
    x1 = min(x1, page.bbox[2])
    bottom = min(bottom, page.bbox[3])
    buf = io.BytesIO()
    page.crop((x0, top, x1, bottom)).to_image(resolution=RENDER_DPI) \
        .original.save(buf, format="PNG")
    return buf.getvalue()


def _widen_to_graphic_band(page, bbox):
    """Grow a figure's box sideways over adjoining artwork that holds no text.

    Some content is drawn as VECTOR PATHS rather than set as text or placed
    as a bitmap. A letterhead is the common case: the logo is a bitmap, and
    the company name, address and phone beside it are outlined shapes. Such
    a block is invisible three times over — extract_text finds no words,
    page.images does not list it, and cropping the bitmap alone cuts it off
    the right-hand edge. Only rendering reveals it, which is exactly how the
    OCR-based system this skill replaces used to read it.

    So the crop grows horizontally across the figure's own rows to take in
    neighbouring vector artwork, and stops the moment a real text word falls
    inside — body text is already extracted and must not be duplicated.
    """
    x0, top, x1, bottom = bbox
    px0, ptop, px1, pbottom = page.bbox
    band_top, band_bottom = top - 4, bottom + 4

    def in_band(o):
        try:
            return (float(o["bottom"]) > band_top
                    and float(o["top"]) < band_bottom)
        except (KeyError, TypeError, ValueError):
            return False

    grown_x0, grown_x1 = x0, x1
    grown_top, grown_bottom = top, bottom
    for obj in list(page.rects or []) + list(page.curves or []):
        if in_band(obj):
            try:
                grown_x0 = min(grown_x0, float(obj["x0"]))
                grown_x1 = max(grown_x1, float(obj["x1"]))
                # Vector lettering usually overshoots the bitmap's rows
                # slightly; without this the first and last lines of an
                # address block come out sliced in half.
                grown_top = min(grown_top, float(obj["top"]))
                grown_bottom = max(grown_bottom, float(obj["bottom"]))
            except (KeyError, TypeError, ValueError):
                continue

    # Never swallow extracted text: that content is already in the corpus,
    # and a transcription of it would duplicate rather than add.
    try:
        words = page.extract_words() or []
    except Exception:
        words = []
    for w in words:
        try:
            if (float(w["bottom"]) > grown_top and float(w["top"]) < grown_bottom
                    and float(w["x1"]) > grown_x0
                    and float(w["x0"]) < grown_x1):
                return (x0, top, x1, bottom)
        except (KeyError, TypeError, ValueError):
            continue

    return (max(grown_x0, px0), max(grown_top, ptop),
            min(grown_x1, px1), min(grown_bottom, pbottom))


def _embedded_page_images(page):
    """(boxes worth reading, count of figures below the floor).

    A page that HAS a text layer still hides content inside its figures —
    letterheads carrying a company name and phone number, charts, scanned
    tables, labels rendered as pictures. Native text extraction cannot see
    any of it, whereas OCR-the-whole-page (what this skill replaced) always
    could. Unpacking them here closes that regression.

    The count of figures below the floor is returned rather than discarded:
    those are usually icons and rules, but not always, and a silent loss is
    worse than a noted one.
    """
    found, skipped = [], 0
    for im in page.images or []:
        try:
            x0, top = float(im["x0"]), float(im["top"])
            x1, bottom = float(im["x1"]), float(im["bottom"])
        except (KeyError, TypeError, ValueError):
            continue
        if (x1 - x0) * (bottom - top) >= MIN_PDF_IMAGE_POINTS:
            found.append(_widen_to_graphic_band(page, (x0, top, x1, bottom)))
        else:
            skipped += 1
    # Reading order: top to bottom, then left to right. Deterministic, and it
    # keeps each marker near the text it sits beside.
    found.sort(key=lambda b: (round(b[1], 1), round(b[0], 1)))
    return found, skipped


def extract_pdf(path: str, key: str = "") -> Extracted:
    """Text layer plus extract_tables() per page. A page with no text layer
    is a scan: it is rendered to PNG and marked for a visual read, which is
    what the old OCR-the-whole-PDF path used to cover."""
    import pdfplumber

    collector = _ImageCollector(os.path.basename(path), key)
    parts: list = []
    try:
        with pdfplumber.open(path) as pdf:
            for n, page in enumerate(pdf.pages, start=1):
                chunk = [f"--- Page {n} ---"]
                text = (page.extract_text() or "").strip()
                if text:
                    chunk.append(text)
                for table in (page.extract_tables() or []):
                    md = rows_to_markdown(table)
                    if md:
                        chunk.append(md)
                if not text:
                    try:
                        img = collector.add(_page_png(page), ".png",
                                            f"page {n}")
                        chunk.append(marker_for(img.image_id))
                    except Exception:
                        chunk.append(f"[[PAGE {n} could not be read]]")
                else:
                    # The page has text, but its figures do not. Each one is
                    # cut out and marked so the visual pass can read it.
                    boxes, skipped = _embedded_page_images(page)
                    for bbox in boxes:
                        try:
                            img = collector.add(_page_region_png(page, bbox),
                                                ".png", f"page {n}",
                                                presized=True)
                        except Exception:
                            continue
                        chunk.append(marker_for(img.image_id))
                    if skipped:
                        # Say so rather than lose it silently. Small figures
                        # are usually icons, but a label rendered as an image
                        # can carry a standard's version number — one real
                        # package showed "ASCE 7-22" as a picture over a text
                        # layer still reading "ASCE 7-16".
                        chunk.append(
                            f"[[{skipped} small figure(s) on this page were "
                            f"not read; any text inside them is missing]]")
                parts.append("\n".join(chunk))
    except Exception as exc:
        raise UnreadableFile(*_why(exc)) from exc

    return Extracted("\n\n".join(parts), collector.images)


# ------------------------------------------------------------- text / csv
def extract_text_file(path: str, key: str = "") -> Extracted:
    """.txt and .csv, decoded and normalized to \n line endings.

    Encodings are tried in order of likelihood. Line endings are normalized
    because a corpus that mixes CRLF and LF makes every downstream character
    count and diff platform-dependent for no benefit.
    """
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except Exception as exc:
        raise UnreadableFile(*_why(exc)) from exc
    for encoding in _ENCODINGS:
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", errors="replace")
    return Extracted(text.replace("\r\n", "\n").replace("\r", "\n"), [])


# --------------------------------------------------------------- dispatch
_DISPATCH = {
    ".docx": extract_docx,
    ".pptx": extract_pptx,
    ".xlsx": extract_xlsx,
    ".pdf": extract_pdf,
    ".csv": extract_text_file,
    ".txt": extract_text_file,
}


def extract_file(path: str, key: str = "") -> Extracted:
    """Extract one file. Raises UnreadableFile with a plain-language reason.

    `key` is the corpus-unique identity every image found here is stamped
    with (see image_key). It defaults to the basename, which is correct
    whenever the corpus holds no two files of that name.
    """
    ext = os.path.splitext(path)[1].lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise UnreadableFile("unsupported file type")
    if ext in IMAGE_EXTENSIONS:
        try:
            with open(path, "rb") as fh:
                data = fh.read()
        except Exception as exc:
            raise UnreadableFile(*_why(exc)) from exc
        name = os.path.basename(path)
        return Extracted("", [RawImage(name, 1, data, ext, "standalone",
                                       key or name)])
    return _DISPATCH[ext](path, key)
