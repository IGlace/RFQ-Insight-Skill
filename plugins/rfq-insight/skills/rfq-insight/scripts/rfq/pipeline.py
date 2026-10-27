"""The RFQ Insight pipeline runner: one call per model stage.

The coordinator (the agent following SKILL.md) used to run about 25 separate
scripts per RFQ, plus two per picture: start/complete markers, validators,
request builders, merges, the deck build and the quality check. Each was a
fresh Python process and a separate tool call. This module runs every
deterministic step in ONE process and stops only where a model worker is
needed:

    result = advance(folder, host)
    "dispatch" -> run one fresh worker per request, then advance() again
    "repair"   -> send "errors" to the same worker, then advance() again
    "done"     -> deliver result["pptx"]
    "stopped"  -> the requested `until` stage is complete
    "blocked"  -> stop and relay result["message"] verbatim

The rules are the ones SKILL.md used to ask the coordinator to apply:
resume rules, archive-on-start, three attempts per model stage,
zero-claims skip, the evaluation gate and execution records. The scripts
this module calls remain available through `rfq_run.py debug` for inspection.
"""

import json
import hashlib
import os
import traceback
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from . import verification as apply_verdicts            # noqa: E402
from . import validation as evaluate_mod  # noqa: E402
from . import verification as extract_claims            # noqa: E402
from . import delivery as finalize_mod  # noqa: E402
from . import planning as plan_input                # noqa: E402
from . import validation as validate                  # noqa: E402

from . import confidence, figures, state, workers
from .corpus import (run_extraction, write_corpus_text, corpus_revision,
                     prepare_evidence_chunks, merge_evidence_receipts,
                     EvidencePreparationError)
from .state import ATTEMPTS_FILE, replace_with_retry
from . import guidance, language, opportunity
from .sources import downgrade_locators, expand_reference_ids
from .figures import identity_matches

MAX_ATTEMPTS = 3          # per model stage, including the first attempt
FIGURE_BATCH = 6          # pictures per figure worker
STAGES = state.STAGES
# Citations the last analysis attempt kept as whole-file sources.
DOWNGRADES_FILE = "source_downgrades.json"
# The deduction a corpus miss costs once the analysis is out of attempts.
FAITHFULNESS_CODE = "V3"

# The exact sentences SKILL.md prescribes. The coordinator relays
# result["message"] verbatim as its only reply.
MSG_NO_FOLDER = "The RFQ folder could not be found; correct the path."
MSG_BAD_PROGRESS = ("The progress record is invalid; choose an explicit "
                    "stage to restart.")
MSG_NOTHING_READABLE = ("The RFQ folder contains no readable supported "
                        "documents.")
MSG_UNREADABLE = ("Cannot read {names}; provide readable copies to generate "
                  "the PowerPoint.")
MSG_TOO_LARGE = ("The RFQ package exceeds the supported size; provide a "
                 "smaller package.")
MSG_ANALYSIS = "The analysis could not be validated; progress is saved."
MSG_VERIFICATION = ("The claim verification could not be completed; "
                    "progress is saved.")
MSG_SLIDES = "The slide plan could not be validated; progress is saved."
MSG_BUILD = "The PowerPoint could not be generated; progress is saved."
MSG_EVALUATE = "The PowerPoint did not pass validation; progress is saved."
MSG_BAD_DELIVERABLES = "The delivery record is invalid; progress is saved."


@dataclass
class _Run:
    folder: str
    work: Path
    host: str
    project: str | None = None
    actual_model: str | None = None
    actual_effort: str | None = None
    restart: str | None = None
    author: str | None = None
    department: str | None = None


def _blocked(message: str) -> dict:
    return {"status": "blocked", "message": message}


def _load_json(path: Path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with open(temporary, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    replace_with_retry(temporary, path)


def _rank(stage: str) -> int:
    return len(STAGES) if stage == "done" else STAGES.index(stage)


# ------------------------------------------------------------------ attempts
def _attempts(work: Path, stage: str) -> dict:
    """How often `stage` has been dispatched since it last started:
    count 0 = not dispatched yet, 1 = the first worker ran, and so on."""
    try:
        data = _load_json(work / ATTEMPTS_FILE)
    except (OSError, ValueError):
        data = None
    if not isinstance(data, dict) or data.get("stage") != stage:
        return {"stage": stage, "count": 0, "image_ids": []}
    return data


def _set_attempts(work: Path, stage: str, count: int, image_ids=(), request_ids=()) -> None:
    _write_json(work / ATTEMPTS_FILE, {"stage": stage, "count": count,
                                       "image_ids": list(image_ids),
                                       "request_ids": list(request_ids)})


def _validation(run, stage, accepted, problems=()):
    state.validate_requests(run.folder,
        _attempts(run.work, stage).get("request_ids", []), accepted, problems)


def _restart(run: _Run, stage: str) -> str:
    """Make `stage` pending again, with a fresh attempt count."""
    figures.invalidate_figure_requests(run.work)
    state.start(run.folder, stage)
    _set_attempts(run.work, stage, 0)
    return stage


def _record(run: _Run, stage: str, image_ids=(None,)) -> None:
    """Execution record for a completed model stage. A failure here is a
    reporting limitation, never a blocker (SKILL.md)."""
    for image_id in image_ids:
        try:
            state.record(
                run.folder, run.host, stage, "isolated",
                actual_model=run.actual_model,
                actual_effort=run.actual_effort, image_id=image_id)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            try:
                (run.work / "execution_error.txt").write_text(
                    str(exc), encoding="utf-8")
            except OSError:
                pass


# -------------------------------------------------------------- resume rules
def _resume_rules(run: _Run, pending: str) -> str:
    """The SKILL.md resume rules that need a look inside the checkpoints."""
    if pending == "extract":
        return pending
    try:
        corpus = _load_json(run.work / "corpus.json")
    except (OSError, ValueError):
        corpus = None
    if (not isinstance(corpus, dict)
            or (corpus.get("extraction") or {}).get("skipped")):
        # No usable corpus, or one with unread inputs: read the folder again
        # so corrected files are picked up (SKILL.md "Resume rules").
        return _restart(run, "extract")
    if _rank(pending) > _rank("analysis"):
        try:
            analysis = _load_json(run.work / "analysis.json")
        except (OSError, ValueError):
            analysis = None
        if analysis is None or validate.check_analysis(
                analysis, runner_codes=validate.RUNNER_CODES):
            # The stored analysis is missing or no longer meets today's
            # contract (e.g. a folder analysed by an older plugin version):
            # answer the sections again instead of building a deck from it.
            return _restart(run, "analysis")
    if _rank(pending) > _rank("verification"):
        claims = extract_claims.extract_claims(analysis)
        revision = corpus_revision(corpus)
        jobs_path = extract_claims.confined_path(run.work, extract_claims.JOBS_FILE)
        receipt_path = extract_claims.confined_path(run.work, extract_claims.RECEIPT_FILE)
        if jobs_path.exists():
            try:
                jobs = _load_json(jobs_path)
            except (OSError, ValueError):
                jobs = None
            if (not extract_claims.jobs_match(run.work, jobs, claims, revision)
                    or not _accepted_verification_current(run.work, jobs)):
                return _restart(run, "verification")
        elif receipt_path.exists():
            # A modern run must not fall through to legacy compatibility
            # when its independent job state has been removed.
            return _restart(run, "verification")
        try:
            verification = _load_json(run.work / "verification.json")
        except (OSError, ValueError):
            verification = None
        if claims and isinstance(verification, dict) and (
                verification.get("receipt_version") == 1 and not jobs_path.exists()
                or verification.get("corpus_revision") is not None
                and verification.get("corpus_revision") != revision):
            return _restart(run, "verification")
        if isinstance(verification, dict) and (
                verification.get("mode") == "in-thread"
                or verification.get("status") == "error"):
            # A stored in-thread or failed verification must be redone in
            # isolation before any later stage (SKILL.md "Resume rules").
            return _restart(run, "verification")
    return pending


# ------------------------------------------------------------------- extract
def _project_name(run: _Run) -> str:
    """The saved name on resume, else the supplied one, else the folder's."""
    try:
        saved = _load_json(run.work / "corpus.json").get("projectName")
    except (OSError, ValueError, AttributeError):
        saved = None
    return saved or run.project or os.path.basename(run.folder.rstrip(os.sep))


def _identity(run: _Run) -> dict:
    """The footer identity to save with the corpus: the run's own
    --author/--department, else the values saved by an earlier extraction
    (a restart without the flags keeps them, as _project_name keeps the
    name)."""
    try:
        saved = _load_json(run.work / "corpus.json")
    except (OSError, ValueError):
        saved = None
    if not isinstance(saved, dict):
        saved = {}
    identity = {"author": run.author if run.author is not None
                else saved.get("author"),
                "department": run.department if run.department is not None
                else saved.get("department")}
    return {k: v for k, v in identity.items() if v is not None}


def _run_extract(run: _Run):
    state.start(run.folder, "extract")
    corpus, _manifest = run_extraction(run.folder, _project_name(run),
                                       extra=_identity(run))
    record = corpus["extraction"]
    if record["skipped"]:
        names = ", ".join(s["filename"] for s in record["skipped"])
        return _blocked(MSG_UNREADABLE.format(names=names))
    if record["parsed"] == 0:
        return _blocked(MSG_NOTHING_READABLE)
    return state.complete(run.folder, "extract")


# ------------------------------------------------------------------- figures
def _transcribed(work: Path, image_id: str, figs=None) -> bool:
    """A worker saved a non-empty transcription (the execution record).
    Whether a picture is sent again is figures.figure_reusable."""
    return figures.figure_reusable(work, image_id, figs)


def _figure_requests(run: _Run, image_ids: list, figs) -> list:
    """Bounded jobs distribute pixel load without discarding any image."""
    batches = figures.balanced_figure_batches(
        figs.manifest.get("images", []), image_ids, run.work / "images",
        FIGURE_BATCH, figs=figs)
    return workers.prepare_figures_batches(run.folder, run.host, batches,
                                           figs=figs)


def _stage_figures(run: _Run):
    # The counter is set only after the requests are built, so a failure
    # while building them leaves the dispatch to be retried next call.
    attempts = _attempts(run.work, "figures")
    try:
        manifest = _load_json(run.work / "images.json")
    except (OSError, ValueError):
        manifest = {"images": []}
    # images.json is parsed once and each image hashed once for the whole
    # call: every helper below reads this FigureSet.
    figs = figures.FigureSet(run.work, manifest)
    entries = manifest.get("images", [])
    image_ids = [entry["id"] for entry in entries]
    # Receipts survive a missing attempts record: certify matching completed
    # workers before a fresh stage start can archive their outputs.
    figures.accept_figure_outputs(run.work, image_ids, figs)
    for job in attempts.get("jobs", []):
        accepted = all(figures.figure_reusable(run.work, i, figs)
                       for i in job["image_ids"])
        state.validate_requests(run.folder, [job["request_id"]], accepted,
                                [] if accepted else ["Some figure outputs are missing or invalid."])
    if attempts["count"] == 0:
        state.start(run.folder, "figures", figs=figs)
    identities = dict(attempts.get("identities", {}))
    rounds = dict(attempts.get("rounds", {}))
    todo = []
    for entry in entries:
        image_id = entry["id"]
        actual = figs.identity(entry)
        if not identity_matches(identities.get(image_id), actual):
            rounds[image_id] = 0
        if (not figures.figure_reusable(run.work, image_id, figs)
                and rounds.get(image_id, 0) < 2):
            todo.append(image_id)
        identities[image_id] = actual
    if todo:
        requests = _figure_requests(run, todo, figs)
        for request in requests:
            state.issue_request(run.folder, request,
                max((rounds.get(i, 0) for i in request["image_ids"]), default=0) + 1)
        for image_id in todo:
            rounds[image_id] = rounds.get(image_id, 0) + 1
        dispatched = list(dict.fromkeys([*attempts.get("image_ids", []), *todo]))
        _write_json(run.work / ATTEMPTS_FILE, {
            "stage": "figures", "count": max(rounds.values(), default=0),
            "image_ids": dispatched, "identities": identities, "rounds": rounds,
            "request_ids": [r["request_id"] for r in requests],
            "jobs": [{"request_id": r["request_id"], "image_ids": r["image_ids"]}
                     for r in requests]})
        return {"status": "dispatch", "stage": "figures", "requests": requests}
    return _after_figures(run, figs)


def _after_figures(run: _Run, figs=None):
    """Merge whatever the figure workers saved. A picture nobody could read
    in two rounds stays marked unread and the run continues (SKILL.md
    step 2)."""
    figs = figures.FigureSet(run.work) if figs is None else figs
    attempts = _attempts(run.work, "figures")
    read = [i for i in attempts.get("image_ids", [])
            if _transcribed(run.work, i, figs)]
    if read:
        _record(run, "figures", image_ids=read)
    figures.run_merge(run.folder, figs)
    figures.invalidate_figure_requests(run.work)
    return state.complete(run.folder, "figures")


# ------------------------------------------------------------ model stages
def _dispatch(run: _Run, stage: str) -> dict:
    """Start `stage` (archiving its previous model output) and ask for one
    fresh worker."""
    state.start(run.folder, stage)
    request = workers.prepare(run.folder, run.host, stage)
    _set_attempts(run.work, stage, 1, request_ids=[request["request_id"]])
    state.issue_request(run.folder, request, 1)
    return {"status": "dispatch", "stage": stage, "requests": [request]}


def _read_output(path: Path):
    """(problems, payload). payload is None when the worker's file is
    missing or is not JSON; problems then says which."""
    if not path.is_file():
        return [f"{path.name} was not written. Write the complete result "
                f"to {path}."], None
    try:
        return [], _load_json(path)
    except ValueError as exc:
        return [f"{path.name} is not valid JSON: {exc}"], None


def _repair_or_block(run: _Run, stage: str, problems: list, message: str):
    """Send the problems back for another attempt, or stop after three."""
    count = _attempts(run.work, stage)["count"]
    _validation(run, stage, False, problems)
    if count >= MAX_ATTEMPTS:
        # A later run starts this stage afresh (archive + three new attempts),
        # exactly like the original "restart the pending stage" rule.
        _set_attempts(run.work, stage, 0)
        return _blocked(message)
    request = workers.scoped_repair(workers.prepare(run.folder, run.host, stage), problems)
    _set_attempts(run.work, stage, count + 1, request_ids=[request["request_id"]])
    state.issue_request(run.folder, request, count + 1, mode="repair")
    return {"status": "repair", "stage": stage, "attempt": count + 1,
            "errors": list(problems),
            "requests": [request]}


def _stage_analysis(run: _Run):
    if _attempts(run.work, "analysis")["count"] == 0:
        corpus = _load_json(run.work / "corpus.json")
        problems = validate.check_corpus(corpus)
        if any(not p.startswith("Corpus too large") for p in problems):
            return _blocked(MSG_NOTHING_READABLE)
        write_corpus_text(run.folder)
        # Preparation is exact Python factoring, never a model-generated
        # summary. The original corpus remains intact for verification.
        from .corpus import deterministic_evidence_receipts
        manifest = prepare_evidence_chunks(corpus, run.work)
        if manifest["required"]:
            try:
                receipts = deterministic_evidence_receipts(manifest)
                prepared = merge_evidence_receipts(corpus, manifest, receipts,
                                                   run.work / "prepared_evidence.txt")
            except EvidencePreparationError as exc:
                return _blocked(str(exc))
            _write_json(run.work / "evidence_jobs.json", manifest)
            _write_json(run.work / "evidence_acceptance.json", {
                "version": 1, "mode": "deterministic", "corpus_revision": corpus_revision(corpus),
                "sha256": hashlib.sha256((run.work / "prepared_evidence.txt").read_bytes()).hexdigest(),
                "coverage": prepared["coverage"]})
        else:
            for name in ("prepared_evidence.txt", "evidence_acceptance.json", "evidence_jobs.json"):
                (run.work / name).unlink(missing_ok=True)
        return _dispatch(run, "analysis")
    return _after_analysis(run)


def _after_analysis(run: _Run):
    corpus = _load_json(run.work / "corpus.json")
    problems, analysis = _read_output(run.work / "analysis.json")
    ids_valid = True
    # Source Material is the runner's: a model's (or an interrupted run's)
    # section 12 goes before the gates and is built again once they pass.
    validate.strip_python_sections(analysis)
    if isinstance(analysis, dict) and isinstance(analysis.get("answers"), list):
        try:
            # Normalize all answers atomically: a stale ID never becomes a
            # guessed filename or the last-attempt whole-file fallback.
            has_ids = any(isinstance(a, dict) and isinstance(a.get("sources"), list)
                          and any(isinstance(r, dict) and "ref_id" in r for r in a["sources"])
                          for a in analysis["answers"])
            from .sources import reference_catalogue
            catalog = ({r["id"]: r for r in reference_catalogue(corpus)["references"]}
                       if has_ids else {})
            expanded = [expand_reference_ids(a.get("sources"), corpus, catalog)
                        if isinstance(a, dict) else None for a in analysis["answers"]]
            for a, refs in zip(analysis["answers"], expanded):
                if isinstance(a, dict) and "sources" in a:
                    a["sources"] = refs
        except ValueError as exc:
            ids_valid = False
            problems = [str(exc)]
    last = _attempts(run.work, "analysis")["count"] >= MAX_ATTEMPTS
    # The last attempt may be read again after an interruption, with the
    # corpus misses it already turned into V3 deductions.
    runner_codes = (FAITHFULNESS_CODE,) if last else ()
    if analysis is not None and ids_valid:
        problems = validate.check_analysis(analysis, corpus=corpus,
                                           runner_codes=runner_codes)
    downgraded = []
    if problems and analysis is not None and ids_valid and last:
        downgraded = _downgrade_locations(analysis, corpus)
        if downgraded:
            problems = validate.check_analysis(analysis, corpus=corpus,
                                               runner_codes=runner_codes)
    if not problems:
        # What the extracted sections copy must occur in the documents.
        problems = validate.check_faithfulness(analysis, corpus)
        if last:
            # The last attempt does not block on a corpus miss: each one
            # costs its section a V3 deduction instead. An owner cell
            # outside the owner set is no miss and still blocks.
            _faithfulness_deductions(analysis, corpus)
            problems = validate.check_owner_cells(analysis)
    if not problems:
        # The answers are written in English; the customer's wording stays
        # in brackets.
        problems = language.check_analysis(analysis)
    if problems:
        return _repair_or_block(run, "analysis", problems, MSG_ANALYSIS)
    # Sections 1-11 passed; Source Material (12) is built from the corpus
    # and the sections' sources, so the slide plan and the deck get all 12.
    finalize_mod.add_python_sections(analysis, corpus)
    _write_json(run.work / "analysis.json", analysis)
    if downgraded:
        _write_json(run.work / "analysis.json", analysis)
        _write_json(run.work / DOWNGRADES_FILE, downgraded)
    else:
        (run.work / DOWNGRADES_FILE).unlink(missing_ok=True)
    _resolve_account(run, analysis, corpus)
    _record(run, "analysis")
    _validation(run, "analysis", True)
    return state.complete(run.folder, "analysis")


def _faithfulness_deductions(analysis: dict, corpus: dict) -> None:
    """Every section's V3 entry from the corpus misses the faithfulness
    gate still finds: one entry naming the missing tokens, or none. It
    replaces the section's earlier V3 entries, so reading the same analysis
    again gives the same deductions."""
    misses = validate.faithfulness_misses(analysis, corpus)
    for answer in analysis["answers"]:
        if not isinstance(answer, dict):
            continue
        tokens = misses.get(answer.get("id"), [])
        entries = [{"rule": FAITHFULNESS_CODE, "count": len(tokens),
                    "items": ", ".join(tokens), "basis": ""}] if tokens else []
        confidence.merge_python_deductions(answer, (FAITHFULNESS_CODE,), entries)


def _downgrade_locations(analysis, corpus: dict) -> list:
    """The last attempt's fallback: how a model spelled a location must
    not block the run. Every cited location its (real) file does not have
    becomes a whole-file citation; the run report lists them (rfq/delivery.py),
    the slides do not. An unknown file is not touched and still blocks."""
    if not isinstance(analysis, dict) or not isinstance(
            analysis.get("answers"), list):
        return []
    files = [f for f in (corpus.get("filesContents") or corpus.get("files")
                         or []) if isinstance(f, dict)]
    changed = []
    for answer in analysis["answers"]:
        if isinstance(answer, dict):
            changed += downgrade_locators(answer.get("sources"), files,
                                          f"Section {answer.get('id')}")
    return changed


def _resolve_account(run: _Run, analysis: dict, corpus: dict) -> None:
    """Salesforce account + KAM for the Opportunity Info slide, looked up by
    Python, never typed by a model. The record goes to account_match.json
    (rfq/delivery.py applies it); a lookup that does not settle also becomes
    one Document Risk line in section 11, replacing an earlier lookup's."""
    text = "\n".join(f.get("extracted_text", "") or ""
                     for f in corpus.get("filesContents", []))
    info = analysis["opportunity"]
    match = guidance.resolve_account(info["customer"], text,
                                     site=info.get("customer_site"))
    _write_json(run.work / "account_match.json", match)
    protected = plan_input.authoritative_risk_items(analysis)
    removed = opportunity.remove_account_risk(analysis, protected)
    if opportunity.add_account_risk(analysis, match) or removed:
        _write_json(run.work / "analysis.json", analysis)


def _refresh_account(run: _Run) -> None:
    """Look the account up again right before the deck is built when its
    record is missing, unreadable or made for another customer or site
    (`account_match_is_current`), and on an explicit restart of finalize
    so an updated accounts.csv or resolver is picked up. The lookup is
    cheap, deterministic Python; only when it fails itself does rfq/delivery.py
    report the record as "could not be read"."""
    try:
        corpus = _load_json(run.work / "corpus.json")
        analysis = _load_json(run.work / "analysis.json")
    except (OSError, ValueError):
        return          # load_checkpoints reports the missing checkpoint
    try:
        match = _load_json(run.work / "account_match.json")
    except (OSError, ValueError):
        match = None
    info = analysis.get("opportunity") if isinstance(analysis, dict) else None
    if (run.restart != "finalize"
            and opportunity.account_match_is_current(info, match)):
        return
    try:
        _resolve_account(run, analysis, corpus)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        pass            # finalize.py adds the "could not be read" line


def _stage_verification(run: _Run):
    analysis = _load_json(extract_claims.confined_path(run.work, "analysis.json"))
    claims = extract_claims.extract_claims(analysis)
    corpus = _load_json(extract_claims.confined_path(run.work, "corpus.json"))
    revision = corpus_revision(corpus)
    try:
        jobs = _load_json(extract_claims.confined_path(run.work, extract_claims.JOBS_FILE))
    except (OSError, ValueError):
        jobs = None
    if (_attempts(run.work, "verification")["count"] == 0 or
            not extract_claims.jobs_match(run.work, jobs, claims, revision)):
        state.start(run.folder, "verification")
        extract_claims.confined_path(run.work, "claims.json")
        extract_claims.confined_path(run.work, "corpus.txt")
        extract_claims.write_claims(run.folder)
        if not claims:
            _set_attempts(run.work, "verification", 0)
            return state.complete(run.folder, "verification")
        write_corpus_text(run.folder)
        jobs = {"version": 1, "corpus_revision": revision,
                "claims_sha256": extract_claims.claims_identity(claims),
                "corpus_text_sha256": hashlib.sha256((run.work / "corpus.txt").read_bytes()).hexdigest(),
                "run_id": uuid.uuid4().hex[:12], "partitions": []}
        groups = extract_claims.partition_claims(claims)
        for index, group in enumerate(groups, 1):
            part = {"partition_id": f"part-{index}",
                    "claim_ids": [claim["id"] for claim in group],
                    "attempt": 1, "request_id": uuid.uuid4().hex,
                    "accepted_sha256": None}
            _verification_paths(run, jobs, part, group, len(groups) > 1)
            jobs["partitions"].append(part)
        return _dispatch_verification(run, jobs, jobs["partitions"], "dispatch")
    return _after_verification(run, jobs)


def _verification_paths(run, jobs, part, claims, partitioned):
    directory = (f"verification/{jobs['corpus_revision'][:12]}-"
                 f"{jobs['claims_sha256'][:12]}/{jobs['run_id']}/"
                 f"{part['partition_id']}/attempt-{part['attempt']}")
    part["claims_path"] = f"{directory}/claims.json" if partitioned else "claims.json"
    part["output_path"] = f"{directory}/verdicts.json" if partitioned else "verdicts.json"
    _write_json(extract_claims.confined_path(run.work, part["claims_path"]), {"claims": claims})
    extract_claims.confined_path(run.work, part["output_path"])


def _dispatch_verification(run, jobs, parts, mode, errors=()):
    path = extract_claims.confined_path(run.work, extract_claims.JOBS_FILE)
    _write_json(path, jobs)
    requests = []
    for part in parts:
        request = workers.prepare_verification_partition(run.folder, run.host, part["partition_id"])
        if mode == "repair":
            relevant = [error for error in errors if error.startswith(part["partition_id"] + ":")]
            request = workers.scoped_repair(request, relevant)
        part["request_id"] = request["request_id"]
        requests.append(request)
    _write_json(path, jobs)
    count = max(part["attempt"] for part in jobs["partitions"])
    _set_attempts(run.work, "verification", count, request_ids=[request["request_id"] for request in requests])
    for request, part in zip(requests, parts):
        state.issue_request(run.folder, request, part["attempt"], mode=mode)
    outcome = {"status": mode, "stage": "verification", "requests": requests}
    if mode == "repair":
        outcome.update({"attempt": max(part["attempt"] for part in parts), "errors": list(errors)})
    return outcome


def _accepted_verification_current(work, jobs):
    """A saved acceptance certifies the exact output bytes, not its filename."""
    for part in jobs["partitions"]:
        try:
            path = extract_claims.confined_path(work, part["output_path"])
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except (OSError, ValueError):
            return False
        if not part.get("accepted_sha256") or part["accepted_sha256"] != digest:
            return False
    try:
        receipt = _load_json(extract_claims.confined_path(work, extract_claims.RECEIPT_FILE))
        claims = _load_json(extract_claims.confined_path(work, "claims.json"))["claims"]
    except (OSError, ValueError, KeyError, TypeError):
        return False
    return (receipt.get("run_id") == jobs["run_id"] and
            extract_claims.receipt_matches(work, receipt, claims, jobs["corpus_revision"])) if isinstance(receipt, dict) else False


def _after_verification(run: _Run, jobs):
    failed, errors, merged = [], [], []
    for part in jobs["partitions"]:
        path = extract_claims.confined_path(run.work, part["output_path"])
        problems, verdicts = _read_output(path)
        if not problems:
            problems = extract_claims.check_verdicts(verdicts, part["claim_ids"])
        digest = hashlib.sha256(path.read_bytes()).hexdigest() if not problems else None
        if (part.get("accepted_sha256") and digest != part["accepted_sha256"]):
            problems.append("The accepted partition output changed; it must be checked again.")
        if problems:
            state.validate_requests(run.folder, [part["request_id"]], False, problems)
            part["accepted_sha256"] = None
            failed.append(part)
            errors.extend(f"{part['partition_id']}: {problem}" for problem in problems)
        else:
            state.validate_requests(run.folder, [part["request_id"]], True)
            part["accepted_sha256"] = digest
            merged.extend(verdicts["verdicts"])
    _write_json(extract_claims.confined_path(run.work, extract_claims.JOBS_FILE), jobs)
    if failed:
        if any(part["attempt"] >= MAX_ATTEMPTS for part in failed):
            _set_attempts(run.work, "verification", 0)
            return _blocked(MSG_VERIFICATION)
        claims = _load_json(extract_claims.confined_path(run.work, "claims.json"))["claims"]
        for part in failed:
            part["attempt"] += 1
            group = [claim for claim in claims if claim["id"] in part["claim_ids"]]
            _verification_paths(run, jobs, part, group, len(jobs["partitions"]) > 1)
        return _dispatch_verification(run, jobs, failed, "repair", errors)
    claims = _load_json(extract_claims.confined_path(run.work, "claims.json"))["claims"]
    merged.sort(key=lambda record: record["id"])
    problems = extract_claims.check_verdicts({"verdicts": merged}, [claim["id"] for claim in claims])
    if problems:
        _set_attempts(run.work, "verification", 0)
        return _blocked(MSG_VERIFICATION)
    _write_json(extract_claims.confined_path(run.work, "verdicts.json"), {"verdicts": merged})
    # The one-partition path also uses verdicts.json: certify the normalized merge.
    if len(jobs["partitions"]) == 1:
        jobs["partitions"][0]["accepted_sha256"] = hashlib.sha256((run.work / "verdicts.json").read_bytes()).hexdigest()
        _write_json(extract_claims.confined_path(run.work, extract_claims.JOBS_FILE), jobs)
    extract_claims.confined_path(run.work, "verification.json")
    record = apply_verdicts.run_apply(run.folder)
    if record.get("status") == "error":
        _set_attempts(run.work, "verification", 0)
        return _blocked(MSG_VERIFICATION)
    record.update({"corpus_revision": jobs["corpus_revision"],
                   "claims_sha256": jobs["claims_sha256"], "receipt_version": 1})
    _write_json(extract_claims.confined_path(run.work, "verification.json"), record)
    receipt = {"version": 1, "run_id": jobs["run_id"],
               "corpus_revision": jobs["corpus_revision"],
               "claims_sha256": jobs["claims_sha256"],
               "artifacts": {name: hashlib.sha256(extract_claims.confined_path(run.work, name).read_bytes()).hexdigest()
                             for name in ("verdicts.json", "verification.json")}}
    _write_json(extract_claims.confined_path(run.work, extract_claims.RECEIPT_FILE), receipt)
    _record(run, "verification")
    _validation(run, "verification", True)
    return state.complete(run.folder, "verification")


def _stage_slides(run: _Run):
    """The slide plan is Python's: every section's markdown is parsed into
    its slides (planning.plan_from_answers). Only when a section does not
    parse does the slide worker plan the whole deck. slide_planning.json
    records which way it went; plan_actions.json holds the parser's
    sanitizer actions (text dropped outside a section's shape), which
    rfq/delivery.py adds to the run report."""
    if _attempts(run.work, "slides")["count"] == 0:
        plan_input.write_plan_input(run.folder)
        draft, record = plan_input.plan_from_answers(
            _load_json(run.work / "corpus.json"), _load_json(run.work / "analysis.json"))
        _write_json(run.work / "plan_actions.json", record["actions"] if draft else [])
        if draft is not None:
            state.start(run.folder, "slides")
            _write_json(run.work / "slide_plan.json", draft)
            _write_json(run.work / "slide_planning.json", {
                "version": 1, "mode": "deterministic", "parsed": record["parsed"]})
            return state.complete(run.folder, "slides")
        _write_json(run.work / "slide_planning.json", {
            "version": 1, "mode": "worker", "unparsable": record["unparsable"]})
        return _dispatch(run, "slides")
    return _after_slides(run)


def _after_slides(run: _Run):
    problems, draft = _read_output(run.work / "slide_plan.json")
    if draft is not None:
        problems = validate.check_plan(draft)
    if problems:
        return _repair_or_block(run, "slides", problems, MSG_SLIDES)
    _record(run, "slides")
    _validation(run, "slides", True)
    return state.complete(run.folder, "slides")


# ------------------------------------------------------- deck and delivery
def _build_deck(run: _Run):
    """finalize() + write_outputs(): the deck, the run report and
    .work/deliverables.json. Returns (pptx_path, report_path).
    Raises ValueError when the checkpoints cannot make a valid deck."""
    cp = finalize_mod.load_checkpoints(run.folder)
    _plan, deck, report = finalize_mod.finalize(
        cp["corpus"], cp["analysis"], cp["draft"], cp["verification"],
        cp["execution"], account=cp["account"], downgrades=cp["downgrades"],
        manifest=cp["manifest"], images_dir=cp["images_dir"])
    return finalize_mod.write_outputs(run.folder, cp["corpus"], deck, report)


def _evaluate_deck(run: _Run, report_path: str) -> bool:
    """The quality gate (SKILL.md step 8). The output is kept internally in
    .work/evaluation.txt; True when there is no FAIL."""
    try:
        manifest = _load_json(run.work / "images.json")
    except (OSError, ValueError):
        manifest = {"images": []}
    fails, warns, oks = evaluate_mod.run_evaluation(
        report_path, str(run.work / "corpus.json"),
        manifest=manifest if isinstance(manifest, dict) else {"images": []})
    lines = evaluate_mod.format_lines(fails, warns, oks)
    lines.append(f"\n{len(fails)} fail / {len(warns)} warn / {len(oks)} pass")
    (run.work / "evaluation.txt").write_text("\n".join(lines) + "\n",
                                             encoding="utf-8")
    return not fails


def _deliverables(run: _Run):
    """(pptx, report) from .work/deliverables.json when both files exist
    inside output/ and the deck is non-empty; None when something is
    missing (rebuild). Raises ValueError for a malformed record or a path
    outside output/ (a blocker)."""
    path = run.work / "deliverables.json"
    if not path.is_file():
        return None
    data = _load_json(path)
    if not isinstance(data, dict):
        raise ValueError("deliverables.json is not an object.")
    out_dir = (Path(run.folder) / "output").resolve()
    found = []
    for key in ("pptx", "report"):
        value = data.get(key)
        if not isinstance(value, str) or not value:
            raise ValueError(f"deliverables.json has no '{key}' path.")
        target = Path(value).resolve()
        if not target.is_relative_to(out_dir):
            raise ValueError("A recorded deliverable is outside output/.")
        if not target.is_file():
            return None
        found.append(target)
    if found[0].stat().st_size == 0:
        return None
    return str(found[0]), str(found[1])


def _stage_finalize(run: _Run):
    state.start(run.folder, "finalize")
    _refresh_account(run)
    try:
        _build_deck(run)
    except (ValueError, OSError):
        # Retain the cause for troubleshooting without exposing a traceback
        # in the concise user-facing result. Logging must not block delivery.
        try:
            (run.work / "finalize_error.txt").write_text(
                traceback.format_exc(), encoding="utf-8")
        except OSError:
            pass
        return _blocked(MSG_BUILD)
    return state.complete(run.folder, "finalize")


def _check_and_deliver(run: _Run, complete_stage: bool):
    try:
        found = _deliverables(run)
    except ValueError:
        return _blocked(MSG_BAD_DELIVERABLES)
    if found is None:
        return _restart(run, "finalize")     # build a new pair
    if not _evaluate_deck(run, found[1]):
        return _blocked(MSG_EVALUATE)
    if complete_stage:
        state.complete(run.folder, "evaluate")
    return {"status": "done", "pptx": found[0], "report": found[1]}


def _stage_evaluate(run: _Run):
    state.start(run.folder, "evaluate")
    return _check_and_deliver(run, complete_stage=True)


def _stage_done(run: _Run):
    """A finished folder: check again and deliver the recorded deck without
    rebuilding it (SKILL.md "Resume rules")."""
    return _check_and_deliver(run, complete_stage=False)


# -------------------------------------------------------------------- driver
HANDLERS = {
    "extract": _run_extract,
    "figures": _stage_figures,
    "analysis": _stage_analysis,
    "verification": _stage_verification,
    "slides": _stage_slides,
    "finalize": _stage_finalize,
    "evaluate": _stage_evaluate,
    "done": _stage_done,
}


def advance(folder, host, project=None, actual_model=None,
            actual_effort=None, until=None, restart=None, author=None,
            department=None) -> dict:
    """Run every deterministic step up to the next model stage.

    `restart` makes that stage pending again (with fresh attempts) instead
    of resuming the saved one; it also repairs an invalid progress record.

    Returns one of the result dicts described in the module docstring.
    Raises ValueError for an unknown host or stage (`until`/`restart`).
    Data errors raised by the stage helpers propagate; the CLI turns them
    into exit code 2.
    """
    if host not in ("claude", "codex"):
        raise ValueError(f"Unknown host: {host}")
    for stage in (until, restart):
        if stage is not None and stage not in STAGES:
            raise ValueError(f"Unknown stage: {stage}")
    path = Path(folder).expanduser()
    if not path.is_dir():
        return _blocked(MSG_NO_FOLDER)
    folder = str(path.resolve())
    run = _Run(folder, Path(folder) / "output" / ".work", host, project,
               actual_model, actual_effort, restart, author, department)
    if restart is not None:
        pending = _resume_rules(run, _restart(run, restart))
    else:
        try:
            pending = _resume_rules(run, state.resume(folder))
        except ValueError:
            return _blocked(MSG_BAD_PROGRESS)

    # Every pass either completes a stage or returns; the bound only stops
    # a bug from spinning forever.
    for _ in range(4 * len(STAGES)):
        if until is not None and _rank(pending) > _rank(until):
            return {"status": "stopped", "stage": until}
        started = time.perf_counter()
        timing_outcome = "failed"
        try:
            outcome = HANDLERS[pending](run)
            timing_outcome = outcome.get("status") if isinstance(outcome, dict) else "accepted"
        finally:
            state.record_duration(run.folder, pending, time.perf_counter() - started,
                                   timing_outcome)
        if isinstance(outcome, dict):
            return outcome
        pending = outcome
    raise RuntimeError("The RFQ pipeline did not settle; this is a bug.")
