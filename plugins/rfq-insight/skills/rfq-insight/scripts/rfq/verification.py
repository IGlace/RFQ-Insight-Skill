"""Extract checkable claims, apply verdicts, and explain confidence ratings."""

from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re

from . import opportunity
from .guidance import clean_site, fold
from .schema import OPPORTUNITY, RISKS
from .sources import DOWNGRADE_NOTE

ABSENCE_MARKERS = ("not found", "info not available", "not stated",
                   "no further parties")

# Section-1 lines for Account Name (Site) / KAM (PTE) always read "Info not
# available" in the model's own answer (the application fills them, not the
# model - see the QA prompt), so they are a formatting artefact, never a
# genuine absence claim.
_FIELD_PREFIXES = tuple(p.lower() for p in opportunity.ACCOUNT_FIELD_PREFIXES)


MAX_PER_SECTION = 3
PARTITION_THRESHOLD = 8
PARTITION_SIZE = 6
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


def check_candidates(answer: dict) -> list:
    """Every line of one stage-1 answer that qualifies for the check, as
    (kind, claim) pairs in answer order - before the per-section and
    overall caps. The slide notes (rfq/verification.py) count these to say
    how many statements the caps left unchecked."""
    sid = answer.get("id")
    found = []
    for line in str(answer.get("answer", "")).splitlines():
        clean = re.sub(r"[*|#]+", "", line).strip().lstrip("- ").strip()
        if sid == OPPORTUNITY and clean.lower().startswith(_FIELD_PREFIXES):
            continue
        if sid == RISKS and clean.startswith(
                opportunity.ACCOUNT_RISK_PREFIXES):
            continue
        low = line.lower()
        is_absence = any(m in low for m in ABSENCE_MARKERS)
        is_derived = "(inferred)" in low and any(c.isdigit() for c in line)
        if is_absence or is_derived:
            found.append(("absence" if is_absence else "derived", clean))
    return found


def extract_claims(analysis: dict, max_claims: int = 20) -> list:
    """Pull the checkable claims out of the stage-1 answers."""
    claims = []
    for a in analysis.get("answers", []):
        for kind, clean in check_candidates(a)[:MAX_PER_SECTION]:
            claims.append({
                "id": len(claims) + 1,
                "section": a.get("id"),
                "kind": kind,
                "claim": clean,
                "context": str(a.get("answer", "")),
            })
            if len(claims) >= max_claims:
                return claims
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


REFUTING = ("refuted", "ambiguous")

LOWERED_NOTE = ('Lowered to low by the independent check: the documents '
                'contradict {claims}.')
CONTRADICTED = '"{claim}" (quote: "{quote}")'
MAX_LISTED = 3          # contradicted statements named per section
RATED_BEFORE = "The analysis had rated this section {rating}: {reason}"
_RATED_BEFORE = re.compile(
    r"The analysis had rated this section (\w*):\s*(.*)\Z", re.DOTALL)


def model_rating(answer: dict) -> tuple:
    """(rating, reason) as the analysis wrote them. A section this module
    already lowered is read back from its RATED_BEFORE sentence, so
    applying the verdicts again never nests or repeats anything."""
    reason = str(answer.get("confidence_reason", "") or "").strip()
    found = _RATED_BEFORE.search(reason)
    if found:
        return found.group(1), found.group(2)
    return str(answer.get("confidence", "") or ""), reason


def lowered_reason(answer: dict, contradicted: list) -> str:
    """The lowered section's reason: the "Lowered to low" sentence first
    (up to MAX_LISTED contradicted statements, then "and N more"), then
    the analysis's own rating and reason."""
    items = [CONTRADICTED.format(claim=claim, quote=quote)
             for claim, quote in contradicted[:MAX_LISTED]]
    more = len(contradicted) - MAX_LISTED
    if more > 0:
        items.append(f"and {more} more statement(s) (listed in the run "
                     f"report)")
    rating, reason = model_rating(answer)
    return (f"{LOWERED_NOTE.format(claims='; '.join(items))} "
            f"{RATED_BEFORE.format(rating=rating, reason=reason)}").strip()


def apply_verdicts(analysis: dict, claims: list, verdicts: dict,
                   mode: str = "subagent") -> dict:
    """Merge verdicts into the claims and cap refuted sections at "low"."""
    if not claims:
        return {"status": "no_claims", "mode": mode, "claims": [],
                "refuted_sections": [], "rejected_verdicts": []}

    by_id = {v.get("id"): v for v in (verdicts or {}).get("verdicts", [])}
    results, refuted_sections, rejected = [], set(), []
    contradicted = {}

    for claim in claims:
        verdict_record = by_id.get(claim["id"], {})
        verdict = verdict_record.get("verdict", "unchecked")
        evidence = str(verdict_record.get("evidence", "") or "").strip()

        if verdict in REFUTING and not evidence:
            rejected.append(
                f"claim {claim['id']} (section {claim['section']}): "
                f"{verdict} without a verbatim quote, so it was not applied")
            verdict = "unchecked"
            evidence = ""

        results.append({**claim, "verdict": verdict, "evidence": evidence})
        if verdict == "refuted":
            refuted_sections.add(claim["section"])
            # One entry per claim id, however often it is listed.
            contradicted.setdefault(claim["section"], {}).setdefault(
                claim["id"], (claim["claim"], evidence))

    for answer in analysis.get("answers", []):
        if answer.get("id") in refuted_sections:
            # Rebuilt from the analysis's own reason every time, so a
            # resume that applies the verdicts again changes nothing.
            answer["confidence_reason"] = lowered_reason(
                answer, list(contradicted[answer["id"]].values()))
            answer["confidence"] = "low"

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


RATING_GUIDE = (
    "How the rating works:\n"
    "- High: the answer has direct or corroborated support, with no material "
    "unresolved inference or contradiction. A confirmed absence can also "
    "be high; \"Info not available\" alone does not establish search coverage.\n"
    "- Medium: part of the answer is inferred, partial or taken from a "
    "secondary document, or a missing item may sit in a part of the "
    "documents that could not be read (for example an unreadable picture).\n"
    "- Low: the documents contradict each other or are ambiguous on this "
    "section, the answer rests mainly on inference, or the independent "
    "check found a statement that the documents contradict.")

CHECK_SCOPE = "Only selected missing-information claims and calculated dates or quantities were checked."
NO_CHECK = "Check: no statements were selected for a second review."
CHECK_FAILED = ("Independent check: the second check could not run for "
                "this deck, so this rating was not double-checked.")

# The product-picture slides (rfq/pictures.py) sit in the Technical section
# but carry no chip: the application adds them, no answer is rated.
PICTURE_NOTES = ("Pictures selected by the application from the RFQ "
                 "documents; captions written by the figure reader. Not part "
                 "of the section's confidence rating.")

_VERDICT_WORDS = (("confirmed", "confirmed"),
                  ("refuted", "contradicted by the documents"),
                  ("ambiguous", "found ambiguous"),
                  ("unchecked", "not checked"))


def _not_rechecked(count: int) -> str:
    return f"{count} additional statements were not checked (not present in the saved check record)."


def _check_details(claims) -> str:
    """Preserve recorded statements and quotes, without inventing evidence."""
    words = dict(_VERDICT_WORDS)
    lines = []
    for claim in claims:
        statement = str(claim.get("claim") or "").strip()
        if not statement:
            continue
        verdict = words.get(claim.get("verdict"), "not checked")
        quote = str(claim.get("evidence") or "").strip()
        evidence = f'Source text: "{quote}"' if quote else "No source quote was recorded."
        lines.append(f'- {statement}\n  Result: {verdict}. {evidence}')
    return "\n\nStatements checked:\n" + "\n".join(lines) if lines else ""


def check_summary(section_id, verification, candidates: int = 0) -> str:
    """What the independent check did for this section. `candidates` is
    how many of its statements qualify for the check (extract_claims'
    rule). Claims missing from the saved record were not checked; the
    record alone does not establish whether a limit or another omission
    caused that gap."""
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
        return (f"Check: {_not_rechecked(skipped)}" if skipped
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
    text = (f"Check: {checked} statements reviewed {reviewer}"
            + (": " + ", ".join(parts) if parts else "") + ".")
    if unchecked:
        text += f" {unchecked} statements were not checked (no usable result)."
    if skipped:
        text += f" {_not_rechecked(skipped)}"
    return f"{text} {CHECK_SCOPE}{_check_details(claims)}"


def answer_evidence_notes(answer: dict) -> str:
    """Explain the recorded answer's uncertainty markers, not factual counts.

    Untagged lines are never counted as direct evidence: that would imply
    factual validation the application has not performed.
    """
    lines = [line.strip() for line in str(answer.get("answer") or "").splitlines()
             if "(inferred)" in line.lower()]
    selected = check_candidates(answer)
    parts = []
    if lines:
        parts.append("Estimates or assumptions:\n" + "\n".join("- " + line for line in lines))
    absences = [claim for kind, claim in selected if kind == "absence"]
    if absences:
        parts.append("Information reported as missing:\n" + "\n".join(
            "- " + claim for claim in absences))
    return "\n\n".join(parts)


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


def confidence_notes(rating: str, reason: str, check: str,
                     extra: str = "") -> str:
    """The full notes text for one section."""
    reason = (reason or "").strip() or "No reason was recorded for this rating."
    # Historical downgrade records retain the former rating for audit;
    # presentation notes explain only the current reason.
    reason = _RATED_BEFORE.sub("", reason).strip()
    check = check.partition("\n\nStatements checked:")[0]
    block = f"{extra}\n\n" if extra else ""
    return (f"CONFIDENCE: {str(rating).upper()}\n\n"
            f"Reason:\n{reason}\n\n"
            f"{check}\n\n"
            f"{block}").strip()


def attach_confidence_notes(plan: dict, analysis: dict, verification,
                            account=None, downgrades=None) -> list:
    """Set question["confidenceNotes"] for every rated section; Opportunity
    Info also explains the account lookup. Returns actions for the run
    report."""
    by_id = {a.get("id"): a for a in analysis.get("answers", [])
             if isinstance(a, dict)}
    noted = 0
    for question in plan.get("questions", []):
        number = question.get("number")
        answer = by_id.get(number)
        rating = question.get("confidence")
        if not answer or not rating:
            continue
        extra = "\n\n".join(part for part in (
            question.get("sourceDetails"),
            downgrade_notes(number, downgrades),
            account_lookup_notes(account) if number == OPPORTUNITY else "")
            if part)
        question["confidenceNotes"] = confidence_notes(
            rating, answer.get("confidence_reason", ""),
            check_summary(number, verification,
                          len(check_candidates(answer))), extra)
        noted += 1
    # One run-report line, not one per section.
    return [f"confidence notes: {noted} sections"] if noted else []
