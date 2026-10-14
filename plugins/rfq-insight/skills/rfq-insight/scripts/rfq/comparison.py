"""Compare two RFQ Insight run reports section by section.

The run report rfq/delivery.py writes next to every deck is the comparison
source - never the .pptx (hand edits, layouts and pagination would all read
as differences). Only reports of the current 12-section version are
accepted; anything older is refused with one sentence, never converted.

Every section becomes a dict of keyed items with atomic components and
readable values. These dicts are then diffed: same key -> unchanged/changed,
leftover keys paired
by difflib similarity >= SIMILARITY -> changed (ownership cells only within
one phase), the rest added/removed (owner-less ownership cells dropped).

Deliberately NOT compared: the Additional Information section (follow-up
questions are ad hoc per run), source lines (page numbers shift between
revisions) and product pictures (captions are model wording).

PowerPoint dependencies are imported inside rendering functions, so JSON
comparison remains usable without presentation dependencies.
"""

import datetime
import difflib
import json
import os
from datetime import date

from .dates import (WEEK_MONTHS, contains_calendar_day, exact_calendar_date,
                    time_pos)
from .schema import (OPPORTUNITY, SECTION_IDS, TIMING, TITLES,
                     section_number_errors)

SIMILARITY = 0.6
DAYS_PER_MONTH = 30.436875
OLD_FORMAT = ("This run report was made by an older RFQ Insight version and "
              "cannot be compared; run the analysis again first.")
OLD_FORMAT_IN = ("The run report in {} was made by an older RFQ Insight "
                 "version and cannot be compared; run the analysis there "
                 "again first.")
SKIPPED_LAYOUTS = {"pictures", "opportunity"}
EMPTY_OWNER = {"", "-", "—", "–"}
NO_OWNER = "—"
OWNERSHIP_SEP = " × "                   # ownership cell key: "<task> × <phase>"

# The Opportunity Info slide's rows (rfq.opportunity.OPPORTUNITY_ROWS) plus
# customer_site, which is not on the slide but picks the Salesforce account.
OPPORTUNITY_FIELDS = (
    ("Customer", "customer"),
    ("Customer site", "customer_site"),
    ("Customer contact", "customer_contact"),
    ("Quotation due date", "quotation_due_date"),
    ("Opportunity name", "opportunity_name"),
    ("Account Name (Site)", "account_name"),
    ("KAM (PTE)", "kam_pte"),
    ("Project type", "project_type"),
    ("Lead product", "lead_product"),
    ("Technology", "technology"),
    ("Industry", "industry"),
)
PERCENT_GROUPS = (("Products (%)", "products"), ("Skills (%)", "skills"))


class ReportFormatError(ValueError):
    """The file is not a readable run report of the current version."""


# ------------------------------------------------------------------ loading
def check_report(report) -> None:
    """Raise ReportFormatError unless `report` is a 12-section run report."""
    if not isinstance(report, dict):
        raise ReportFormatError(OLD_FORMAT)
    analysis, plan = report.get("analysis"), report.get("slidePlan")
    if not isinstance(analysis, dict) or not isinstance(plan, dict):
        raise ReportFormatError(OLD_FORMAT)
    if not isinstance(analysis.get("opportunity"), dict):
        raise ReportFormatError(OLD_FORMAT)
    questions = plan.get("questions")
    if (not isinstance(questions, list)
            or any(not isinstance(q, dict) for q in questions)
            or section_number_errors([q.get("number") for q in questions],
                                     allow_additional=True)):
        raise ReportFormatError(OLD_FORMAT)
    titles = {}
    for q in questions:
        number = q["number"]
        if number in TITLES:
            titles[number] = q.get("titleEn")
    if titles != {i: TITLES[i][0] for i in SECTION_IDS}:
        raise ReportFormatError(OLD_FORMAT)


def load_report(path: str, folder_name: str = "") -> dict:
    """The report at `path`; `folder_name` (the RFQ folder it belongs to)
    is named in the refusal messages when given."""
    where = f" in {folder_name}" if folder_name else ""
    try:
        with open(path, encoding="utf-8") as fh:
            report = json.load(fh)
    except (OSError, ValueError):
        raise ReportFormatError(
            f"The run report {os.path.basename(path)}{where} could not be "
            f"read; run the analysis there again.") from None
    try:
        check_report(report)
    except ReportFormatError:
        if not folder_name:
            raise
        raise ReportFormatError(OLD_FORMAT_IN.format(folder_name)) from None
    return report


# -------------------------------------------------------------------- items
def _clean(text) -> str:
    return " ".join(str(text if text is not None else "").split())


def table_component(columns, row):
    width = max(len(columns), len(row))
    headers = [_clean(columns[i]) if i < len(columns) else f"Column {i + 1}"
               for i in range(width)]
    cells = [_clean(row[i]) if i < len(row) else "" for i in range(width)]
    signature = json.dumps([headers, cells], ensure_ascii=False,
                           separators=(",", ":"))
    display = "; ".join(
        f"{header or ('Column ' + str(i + 1))}: {cell or '(blank)'}"
        for i, (header, cell) in enumerate(zip(headers, cells)))
    return {"signature": signature, "display": display}


def _text_component(value):
    value = _clean(value)
    return {"signature": json.dumps(["text", value], ensure_ascii=False,
                                    separators=(",", ":")),
            "display": value}


def _merge(items: dict, key: str, component: dict, date_evidence) -> None:
    """Merge whole components and raw date evidence in encounter order.

    Text separators are display punctuation, never component boundaries.
    Evidence merges even when a component's cleaned signature repeats.
    """
    if key not in items:
        items[key] = {"value": "", "date": None,
                      "exact_day": None, "precision": "invalid",
                      "components": [], "date_evidence": []}
    item = items[key]
    if not any(c["signature"] == component["signature"]
               for c in item["components"]):
        item["components"].append(component)
    item["value"] = " | ".join(c["display"] for c in item["components"]
                               if c["display"])
    for token in date_evidence:
        if token not in item["date_evidence"]:
            item["date_evidence"].append(token)
    if item["date"] is None:
        item["date"] = _first_date(date_evidence)
    normalized = []
    for token in item["date_evidence"]:
        exact = exact_calendar_date(token)
        if exact is not None:
            value = ("day", exact.isoformat())
        elif contains_calendar_day(token):
            value = ("invalid", _clean(token))
        else:
            pos = time_pos(token)
            value = (("coarse", pos) if pos is not None
                     else ("invalid", _clean(token)))
        if value not in normalized:
            normalized.append(value)
    item["exact_day"] = None
    if len(normalized) > 1:
        item["precision"] = "conflicting"
    elif normalized:
        item["precision"], value = normalized[0]
        if item["precision"] == "day":
            item["exact_day"] = value
    else:
        item["precision"] = "invalid"


def _first_date(cells):
    for cell in cells:
        pos = time_pos(cell)
        if pos is not None:
            return pos
    return None


def _row_key(cells: list, n: int) -> str:
    """A table row's key: its first cell, or '(row N)' when that cell is
    empty - the row is still compared, not dropped."""
    return cells[0] or f"(row {n})"


def _slide_items(slide: dict, state: dict, dated: bool) -> list:
    """(key, component, date_evidence) triples, in slide order."""
    layout = slide.get("layout")
    out = []
    if layout == "table":
        for n, row in enumerate(slide.get("rows") or [], start=1):
            cells = [_clean(c) for c in row]
            if not cells or not any(cells):
                continue
            evidence = ([str(c) for c in row if time_pos(c) is not None
                         or contains_calendar_day(c)]
                        if dated else [])
            out.append((_row_key(cells, n),
                        table_component(slide.get("columns") or [], row), evidence))
    elif layout == "ownership":
        cols = [_clean(c) for c in slide.get("columns") or []]
        for n, row in enumerate(slide.get("rows") or [], start=1):
            cells = [_clean(c) for c in row]
            if not cells or not any(cells):
                continue
            for ci in range(1, len(cols)):
                owner = cells[ci] if ci < len(cells) else ""
                out.append((f"{_row_key(cells, n)}{OWNERSHIP_SEP}{cols[ci]}",
                            NO_OWNER if owner in EMPTY_OWNER else owner, None))
    elif layout in ("gantt", "timeline"):
        for step in slide.get("steps") or []:
            raw_date = step.get("date", "")
            date = _clean(raw_date)
            out.append((step.get("label", ""), date,
                        [str(raw_date)] if raw_date is not None else []))
    elif layout == "bullets":
        for bullet in slide.get("bullets") or []:
            out.append((bullet.get("text", ""), "", None))
    elif layout == "panel":
        for item in slide.get("items") or []:
            out.append((item, _clean(slide.get("heading", "")), None))
    elif layout == "phases":
        for phase in slide.get("phases") or []:
            out.append((phase.get("name", ""), phase.get("desc", ""), None))
    elif layout == "collab":
        for party in slide.get("parties") or []:
            out.append((party.get("name", ""), party.get("role", ""), None))
    elif layout == "prose":
        for para in str(slide.get("body", "")).split("\n"):
            if para.strip():
                state["para"] += 1
                out.append((f"Paragraph {state['para']}", para, None))
    elif layout == "twoColumn":
        for side in ("left", "right"):
            heading = _clean(slide.get(f"{side}Heading", ""))
            for item in slide.get(f"{side}Items") or []:
                out.append((item, heading, None))
    elif layout == "prosCons":
        for item in slide.get("pros") or []:
            out.append((item, "Pro", None))
        for item in slide.get("cons") or []:
            out.append((item, "Con", None))
    elif layout == "kpi":
        for kpi in slide.get("kpis") or []:
            out.append((kpi.get("label", ""),
                        f"{kpi.get('value', '')} {kpi.get('unit') or ''}", None))
    return [(key, component if isinstance(component, dict)
             else _text_component(component), evidence or [])
            for key, component, evidence in out]


def _opportunity_items(info: dict) -> dict:
    items: dict = {}
    for label, field in OPPORTUNITY_FIELDS:
        _merge(items, label, _text_component(info.get(field, "")), [])
    for group, field in PERCENT_GROUPS:
        for entry in info.get(field) or []:
            if isinstance(entry, dict) and _clean(entry.get("name")):
                _merge(items, f"{group} – {_clean(entry['name'])}",
                       _text_component(f"{entry.get('percent', '')}%"), [])
    return items


def section_items(report: dict, sid: int) -> dict:
    """Keyed readable values, ordered components and raw date evidence."""
    if sid == OPPORTUNITY:
        return _opportunity_items(report["analysis"]["opportunity"])
    items: dict = {}
    state = {"para": 0}
    for q in report["slidePlan"].get("questions") or []:
        if not isinstance(q, dict) or q.get("number") != sid:
            continue
        for slide in q.get("slides") or []:
            if (not isinstance(slide, dict)
                    or slide.get("layout") in SKIPPED_LAYOUTS):
                continue
            local: dict = {}
            for key, component, evidence in _slide_items(slide, state,
                                                         dated=(sid == TIMING)):
                key = _clean(key)
                if not key:
                    continue
                base, n = key, 2
                while key in local:                 # same key, same slide
                    key = f"{base} ({n})"
                    n += 1
                local[key] = (component, evidence)
            for key, (component, evidence) in local.items():
                _merge(items, key, component, evidence)
    return items


# --------------------------------------------------------------------- diff
def format_shift(delta_months: float) -> str:
    """'+1.5 months' / '-2 months' / '+1 month' / '+3 weeks' / '-2 days'."""
    if abs(delta_months) >= 1:
        text = f"{delta_months:+.1f}".rstrip("0").rstrip(".")
        unit = "month" if text in ("+1", "-1") else "months"
        return f"{text} {unit}"
    weeks = round(delta_months / WEEK_MONTHS)
    if weeks:
        return f"{weeks:+d} week{'s' if abs(weeks) != 1 else ''}"
    days = round(delta_months * DAYS_PER_MONTH)
    return f"{days:+d} day{'s' if abs(days) != 1 else ''}"


def exact_day_shift(left, right):
    days = (right - left).days
    count, unit = (days // 7, "week") if days and days % 7 == 0 else (days, "day")
    return f"{count:+d} {unit}" + ("" if abs(count) == 1 else "s")


def _changed_label(a: dict, b: dict) -> str:
    if a.get("precision") == b.get("precision") == "day":
        left = date.fromisoformat(a["exact_day"])
        right = date.fromisoformat(b["exact_day"])
        if left != right:
            return f"Changed ({exact_day_shift(left, right)})"
    elif a.get("precision") == b.get("precision") == "coarse":
        left, right = a.get("date"), b.get("date")
        if left is not None and right is not None and abs(right - left) > 1e-9:
            return f"Changed (approximately {format_shift(right - left)})"
    return "Changed"


def _show(key: str, item: dict) -> str:
    return f"{key} ({item['value']})" if item["value"] else key


def _task_phase(key: str):
    """('<task>', '<phase>') of an ownership cell key '<task> × <phase>';
    (key, '') for every other key. Ownership cells pair only within one
    phase and on the task alone - the shared ' × <phase>' suffix would
    otherwise make two different tasks look similar."""
    task, sep, phase = key.rpartition(OWNERSHIP_SEP)
    return (task, phase) if sep else (key, "")


def _owner_less(key: str, item: dict) -> bool:
    """An ownership cell without an owner: noise as an Added/Removed row."""
    return OWNERSHIP_SEP in key and item["value"] == NO_OWNER


def diff_items(a: dict, b: dict, fuzzy: bool = True):
    """(counts, rows) - rows list only the differences."""
    counts = {"unchanged": 0, "changed": 0, "added": 0, "removed": 0}
    rows = []
    for key, item_a in a.items():
        if key not in b:
            continue
        item_b = b[key]
        if "components" in item_a and "components" in item_b:
            equal = ([c["signature"] for c in item_a["components"]]
                     == [c["signature"] for c in item_b["components"]])
        else:                         # direct value/date helper inputs
            equal = item_a["value"] == item_b["value"]
        if equal:
            counts["unchanged"] += 1
            continue
        counts["changed"] += 1
        rows.append({"item": key, "a": item_a["value"] or "—",
                     "b": item_b["value"] or "—",
                     "change": _changed_label(item_a, item_b)})

    only_a = [k for k in a if k not in b]
    only_b = [k for k in b if k not in a]
    used_a, used_b = set(), set()
    if fuzzy:
        pairs = []
        for ia, ka in enumerate(only_a):
            task_a, phase_a = _task_phase(ka)
            for ib, kb in enumerate(only_b):
                task_b, phase_b = _task_phase(kb)
                if phase_a != phase_b:
                    continue
                ratio = difflib.SequenceMatcher(None, task_a.lower(),
                                                task_b.lower()).ratio()
                if ratio >= SIMILARITY:
                    pairs.append((-ratio, ia, ib))
        for _, ia, ib in sorted(pairs):
            ka, kb = only_a[ia], only_b[ib]
            if ka in used_a or kb in used_b:
                continue
            used_a.add(ka)
            used_b.add(kb)
            counts["changed"] += 1
            rows.append({"item": kb, "a": _show(ka, a[ka]),
                         "b": _show(kb, b[kb]),
                         "change": _changed_label(a[ka], b[kb])})
    for ka in only_a:
        if ka not in used_a and not _owner_less(ka, a[ka]):
            counts["removed"] += 1
            rows.append({"item": ka, "a": a[ka]["value"] or "listed",
                         "b": "—", "change": "Removed"})
    for kb in only_b:
        if kb not in used_b and not _owner_less(kb, b[kb]):
            counts["added"] += 1
            rows.append({"item": kb, "a": "—",
                         "b": b[kb]["value"] or "listed", "change": "Added"})
    return counts, rows


# ------------------------------------------------------------------ compare
def _meta(report: dict) -> dict:
    plan = report["slidePlan"]
    label = (_clean(report["analysis"]["opportunity"].get("opportunity_name"))
             or _clean(plan.get("projectName"))
             or _clean(report.get("run", {}).get("projectName")) or "RFQ")
    return {"label": label, "date": str(plan.get("date", "") or "")}


def column_labels(meta_a: dict, meta_b: dict):
    from .dates import display_date
    if meta_a["label"] != meta_b["label"]:
        return meta_a["label"], meta_b["label"]
    if meta_a["date"] and meta_b["date"] and meta_a["date"] != meta_b["date"]:
        return (f"Run {display_date(meta_a['date'])}",
                f"Run {display_date(meta_b['date'])}")
    return "Run A", "Run B"


def compare_reports(a: dict, b: dict) -> dict:
    check_report(a)
    check_report(b)
    meta_a, meta_b = _meta(a), _meta(b)
    meta_a["column"], meta_b["column"] = column_labels(meta_a, meta_b)
    sections = []
    for sid in SECTION_IDS:
        counts, items = diff_items(section_items(a, sid),
                                   section_items(b, sid),
                                   fuzzy=(sid != OPPORTUNITY))
        sections.append({"id": sid, "title": TITLES[sid][0],
                         "counts": counts, "items": items})
    return {"a": meta_a, "b": meta_b, "sections": sections}


# ------------------------------------------------------------- orchestration
SAME_REPORT = "Choose two different RFQ analyses to compare."
COMPARISON_PREFIX = "RFQ Insight Comparison_"
_VS = " vs "


def comparison_basename(label_a: str, label_b: str, iso_date: str,
                        out_dir: str = "") -> str:
    """'RFQ Insight Comparison_<A> vs <B>_<DDMMYYYY>', without extension.

    Like naming.deck_basename(): with `out_dir`, the two names are cut (at
    a word boundary; prefix, ' vs ' and date stay) so `out_dir/<base>.pptx`
    stays within MAX_PATH. A name shorter than half the budget is kept
    whole and the other one gets the rest."""
    from .delivery import (EXT_MARGIN, MAX_PATH, safe_filename,
                           truncate_at_word)
    from .dates import compact_date
    suffix = f"_{compact_date(iso_date)}"
    a, b = safe_filename(label_a), safe_filename(label_b)
    if out_dir:
        budget = (MAX_PATH - len(out_dir) - 1 - len(COMPARISON_PREFIX)
                  - len(_VS) - len(suffix) - EXT_MARGIN)
        if len(a) + len(b) > budget:
            half = budget // 2
            if len(a) <= half:
                b = truncate_at_word(b, budget - len(a))
            elif len(b) <= half:
                a = truncate_at_word(a, budget - len(b))
            else:
                a, b = (truncate_at_word(a, half),
                        truncate_at_word(b, budget - half))
        a, b = a or "RFQ", b or "RFQ"
    return f"{COMPARISON_PREFIX}{a}{_VS}{b}{suffix}"


def _folder_name(folder: str) -> str:
    root = os.path.abspath(folder)
    return os.path.basename(root.rstrip("\\/")) or root


def _resolved(path: str) -> str:
    """Absolute with links resolved - like the pipeline's Path.resolve()
    check of the same record."""
    return os.path.realpath(os.path.abspath(path))


def _is_inside(path: str, folder: str) -> bool:
    path, folder = os.path.normcase(path), os.path.normcase(folder)
    try:
        return os.path.commonpath([path, folder]) == folder
    except ValueError:                       # different drives on Windows
        return False


def _report_path(folder: str) -> str:
    """The report of the folder's last finished run, from deliverables.json
    only - a report file name is never guessed."""
    root = os.path.abspath(folder)
    name = _folder_name(folder)
    record = os.path.join(root, "output", ".work", "deliverables.json")
    if not os.path.isfile(record):
        raise ReportFormatError(f"No finished RFQ Insight run was found in "
                                f"{name}; run the analysis there first.")
    try:
        with open(record, encoding="utf-8") as fh:
            path = _resolved(str(json.load(fh)["report"]))
    except (OSError, ValueError, KeyError, TypeError):
        raise ReportFormatError(f"The run record in {name} is unreadable; "
                                f"run the analysis there again.") from None
    out_dir = _resolved(os.path.join(root, "output"))
    if not _is_inside(path, out_dir):
        # The record keeps absolute paths: after the RFQ folder was moved or
        # renamed, the same report name in its own output/ is the report.
        path = os.path.join(out_dir, os.path.basename(path))
    if not os.path.isfile(path):
        raise ReportFormatError(f"The run record in {name} does not point to "
                                f"a report in its output folder; run the "
                                f"analysis there again.")
    return path


def _write_json(path: str, data) -> None:
    """Write through a temp file and replace, so a reader never sees half."""
    from .state import replace_with_retry
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    replace_with_retry(tmp, path)


def run_compare(folder_a: str, folder_b: str, today: str | None = None) -> dict:
    """Compare the last runs of two RFQ folders; write the comparison JSON
    and deck into folder A's output/. Never raises for a user-level problem:
    those come back as {"status": "blocked", "message": ...}."""
    from .delivery import next_free

    try:
        path_a, path_b = _report_path(folder_a), _report_path(folder_b)
        if os.path.normcase(path_a) == os.path.normcase(path_b):
            raise ReportFormatError(SAME_REPORT)
        comparison = compare_reports(
            load_report(path_a, _folder_name(folder_a)),
            load_report(path_b, _folder_name(folder_b)))
    except ReportFormatError as exc:
        return {"status": "blocked", "message": str(exc)}

    iso = today or datetime.date.today().isoformat()
    comparison["date"] = iso
    out_dir = os.path.join(os.path.abspath(folder_a), "output")
    work = os.path.join(out_dir, ".work")
    os.makedirs(work, exist_ok=True)
    _write_json(os.path.join(work, "comparison.json"), comparison)

    deck = render_comparison(comparison)
    base = comparison_basename(comparison["a"]["label"],
                               comparison["b"]["label"], iso, out_dir=out_dir)
    pptx_path = next_free(out_dir, base, exts=(".pptx",)) + ".pptx"
    with open(pptx_path, "xb") as fh:         # exclusive: never overwrite
        fh.write(deck)
    return {"status": "done", "pptx": pptx_path}


OVERVIEW_COLUMNS = ["Section", "Unchanged", "Changed", "Added", "Removed"]
COUNT_KEYS = ("unchanged", "changed", "added", "removed")
CHANGE_COLORS = (("Added", "13A538"), ("Removed", "C0392B"), ("Changed", "E9B300"))
TABLE_TOP = 1.55
COVER_PT = 28                 # main_cover's title size for a two-line title
COVER_LINES = 2               # wrapped lines per cover name (4 fill its box)
ELLIPSIS = "…"


def change_color(value):
    """Fill colour for a Change cell, or None (renderer default fill)."""
    text = str(value).strip()
    for prefix, color in CHANGE_COLORS:
        if text.startswith(prefix):
            return color
    return None


def ellipsize(text, avail_w, size, max_lines, bold=False):
    """`text` cut (at a word boundary when one exists) and ended with "…"
    so it wraps to at most `max_lines` lines inside `avail_w` inches;
    unchanged when it already fits."""
    from . import renderer as R
    text = str(text)
    if R._wrap_count(text, avail_w, size, bold) <= max_lines:
        return text

    def fits(n):
        return R._wrap_count(text[:n].rstrip() + ELLIPSIS, avail_w, size,
                             bold) <= max_lines

    lo, hi = 0, len(text)                  # longest prefix that fits
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if fits(mid):
            lo = mid
        else:
            hi = mid - 1
    cut = text[:lo]
    if not text[lo].isspace() and cut.rfind(" ") > 0:    # mid-word: back off
        cut = cut[:cut.rfind(" ")]
    return cut.rstrip(" .,;:–-") + ELLIPSIS


def _cover_name(line):
    """One cover line, at most COVER_LINES wrapped lines: two long names
    would otherwise run out of main_cover's fixed title box."""
    from . import renderer as R
    return ellipsize(line, R.PAGE_W - 2 * R.M, COVER_PT, COVER_LINES,
                     bold=True)


def _fit_row(row, widths, budget):
    """`row` with every cell cut so the row alone fits `budget` inches - one
    oversized row (a long changed paragraph) could not be paginated."""
    from . import renderer as R
    if R._row_height(row, widths, R.TABLE_PT) <= budget:
        return row
    line_h = R.LINE_H_EM * R.TABLE_PT / 72.0
    max_lines = max(int((budget - R.CELL_V_PAD) / line_h), 1)
    return [ellipsize(cell, max(widths[ci] - 0.15, 0.3), R.TABLE_PT, max_lines)
            for ci, cell in enumerate(row)]


def _overview(prs, comparison, ctx):
    from . import renderer as R
    s = R.content_slide(prs, ctx, "Comparison Overview")
    tw = R.PAGE_W - 2 * R.M
    rows = [[sec["title"]] + [str(sec["counts"][k]) for k in COUNT_KEYS]
            for sec in comparison["sections"]]
    R._std_table(s, OVERVIEW_COLUMNS, rows, R.M, TABLE_TOP, tw,
                 cell_size=R.TABLE_PT,
                 col_widths=[tw * 0.44] + [tw * 0.14] * 4)


def _section(prs, comparison, section, ctx):
    from . import renderer as R
    cols = ["Item", comparison["a"]["column"], comparison["b"]["column"],
            "Change"]
    tw = R.PAGE_W - 2 * R.M
    widths = [tw * 0.28, tw * 0.29, tw * 0.29, tw * 0.14]
    budget = R.CONTENT_BOTTOM - TABLE_TOP
    header_h = R._row_height(cols, widths, R.TABLE_PT + 0.5,
                             min_row=R.HEADER_MIN, bold=True)
    rows = [_fit_row([it["item"], it["a"], it["b"], it["change"]], widths,
                     budget - header_h)
            for it in section["items"]]
    chunks = R._paginate_rows(rows, widths, R.TABLE_PT, budget, header=cols)
    title = f"{section['title']} — Changes"
    for i, chunk in enumerate(chunks):
        s = R.content_slide(prs, ctx, title + ("" if i == 0 else " (cont.)"))
        R._std_table(s, cols, chunk, R.M, TABLE_TOP, tw,
                     cell_size=R.TABLE_PT, owner_map=change_color,
                     col_widths=widths, owner_cols={3})


def create_comparison(comparison: dict):
    from . import renderer as R
    from pptx import Presentation
    from pptx.util import Inches
    from .dates import display_date
    prs = Presentation()
    prs.slide_width = Inches(R.PAGE_W)
    prs.slide_height = Inches(R.PAGE_H)
    label_a, label_b = comparison["a"]["label"], comparison["b"]["label"]
    iso = comparison.get("date", "")
    ctx = {"project": f"{label_a} vs {label_b}",
           "date": display_date(iso) if iso else "",
           "page": 0, "conf": "", "source": ""}
    cover = f"{_cover_name(label_a)}\n{_cover_name(f'vs {label_b}')}"
    R.main_cover(prs, {"projectName": cover,
                       "oppId": "", "date": iso}, ctx)
    _overview(prs, comparison, ctx)
    for section in comparison["sections"]:
        if section["items"]:
            _section(prs, comparison, section, ctx)
    return prs


def render_comparison(comparison: dict) -> bytes:
    import io
    buf = io.BytesIO()
    create_comparison(comparison).save(buf)
    return buf.getvalue()
