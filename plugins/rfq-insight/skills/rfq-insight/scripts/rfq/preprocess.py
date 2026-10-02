"""Corpus preprocessing for Copilot-extracted text (fix #2).

The corpus text comes from Copilot Studio's GetFileContents (SharePoint), which
we cannot change. This pass cleans extraction ARTIFACTS without touching
content, so the model spends its attention on the RFQ, not on noise.

STRICTLY PATTERN-BASED and safe by construction: it removes only
  * bare page numbers ("25", "Page 3 of 12"),
  * short classification banners ("RESTRICTED", "Confidential",
    "Mclaren RESTRICTED", "Internal use only", ...),
and normalizes whitespace (NBSP/tabs, 3+ blank lines -> one).

It deliberately does NOT use a "repeated line" heuristic: flattened tables
legitimately repeat short lines ("Info not available", "Supplier", "Yes"),
and deleting those would destroy content. Anything not matching the explicit
patterns above passes through untouched.
"""

import re

# bare page numbers / "Page X of Y"
_PAGE_NUM = re.compile(r"^\s*(page\s+)?\d{1,4}(\s*(of|/)\s*\d{1,4})?\s*$",
                       re.IGNORECASE)

# classification banners: a short line consisting (almost) only of a
# company name and/or a classification word
_CLASS_WORDS = (r"(restricted|confidential|internal( use)?( only)?|proprietary"
                r"|uncontrolled( copy| when printed)?|company confidential"
                r"|all rights reserved)")
_BANNER = re.compile(
    r"^\s*(\S+\s+)?" + _CLASS_WORDS + r"(\s+\S+)?\s*$", re.IGNORECASE)
_BANNER_MAX_LEN = 45


def clean_extracted_text(text: str) -> str:
    """Clean one file's extracted_text. Safe to call on anything."""
    if not text:
        return text
    # normalize whitespace variants the extractor emits
    text = text.replace(" ", " ").replace("\t", " ")
    out = []
    for raw in text.split("\n"):
        s = raw.strip()
        if _PAGE_NUM.match(s):
            continue
        if len(s) <= _BANNER_MAX_LEN and _BANNER.match(s):
            continue
        out.append(raw.rstrip())
    cleaned = "\n".join(out)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)   # collapse blank-line runs
    return cleaned.strip()


def clean_corpus_files(files: list[dict]) -> tuple[list[dict], dict]:
    """Clean every file's extracted_text; returns (files, stats) — stats go
    into the run payload so the effect is auditable."""
    stats = {}
    cleaned_files = []
    for f in files:
        original = f.get("extracted_text", "") or ""
        cleaned = clean_extracted_text(original)
        g = dict(f)
        g["extracted_text"] = cleaned
        cleaned_files.append(g)
        stats[f.get("filename", "?")] = {
            "chars_before": len(original),
            "chars_after": len(cleaned),
            "removed_pct": round(100 * (1 - len(cleaned) / len(original)), 1)
            if original else 0.0,
        }
    return cleaned_files, stats
