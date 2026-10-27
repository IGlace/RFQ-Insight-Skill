"""Where each answer comes from: locator parsing, corpus checks, source line.

Stage 1 cites `sources` = [{"filename", "locator"}] per section. This module
is the single authority on what a locator may look like, whether it exists in
the corpus, and how the deck prints it. The model never writes the printed
line - rfq/delivery.py builds it here, deterministically.

A locator points at a marker the extractors already write into the corpus:

    "p. 12" / "p. 12-13"     ->  --- Page 12 ---        (PDF)
    "slide 3" / "slide 3-4"  ->  --- Slide 3 ---        (PowerPoint)
    "sheet 'Plan'"           ->  --- Sheet: Plan ---    (Excel)
    "section 3.2 Timing"     ->  --- Section: 3.2 Timing ---  (Word heading)
    "p. 12; section Scope"    ->  both markers in the same source region
    ""                       ->  a file without stable location markers
    "whole file (location unavailable)" -> explicit coverage limitation

Pages and slides may also be listed ("pp. 12, 14", "p. 12 f." = 12-13):
the parsed tuple is then (kind, a1, b1, a2, b2, ...), one pair per range.
"""

import re
import hashlib
import json

from .guidance import INFO_NOT_AVAILABLE
from .schema import ADDITIONAL_INFO_ID, OPPORTUNITY, SOURCES

NOT_FOUND_LINE = "Source: not found in the RFQ documents"
# Section 1's Account Name and KAM come from the Salesforce account list
# (rfq/guidance.py), not from the RFQ - named last on that section's line.
ACCOUNT_LIST_SOURCE = "Salesforce account list"
LINE_CHARS = 150          # fits the content width on one line at 8 pt
_PREFIX = "Source: "

_DASH = r"\s*[-\u2010-\u2015]\s*"
_PAGE_RE = re.compile(r"^(?:pages?|pg\.?|pp?\.?)\s*(\d.*)$", re.IGNORECASE)
_SLIDE_RE = re.compile(r"^slides?\s*(\d.*)$", re.IGNORECASE)
# One range of a page/slide list: "12", "12-13" or "12 f." (= 12-13).
_SPAN_RE = re.compile(r"^(\d+)(?:" + _DASH + r"(\d+)|\s*(f)\.?)?$",
                      re.IGNORECASE)
_BARE_SHEET_RE = re.compile(r"^sheet\d+$", re.IGNORECASE)     # "Sheet1"
_SHEET_RE = re.compile(r"^sheet\s*:?\s*(.+)$", re.IGNORECASE)
_SECTION_RE = re.compile(r"^(?:section|chapter)\s*:?\s*(.+)$", re.IGNORECASE)
_SHEET_MARKER_RE = re.compile(r"^--- Sheet: (.+?) ---$", re.MULTILINE)
_SECTION_MARKER_RE = re.compile(r"^--- Section: (.+?) ---$", re.MULTILINE)
_SECTION_PATH_RE = re.compile(r"^--- Section Path: (.+?) ---$", re.MULTILINE)
_LOCATION_MARKER_RE = re.compile(r"^--- (?:Page \d+|Slide \d+|Sheet: .+|Section: .+) ---$", re.MULTILINE)
_RENDERED_SPAN_RE = re.compile(r"\[\[(Table|Paragraph) spans rendered pages (\d+)-(\d+)\]\]")
WHOLE_FILE_LIMITATION = "whole file (location unavailable)"
_QUOTES = "'\"\u2018\u2019\u201c\u201d"
# A corpus writes typographic dashes and quotes, a model types ASCII: every
# dash (U+2010-U+2015) compares as "-" and quote marks are dropped
# wherever they stand, on both sides of the comparison.
_SPELLING = str.maketrans({**{chr(c): "-" for c in range(0x2010, 0x2016)},
                           **{q: None for q in _QUOTES}})
_LIST_MAX = 15            # names a repair message lists before "…"

LOCATOR_HELP = ("'p. 12', 'p. 12-13', 'slide 3', \"sheet 'Name'\", "
                "'section <heading text>', 'p. 12; section <heading text>', "
                "'whole file (location unavailable)', or empty for files "
                "without location markers")


def reference_catalogue(corpus):
    """Generate current-evidence IDs for verified file/page/chapter regions.

    IDs bind to the whole file's evidence, including merged figure text, so
    a citation cannot silently reuse an ID after the source changes.
    """
    rows = []
    files = [f for f in corpus.get("filesContents", []) if isinstance(f, dict)]
    counts = {}
    for file in files:
        counts[file.get("filename")] = counts.get(file.get("filename"), 0) + 1
    for file in files:
        filename = file.get("filename", "")
        if not filename or counts[filename] != 1:
            # Legacy filename citations cannot distinguish duplicate basenames.
            # Never supply apparently precise IDs for that ambiguity.
            continue
        text = file.get("extracted_text", "") or ""
        identity = hashlib.sha256(json.dumps({"path": file.get("path", filename),
            "sha256": file.get("sha256"), "text": text}, ensure_ascii=False,
            sort_keys=True).encode("utf-8")).hexdigest()
        candidates = [] if _LOCATION_MARKER_RE.search(text) else [""]
        page, heading, section_path = None, None, None
        for line in text.splitlines():
            match = re.fullmatch(r"--- Page (\d+) ---", line)
            if match:
                page = int(match[1])
                candidates.append(f"p. {page}")
                if heading:
                    candidates.append(f"p. {page}; section {section_path or heading}")
            match = _SECTION_MARKER_RE.fullmatch(line)
            if match:
                heading, section_path = match[1], None
                candidates.append("section " + heading)
                if page:
                    candidates.append(f"p. {page}; section {heading}")
            match = _SECTION_PATH_RE.fullmatch(line)
            if match:
                section_path = match[1]
                candidates.append("section " + section_path)
                if page:
                    candidates.append(f"p. {page}; section {section_path}")
            match = re.fullmatch(r"--- Slide (\d+) ---", line)
            if match:
                candidates.append("slide " + match[1])
            match = _SHEET_MARKER_RE.fullmatch(line)
            if match:
                candidates.append("sheet '" + match[1] + "'")
            match = _RENDERED_SPAN_RE.fullmatch(line)
            if match:
                span = f"p. {match[2]}-{match[3]}"
                candidates.append(span)
                if heading:
                    candidates.append(span + "; section " + (section_path or heading))
        for locator in dict.fromkeys(candidates):
            parsed = parse_locator(locator)
            if parsed is None or not locator_exists(text, parsed):
                continue
            ref_id = "src-" + hashlib.sha256((identity + "\n" + locator).encode("utf-8")).hexdigest()[:24]
            rows.append({"id": ref_id, "filename": filename, "locator": locator,
                         "path": file.get("path", filename)})
    return {"version": 1, "references": rows}


def expand_reference_ids(refs, corpus, catalog=None):
    """Expand IDs using a current caller index; legacy sources need no catalogue."""
    if not isinstance(refs, list) or not any(
            isinstance(ref, dict) and "ref_id" in ref for ref in refs):
        return refs
    if catalog is None:
        catalog = {row["id"]: row for row in reference_catalogue(corpus)["references"]}
    expanded = []
    for ref in refs:
        if not isinstance(ref, dict) or "ref_id" not in ref:
            expanded.append(ref)
            continue
        if set(ref) != {"ref_id"}:
            raise ValueError("A source reference ID object must contain only ref_id.")
        row = catalog.get(ref["ref_id"]) if isinstance(ref["ref_id"], str) else None
        if row is None:
            raise ValueError("Unknown or stale source reference ID; select a current catalogue entry.")
        expanded.append({"filename": row["filename"], "locator": row["locator"]})
    return expanded


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text).translate(_SPELLING)).strip().casefold()


def _spans(text: str):
    """'12', '12-13', '12 f.' or a comma list of them -> (a1, b1, ...), or
    None when any part is not a valid range."""
    out = []
    for part in text.split(","):
        m = _SPAN_RE.match(part.strip())
        if not m:
            return None
        a = int(m.group(1))
        b = int(m.group(2)) if m.group(2) else a + 1 if m.group(3) else a
        if not 0 < a <= b:
            return None
        out += [a, b]
    return tuple(out)


def _pairs(parsed) -> list:
    return list(zip(parsed[1::2], parsed[2::2]))


def _numbers(parsed) -> list:
    return [n for a, b in _pairs(parsed) for n in range(a, b + 1)]


def _span_text(parsed) -> str:
    return ", ".join(str(a) if a == b else f"{a}-{b}" for a, b in _pairs(parsed))


def parse_locator(locator: str):
    """Locator string -> tuple, or None when it is not a valid locator."""
    loc = re.sub(r"\s+", " ", str(locator or "")).strip()
    if not loc:
        return ("none",)
    if loc.casefold() == WHOLE_FILE_LIMITATION:
        return ("whole",)
    # Exactly two independently validated locators. A section may contain
    # punctuation, so split only at the page/section boundary.
    composite = re.match(r"^((?:pages?|pg\.?|pp?\.?)\s*\d[^;]*);\s*((?:section|chapter)\s*:.+|(?:section|chapter)\s+.+)$", loc, re.IGNORECASE)
    if composite:
        page, section = parse_locator(composite[1]), parse_locator(composite[2])
        return ("composite", page, section) if page and section else None
    reverse = re.match(r"^((?:section|chapter)\s+.+);\s*((?:pages?|pg\.?|pp?\.?)\s*\d[^;]*)$", loc, re.IGNORECASE)
    if reverse:
        section, page = parse_locator(reverse[1]), parse_locator(reverse[2])
        return ("composite", page, section) if page and section else None
    for kind, rx in (("page", _PAGE_RE), ("slide", _SLIDE_RE)):
        m = rx.match(loc)
        if m:
            spans = _spans(m.group(1))
            return (kind, *spans) if spans else None
    if _BARE_SHEET_RE.match(loc):
        return ("sheet", loc)
    m = _SHEET_RE.match(loc)
    if m:
        name = m.group(1).strip().strip(_QUOTES).strip()
        return ("sheet", name) if name else None
    m = _SECTION_RE.match(loc)
    if m:
        text = m.group(1).strip()
        return ("section", text) if text else None
    return None


def canonical_locator(parsed) -> str:
    kind = parsed[0]
    if kind == "whole":
        return WHOLE_FILE_LIMITATION
    if kind == "composite":
        return "; ".join(canonical_locator(p) for p in parsed[1:])
    if kind in ("page", "slide"):
        label = "p." if kind == "page" else "slide"
        return f"{label} {_span_text(parsed)}"
    if kind == "sheet":
        return f"sheet '{parsed[1]}'"
    if kind == "section":
        return f"section {parsed[1]}"
    return ""


def _describe(parsed) -> str:
    kind = parsed[0]
    if kind == "composite":
        return "combined " + canonical_locator(parsed)
    if kind in ("page", "slide"):
        one = len(parsed) == 3 and parsed[1] == parsed[2]
        return f"{kind}{'' if one else 's'} {_span_text(parsed)}"
    if kind == "sheet":
        return f"sheet '{parsed[1]}'"
    return f"section heading matching '{parsed[1]}'"


def _marker_names(texts, kind) -> list:
    """The sheet names or section headings of a file, as its markers write
    them, in order, each once."""
    rx = _SHEET_MARKER_RE if kind == "sheet" else _SECTION_MARKER_RE
    names = []
    for text in texts:
        for name in rx.findall(text or ""):
            if name not in names:
                names.append(name)
    return names


def _match_name(names, parsed):
    """The marker name a sheet/section locator points at, or None. A sheet
    must match whole; a partial section heading must identify exactly one."""
    want = _norm(parsed[1])
    if not want:
        return None
    exact = [n for n in names if _norm(n) == want]
    if len(exact) == 1:
        return exact[0]
    if parsed[0] == "sheet" or exact:
        return None
    matches = [n for n in names if want in _norm(n)]
    return matches[0] if len(matches) == 1 else None


def _section_name(texts, parsed):
    names = _marker_names(texts, "section")
    if " > " in parsed[1]:
        paths = [p for text in texts for p in _SECTION_PATH_RE.findall(text or "")]
        found = _match_name(list(dict.fromkeys(paths)), parsed)
        return found.rsplit(" > ", 1)[-1] if found else None
    found = _match_name(names, parsed)
    if found is not None:
        paths = {p for text in texts for p in _SECTION_PATH_RE.findall(text or "")
                 if _norm(p.rsplit(" > ", 1)[-1]) == _norm(found)}
        if len(paths) > 1:
            return None
    return found


def locator_exists(text: str, parsed) -> bool:
    """True when the location marker(s) for `parsed` occur in `text`."""
    kind = parsed[0]
    text = text or ""
    if kind in ("none", "whole"):
        return True
    if kind == "composite":
        page, section = parsed[1:]
        if not locator_exists(text, page):
            return False
        found = _section_name([text], section)
        if found is None:
            return False
        # A correct page and a correct section in unrelated document regions
        # are insufficient. Track where each section occurs on real pages.
        active, current = False, None
        qualified = " > " in section[1]
        matched_path = (_match_name(list(dict.fromkeys(_SECTION_PATH_RE.findall(text))), section)
                        if qualified else None)
        heading_pages = set()
        for line in text.splitlines():
            marker = re.fullmatch(r"--- Page (\d+) ---", line)
            if marker:
                current = int(marker.group(1))
                continue
            heading = _SECTION_MARKER_RE.fullmatch(line)
            if heading:
                active = not qualified and _norm(heading.group(1)) == _norm(found)
            path = _SECTION_PATH_RE.fullmatch(line)
            if path:
                active = (_norm(path.group(1)) == _norm(matched_path) if qualified
                          else any(_norm(piece) == _norm(found)
                                   for piece in path.group(1).split(" > ")))
            if active and current is not None and line.strip():
                heading_pages.add(current)
                span = _RENDERED_SPAN_RE.fullmatch(line)
                if span:
                    heading_pages.update(range(int(span[2]), int(span[3]) + 1))
        return set(_numbers(page)).issubset(heading_pages)
    if kind in ("page", "slide"):
        word = "Page" if kind == "page" else "Slide"
        available = {int(n) for n in re.findall(r"^--- " + word + r" (\d+) ---$", text, re.MULTILINE)}
        if kind == "page":
            for _label, first, last in _RENDERED_SPAN_RE.findall(text):
                available.update(range(int(first), int(last) + 1))
        return set(_numbers(parsed)).issubset(available)
    if kind == "section":
        return _section_name([text], parsed) is not None
    return _match_name(_marker_names([text], kind), parsed) is not None


def _texts_by_name(files) -> dict:
    """filename -> the extracted texts of every corpus entry with that name
    (two folders may hold the same basename)."""
    texts: dict = {}
    for f in files or []:
        if isinstance(f, dict):
            texts.setdefault(f.get("filename", ""), []).append(
                f.get("extracted_text", "") or "")
    return texts


def _known_names(texts, kind) -> str:
    """' Its sheets: ...' for a repair message - the locations the model can
    really cite in that file (at most _LIST_MAX)."""
    if kind not in ("sheet", "section"):
        return ""
    what = "sheets" if kind == "sheet" else "sections"
    names = [canonical_locator((kind, n)) for n in _marker_names(texts, kind)]
    if not names:
        return f" It has no {what}."
    more = "; …" if len(names) > _LIST_MAX else ""
    return f" Its {what}: " + "; ".join(names[:_LIST_MAX]) + more + "."


def check_sources(sources, files, label, require=False) -> list:
    """Repair messages for one answer's `sources`; [] when all are valid.

    A filename may belong to several corpus entries (two folders, one
    basename) - the locator is valid when ANY of them carries the marker."""
    if not isinstance(sources, list):
        return [f"{label}: 'sources' must be a list."]
    texts = _texts_by_name(files)
    problems = []
    if require and not sources:
        problems.append(f"{label} has no sources; cite at least one corpus "
                        f"file it is based on, or set not_found to true.")
    for n, src in enumerate(sources, start=1):
        if not isinstance(src, dict):
            problems.append(f"{label} source #{n} is not an object.")
            continue
        name = str(src.get("filename", ""))
        loc = str(src.get("locator", "") or "")
        if name not in texts:
            problems.append(f"{label} source #{n}: '{name}' is not a corpus "
                            f"file; copy the name exactly from a "
                            f"=== FILE: === header.")
            continue
        parsed = parse_locator(loc)
        if parsed is None:
            problems.append(f"{label} source #{n}: locator {loc!r} is not one "
                            f"of: {LOCATOR_HELP}.")
            continue
        if parsed[0] == "none" and _needs_location(texts[name], label):
            problems.append(f"{label} source #{n}: {name} requires a specific "
                            "location from its --- markers ---; if no cited "
                            "location can be verified, explicitly use "
                            f"'{WHOLE_FILE_LIMITATION}'.")
            continue
        if not any(locator_exists(t, parsed) for t in texts[name]):
            problems.append(f"{label} source #{n}: {name} has no "
                            f"{_describe(parsed)}; cite a location that "
                            f"appears among that file's --- markers ---."
                            + _known_names(texts[name], parsed[0]))
    return problems


DOWNGRADE_NOTE = ("Specific cited locations could not be verified; sources "
                  "are explicitly marked as whole-file coverage limitations: ")


def _needs_location(texts, label):
    # Source Material inventories documents rather than evidencing a claim.
    inventory = re.fullmatch(rf"Section {SOURCES}", str(label))
    return not inventory and any(_LOCATION_MARKER_RE.search(t or "") for t in texts)


def downgrade_locators(sources, files, label) -> list:
    """Last-attempt fallback: explicitly disclose unverifiable locations.

    A real file with an invalid, ambiguous, or missing specific locator is
    marked as a whole-file coverage limitation, visible in slides and notes.
    Changes sources in place and records the original citation for the run
    report. An unknown FILE is left alone and check_sources still rejects it.
    """
    texts = _texts_by_name(files)
    changed = []
    for src in sources if isinstance(sources, list) else []:
        if not isinstance(src, dict):
            continue
        name = str(src.get("filename", ""))
        loc = str(src.get("locator", "") or "").strip()
        if name not in texts:
            continue
        parsed = parse_locator(loc)
        if (parsed is None or not any(locator_exists(t, parsed) for t in texts[name])
                or parsed[0] == "none" and _needs_location(texts[name], label)):
            src["locator"] = WHOLE_FILE_LIMITATION
            changed.append(f"{label}: {name} {loc or '(no specific location)'}")
    return changed


def corpus_spelling(sources, files) -> list:
    """A copy of `sources` whose sheet and section locators name the marker
    as the corpus writes it ("section 3.2 – Timing", not the model's
    "section 3.2 - timing"), so the printed line shows the document's own
    spelling. Pages, slides and anything unmatched stay as cited."""
    texts = _texts_by_name(files)
    out = []
    for src in sources or []:
        if isinstance(src, dict) and str(src.get("filename", "")) in texts:
            parsed = parse_locator(str(src.get("locator", "") or ""))
            if parsed is not None and parsed[0] in ("sheet", "section"):
                found = (_section_name(texts[str(src["filename"])], parsed)
                         if parsed[0] == "section" else _match_name(_marker_names(
                             texts[str(src["filename"])], parsed[0]), parsed))
                if found is not None:
                    if parsed[0] == "section" and " > " in parsed[1]:
                        found = _match_name(list(dict.fromkeys(
                            p for t in texts[str(src["filename"])]
                            for p in _SECTION_PATH_RE.findall(t))), parsed)
                    src = dict(src, locator=canonical_locator(
                        (parsed[0], found)))
            elif parsed is not None and parsed[0] == "composite":
                found = _section_name(texts[str(src["filename"])], parsed[2])
                if found is not None and any(locator_exists(t, parsed)
                                             for t in texts[str(src["filename"])]):
                    if " > " in parsed[2][1]:
                        found = _match_name(list(dict.fromkeys(
                            p for t in texts[str(src["filename"])]
                            for p in _SECTION_PATH_RE.findall(t))), parsed[2])
                    src = dict(src, locator=canonical_locator(
                        ("composite", parsed[1], ("section", found))))
            page = parsed[1] if parsed is not None and parsed[0] == "composite" else (
                parsed if parsed is not None and parsed[0] == "page" else None)
            if page is not None:
                file_texts = texts[str(src["filename"])]
                direct = {int(n) for t in file_texts for n in re.findall(
                    r"^--- Page (\d+) ---$", t, re.MULTILINE)}
                wanted = set(_numbers(page))
                missing = wanted - direct
                for t in file_texts:
                    for _kind, first, last in _RENDERED_SPAN_RE.findall(t):
                        span = set(range(int(first), int(last) + 1))
                        if missing.intersection(span):
                            wanted.update(span)
                if wanted != set(_numbers(page)):
                    expanded = parse_locator("p. " + _ranges(wanted))
                    new = ("composite", expanded, parse_locator(src["locator"])[2]) if parsed[0] == "composite" else expanded
                    src = dict(src, locator=canonical_locator(new))
        out.append(src)
    return out


def _ranges(nums) -> str:
    nums = sorted(set(nums))
    out, i = [], 0
    while i < len(nums):
        j = i
        while j + 1 < len(nums) and nums[j + 1] == nums[j] + 1:
            j += 1
        out.append(str(nums[i]) if i == j else f"{nums[i]}-{nums[j]}")
        i = j + 1
    return ", ".join(out)


def _file_part(name: str, parsed_list: list) -> str:
    pages, slides, sheets, sections = [], [], [], []
    for p in parsed_list:
        if p[0] == "composite":
            for component in p[1:]:
                if component[0] == "page":
                    pages.extend(_numbers(component))
                elif component[0] == "section" and component[1] not in sections:
                    sections.append(component[1])
        elif p[0] == "whole":
            continue
        elif p[0] == "page":
            pages.extend(_numbers(p))
        elif p[0] == "slide":
            slides.extend(_numbers(p))
        elif p[0] == "sheet" and p[1] not in sheets:
            sheets.append(p[1])
        elif p[0] == "section" and p[1] not in sections:
            sections.append(p[1])
    bits = []
    if pages:
        bits.append("p. " + _ranges(pages))
    if slides:
        bits.append("slide " + _ranges(slides))
    bits += [f"sheet '{s}'" for s in sheets]
    bits += [f"section {s}" for s in sections]
    if any(p[0] == "whole" for p in parsed_list):
        bits.append(WHOLE_FILE_LIMITATION)
    return name + (" " + ", ".join(bits) if bits else "")


def format_source_line(sources, not_found, max_chars=LINE_CHARS) -> str:
    """One printable line: files in citation order, locations merged per
    file, cut to `max_chars` with "; +N more" so it never wraps."""
    if not_found or not sources:
        return NOT_FOUND_LINE
    order, located = [], {}
    for src in sources:
        if not isinstance(src, dict):
            continue
        name = str(src.get("filename", "")).strip()
        if not name:
            continue
        if name not in located:
            order.append(name)
            located[name] = []
        parsed = parse_locator(str(src.get("locator", "") or ""))
        if parsed is not None and parsed[0] != "none":
            located[name].append(parsed)
    if not order:
        return NOT_FOUND_LINE
    parts = [_file_part(name, located[name]) for name in order]
    for k in range(len(parts), 0, -1):
        more = f"; +{len(parts) - k} more" if k < len(parts) else ""
        line = _PREFIX + "; ".join(parts[:k]) + more
        if len(line) <= max_chars:
            return line
    more = f"; +{len(parts) - 1} more" if len(parts) > 1 else ""
    room = max(max_chars - len(_PREFIX) - len(more) - 1, 1)
    if located[order[0]]:
        # Long original basenames must leave the PM a location on the slide.
        # Preserve it first, shortening only the filename; full names and
        # complete headings remain available in the source notes.
        context = _file_part("", located[order[0]]).strip()
        if len(context) + 12 < room:
            name_room = room - len(context) - 2
            return (_PREFIX + order[0][:name_room].rstrip() + "… "
                    + context + more)
        short_context = context[:max(12, room // 2)].rstrip() + "…"
        name_room = max(1, room - len(short_context) - 2)
        return (_PREFIX + order[0][:name_room].rstrip() + "… "
                + short_context + more)
    return _PREFIX + parts[0][:room].rstrip() + "…" + more


def format_source_details(sources, not_found=False, files=None) -> str:
    """Complete notes-ready citations, with real hierarchy and limitations.

    Never use the slide's 150-character truncation. When corpus evidence is
    supplied, an invalid/ambiguous locator is disclosed rather than expanded
    to the first vaguely matching heading.
    """
    if not_found or not sources:
        return NOT_FOUND_LINE
    texts = _texts_by_name(files)
    entries = {}
    for src in corpus_spelling(sources, files) if files is not None else sources:
        if not isinstance(src, dict) or not src.get("filename"):
            continue
        name = str(src["filename"])
        parsed = parse_locator(str(src.get("locator", "") or ""))
        valid = parsed is not None and (files is None or name in texts and any(
            locator_exists(t, parsed) for t in texts[name]))
        if not valid or parsed[0] == "whole":
            location = "Location: unavailable; check the whole file."
        elif parsed[0] == "none":
            location = ("Location: whole file (specific location not supplied)" if any(
                _LOCATION_MARKER_RE.search(t) for t in texts.get(name, []))
                        else "Location: whole file (no stable page or section available)")
        else:
            locations = parsed[1:] if parsed[0] == "composite" else (parsed,)
            labels = []
            for part in locations:
                kind = part[0]
                if kind == "page":
                    label = "Page" if len(_numbers(part)) == 1 else "Pages"
                    labels.append(f"{label}: {_span_text(part)}")
                elif kind == "slide":
                    label = "Slide" if len(_numbers(part)) == 1 else "Slides"
                    labels.append(f"{label}: {_span_text(part)}")
                elif kind == "sheet":
                    labels.append(f"Sheet: {part[1]}")
                elif kind == "section":
                    labels.insert(0, f"Section: {part[1]}")
            location = "\n".join(labels)
            section = parsed[2] if parsed[0] == "composite" else (
                parsed if parsed[0] == "section" else None)
            if section is not None:
                paths = [p for t in texts.get(name, []) for p in _SECTION_PATH_RE.findall(t)
                         if _norm(p.rsplit(" > ", 1)[-1]) == _norm(section[1])]
                unique = list(dict.fromkeys(paths))
                if len(unique) == 1:
                    location += "\nChapter hierarchy: " + unique[0]
            if name.casefold().endswith(".docx") and not any(
                    re.search(r"^--- Page \d+ ---$", t, re.MULTILINE)
                    for t in texts.get(name, [])):
                location += "\nPage: unavailable; find the section named above."
            page = parsed[1] if parsed[0] == "composite" else (parsed if parsed[0] == "page" else None)
            if page:
                spans = [label.casefold() for t in texts.get(name, [])
                         for label, first, last in _RENDERED_SPAN_RE.findall(t)
                         if set(_numbers(page)).intersection(range(int(first), int(last) + 1))]
                if "table" in spans:
                    location += "\nNote: the table spans these pages; the exact page of each row is unavailable."
                elif "paragraph" in spans:
                    location += "\nNote: the paragraph spans these pages; the exact page of each sentence is unavailable."
        group = entries.setdefault(name, [])
        if location not in group:
            group.append(location)
    blocks = ["File: " + name + "\n" + "\n\n".join(
        "\n".join("  " + line for line in location.splitlines())
        for location in locations) for name, locations in entries.items()]
    return "Sources:\n\n" + "\n\n".join(blocks) if blocks else NOT_FOUND_LINE


def _account_applied(analysis) -> bool:
    """True when finalize applied a Salesforce match (status matched or
    no_kam): only then does the opportunity carry a real account name."""
    info = (analysis or {}).get("opportunity")
    return isinstance(info, dict) and (
        info.get("account_name") or INFO_NOT_AVAILABLE) != INFO_NOT_AVAILABLE


def _with_account_list(sources, not_found) -> str:
    """Section 1's line when the account match was applied: the RFQ part
    is cut short enough that the account list always stays visible as the
    last entry, never hidden behind "; +N more"."""
    tail = "; " + ACCOUNT_LIST_SOURCE
    rfq = format_source_line(sources, not_found,
                             max_chars=LINE_CHARS - len(tail))
    if rfq == NOT_FOUND_LINE:
        return _PREFIX + ACCOUNT_LIST_SOURCE
    return rfq + tail


def attach_sources(plan, analysis, followups=None, files=None):
    """Set `sourceLine` on every question (app layer, never the model).

    Sections match their answer on number == id (the C1 contract). The
    Additional Information question cites the sources of every follow-up
    currently placed in the deck. `analysis` is the one finalize applied
    the account match to (also the run report's), so a rebuilt deck gets
    the same lines. With the corpus `files`, sheet and section names are
    printed as the documents write them (corpus_spelling)."""
    def spelled(sources):
        return corpus_spelling(sources, files) if files else list(sources)

    lines, details = {}, {}
    for a in (analysis or {}).get("answers", []):
        sources = spelled(a.get("sources") or [])
        not_found = bool(a.get("not_found"))
        details[a.get("id")] = format_source_details(sources, not_found, files)
        if a.get("id") == OPPORTUNITY and _account_applied(analysis):
            lines[a.get("id")] = _with_account_list(sources, not_found)
            if details[a.get("id")] == NOT_FOUND_LINE:
                details[a.get("id")] = "Sources:\n\nReference: " + ACCOUNT_LIST_SOURCE
            else:
                details[a.get("id")] += "\n\nReference: " + ACCOUNT_LIST_SOURCE
        else:
            lines[a.get("id")] = format_source_line(sources, not_found)
    in_deck = [f for f in (followups or {}).get("followups", [])
               if isinstance(f, dict) and f.get("in_deck")]
    fu_sources = spelled([s for f in in_deck for s in (f.get("sources") or [])])
    for q in plan.get("questions", []):
        if q.get("number") == ADDITIONAL_INFO_ID:
            q["sourceLine"] = format_source_line(fu_sources, not fu_sources)
            q["sourceDetails"] = format_source_details(fu_sources, not fu_sources, files)
        else:
            q["sourceLine"] = lines.get(q.get("number"), NOT_FOUND_LINE)
            q["sourceDetails"] = details.get(q.get("number"), NOT_FOUND_LINE)
    return plan
