"""Opportunity Info: the Salesforce account step and the deterministic slide.

The slide-plan model never fills this slide. Stage 1 returns the facts as
a structured `opportunity` object (validated against the Guidance
Document), the runner adds the Salesforce account, and rfq/delivery.py turns
the result into one `opportunity` slide with three tables.
"""

import copy

from .guidance import INFO_NOT_AVAILABLE, clean_site, vocabulary
from .schema import RISKS, TITLES
from .planning import clean_evidence_tags

MAIN_COLUMNS = ["Opportunity Info", "Definition according to RFQ"]
PRODUCTS_COLUMNS = ["Products (%)", "Definition according to RFQ"]
SKILLS_COLUMNS = ["Skills (%)", "Definition according to RFQ"]

# Row order of the client's slide (18.09.2026).
OPPORTUNITY_ROWS = (
    ("Customer", "customer"),
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


# ----------------------------------------------------------- account step
# Row labels rfq/verification.py must not mistake for the model's own claims -
# these two rows are filled by the application, never extracted from the RFQ
# (see the QA prompt), so "Info not available" there is not an absence claim.
ACCOUNT_FIELD_PREFIXES = tuple(
    label for label, key in OPPORTUNITY_ROWS if key in ("account_name", "kam_pte"))

# Sentence this module's lookup status can turn into, read unresolved.
UNREADABLE_ACCOUNT_RISK_LINE = (
    'Salesforce account lookup result could not be read; Account and KAM '
    'left as "Info not available".')

# The exact opening words of every sentence account_risk_line() can produce -
# rfq/verification.py imports these to recognise its OWN risk line in section
# 11's text (rather than duplicating the wording in two places), so it is
# never mistaken for an absence claim in the model's own answer.
ACCOUNT_RISK_PREFIXES = (
    "Account Name (Site) and KAM (PTE) could not be matched",
    "No exact Salesforce account match for",
    "No Salesforce account matches",
    "The Salesforce account \"",
    "Salesforce account lookup result could not be read",
)


def _distinct_candidate_names(match: dict) -> list:
    """Each distinct `candidate_details` display name once, in order, with
    its KAM in parentheses only when the SAME name is listed more than once
    with a DIFFERENT KAM (duplicate Salesforce rows for one account name)."""
    details = match.get("candidate_details") or []
    if not details:
        return list(dict.fromkeys(match.get("candidates", [])))
    kams_by_name = {}
    for d in details:
        kams_by_name.setdefault(d.get("account_name", ""), set()).add(
            d.get("kam_pte", ""))
    names, seen = [], set()
    for d in details:
        name = d.get("account_name", "")
        if not name or name in seen:
            continue
        seen.add(name)
        if len(kams_by_name.get(name, ())) > 1:
            names.append(f"{name} ({d.get('kam_pte', '')})")
        else:
            names.append(name)
    return names


def account_risk_line(match: dict):
    """The Document Risk sentence for a lookup that did not settle, or None."""
    status = (match or {}).get("status")
    customer = match.get("customer", "") if match else ""
    if status == "unreadable":
        return UNREADABLE_ACCOUNT_RISK_LINE
    if status == "ambiguous":
        if match.get("tier") != "exact":
            # No candidate even matches the name: naming them would read as
            # a confident short-list the lookup never actually had.
            return (f'No exact Salesforce account match for "{customer}"; '
                    f"close candidates are listed in the notes.")
        names = _distinct_candidate_names(match)
        shown, extra = names[:3], max(len(names) - 3, 0)
        names_text = "; ".join(shown) + (f"; and {extra} more" if extra else "")
        return (f"Account Name (Site) and KAM (PTE) could not be matched to "
                f"one Salesforce account for \"{customer}\" (candidates: "
                f"{names_text}); confirm the account manually.")
    if status == "none":
        return f'No Salesforce account matches "{customer}".'
    if status == "no_kam":
        return (f"The Salesforce account \"{match.get('account_name', '')}\" "
                f"has no KAM (PTE) assigned.")
    return None


def add_account_risk(analysis: dict, match: dict) -> bool:
    """Append the risk sentence to section 11 once. True when it changed."""
    line = account_risk_line(match)
    if not line:
        return False
    for answer in analysis.get("answers", []):
        if answer.get("id") == RISKS:
            text = str(answer.get("answer", ""))
            if line in text:
                return False
            answer["answer"] = text.rstrip() + "\n- " + line
            return True
    return False


def without_account_risk(text: str, protected_items=()) -> str:
    """Section 11's text minus the risk lines add_account_risk appended."""
    return "\n".join(ln for ln in str(text).split("\n") if not (
        ln.startswith("- ") and ln[2:] not in protected_items
        and ln[2:].startswith(ACCOUNT_RISK_PREFIXES)))


def remove_account_risk(analysis: dict, protected_items=()) -> bool:
    """Drop the risk sentence an earlier lookup appended to section 11, so
    a lookup that runs again (finalize) replaces it rather than adding a
    contradicting second one. True when it changed."""
    for answer in analysis.get("answers", []):
        if answer.get("id") == RISKS:
            text = str(answer.get("answer", ""))
            kept = without_account_risk(text, protected_items)
            if kept == text:
                return False
            answer["answer"] = kept
            return True
    return False


# Any Risk Detection item that mentions one of these is about the account
# lookup - the application's line, never the slide model's (lower case).
_ACCOUNT_ITEM_MARKERS = ("salesforce", "account name (site)", "kam (pte)")


def place_account_risk(plan: dict, line, protected_items=()) -> list:
    """Section 11's account risk on the slides, owned by the application:
    every panel item that mentions the account (a model paraphrase, an older
    plan's copy) is dropped - with a panel it empties - and `line`, when
    there is one, becomes the last item of the Document Risks panel (one is
    added when the plan has none). Returns the actions for the run report."""
    question = next((q for q in plan.get("questions", [])
                     if q.get("number") == RISKS), None)
    if question is None:
        return []
    removed, slides = False, []
    for slide in question.get("slides", []):
        if slide.get("layout") == "panel":
            items = slide.get("items") or []
            kept = [item for item in items if item in protected_items or not any(
                m in str(item).lower() for m in _ACCOUNT_ITEM_MARKERS)]
            if len(kept) != len(items):
                removed = True
                if not kept:
                    continue
                slide["items"] = kept
        slides.append(slide)
    question["slides"] = slides
    if line:
        documents = [sl for sl in slides if sl.get("layout") == "panel"
                     and "Document" in str(sl.get("heading", ""))]
        if documents:
            documents[-1]["items"].append(line)
        else:
            slides.append({"layout": "panel", "title": TITLES[RISKS][0],
                           "heading": "Document Risks", "items": [line]})
        return ["account risk line: replaced"]
    return ["account risk line: removed"] if removed else []


def account_match_is_current(info: dict, match) -> bool:
    """True when `match` is a real lookup result for THIS analysis - the
    same customer and the same own-site it was resolved against. A mismatch
    means analysis.json changed (e.g. a resumed, re-typed run) after the
    lookup ran: applying it anyway would silently attach the wrong account.
    The lookup stores the cleaned site, so both sides are compared cleaned
    ("Info not available" and "" are the same address, a trailing
    "(inferred)" is no new one)."""
    if not isinstance(match, dict) or not isinstance(info, dict):
        return False
    return (match.get("customer") == info.get("customer") and
            clean_site(match.get("customer_site")) ==
            clean_site(info.get("customer_site")))


def apply_account_match(analysis: dict, match) -> dict:
    """A copy of the analysis whose opportunity carries the looked-up
    account. A missing, corrupt or stale match (`account_match_is_current`
    is False) leaves "Info not available" rather than the model's own text -
    the model is explicitly told not to fill these two fields, so its answer
    is never a legitimate fallback value."""
    applied = copy.deepcopy(analysis)
    info = applied.get("opportunity")
    if isinstance(info, dict):
        if account_match_is_current(info, match):
            info["account_name"] = match.get("account_name") or INFO_NOT_AVAILABLE
            info["kam_pte"] = match.get("kam_pte") or INFO_NOT_AVAILABLE
        else:
            info["account_name"] = INFO_NOT_AVAILABLE
            info["kam_pte"] = INFO_NOT_AVAILABLE
    return applied


# ------------------------------------------------------------------ slide
def display_name(info, fallback: str) -> str:
    """The deck's display name (cover title, footer, end slide): the
    opportunity name once the analysis has a real one, else `fallback` -
    the run's own name (`--project` or the folder's)."""
    name = ""
    if isinstance(info, dict):
        name = str(info.get("opportunity_name") or "").strip()
    if name and name != INFO_NOT_AVAILABLE:
        return name
    return fallback


def _percent_rows(items, kind: str) -> list:
    """[[name, "35%"], ...]: largest share first; equal shares keep the
    Guidance order, so the table is deterministic."""
    order = {name: i for i, name in enumerate(vocabulary(kind))}
    ranked = sorted(items or [], key=lambda item: (
        -int(item.get("percent", 0)), order.get(item.get("name"), len(order))))
    return [[str(item.get("name", "")), f"{int(item.get('percent', 0))}%"]
            for item in ranked]


def _value(info: dict, key: str) -> str:
    value = str(info.get(key) or "")
    # A table cell is one text run: several contact lines become one line.
    # Build and validation expectations share cleanup; tag-only missing
    # values must remain visible rather than becoming a blank table cell.
    parts = [clean_evidence_tags(part) for part in value.splitlines()]
    return "; ".join(part for part in parts if part) or INFO_NOT_AVAILABLE


def build_opportunity_slide(info: dict) -> dict:
    """The complete `opportunity` slide for the renderer."""
    return {"layout": "opportunity", "title": "Opportunity Info",
            "columns": list(MAIN_COLUMNS),
            "rows": [[label, _value(info, key)]
                     for label, key in OPPORTUNITY_ROWS],
            "products": _percent_rows(info.get("products"), "products"),
            "skills": _percent_rows(info.get("skills"), "skills")}


def fill_opportunity_slide(plan: dict, analysis: dict) -> list:
    """Replace section 1's placeholder with the built slide."""
    from .schema import OPPORTUNITY
    info = analysis.get("opportunity")
    if not isinstance(info, dict):
        return []
    for question in plan.get("questions", []):
        if question.get("number") == OPPORTUNITY:
            question["slides"] = [build_opportunity_slide(info)]
            return ["opportunity: slide built from the analysis"]
    return []
