"""Follow-up question history, revision gates, worker orchestration, and decks."""
import copy
import datetime
import json
import re
import tempfile
import uuid
from pathlib import Path

from pydantic import ValidationError

from . import confidence, state, workers
from .corpus import corpus_changes, corpus_revision, format_corpus
from .delivery import add_product_pictures, deliverable_paths, scored_analysis
from .planning import _TAG_RE
from .opportunity import account_match_is_current
from .schema import (ADDITIONAL_INFO_ID, ADDITIONAL_INFO_TITLE, SOURCES,
                     Deduction, SlidePlan, rules_for, tighten_plan)
from .sources import (attach_sources, check_sources, corpus_spelling,
                      format_source_details, format_source_line)
from .state import ATTEMPTS_FILE, replace_with_retry
from .validation import (MAX_DEDUCTION_WORDS, check_final_opportunity,
                         check_text_faithfulness, text_faithfulness_misses)
from .verification import NO_CHECK, attach_confidence_notes

FILE = "followups.json"
ANSWER_FIELDS = {"id", "answer", "sources", "not_found", "mode", "deductions"}
MODES = ("extracted", "analysed")
NOT_FOUND = "Not found in the RFQ documents."
# The deduction a corpus miss costs an extracted answer once the follow-up
# is out of attempts (as pipeline.FAITHFULNESS_CODE for the analysis).
FAITHFULNESS_CODE = "V3"


def write_json(path: Path, data) -> None:
    """Atomic write: a crash never leaves half a JSON file behind."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8",
                                         dir=path.parent, prefix="tmp-",
                                         suffix=".json", delete=False) as fh:
            temporary = Path(fh.name)
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        replace_with_retry(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def load(work: Path) -> dict:
    path = Path(work) / FILE
    if not path.is_file():
        return {"followups": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(data, dict) or not isinstance(data.get("followups"), list)
            or not all(isinstance(e, dict) and isinstance(e.get("id"), int)
                       for e in data["followups"])):
        raise ValueError("The follow-up history is not a valid record; "
                         "it was left unchanged.")
    return data


def next_id(work: Path) -> int:
    return max((e["id"] for e in load(work)["followups"]), default=0) + 1


def append(work: Path, question: dict, answer: dict) -> dict:
    revision = question.get("corpus_revision")
    if not isinstance(revision, str) or not revision:
        raise ValueError("The follow-up question has no corpus revision.")
    data = load(work)
    entry = {
        "id": question["id"],
        "asked_at": question["asked_at"],
        "question": question["question"],
        "answer": answer["answer"].strip(),
        "sources": [{"filename": s["filename"],
                     "locator": str(s.get("locator", "") or "")}
                    for s in answer.get("sources", [])],
        "not_found": bool(answer["not_found"]),
        "in_deck": False,
        "corpus_revision": revision,
        # The answer's own mode and deductions (follow-up prompt v2); an
        # older answer has neither and scores 10/10.
        "mode": answer.get("mode"),
        "deductions": [dict(entry) for entry in answer.get("deductions") or []],
    }
    if any(e["id"] == entry["id"] for e in data["followups"]):
        raise ValueError(f"Follow-up {entry['id']} is already stored.")
    data["followups"].append(entry)
    write_json(Path(work) / FILE, data)
    return entry


def mark_in_deck(work: Path, ids: list) -> list:
    data = load(work)
    known = {e["id"]: e for e in data["followups"]}
    unknown = [i for i in ids if i not in known]
    if unknown:
        raise ValueError("Unknown follow-up id(s): "
                         + ", ".join(str(i) for i in unknown))
    for i in ids:
        known[i]["in_deck"] = True
    write_json(Path(work) / FILE, data)
    return [known[i] for i in ids]


def check_followup_answer(answer, corpus: dict, question_id: int) -> list:
    """Every problem at once, phrased so a repair attempt can act on it.
    The echoed `id` ties the answer to the pending question, so an answer
    left over from another question is never stored under this one."""
    if not isinstance(answer, dict):
        return ["The follow-up answer must be a JSON object."]
    problems = []
    extra = sorted(set(answer) - ANSWER_FIELDS)
    if extra:
        problems.append(f"Unknown field(s): {', '.join(extra)}; use only "
                        f"id, answer, sources, not_found, mode and "
                        f"deductions.")
    echoed = answer.get("id")
    if type(echoed) is not int or echoed != question_id:
        problems.append(f"'id' must be {question_id}, the id in "
                        f"followup_question.json; write the answer to that "
                        f"question only.")
    text = answer.get("answer")
    if not isinstance(text, str) or not text.strip():
        problems.append("'answer' must be a non-empty string.")
    not_found = answer.get("not_found")
    if not isinstance(not_found, bool):
        problems.append("'not_found' must be true or false.")
    elif (not_found and isinstance(text, str) and text.strip()
          and not text.strip().startswith(NOT_FOUND)):
        problems.append(f'A not_found answer must start with "{NOT_FOUND}"')
    sources = answer.get("sources")
    if not isinstance(sources, list):
        problems.append("'sources' must be a list.")
        sources = []
    # The same file + locator rules as the analysis (rfq/sources.py): a cited
    # page, slide, sheet or Word section must exist in that file.
    problems.extend(check_sources(
        sources, [f for f in corpus.get("filesContents", [])
                  if isinstance(f, dict)], "Follow-up"))
    if not_found is False and isinstance(answer.get("sources"), list) \
            and not sources:
        problems.append("An answer that was found must cite at least one source.")
    return (problems + _deduction_problems(answer)
            + faithfulness_problems(answer, corpus))


def _deduction_problems(answer: dict) -> list:
    """The answer's `mode` and `deductions` against the catalogue: the
    model rules of Additional Information for that mode (G3 only when
    extracted, S2.1 only when analysed). A new answer must declare its
    mode; each deduction must match schema.Deduction exactly before it is
    priced, and only a code the answer may not use is told the codes it
    may."""
    mode = answer.get("mode")
    if mode not in MODES:
        return ['\'mode\' must be "extracted" or "analysed".']
    deductions = answer.get("deductions", [])
    if not isinstance(deductions, list) or any(
            not isinstance(entry, dict) for entry in deductions):
        return ["'deductions' must be a list of objects (rule, count, items, "
                "basis)."]
    allowed = ", ".join(rule.code for rule in rules_for(ADDITIONAL_INFO_ID, mode))
    problems = []
    for entry in deductions:
        label = f"Follow-up deduction {entry.get('rule')}"
        try:
            Deduction.model_validate(entry, strict=True)
        except ValidationError as exc:
            faults = "; ".join(
                f"{'.'.join(map(str, error['loc'])) or 'entry'}: {error['msg']}"
                for error in exc.errors())
            problems.append(f"{label} must be {{rule, count, items, basis}} "
                            f"({faults}).")
            continue
        try:
            confidence.resolve([entry], ADDITIONAL_INFO_ID, mode)
        except ValueError as exc:
            problems.append(f"Follow-up: {exc} Use one of: {allowed}.")
        items = entry.get("items", "")
        if len(items.split()) > MAX_DEDUCTION_WORDS:
            problems.append(f"{label}: items must be at most "
                            f"{MAX_DEDUCTION_WORDS} words.")
    return problems


def faithfulness_problems(answer, corpus) -> list:
    """An extracted answer copies the documents: its dates, standard
    designations and number+unit pairs must occur in them (the analysis
    gate's checks, CONTRACT section 8). An analysed answer is not gated."""
    if not isinstance(answer, dict) or answer.get("mode") != "extracted":
        return []
    return check_text_faithfulness(answer.get("answer", ""), corpus, "Follow-up")


def _faithfulness_deduction(answer: dict, corpus) -> None:
    """The last attempt's V3 entry: one naming every corpus miss (or none),
    replacing an earlier V3 entry, so reading the answer again gives the
    same deductions."""
    tokens = (text_faithfulness_misses(answer.get("answer", ""), corpus)
              if answer.get("mode") == "extracted" else [])
    entries = [{"rule": FAITHFULNESS_CODE, "count": len(tokens),
                "items": ", ".join(tokens), "basis": ""}] if tokens else []
    confidence.merge_python_deductions(answer, (FAITHFULNESS_CODE,), entries)


def format_sources(sources: list) -> str:
    """'SOR.pdf p. 12, p. 14; notes.txt' - files in first-cited order."""
    order, locators = [], {}
    for s in sources:
        name = s.get("filename", "")
        if name not in locators:
            order.append(name)
            locators[name] = []
        loc = str(s.get("locator", "") or "").strip()
        if loc and loc not in locators[name]:
            locators[name].append(loc)
    return "; ".join(f"{name} {', '.join(locators[name])}".strip()
                     for name in order)


MAX_ATTEMPTS = 3
QUESTION = "followup_question.json"
ANSWER = "followup_answer.json"
STATE = "followup_state.json"
REFRESH_STAGES = ("extract", "figures")
REFRESH_HINT = ("Run `rfq_run.py next` with `--until figures` until it "
                "returns status `stopped`, then ask the question again.")
MSG_INVALID = "The follow-up answer could not be validated."


def _work(folder: str) -> Path:
    return Path(folder).expanduser().resolve() / "output" / ".work"


def _read(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _blocked(message: str) -> dict:
    return {"status": "blocked", "message": message}


def _archive(work: Path, name: str) -> None:
    """Move an old model output aside so a fresh worker never reads it."""
    path = work / name
    if path.is_file():
        target = work / "history" / uuid.uuid4().hex / name
        target.parent.mkdir(parents=True, exist_ok=True)
        replace_with_retry(path, target)


def _record(folder: str, host: str, actual_model, actual_effort) -> None:
    """The same execution record the main stages write. A recording
    failure is a reporting limitation, never a blocker."""
    try:
        state.record(folder, host, "followup", "isolated",
                                actual_model=actual_model,
                                actual_effort=actual_effort)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        try:
            (_work(folder) / "execution_error.txt").write_text(
                str(exc), encoding="utf-8")
        except OSError:
            pass


def _folder(folder: str) -> str:
    """One absolute path for every helper, so "~/RFQ" and "RFQ" work too."""
    return str(Path(folder).expanduser().resolve())


def _stale(folder: str, changes: dict, message: str) -> dict:
    """Invalidate a pending answer and restart reading changed documents."""
    work = _work(folder)
    state.start(folder, "extract")
    (work / ATTEMPTS_FILE).unlink(missing_ok=True)
    (work / STATE).unlink(missing_ok=True)
    return {"status": "stale", "changes": changes,
            "message": message + " " + REFRESH_HINT}


def ask(folder: str, host: str, question: str) -> dict:
    folder = _folder(folder)
    question = " ".join(str(question or "").split())
    if not question:
        return _blocked("A follow-up question is required.")
    work = _work(folder)
    if not (work / "corpus.json").is_file():
        return _blocked("This RFQ folder has not been analysed yet; run the "
                        "RFQ analysis first.")
    corpus = _read(work / "corpus.json")
    changes = corpus_changes(folder, corpus)
    if any(changes.values()):
        return _stale(folder, changes,
                      "The RFQ files changed since the last run.")
    if state.resume(folder) in REFRESH_STAGES:
        return {"status": "stale", "changes": changes,
                "message": "The RFQ documents are not fully read yet. "
                           + REFRESH_HINT}

    from .corpus import write_corpus_text
    write_corpus_text(folder)
    qid = next_id(work)
    if (work / QUESTION).is_file():
        # Every dispatch reserves its identity, including unanswered or
        # stale questions. A late worker must never match a new question.
        qid = max(qid, _read(work / QUESTION)["id"] + 1)
    revision = corpus_revision(corpus)
    _archive(work, ANSWER)
    write_json(work / QUESTION, {
        "id": qid, "question": question,
        "asked_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "corpus_revision": revision})
    request = workers.prepare(folder, host, "followup")
    write_json(work / STATE, {"id": qid, "attempt": 1, "host": host,
                                  "corpus_revision": revision,
                                  "request_id": request["request_id"]})
    state.issue_request(folder, request, 1)
    return {"status": "dispatch", "stage": "followup",
            "requests": [request]}


def answer(folder: str, host: str, actual_model: str | None = None,
           actual_effort: str | None = None) -> dict:
    folder = _folder(folder)
    work = _work(folder)
    if not (work / STATE).is_file() or not (work / QUESTION).is_file():
        return _blocked("No follow-up question is pending; ask one first.")
    pending_state = _read(work / STATE)
    question = _read(work / QUESTION)
    corpus = _read(work / "corpus.json")
    changes = corpus_changes(folder, corpus)
    revision = corpus_revision(corpus)
    if (any(changes.values())
            or question.get("corpus_revision") != revision
            or pending_state.get("corpus_revision") != revision
            or state.resume(folder) in REFRESH_STAGES):
        return _stale(folder, changes,
                      "The RFQ documents changed while the question was "
                      "being answered; dispatch the same question again "
                      "after refreshing.")
    _record(folder, host, actual_model, actual_effort)

    payload = None
    try:
        payload = _read(work / ANSWER)
    except FileNotFoundError:
        problems = [f"{ANSWER} was not written."]
    except ValueError as exc:       # broken JSON or not UTF-8
        problems = [f"{ANSWER} is not valid JSON: {exc}"]
    else:
        from .sources import expand_reference_ids
        try:
            if isinstance(payload, dict) and "sources" in payload:
                payload["sources"] = expand_reference_ids(payload["sources"], corpus)
            problems = check_followup_answer(payload, corpus, question["id"])
        except ValueError as exc:
            problems = [str(exc)]
        else:
            misses = faithfulness_problems(payload, corpus)
            if (misses and int(pending_state.get("attempt", 1)) >= MAX_ATTEMPTS
                    and all(problem in misses for problem in problems)):
                # The last attempt does not block on a corpus miss alone:
                # the answer is stored with a V3 deduction naming the tokens.
                _faithfulness_deduction(payload, corpus)
                problems = []

    state.validate_requests(folder, [pending_state.get("request_id")], not problems, problems)
    if problems:
        attempt = int(pending_state.get("attempt", 1)) + 1
        if attempt > MAX_ATTEMPTS:
            # Cleared, so the next `ask` starts a new question cleanly.
            (work / STATE).unlink()
            return _blocked(MSG_INVALID)
        pending_state["attempt"] = attempt
        request = workers.scoped_repair(workers.prepare(folder, host, "followup"), problems)
        pending_state["request_id"] = request["request_id"]
        write_json(work / STATE, pending_state)
        state.issue_request(folder, request, attempt, mode="repair")
        return {"status": "repair", "stage": "followup", "attempt": attempt,
                "errors": problems,
                "requests": [request]}

    entry = append(work, question, payload)
    (work / STATE).unlink()
    return {"status": "answered", "id": entry["id"], "answer": entry["answer"],
            "sources": entry["sources"], "not_found": entry["not_found"]}


# ------------------------------------------------- Additional Information deck
_BULLET = re.compile(r"^\s*[-*•▪]\s+")
_NUMBER = re.compile(r"^\s*(\d+)[.)]\s+")
MSG_NO_CURRENT = ("No current follow-up answer is available to add; ask the "
                  "question again using the current RFQ documents.")
MSG_OUTDATED = ("The RFQ documents changed since the latest presentation; run "
                "the RFQ analysis again first.")
MSG_NOT_SAVED = ("The new PowerPoint could not be saved; the earlier "
                 "presentation is unchanged.")
MSG_PRE_SCORING = ("The RFQ analysis predates the current scoring; run the "
                   "analysis again before adding follow-ups.")


def shorten(text: str, limit: int = 80) -> str:
    """One line, at most `limit` characters, cut at a word boundary."""
    text = " ".join(str(text).split())
    if len(text) <= limit:
        return text
    cut = text[:limit - 1].rsplit(" ", 1)[0].rstrip(",;:")
    return cut + "…"


def _numbered_list(lines: list) -> bool:
    """True when the numbered lines count 1, 2, 3 ... (at least two), so a
    lone "12. März 2027: SOP" keeps its day."""
    numbers = [int(m.group(1)) for m in map(_NUMBER.match, lines) if m]
    return len(numbers) >= 2 and numbers == list(range(1, len(numbers) + 1))


def answer_items(entry: dict) -> list:
    """Answer lines as panel items, list markers and evidence tags removed.
    The sources are the slide's own source line (build_additional_info)."""
    items = []
    lines = str(entry.get("answer", "")).splitlines()
    numbered = _numbered_list(lines)
    for line in lines:
        marker = _NUMBER if numbered and _NUMBER.match(line) else _BULLET
        line = marker.sub("", line)
        line = re.sub(r"\s{2,}", " ", _TAG_RE.sub("", line)).strip()
        if line:
            items.append(line)
    return items


def _source_line(entry: dict, files) -> str:
    """The follow-up's own source line. A not-found answer keeps the
    sources of the related information it gives."""
    sources = entry.get("sources") or []
    if files:
        sources = corpus_spelling(sources, files)
    return format_source_line(sources, not sources)


def build_additional_info(entries: list, files=None) -> dict:
    """One panel slide per follow-up, each with its own source line; the
    question-level line (attach_sources) stays the combined list for the
    run report. `files` = the corpus, for the documents' own spelling."""
    title_en, title_de = ADDITIONAL_INFO_TITLE
    return {
        "number": ADDITIONAL_INFO_ID, "titleEn": title_en, "titleDe": title_de,
        "confidence": "",
        "slides": [{"layout": "panel", "title": title_en,
                    "heading": shorten(e["question"]),
                    "items": answer_items(e),
                    "sourceLine": _source_line(e, files),
                    "sourceDetails": format_source_details(
                        e.get("sources") or [], not e.get("sources"), files)}
                   for e in sorted(entries, key=lambda e: e["id"])],
    }


def followup_confidence(entry: dict) -> tuple:
    """(resolved deductions, score, band) of one follow-up answer, priced
    like a section's for its mode. An older entry (no mode, no deductions)
    scores 10/10; with mode None the mode-bound rules (G3, S2.1) are
    refused. Raises ValueError for a code the entry may not carry."""
    resolved = confidence.resolve(entry.get("deductions") or [],
                                  ADDITIONAL_INFO_ID, entry.get("mode"),
                                  allow_python=True)
    value = confidence.score(resolved, ADDITIONAL_INFO_ID)
    return resolved, value, confidence.band(value)


def _costly_lines(resolved: list, not_found: bool) -> list:
    lines = [entry["line"] for entry in resolved if entry["points"]]
    return lines or [confidence.NO_DEDUCTIONS_ABSENT if not_found
                     else confidence.NO_DEDUCTIONS]


def attach_followup_confidence(plan: dict, entries: list) -> None:
    """Band, score, deductions and notes of the Additional Information
    question, from the follow-up entries it shows. One answer: its own
    score and the notes of any section. Several: the lowest score, then
    each answer's band and deduction lines under its question. Follow-up
    answers have no second review (NO_CHECK)."""
    question = next((q for q in plan.get("questions", [])
                     if q.get("number") == ADDITIONAL_INFO_ID), None)
    if question is None or not entries:
        return
    rated = [(entry, *followup_confidence(entry))
             for entry in sorted(entries, key=lambda e: e["id"])]
    value = min(score for _, _, score, _ in rated)
    level = confidence.band(value)
    if len(rated) == 1:
        entry, resolved, _, _ = rated[0]
        lines = [item["line"] for item in resolved if item["points"]]
        notes = confidence.notes(value, level, lines, NO_CHECK, "",
                                 question.get("sourceDetails") or "",
                                 not_found=bool(entry.get("not_found")),
                                 deductions=resolved)
    else:
        lines = []
        for entry, resolved, _, entry_level in rated:
            lines.append(f'Follow-up {entry["id"]} '
                         f'"{shorten(entry.get("question", ""), 60)}": '
                         f"{confidence.BAND_WORD[entry_level]}")
            lines += _costly_lines(resolved, bool(entry.get("not_found")))
        notes = confidence.notes(value, level, lines, NO_CHECK, "",
                                 question.get("sourceDetails") or "",
                                 deductions=[item for _, resolved, _, _ in rated
                                             for item in resolved])
    question["confidence"] = level
    question["score"] = value
    question["deductions"] = [dict(item, followup=entry["id"])
                              for entry, resolved, _, _ in rated
                              for item in resolved]
    question["confidenceNotes"] = notes


def insert_additional_info(questions: list, entries: list,
                           files=None) -> list:
    """Replace any earlier Additional Information section with one built
    from `entries`, placed right before Source Material."""
    kept = [q for q in questions if q.get("number") != ADDITIONAL_INFO_ID]
    at = next((i for i, q in enumerate(kept) if q.get("number") == SOURCES),
              len(kept))
    return kept[:at] + [build_additional_info(entries, files)] + kept[at:]


def eligible_followups(entries, revision, requested_ids=None, in_latest=()):
    """Select current answers and account for preserved obsolete history."""
    by_id = {entry["id"]: entry for entry in entries}
    existing = set(in_latest)
    explicit = requested_ids is not None
    requested = (set(requested_ids) if explicit else
                 {entry["id"] for entry in entries
                  if entry.get("corpus_revision") == revision} - existing)
    selected = existing | requested
    unknown = sorted(selected - by_id.keys())
    stale = sorted(i for i in selected & by_id.keys()
                   if by_id[i].get("corpus_revision") != revision)
    if unknown:
        raise ValueError("Unknown follow-up id(s): " + ", ".join(map(str, unknown)))
    if stale:
        raise ValueError("Follow-up answers refer to older RFQ documents: "
                         + ", ".join(map(str, stale)))
    chosen = [by_id[i] for i in sorted(selected)]
    excluded = [{"id": entry["id"], "reason": "different or unknown corpus revision"}
                for entry in entries
                if entry.get("corpus_revision") != revision]
    return chosen, excluded


def add_followups(folder: str, ids: list | None = None) -> dict:
    """A new deck = the latest deck plus the Additional Information section.

    The latest run report's slidePlan is the exact plan the renderer drew
    the latest deck from (rfq/delivery.py stores it after the Opportunity Info
    slide, the account lookup and the guards were applied), so re-rendering
    it reproduces that deck slide for slide. Only the date (today) and the
    extra section change; the earlier files are never touched.

    "Already in the latest deck" is the latest report's followupsInDeck: a
    deck the normal run rebuilt later has none, so current-revision answers
    are eligible again. The entries' in_deck flags are history only."""
    folder = _folder(folder)
    work = _work(folder)
    try:
        deliverables = _read(work / "deliverables.json")
        report = _read(Path(deliverables["report"]))
        report["slidePlan"]["questions"]
    except (OSError, ValueError, KeyError, TypeError):
        return _blocked("No finished presentation was found for this RFQ "
                        "folder; run the RFQ analysis first.")
    # A deck from before the scored confidence cannot take scored follow-up
    # sections next to its sections' old ratings.
    if not scored_analysis(report.get("analysis")):
        return _blocked(MSG_PRE_SCORING)
    # Never mix the older documents' sections with answers from new ones.
    try:
        corpus = _read(work / "corpus.json")
        revision = corpus_revision(corpus)
        if (any(corpus_changes(folder, corpus).values())
                or state.resume(folder) != "done"
                or (report.get("run") or {}).get("corpusRevision") != revision):
            return _blocked(MSG_OUTDATED)
        entries = load(work)["followups"]
        in_latest = set((report.get("run") or {}).get("followupsInDeck") or [])
        chosen, excluded = eligible_followups(entries, revision, ids, in_latest)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        return _blocked(str(exc))
    if not {entry["id"] for entry in chosen} - in_latest:
        return _blocked(MSG_NO_CURRENT)
    # The chosen entries count as in the deck BEFORE rendering, so a step
    # added before render (e.g. Plan 5's attach_sources) sees them as such.
    view = {"followups": [dict(e, in_deck=True) for e in chosen]}

    files = corpus.get("filesContents")
    plan = copy.deepcopy(report["slidePlan"])
    # Reject malformed saved questions/slides before insertion and citation
    # attachment traverse them. Keep the raw saved plan for the rebuild.
    try:
        SlidePlan.model_validate(plan)
    except ValueError as exc:
        return _blocked(str(exc))
    add_product_pictures(plan, None, None)
    plan["questions"] = insert_additional_info(plan["questions"],
                                               view["followups"], files)
    plan["date"] = datetime.date.today().isoformat()
    # Additional Information names the sources of the answers it shows; the
    # other sections get the same lines finalize gave the latest deck.
    attach_sources(plan, report.get("analysis") or {}, view, files=files)
    saved_account_notes = next(((q.get("confidenceNotes") or "").partition(
        "Account lookup (")[2].partition("\n\nHow the rating works:")[0]
        for q in plan["questions"] if q.get("number") == 1), "")
    try:
        account = _read(work / "account_match.json")
    except (OSError, ValueError):
        account = None
    saved_info = report.get("analysis", {}).get("opportunity") or {}
    if not account_match_is_current(saved_info, account) or any(
            saved_info.get(key) != (account or {}).get(key)
            for key in ("account_name", "kam_pte")):
        account = None
    attach_confidence_notes(plan, report.get("analysis") or {},
                            report.get("verification"), account)
    if not account and saved_account_notes:
        opportunity_question = next((q for q in plan["questions"] if q.get("number") == 1), None)
        if opportunity_question:
            opportunity_question["confidenceNotes"] += "\n\nAccount lookup (" + saved_account_notes
    try:
        attach_followup_confidence(plan, view["followups"])
    except ValueError as exc:
        return _blocked(str(exc))
    # The same gate and None-pruning rfq_run.py render applies to a stored plan.
    try:
        plan = tighten_plan(SlidePlan.model_validate(plan).model_dump())
    except ValueError as exc:
        return _blocked(str(exc))
    problems = check_final_opportunity(report.get("analysis", {}), plan)
    if problems:
        return _blocked(" ".join(problems))
    # The latest plan's product-picture slides draw from .work/images.
    from .renderer import render_to_bytes     # python-pptx: only to build a deck
    try:
        deck = render_to_bytes(plan, images_dir=str(work / "images"))
    except ValueError as exc:
        return _blocked(str(exc))

    opportunity = (report.get("analysis") or {}).get("opportunity") or {}
    name = (opportunity.get("opportunity_name")
            or report.get("run", {}).get("projectName") or "RFQ")
    pptx_path, report_path = deliverable_paths(folder, name, plan["date"])
    new_report = copy.deepcopy(report)
    new_report["slidePlan"] = plan
    new_report.setdefault("run", {})["pictures"] = []
    new_report.setdefault("run", {})["generatedAt"] = \
        datetime.datetime.now().isoformat(timespec="seconds")
    new_report["run"]["followupsInDeck"] = sorted(e["id"] for e in chosen)
    new_report["run"]["followupsExcluded"] = excluded

    report_text = json.dumps(new_report, ensure_ascii=False, indent=2)
    written = []
    try:
        for path, data in ((pptx_path, deck), (report_path, report_text)):
            _write_new(path, data)
            written.append(path)
        write_json(work / "deliverables.json",
                         {"pptx": pptx_path, "report": report_path})
    except OSError:
        # No half delivery: a deck without its report (or one the delivery
        # record does not point to) is removed again.
        for path in written:
            Path(path).unlink(missing_ok=True)
        return _blocked(MSG_NOT_SAVED)
    try:
        mark_in_deck(work, sorted(e["id"] for e in chosen))
    except OSError:
        pass            # history only; followupsInDeck above is authoritative
    return {"status": "done", "pptx": pptx_path, "report": report_path}


def _write_new(path: str, data) -> None:
    """Exclusive creation: an earlier deck or report is never overwritten,
    and a write that fails half-way leaves no partial file behind."""
    binary = isinstance(data, bytes)
    fh = open(path, "xb" if binary else "x",
              encoding=None if binary else "utf-8")
    try:
        with fh:
            fh.write(data)
    except OSError:
        Path(path).unlink(missing_ok=True)
        raise
