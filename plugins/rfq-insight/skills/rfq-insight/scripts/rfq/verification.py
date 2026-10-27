"""Harvest checkable claims, turn verdicts into deductions, and write the
confidence notes of every section."""

from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re

from . import confidence, opportunity
from .guidance import clean_site, fold
from .schema import DESCRIPTION, OPPORTUNITY, RISKS, SECTION_MODES
from .sources import DOWNGRADE_NOTE
from .validation import STANDARD_RE

ABSENCE_MARKERS = ("not found", "info not available", "not stated",
                   "no further parties", "no definition in the rfq")

# Section-1 lines for Account Name (Site) / KAM (PTE) always read "Info not
# available" in the model's own answer (the application fills them, not the
# model - see the QA prompt), so they are a formatting artefact, never a
# genuine absence claim.
_FIELD_PREFIXES = tuple(p.lower() for p in opportunity.ACCOUNT_FIELD_PREFIXES)


MAX_PER_SECTION = 6      # claims checked per section
MAX_STATED = 4           # of which "stated" claims, in answer order
MAX_CLAIMS = 48          # claims checked per run
PARTITION_THRESHOLD = 8
PARTITION_SIZE = 8       # 48 claims -> at most 6 parallel verifiers
JOBS_FILE = "verification_jobs.json"
RECEIPT_FILE = "verification_receipt.json"


def claims_identity(claims: list) -> str:
    canonical = json.dumps(claims, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def partition_claims(claims: list) -> list:
    size = PARTITION_SIZE if len(claims) >= PARTITION_THRESHOLD else len(claims)
    return [claims[start:start + size] for start in range(0, len(claims), size)] if size else []


def check_verdicts(payload, claim_ids) -> list:
    """Require exactly one well-shaped verdict for every selected integer ID."""
    if not isinstance(payload, dict) or not isinstance(payload.get("verdicts"), list):
        return ["verdicts.json must be an object with a 'verdicts' list."]
    problems, seen = [], set()
    expected = set(claim_ids)
    for record in payload["verdicts"]:
        if not isinstance(record, dict):
            problems.append("Every verdict must be an object.")
            continue
        claim_id = record.get("id")
        if type(claim_id) is not int:
            problems.append("Every verdict id must be an integer.")
            continue
        if claim_id in seen:
            problems.append(f"Duplicate verdict id: {claim_id}.")
        seen.add(claim_id)
        if claim_id not in expected:
            problems.append(f"Unexpected verdict id: {claim_id}.")
        if record.get("verdict") not in ("confirmed", "refuted", "ambiguous"):
            problems.append(f"Claim {claim_id} has an invalid verdict.")
        if not isinstance(record.get("evidence", ""), str):
            problems.append(f"Claim {claim_id} evidence must be a string.")
    missing = sorted(expected - seen)
    if missing:
        problems.append(f"Missing verdict ids: {missing}.")
    return problems


def confined_path(work, relative) -> Path:
    """Reject traversal, symlinks and directories before any checkpoint IO."""
    work = Path(work).absolute()
    if not isinstance(relative, str) or not relative or "\\" in relative or ":" in relative:
        raise ValueError("A verification path must be relative to the work directory.")
    name = Path(relative)
    if name.is_absolute() or any(part in (".", "..") for part in name.parts):
        raise ValueError("A verification path escapes the work directory.")
    target = work / name
    if not target.resolve().is_relative_to(work.resolve()):
        raise ValueError("A verification path escapes the work directory.")
    for path in (target, *target.parents):
        if path == work:
            break
        if path.is_symlink():
            raise ValueError("A verification checkpoint may not use symlinks.")
    if target.exists() and not target.is_file():
        raise ValueError("A verification checkpoint must be a regular file.")
    return target


def archive_paths(work) -> list:
    """All partition artifacts, confined before state.start moves any file."""
    work = Path(work)
    root = work / "verification"
    if root.is_symlink() or not root.resolve().is_relative_to(work.resolve()):
        raise ValueError("The verification directory escapes the work directory.")
    paths = [confined_path(work, JOBS_FILE), confined_path(work, RECEIPT_FILE)]
    for directory, directories, filenames in os.walk(root, followlinks=False):
        # A malformed file entry replaced by a directory is not evidence.
        # Leave it untouched; new job paths use a fresh run ID.
        directories[:] = [name for name in directories
                          if name not in ("claims.json", "verdicts.json")]
        for name in directories + filenames:
            path = Path(directory) / name
            if path.is_symlink():
                raise ValueError("A verification checkpoint may not use symlinks.")
        for name in filenames:
            path = Path(directory) / name
            paths.append(confined_path(work, path.relative_to(work).as_posix()))
    return paths


def jobs_match(work, jobs, claims, revision) -> bool:
    """Only complete, current coordinator job descriptors can be resumed."""
    if (not isinstance(jobs, dict) or jobs.get("version") != 1 or
            jobs.get("corpus_revision") != revision or
            jobs.get("claims_sha256") != claims_identity(claims) or
            not isinstance(jobs.get("run_id"), str) or
            re.fullmatch(r"[a-f0-9]{12}", jobs["run_id"]) is None):
        return False
    try:
        if _load(confined_path(work, "claims.json")) != {"claims": claims}:
            return False
        if jobs.get("corpus_text_sha256") != hashlib.sha256(confined_path(work, "corpus.txt").read_bytes()).hexdigest():
            return False
    except (OSError, ValueError):
        return False
    groups = partition_claims(claims)
    parts = jobs.get("partitions")
    if not isinstance(parts, list) or len(parts) != len(groups):
        return False
    base = f"verification/{revision[:12]}-{jobs['claims_sha256'][:12]}/{jobs['run_id']}"
    for index, (part, group) in enumerate(zip(parts, groups), 1):
        if (not isinstance(part, dict) or part.get("partition_id") != f"part-{index}" or
                part.get("claim_ids") != [claim["id"] for claim in group] or
                type(part.get("attempt")) is not int or not 1 <= part["attempt"] <= 3 or
                not isinstance(part.get("request_id"), str) or not part["request_id"] or
                (part.get("accepted_sha256") is not None and
                 (not isinstance(part["accepted_sha256"], str) or
                  re.fullmatch(r"[a-f0-9]{64}", part["accepted_sha256"]) is None))):
            return False
        directory = f"{base}/part-{index}/attempt-{part['attempt']}"
        expected_claims = f"{directory}/claims.json" if len(groups) > 1 else "claims.json"
        expected_output = f"{directory}/verdicts.json" if len(groups) > 1 else "verdicts.json"
        if part.get("claims_path") != expected_claims or part.get("output_path") != expected_output:
            return False
        try:
            path = confined_path(work, expected_claims)
            confined_path(work, expected_output)
            if _load(path) != {"claims": group}:
                return False
        except (OSError, ValueError):
            return False
    return True


def receipt_matches(work, receipt, claims, revision) -> bool:
    """Certify the complete coordinator artifacts independently of the jobs file."""
    if (not isinstance(receipt, dict) or receipt.get("version") != 1 or
            receipt.get("corpus_revision") != revision or
            receipt.get("claims_sha256") != claims_identity(claims) or
            not isinstance(receipt.get("artifacts"), dict) or
            set(receipt["artifacts"]) != {"verdicts.json", "verification.json"}):
        return False
    try:
        return all(isinstance(expected, str) and len(expected) == 64 and
                   hashlib.sha256(confined_path(work, name).read_bytes()).hexdigest() == expected
                   for name, expected in receipt["artifacts"].items())
    except (OSError, ValueError):
        return False


_SEPARATOR_CELL = re.compile(r":?-+:?")       # as validation._tables reads it
_BULLET = re.compile(r"(?:[-*\u2022]|\d+[.)])\s")
_NUMBERED = re.compile(r"^\d+[.)]\s+")
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"\u201c(])")
# The one item an empty risk group holds ("No document risk was found.")
# names no clause, so there is no triggering fact to check.
# An empty risk group's one item ("No contradictions, vague or ambiguous
# content found in the RFQ.", prompt v14 7.11.6) has no trigger to check.
_EMPTY_RISK_GROUP = re.compile(r"No\b.*\b(?:found|identified|detected)\b", re.I)


def _cells(line: str) -> list:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _is_separator(line: str) -> bool:
    return all(_SEPARATOR_CELL.fullmatch(cell) for cell in _cells(line))


def _content_lines(text: str):
    """(shape, clean) per content line of an answer, in order. shape is
    "row" (a table data row, cells joined with " | "), "bullet" or "text".
    A table's header and separator rows (the first two rows of a pipe
    block when the second is a separator), headings and blank lines are
    skipped; a numbered-list prefix is dropped."""
    lines = text.splitlines()
    piped = [line.strip().startswith("|") for line in lines]
    skip = set()
    for index in range(len(lines) - 1):
        if (piped[index] and piped[index + 1]
                and (index == 0 or not piped[index - 1])
                and _is_separator(lines[index + 1])):
            skip |= {index, index + 1}
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or index in skip:
            continue
        if piped[index]:
            cells = [re.sub(r"[*#]+", "", cell) for cell in _cells(stripped)]
            yield "row", " | ".join(cell.strip() for cell in cells)
            continue
        shape = "bullet" if _BULLET.match(stripped) else "text"
        clean = re.sub(r"[*|#]+", "", line).strip().lstrip("- ").strip()
        yield shape, _NUMBERED.sub("", clean)


def _sentences(text: str) -> list:
    """The sentences of a Description line; a piece under 4 words
    ("Approx.", "5 kW.") is joined to the sentence before it, or to the
    next one when it comes first."""
    merged, pending = [], ""
    for piece in (p.strip() for p in _SENTENCE_BREAK.split(text)):
        if not piece:
            continue
        piece = f"{pending} {piece}" if pending else piece
        pending = ""
        if len(piece.split()) >= 4:
            merged.append(piece)
        elif merged:
            merged[-1] = f"{merged[-1]} {piece}"
        else:
            pending = piece
    return merged + ([pending] if pending else [])


def _marked_kind(text: str, extracted: bool):
    """"absence" for a missing-information line, "derived" for an
    (inferred) one (outside extracted sections only with a digit, the
    pre-v3 rule), else None."""
    low = text.lower()
    if any(marker in low for marker in ABSENCE_MARKERS):
        return "absence"
    if "(inferred)" in low and (extracted or any(c.isdigit() for c in text)):
        return "derived"
    return None


def check_candidates(answer: dict) -> list:
    """Every statement of one answer that qualifies for the check, as
    (kind, claim) pairs in answer order, before the per-section and overall
    caps (the notes count these to say how many went unchecked).

    By section mode (schema.SECTION_MODES): an extracted section gives
    every absence and (inferred) line plus up to MAX_STATED "stated" table
    rows or bullets that carry a digit or a standard designation;
    Description gives its absence and inferred lines and up to MAX_STATED
    sentences as "stated"; Risk Detection gives each risk item as a
    "trigger" (its triggering fact must exist); Opportunity Info gives
    absence and inferred lines; Source Material (Python-built) nothing."""
    sid = answer.get("id")
    mode = SECTION_MODES.get(sid)
    if mode == "python":
        return []
    extracted = mode == "extracted"
    found, stated = [], 0
    for shape, clean in _content_lines(str(answer.get("answer", ""))):
        if sid == OPPORTUNITY and clean.lower().startswith(_FIELD_PREFIXES):
            continue
        if sid == RISKS and clean.startswith(
                opportunity.ACCOUNT_RISK_PREFIXES):
            continue
        pieces = _sentences(clean) if sid == DESCRIPTION else [clean]
        for piece in pieces:
            kind = _marked_kind(piece, extracted)
            if kind is None:
                if sid == DESCRIPTION or (
                        extracted and shape in ("row", "bullet") and (
                            any(c.isdigit() for c in piece)
                            or STANDARD_RE.search(piece))):
                    kind = "stated"
                elif (sid == RISKS and shape == "bullet"
                      and not _EMPTY_RISK_GROUP.match(piece)):
                    kind = "trigger"
            if kind == "stated":
                if stated >= MAX_STATED:
                    continue
                stated += 1
            if kind:
                found.append((kind, piece))
    return found


def extract_claims(analysis: dict, max_claims: int = MAX_CLAIMS) -> list:
    """The checkable claims of the stage-1 answers. Each section offers at
    most MAX_PER_SECTION (absence, derived and trigger claims before stated
    ones, answer order inside each group); the run's `max_claims` are
    shared round-robin, one claim per section per pass, so the last
    sections are never starved. Returned by section, then answer order."""
    answers = [a for a in analysis.get("answers", []) if isinstance(a, dict)]
    offers = []
    for a in answers:
        found = check_candidates(a)
        offers.append((found, sorted(range(len(found)), key=lambda i: (
            found[i][0] == "stated", i))[:MAX_PER_SECTION]))
    chosen = [[] for _ in answers]
    taken = 0
    for turn in range(MAX_PER_SECTION):
        for slot, (_found, order) in enumerate(offers):
            if taken < max_claims and turn < len(order):
                chosen[slot].append(order[turn])
                taken += 1
    claims = []
    for a, (found, _order), picked in zip(answers, offers, chosen):
        for index in sorted(picked):
            kind, clean = found[index]
            claims.append({
                "id": len(claims) + 1,
                "section": a.get("id"),
                "kind": kind,
                "claim": clean,
                "context": str(a.get("answer", "")),
            })
    return claims


def write_claims(folder: str) -> list:
    """Harvest claims from .work/analysis.json into .work/claims.json.
    Raises FileNotFoundError when the analysis is missing."""
    work = os.path.join(os.path.abspath(folder), "output", ".work")
    with open(os.path.join(work, "analysis.json"), encoding="utf-8") as fh:
        analysis = json.load(fh)
    claims = extract_claims(analysis)
    with open(os.path.join(work, "claims.json"), "w", encoding="utf-8") as fh:
        json.dump({"claims": claims}, fh, ensure_ascii=False, indent=2)
    return claims


# Only a refuted claim costs points (V1). An ambiguous verdict is reported
# on the Check line and costs nothing; the V2 entries older runs wrote are
# cleared when verdicts are applied again.
REFUTING = ("refuted",)
# Verdicts the verifier prompt requires a verbatim quote for; one without it
# is invalid and counts as unchecked.
QUOTED = ("refuted", "ambiguous")
VERDICT_CODES = ("V1",)           # refuted (schema.RULES)
_RETIRED_CODES = ("V2",)          # ambiguous, before the client decision
_CLEARED_CODES = VERDICT_CODES + _RETIRED_CODES


# The claim and the quote in a V1 notes line, in words each.
VERDICT_LINE_WORDS = 20
_NO_CLAUSE = re.compile(r"No clause on (.+?) in the corpus\.?", re.I)


def _capped(text: str, limit: int = VERDICT_LINE_WORDS) -> str:
    words = text.split()
    return text if len(words) <= limit else " ".join(words[:limit]) + "…"


def _claim_sentence(claim: str) -> str:
    """A harvested table row ("Fuel | Gasoline Ron95 | Engine development
    boundary") as a sentence: the first cell as its label, the other cells
    joined with ", " ("Fuel: Gasoline Ron95, Engine development boundary")."""
    if " | " not in claim:
        return claim
    first, *rest = claim.split(" | ")
    rest = [cell for cell in (part.strip() for part in rest) if cell]
    return f"{first.strip()}: {', '.join(rest)}" if rest else first.strip()


def _verdict_entry(code, claim, evidence) -> dict:
    """The V1 entry of one verdict: the claim as a sentence and the
    quote, about VERDICT_LINE_WORDS words each; a refuted trigger with no clause
    on its subject names that instead of a quote."""
    no_clause = _NO_CLAUSE.fullmatch(evidence.strip())
    basis = (f"no clause on {no_clause.group(1)} in the corpus" if no_clause
             else f'quote: "{_capped(evidence)}"')
    return {"rule": code, "count": 1,
            "items": f'"{_capped(_claim_sentence(claim))}"', "basis": basis}


def apply_verdicts(analysis: dict, claims: list, verdicts: dict,
                   mode: str = "subagent") -> dict:
    """Merge the verdicts into the claims and write them as deductions: a
    refuted claim is a V1 entry on its section's answer; an ambiguous one
    is only counted on the Check line. The runner's earlier V1 entries (and
    an older run's V2 entries) are replaced, so applying the same verdicts
    again changes nothing. A refuted "stated" claim in an extracted section
    also names its section in refuted_sections (a contradicted value, for
    the report)."""
    by_id = {v.get("id"): v for v in (verdicts or {}).get("verdicts", [])
             if isinstance(v, dict)} if claims else {}
    results, refuted_sections, rejected = [], set(), []
    entries, seen = {}, set()

    for claim in claims:
        verdict_record = by_id.get(claim["id"], {})
        verdict = verdict_record.get("verdict", "unchecked")
        evidence = str(verdict_record.get("evidence", "") or "").strip()

        if verdict in QUOTED and not evidence:
            rejected.append(
                f"claim {claim['id']} (section {claim['section']}): "
                f"{verdict} without a verbatim quote, so it was not applied")
            verdict = "unchecked"
            evidence = ""

        results.append({**claim, "verdict": verdict, "evidence": evidence})
        # One entry per claim id, however often it is listed.
        if verdict in REFUTING and claim["id"] not in seen:
            seen.add(claim["id"])
            entries.setdefault(claim["section"], []).append(
                _verdict_entry("V1", claim["claim"], evidence))
        if (verdict == "refuted" and claim.get("kind") == "stated"
                and SECTION_MODES.get(claim["section"]) == "extracted"):
            refuted_sections.add(claim["section"])

    for answer in analysis.get("answers", []):
        if isinstance(answer, dict):
            confidence.merge_python_deductions(
                answer, _CLEARED_CODES, entries.get(answer.get("id"), []))

    if not claims:
        return {"status": "no_claims", "mode": mode, "claims": [],
                "refuted_sections": [], "rejected_verdicts": []}
    return {"status": "ok", "mode": mode, "claims": results,
            "refuted_sections": sorted(refuted_sections),
            "rejected_verdicts": rejected}


def _load(path: str):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def run_apply(folder: str, mode: str = "subagent") -> dict:
    """Apply .work/verdicts.json; write verification.json and the updated
    analysis.json; return the verification record.

    Raises FileNotFoundError when analysis.json or claims.json is missing.
    A missing or unreadable verdicts.json is NOT raised: it becomes a record
    with status "error", exactly as the CLI has always done.
    """
    work = os.path.join(os.path.abspath(folder), "output", ".work")
    analysis = _load(os.path.join(work, "analysis.json"))
    claims = _load(os.path.join(work, "claims.json")).get("claims", [])
    try:
        verdicts = _load(os.path.join(work, "verdicts.json"))
        record = apply_verdicts(analysis, claims, verdicts, mode=mode)
    except Exception as exc:
        # No usable verdicts: an earlier application's entries go too.
        for answer in analysis.get("answers", []):
            if isinstance(answer, dict):
                confidence.merge_python_deductions(answer, _CLEARED_CODES, [])
        record = {"status": "error", "mode": mode,
                  "error": f"{type(exc).__name__}: {exc}",
                  "claims": claims, "refuted_sections": [],
                  "rejected_verdicts": []}
    with open(os.path.join(work, "analysis.json"), "w", encoding="utf-8") as fh:
        json.dump(analysis, fh, ensure_ascii=False, indent=2)
    with open(os.path.join(work, "verification.json"), "w",
              encoding="utf-8") as fh:
        json.dump(record, fh, ensure_ascii=False, indent=2)
    return record


NO_CHECK = "Check: no statements were selected for a second review."
CHECK_FAILED = "Check: the independent check could not run; nothing was reviewed."

_VERDICT_WORDS = (("confirmed", "confirmed"),
                  ("refuted", "contradicted by the documents"),
                  ("ambiguous", "found ambiguous"),
                  ("unchecked", "not checked"))


def _skipped(count: int) -> str:
    return f"; {count} more not checked (cap)"


def check_summary(section_id, verification, candidates: int = 0) -> str:
    """The one "Check:" line of a section's notes: what the independent
    check did for it. `candidates` is how many of its statements qualify
    for the check (check_candidates); those missing from the saved record
    were left out by the claim caps and are counted as "more not checked
    (cap)". Client-facing, so it stays one line."""
    if verification is not None and not isinstance(verification, dict):
        verification = None
    if verification is not None and verification.get("status") == "error":
        return CHECK_FAILED
    if verification is None:
        return CHECK_FAILED if candidates else NO_CHECK
    claims = [c for c in verification.get("claims", []) or []
              if isinstance(c, dict) and c.get("section") == section_id]
    skipped = max(candidates - len(claims), 0)
    if not claims:
        return (f"Check: 0 statements reviewed{_skipped(skipped)}." if skipped
                else NO_CHECK)
    counts = Counter(c.get("verdict", "unchecked") for c in claims)
    checked = sum(counts[key] for key in ("confirmed", "refuted", "ambiguous"))
    unchecked = len(claims) - checked
    parts = [f"{counts[key]} {words}" for key, words in _VERDICT_WORDS
             if key != "unchecked" and counts[key]]
    mode = verification.get("mode")
    reviewer = ("by a separate reviewer" if mode in ("subagent", "isolated") else
                "in this chat; this was not an independent review" if mode == "in-thread" else
                "using saved results; reviewer independence was not recorded")
    noun = "statement" if checked == 1 else "statements"
    text = (f"Check: {checked} {noun} reviewed {reviewer}"
            + (": " + ", ".join(parts) if parts else ""))
    if unchecked:
        text += f"; {unchecked} without a usable result"
    if skipped:
        text += _skipped(skipped)
    return text + "."


_ACCOUNT_RESULT = {
    "matched": "Result: {account_name}, KAM {kam_pte}.",
    "no_kam": ('Result: {account_name}. This account has no KAM (PTE) '
               'assigned, so KAM (PTE) shows "Info not available".'),
    "ambiguous": ('Result: no single account fits, so Account Name (Site) '
                  'and KAM (PTE) show "Info not available".'),
    "none": ('Result: no account in the list matches this customer name, so '
             'Account Name (Site) and KAM (PTE) show "Info not available".'),
    # rfq/delivery.py: account_match.json missing, unreadable, or made for
    # another customer name or address (account_match_is_current).
    "unreadable": ('Result: the saved lookup result could not be used (it '
                   'is missing, unreadable, or was made for a different '
                   'customer name or address), so Account Name (Site) and '
                   'KAM (PTE) show "Info not available" (see Document '
                   'Risks).'),
}


def _candidate(detail) -> str:
    """'Bosch (Waiblingen) (Germany, KAM X)'; the country is left out when
    it is the site the account name already shows ('Bosch (Brazil), KAM Y')."""
    name = detail.get("account_name", "")
    country = detail.get("country") or ""
    kam = f'KAM {detail.get("kam_pte", "")}'
    if country and fold(country) == fold(detail.get("site") or ""):
        return f"{name}, {kam}"
    return f'{name} ({country or "country not given"}, {kam})'


def _candidate_lines(details) -> list:
    """One line per candidate with its reason; candidates that share the
    very same reason are folded into one "Not chosen (n accounts): ..."
    line with every name listed below it."""
    groups = {}
    for d in details:
        groups.setdefault(d.get("reason", ""), []).append(d)
    lines = []
    for reason, group in groups.items():
        if len(group) == 1:
            lines.append(f"- {_candidate(group[0])}: {reason}")
            continue
        verdict, sep, why = reason.partition(": ")
        lines.append(f"- {verdict} ({len(group)} accounts): {why}" if sep
                     else f"- ({len(group)} accounts) {reason}")
        lines += [f"  - {_candidate(d)}" for d in group]
    return lines


def account_lookup_notes(match) -> str:
    """The Salesforce account lookup explained (Opportunity Info only):
    the name searched, the customer's own address used, the result, and
    every close candidate with the reason it was or was not chosen. "" when
    there is no lookup record."""
    if not isinstance(match, dict) or match.get("status") not in _ACCOUNT_RESULT:
        return ""
    lines = ["Account lookup (Salesforce account list, Guidance Document):",
             f'Customer name in the RFQ: "{match.get("customer", "")}"']
    if match["status"] != "unreadable":
        site = clean_site(match.get("customer_site"))
        if site:
            lines.append("Customer's own address in the RFQ (used first to "
                         f'tell its sites apart): "{site}"')
        else:
            lines.append("Customer's own address in the RFQ: none (no "
                         "customer address in the RFQ).")
    lines.append(_ACCOUNT_RESULT[match["status"]].format(
        account_name=match.get("account_name", ""),
        kam_pte=match.get("kam_pte", "")))
    details = (match.get("candidate_details") or []
               if match["status"] != "unreadable" else [])
    if details:
        lines.append("Candidates considered:")
        lines += _candidate_lines(details)
        more = int(match.get("candidate_count") or len(details)) - len(details)
        if more > 0:
            lines.append(f"- ... and {more} more account(s) with the same "
                         f"name match, not listed.")
    return "\n".join(lines)


def downgrade_notes(section_id, downgrades) -> str:
    """One sentence naming this section's cited locations that were not
    found and kept as whole-file sources (.work/source_downgrades.json
    entries read "Section <id>: <file> <locator>"); "" when none."""
    prefix = f"Section {section_id}: "
    found = [str(d)[len(prefix):] for d in downgrades or []
             if str(d).startswith(prefix)]
    return f"{DOWNGRADE_NOTE}{'; '.join(found)}." if found else ""


def _usable_deductions(number, answer: dict) -> tuple:
    """(entries the section allows, codes of the ones it does not). A
    stored analysis is read as it is: an unknown or misplaced code is
    left out of the score instead of failing the deck."""
    kept, ignored = [], []
    for entry in answer.get("deductions") or []:
        try:
            confidence.resolve([entry], number, answer.get("mode"),
                               allow_python=True)
        except (ValueError, AttributeError, TypeError):
            ignored.append(str(entry.get("rule", "")) if isinstance(entry, dict)
                           else repr(entry))
            continue
        kept.append(entry)
    return kept, ignored


def split_deductions(answer: dict) -> list:
    """Section 1's P1/P2 entries - the percentage slide's own deductions."""
    kept, _ignored = _usable_deductions(OPPORTUNITY, answer)
    return confidence.partition_split(kept)[1]


def section_confidence(number, answer: dict) -> tuple:
    """(resolved deductions, score, band) of one answer: the model's own
    entries and the runner's (V1-V3) priced by rfq/confidence.py. Entries
    the section does not allow are left out (_usable_deductions).

    The score is capped by what the content actually IS - an estimate cannot
    reach High however few points it cost (client requirement 1,
    15.10.2026) - and the band follows the score as it always has."""
    kept, _ignored = _usable_deductions(number, answer)
    # The percentage split is rated on its own slide, never here.
    kept = confidence.partition_split(kept)[0]
    resolved = confidence.resolve(kept, number, answer.get("mode"),
                                  allow_python=True)
    value = confidence.score(resolved, number)
    return resolved, value, confidence.band(value)


def confidence_notes(number, answer: dict, check: str, extra: str = "") -> str:
    """The notes of one section: score and band, whether the content was
    extracted or inferred, one line per deduction that costs points (entries
    past a cap are left out), whether anything had to be settled, the check
    line, the shown line when the answer was trimmed, then `extra` (sources,
    downgrade note, account lookup) after a blank line."""
    resolved, value, level = section_confidence(number, answer)
    return confidence.notes(
        value, level, [entry["line"] for entry in resolved if entry["points"]],
        check, confidence.shown_line(number, answer.get("shown")), extra,
        not_found=bool(answer.get("not_found")), deductions=resolved)


def attach_confidence_notes(plan: dict, analysis: dict, verification,
                            account=None, downgrades=None) -> list:
    """Set confidence (band), score, deductions (resolved) and
    confidenceNotes on every question the analysis answers; Opportunity
    Info also explains the account lookup. Returns actions for the run
    report."""
    by_id = {a.get("id"): a for a in analysis.get("answers", [])
             if isinstance(a, dict)}
    noted, actions = 0, []
    for question in plan.get("questions", []):
        number = question.get("number")
        answer = by_id.get(number)
        if not answer:
            continue
        actions += [f"Section {number}: ignored an unrecognised deduction {code}"
                    for code in _usable_deductions(number, answer)[1]]
        resolved, value, level = section_confidence(number, answer)
        extra = "\n\n".join(part for part in (
            question.get("sourceDetails"),
            downgrade_notes(number, downgrades),
            account_lookup_notes(account) if number == OPPORTUNITY else "")
            if part)
        question["confidence"] = level
        question["score"] = value
        question["deductions"] = resolved
        question["confidenceNotes"] = confidence_notes(
            number, answer, check_summary(
                number, verification, len(check_candidates(answer))), extra)
        noted += 1
    # One run-report line, not one per section.
    return actions + ([f"confidence notes: {noted} sections"] if noted else [])
