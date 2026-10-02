"""One parser for milestone date strings, shared by the renderer and the checker.

Two callers read these strings for different reasons: `renderer.py` places a
milestone on the Gantt calendar axis, `evaluate.py` decides whether the slide
plan lists them in order (check C5). C5 is a CONSISTENCY check - "is the plan
in the order the deck draws it?" - so it must never hold an independent opinion
about what a date means. Every disagreement between the two is a false warning
on a correctly drawn deck, which is how the original defect surfaced: the
renderer honoured the "early / mid / end of" qualifiers, the checker did not,
so "end of 2026" keyed to mid-year and sorted BEFORE "December 2026".

Two copies of this logic cannot be kept in step by discipline alone, so there
is only one. It lives here rather than in `renderer.py` because the checker has
to stay runnable against a report JSON with nothing installed - `renderer.py`
imports python-pptx and Pillow at module level, and a checker that cannot run
is worse than one that is coarse.

STDLIB ONLY. Adding a third-party import here re-creates the problem.
"""

import re

# Month-name tokens, English AND German (RFQ corpora are frequently
# bilingual). English three-letter prefixes already cover the German names
# that share them (januar/februar/april/juni/juli/august/september/november);
# the four that differ get their own tokens: märz/maerz/mrz, mai, okt, dez.
MON_NUM = {"jan": 1, "feb": 2, "mar": 3, "märz": 3, "maerz": 3, "mrz": 3,
           "apr": 4, "may": 5, "mai": 5, "jun": 6, "jul": 7, "aug": 8,
           "sep": 9, "oct": 10, "okt": 10, "nov": 11, "dec": 12, "dez": 12}
MON_RE = r"\b(märz|maerz|mrz|jan|feb|mar|apr|may|mai|jun|jul|aug|sep|oct|okt|nov|dec|dez)"

WEEK_MONTHS = 12.0 / (365.2425 / 7.0)     # one ISO calendar week in months

# Deterministic anchors for fuzzy qualifiers ("early", "mid", "late" and the
# German Anfang/Mitte/Ende), as a FRACTION of whatever span they qualify —
# the same word always lands at the same relative position, whether it
# qualifies a month ("late September 2027"), a quarter ("mid Q2 2027"), a
# half-year or a bare year. 0.10 / 0.50 / 0.92 of the span.
QUALIFIERS = (("early", 0.10), ("beginning", 0.10), ("begin", 0.10),
              ("anfang", 0.10), ("start of", 0.10),
              ("mid", 0.50), ("mitte", 0.50),
              ("ende", 0.92), ("end", 0.92), ("late", 0.92), ("spät", 0.92))


def qualifier(t):
    """The qualifier fraction found in `t`, or None. First match in the fixed
    table order wins ("ende" is tested before "end" so both hit 0.92)."""
    for word, frac in QUALIFIERS:
        if re.search(r"\b" + word, t):
            return frac
    return None


def _span_pos(base, span_months, t, end):
    """Position inside a coarse span (month/quarter/half-year/year): the
    qualifier fraction when one is present, else the span start (or its end
    when `end=True`, for Gantt bar end dates)."""
    q = qualifier(t)
    if q is not None:
        return base + q * span_months
    return base + (span_months * 0.95 if end else 0.0)


def _dm_pos(y, mo, day):
    """year/month/day -> fractional month position; None for invalid parts —
    an unplaceable milestone is DISCLOSED (callout), never drawn at a wrong
    position (the old parser clamped month 15 to December silently)."""
    if not (1 <= mo <= 12 and 1 <= day <= 31):
        return None
    return y * 12 + (mo - 1) + min(day - 1, 30) / 31.0


def time_pos(s, end=False):
    """Parse a milestone/phase date string to a fractional month position
    (year*12 + month-1 + day-fraction), or None if no calendar position can
    be derived. `end=True` resolves coarse spans (quarter / month / half-year
    / year / calendar week) to their END instead of their start — for Gantt
    bar end dates.

    Handles: 2026/7/15 · 2026-07-15 · 15.07.2026 · 07/15/2026 (US, month
    first when the middle field cannot be one) · 15-Jul-2026 · Jul 15, 2026 ·
    ~Oct 2026 · Okt./Dez./März/Mai 2026 (German) · Q1 2028 · Q1/2028 ·
    KW 38/2026 · CW38 2026 · H1 2027 · early/mid/end of 2027 · 2026.
    Invalid calendar parts (month 13, day 32) return None — better absent
    and disclosed than placed wrong."""
    t = str(s).lower().strip()
    m = re.search(r"(20\d\d)[/.\-](\d{1,2})(?:[/.\-](\d{1,2}))?", t)
    if m:  # yyyy/m[/d]
        y, mo = int(m.group(1)), int(m.group(2))
        day = int(m.group(3)) if m.group(3) else (28 if end else 1)
        pos = _dm_pos(y, mo, day)
        if pos is None and m.group(3):         # yyyy/dd/mm (rare) — swap
            pos = _dm_pos(y, int(m.group(3)), mo)
        if pos is not None:
            return pos
    m = re.search(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](20\d\d)", t)
    if m:  # d.m.yyyy (European default); m/d/yyyy only when d.m is impossible
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        pos = _dm_pos(y, b, a)
        if pos is None:
            pos = _dm_pos(y, a, b)             # US month-first fallback
        if pos is not None:
            return pos
    m = re.search(MON_RE + r"[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s*(20\d\d)", t)
    if m:  # "Jul 15, 2026"
        return _dm_pos(int(m.group(3)), MON_NUM[m.group(1)], int(m.group(2)))
    m = re.search(r"(\d{1,2})(?:st|nd|rd|th)?\.?[\s.\-]+" + MON_RE
                  + r"[a-z]*\.?[\s.\-,]+(20\d\d)", t)
    if m:  # "15-Jul-2026", "15th Sept 2026", "15. Okt 2026"
        return _dm_pos(int(m.group(3)), MON_NUM[m.group(2)], int(m.group(1)))
    m = re.search(MON_RE + r"[a-z]*\.?,?[\s\-./]*(20\d\d)", t)
    if m:  # "Oct 2026", "late September 2027", "Sept/2027", "Okt 2026"
        base = int(m.group(2)) * 12 + MON_NUM[m.group(1)] - 1
        return _span_pos(base, 1.0, t, end)
    m = re.search(r"q([1-4])\s*[/\- ]?\s*(20\d\d)", t) \
        or re.search(r"(20\d\d)\s*[/\- ]?\s*q([1-4])", t)
    if m:  # "Q1 2028", "mid Q2 2027", "end of Q3 2026"
        a, b = m.group(1), m.group(2)
        q, y = (int(a), int(b)) if len(a) == 1 else (int(b), int(a))
        return _span_pos(y * 12 + (q - 1) * 3, 3.0, t, end)
    m = re.search(r"\b[kc]w\s*\.?\s*(\d{1,2})\s*[/\-. ]\s*(20\d\d)", t) \
        or re.search(r"(20\d\d)\s*[/\-. ]?\s*[kc]w\s*\.?\s*(\d{1,2})", t)
    if m:  # calendar week: "KW 38/2026", "CW38 2026", "2026 KW38"
        a, b = m.group(1), m.group(2)
        wk, y = (int(a), int(b)) if len(b) == 4 else (int(b), int(a))
        if 1 <= wk <= 53:
            return y * 12 + (wk - 1) * WEEK_MONTHS \
                + (WEEK_MONTHS * 0.95 if end else 0)
    m = re.search(r"\bh([12])\s*[/\- ]?\s*(20\d\d)", t) \
        or re.search(r"(20\d\d)\s*[/\- ]?\s*h([12])", t)
    if m:  # half-year: "H1 2027", "2027 H2", "late H1 2027"
        a, b = m.group(1), m.group(2)
        h, y = (int(a), int(b)) if len(a) == 1 else (int(b), int(a))
        return _span_pos(y * 12 + (h - 1) * 6, 6.0, t, end)
    m = re.search(r"(20\d\d)", t)
    if m:  # bare year: "2026", "early 2027", "Ende 2026"
        return _span_pos(int(m.group(1)) * 12, 12.0, t, end)
    return None
