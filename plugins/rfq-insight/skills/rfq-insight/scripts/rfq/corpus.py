"""Extract RFQ inputs, format corpus text, and verify corpus revisions."""

import datetime
import hashlib
import json
import os
import re
import uuid
from bisect import bisect_right
from pathlib import Path

from . import extractors, figures
from .extractors import clean_corpus_files
from .figures import filter_images, write_images

OUTPUT_DIRNAME = "output"
WORK_DIRNAME = ".work"
MAIL_DIRNAME = "mail"
# Joins a mail's name to an attachment's name in the corpus ("cover.msg › Spec.pdf").
ATTACHMENT_SEP = " › "


def work_dir(folder: str) -> str:
    return os.path.join(folder, OUTPUT_DIRNAME, WORK_DIRNAME)


def walk_supported(folder: str):
    """(supported file paths, ignored filenames), both sorted.

    Our own output/ subtree is never walked: a previous run's deck must not
    become an input to the next one.
    """
    supported, ignored = [], []
    output_root = os.path.join(os.path.abspath(folder), OUTPUT_DIRNAME)
    for root, dirs, names in os.walk(folder):
        if os.path.abspath(root) == output_root:
            dirs[:] = []
            continue
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for name in sorted(names):
            ext = os.path.splitext(name)[1].lower()
            if ext in extractors.SUPPORTED_EXTENSIONS:
                supported.append(os.path.join(root, name))
            else:
                ignored.append(name)
    return sorted(supported, key=os.path.basename), sorted(ignored)


def _stamp(path: str) -> str:
    return datetime.datetime.fromtimestamp(
        os.path.getmtime(path)).isoformat(timespec="seconds")


def file_sha256(path: str) -> str:
    """SHA-256 of raw input bytes, streamed in 1 MB chunks."""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _add_attachments(folder, path, rel, name, key, mail, files, skipped,
                     raw_images):
    """Unpack a mail's attachments and add each readable one to the corpus
    right after the mail, carrying the mail's sha256 so a changed mail is a
    changed package. Unsupported files and attached mails are listed as
    skipped; a mail that cannot be unpacked loses only its attachments."""
    # work/mail/<key without ".msg">/ - the key is unique per mail, so two
    # mails never share a folder.
    mail_dir = re.sub(r"\.msg(?=(_\d+)?$)", "", key, flags=re.IGNORECASE) or key
    try:
        attachments = extractors.unpack_msg(
            path, os.path.join(work_dir(folder), MAIL_DIRNAME, mail_dir))
    except extractors.UnreadableFile as exc:
        skipped.append({"filename": f"{name}{ATTACHMENT_SEP}(attachments)",
                        "path": f"{rel}{ATTACHMENT_SEP}(attachments)",
                        "reason": exc.reason, "detail": exc.detail})
        return
    for n, att in enumerate(attachments, 1):
        filename = f"{name}{ATTACHMENT_SEP}{att['name']}"
        att_rel = f"{rel}{ATTACHMENT_SEP}{att['name']}"
        att_ext = os.path.splitext(att["name"])[1].lower()
        if att["nested"]:
            skipped.append({"filename": filename, "path": att_rel,
                            "reason": "nested e-mail",
                            "detail": "An e-mail attached to an e-mail is not read."})
            continue
        if att_ext not in extractors.SUPPORTED_EXTENSIONS:
            skipped.append({"filename": filename, "path": att_rel,
                            "reason": "unsupported file type",
                            "detail": f"Attachment type {att_ext or '(none)'} is not read."})
            continue
        try:
            got = extractors.extract_file(att["path"], key=f"{key}_{n}")
        except extractors.UnreadableFile as exc:
            skipped.append({"filename": filename, "path": att_rel,
                            "reason": exc.reason, "detail": exc.detail})
            continue
        except Exception as exc:
            skipped.append({"filename": filename, "path": att_rel,
                            "reason": "I couldn't open it",
                            "detail": f"{type(exc).__name__}: {exc}"})
            continue
        entry = {
            "filename": filename,
            "extension": att_ext.lstrip("."),
            "path": att_rel,
            "sha256": mail["sha256"],
            "file_size": os.path.getsize(att["path"]),
            "modified": mail["modified"],
            "category": extractors.CATEGORY[att_ext],
            "extraction_method": extractors.METHOD[att_ext],
            "source": "extract_corpus.py",
            "processed_at": mail["processed_at"],
            "extracted_text": got.text,
            "attachment_of": name,
        }
        if got.locations:
            entry["locations"] = got.locations
        if got.raw_text:
            entry["raw_extracted_text"] = got.raw_text
        if got.extraction_metrics:
            entry["extraction_metrics"] = got.extraction_metrics
        raw_images.extend(got.images)
        files.append(entry)


def build_corpus(folder: str, project_name: str, native_pages=False):
    """(corpus dict, unpacked images). Never raises on one bad file."""
    supported, ignored = walk_supported(folder)
    files, skipped, raw_images = [], [], []
    used_keys: set = set()

    for path in supported:
        name = os.path.basename(path)
        ext = os.path.splitext(name)[1].lower()
        rel = os.path.relpath(path, folder)
        # The identity every image from this file carries. It comes from
        # the RELATIVE PATH, which is unique, not the basename, which is
        # not: annexes/Spec.docx and attachments/Spec.docx are two
        # documents with two different charts. The counter closes the last
        # gap - two different paths can still slug to the same string.
        key = extractors.image_key(rel)
        if key in used_keys:
            n = 2
            while f"{key}_{n}" in used_keys:
                n += 1
            key = f"{key}_{n}"
        used_keys.add(key)
        try:
            before_sha256 = file_sha256(path)
            if ext == ".docx" and native_pages:
                page_work = work_dir(folder)
                os.makedirs(page_work, exist_ok=True)
                pagination = extractors.render_word_pages(path, page_work)
                got = extractors.extract_docx(path, key, pagination=pagination)
            else:
                got = extractors.extract_file(path, key)
            after_sha256 = file_sha256(path)
            if before_sha256 != after_sha256:
                raise extractors.UnreadableFile(
                    "it changed while I was reading it",
                    "Input SHA-256 changed during extraction; retry extraction.")
            entry = {
                "filename": name,
                "extension": ext.lstrip("."),
                "path": rel,
                "sha256": before_sha256,
                "file_size": os.path.getsize(path),
                "modified": _stamp(path),
                "category": extractors.CATEGORY[ext],
                "extraction_method": extractors.METHOD[ext],
                "source": "extract_corpus.py",
                "processed_at": datetime.datetime.now().isoformat(
                    timespec="seconds"),
                "extracted_text": got.text,
            }
            if got.locations:
                entry["locations"] = got.locations
            if got.raw_text:
                entry["raw_extracted_text"] = got.raw_text
            if got.extraction_metrics:
                entry["extraction_metrics"] = got.extraction_metrics
        except extractors.UnreadableFile as exc:
            skipped.append({"filename": name, "path": rel,
                            "reason": exc.reason, "detail": exc.detail})
            continue
        except Exception as exc:
            # Last-resort guard: no single file may abort the whole run.
            # The extractors convert everything they anticipate into
            # UnreadableFile; this catches what they did not, so the user
            # gets a named skipped file instead of a traceback. The
            # technical cause still reaches the run report via `detail`.
            skipped.append({"filename": name, "path": rel,
                            "reason": "I couldn't open it",
                            "detail": f"{type(exc).__name__}: {exc}"})
            continue
        raw_images.extend(got.images)
        files.append(entry)
        if ext == ".msg":
            _add_attachments(folder, path, rel, name, key, entry,
                             files, skipped, raw_images)

    cleaned, pre_stats = clean_corpus_files(files)
    corpus = {
        "projectName": project_name,
        "oppId": "",
        "filesContents": cleaned,
        "extraction": {
            "parsed": len(cleaned),
            "chars": sum(len(f["extracted_text"]) for f in cleaned),
            "skipped": skipped,
            "ignored": ignored,
            "images_flagged": [],
            "images_filtered": [],
            "preprocess": pre_stats,
        },
    }
    return corpus, raw_images


def drop_markers(corpus: dict, dropped: list) -> int:
    """Remove the placeholder left for every picture that was filtered out.

    Every embedded picture gets a "transcription pending" marker as it is
    unpacked, because at that point nothing knows which ones will earn a
    visual read. filter_images then throws most of them away - a dozen
    inline icons in a statement of work is normal - and no transcription
    will ever arrive for those. Left in place, each one is a sentence in
    the corpus announcing content that does not exist, and the analysis
    prompt is explicitly told to hedge its answers when the corpus says a
    picture is missing. So the marker goes when the picture does.

    Returns the number of markers removed. The surrounding blank line goes
    with the marker, so the paragraph spacing either side is unchanged.
    """
    removed = 0
    for record in dropped:
        marker = extractors.marker_for(record["id"])
        for entry in corpus.get("filesContents", []):
            text = entry.get("extracted_text") or ""
            if marker not in text:
                continue
            text = (text.replace(marker + "\n\n", "")
                        .replace("\n\n" + marker, "")
                        .replace(marker, ""))
            entry["extracted_text"] = text
            removed += 1
    if removed:
        corpus["extraction"]["chars"] = sum(
            len(f.get("extracted_text", "") or "")
            for f in corpus.get("filesContents", []))
    return removed


def summary_lines(corpus: dict, manifest: dict) -> list:
    """What the user is told. Plain language, no internal vocabulary."""
    rec = corpus["extraction"]
    attempted = rec["parsed"] + len(rec["skipped"])
    lines = [f"Read {rec['parsed']} of {attempted} files "
             f"({rec['chars']:,} characters of text)."]

    if rec["skipped"]:
        detail = ", ".join(f"{s['filename']} ({s['reason']})"
                           for s in rec["skipped"])
        lines.append(f"I couldn't read {len(rec['skipped'])}: {detail}.")
    if rec["ignored"]:
        lines.append(f"Ignored {len(rec['ignored'])} file(s) of a type I "
                     f"don't handle: {', '.join(rec['ignored'])}.")
    if manifest["images"]:
        lines.append(f"{len(manifest['images'])} picture(s) need looking at "
                     f"before I can use them.")
    for line in filtered_lines(manifest["filtered"]):
        lines.append(line)
    return lines


# What the user is told about each reason a picture was set aside. Keyed by
# the same reason codes images.REASONS uses, but written as a whole
# sentence about a count - "logos or page furniture" is true of the first
# two and a lie about the other two.
_FILTERED_PHRASES = {
    "too_small": "are too small to hold information - logos, icons, rules",
    "chrome": "repeat through the documents, so they are page furniture",
    "duplicate": "are copies of a picture I am already looking at",
    "cap_reached": "are beyond the limit on how many I read in one run",
    "unreadable": "I could not open as pictures at all",
}


def filtered_lines(filtered: list) -> list:
    """One honest sentence per reason a picture was set aside."""
    groups: dict = {}
    for record in filtered:
        groups.setdefault(record.get("reason", ""), []).append(record)
    # Known reasons first, in the order they are listed above, so the same
    # folder always produces the same summary.
    order = [r for r in _FILTERED_PHRASES if r in groups]
    order += sorted(r for r in groups if r not in _FILTERED_PHRASES)

    lines = []
    for reason in order:
        records = groups[reason]
        phrase = _FILTERED_PHRASES.get(reason) or (
            records[0].get("explanation") or "I set aside")
        lines.append(f"Skipped {len(records)} picture(s) that {phrase}.")
    return lines


def run_extraction(folder: str, project: str | None = None, native_pages=True,
                   extra=None):
    """Extract `folder` and write corpus.json, images/ and images.json.

    `extra` (e.g. the run's author/department) is merged into the corpus
    before it is written; empty values are left out.

    Returns (corpus, manifest). The pipeline runner (rfq/pipeline.py) calls
    this in-process; main() is the same thing for the command line.
    """
    folder = os.path.abspath(folder)
    project = project or os.path.basename(folder.rstrip(os.sep))
    corpus, raw_images = build_corpus(folder, project, native_pages=native_pages)

    work = work_dir(folder)
    os.makedirs(work, exist_ok=True)
    kept, dropped = filter_images(raw_images)
    manifest = write_images(kept, dropped, os.path.join(work, "images"))
    # A filtered-out picture is never transcribed, so its placeholder must
    # not survive into the corpus the analysis reads.
    drop_markers(corpus, manifest["filtered"])

    corpus["extraction"]["images_flagged"] = [e["id"]
                                              for e in manifest["images"]]
    corpus["extraction"]["images_filtered"] = manifest["filtered"]
    corpus.update({k: v for k, v in (extra or {}).items() if v})

    with open(os.path.join(work, "corpus.json"), "w", encoding="utf-8") as fh:
        json.dump(corpus, fh, ensure_ascii=False, indent=2)
    with open(os.path.join(work, "images.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)
    return corpus, manifest


MAX_LINE_CHARS = 1_500


def soft_wrap(text: str, limit: int = MAX_LINE_CHARS) -> str:
    """Break lines longer than `limit` at whitespace; never inside a word
    unless a single token itself exceeds the limit."""
    out = []
    for line in text.split("\n"):
        while len(line) > limit:
            cut = line.rfind(" ", 0, limit)
            if cut <= 0:
                cut = limit
            out.append(line[:cut].rstrip())
            line = line[cut:].lstrip()
        out.append(line)
    return "\n".join(out)


def format_corpus(files: list) -> str:
    """Render the corpus dicts into delimited === FILE: <name> === blocks."""
    blocks = []
    for f in files:
        header = f"=== FILE: {f.get('filename', '')} ==="
        meta = f"(type: {f.get('extension', '')}; path: {f.get('path', '')})"
        body = soft_wrap(f.get('extracted_text', '') or '')
        blocks.append(f"{header}\n{meta}\n{body}")
    return "\n\n".join(blocks)


def write_corpus_text(folder: str, out_path: str | None = None) -> str:
    """Write the delimited corpus text (default: .work/corpus.txt) and return
    its absolute path. Raises FileNotFoundError when corpus.json is missing."""
    work = os.path.join(os.path.abspath(folder), "output", ".work")
    with open(os.path.join(work, "corpus.json"), encoding="utf-8") as fh:
        corpus = json.load(fh)
    text = format_corpus(corpus.get("filesContents", []))
    out_path = os.path.abspath(out_path or os.path.join(work, "corpus.txt"))
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(text)
    from .sources import reference_catalogue
    with open(os.path.join(work, "source_catalog.json"), "w", encoding="utf-8") as fh:
        json.dump(reference_catalogue(corpus), fh, ensure_ascii=False, indent=2)
    return out_path


def corpus_revision(corpus: dict) -> str:
    """Stable v1 revision of raw input identities and extracted evidence.

    Includes merged image transcription and skipped inputs, while ignoring
    display names, generation times and filesystem metadata.
    """
    entries = [
        {"path": str(entry.get("path") or entry.get("filename") or "")
                 .replace("\\", "/"),
         "filename": entry.get("filename", ""),
         "sha256": entry.get("sha256"),
         "text": entry.get("extracted_text") or ""}
        for entry in corpus.get("filesContents") or []]
    entries.sort(key=lambda entry: (entry["path"], entry["filename"]))
    payload = {"version": 1, "files": entries,
               "skipped": corpus.get("extraction", {}).get("skipped", [])}
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def corpus_changes(folder: str, corpus: dict) -> dict:
    """{"added", "removed", "changed"}: sorted relative paths; all empty = fresh."""
    folder = os.path.abspath(folder)
    supported, _ignored = walk_supported(folder)
    on_disk = {os.path.relpath(path, folder): path for path in supported}
    known = {entry.get("path"): entry
             for entry in corpus.get("filesContents", [])
             if isinstance(entry, dict) and entry.get("path")}
    skipped = {item.get("path")
               for item in corpus.get("extraction", {}).get("skipped", [])
               if isinstance(item, dict) and item.get("path")}

    added = sorted(rel for rel in on_disk
                   if rel not in known and rel not in skipped)
    removed = sorted(rel for rel in known if rel not in on_disk)
    changed = []
    for rel, entry in known.items():
        if rel not in on_disk:
            continue
        recorded = entry.get("sha256")
        if not recorded:
            changed.append(rel)
            continue
        try:
            current = file_sha256(on_disk[rel])
        except OSError:
            changed.append(rel)
            continue
        if current != recorded:
            changed.append(rel)
    changed.sort()
    return {"added": added, "removed": removed, "changed": changed}


# Preparation never replaces source text with an unverified semantic summary.
# Its only compression operation is sharing identical, exactly quoted blocks.
EVIDENCE_CHUNK_CHARS = 120_000
EVIDENCE_SYNTHESIS_CHARS = 600_000
_EVIDENCE_MARKER = re.compile(
    r"^--- (?:Page (?P<page>\d+)|Section(?: Path)?: (?P<section>.+?)) ---\r?$",
    re.MULTILINE)


class EvidencePreparationError(ValueError):
    """Preparation is incomplete, stale, unsafe, or cannot fit synthesis."""


def _evidence_path(work, relative):
    """Resolve only descendants, including protection against symlink escapes."""
    root = Path(work).resolve()
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise EvidencePreparationError("Evidence path must be relative to the work directory.")
    target = (root / relative).resolve()
    if target == root or not target.is_relative_to(root):
        raise EvidencePreparationError("Evidence path escapes the work directory.")
    return target


def _evidence_text(chunk):
    try:
        path = _evidence_path(chunk["work_dir"], chunk["text_path"])
        data = path.read_bytes()
        text = data.decode("utf-8")
    except (KeyError, OSError, UnicodeError) as exc:
        raise EvidencePreparationError("Immutable evidence chunk is unavailable.") from exc
    if hashlib.sha256(data).hexdigest() != chunk.get("chunk_sha256"):
        raise EvidencePreparationError("Immutable evidence chunk hash changed.")
    if len(text) != chunk.get("end", -1) - chunk.get("start", -1):
        raise EvidencePreparationError("Immutable evidence chunk length changed.")
    return text


def _source_locations(text):
    """Known page/chapter context; never invent a physical page for plain text."""
    matches = list(_EVIDENCE_MARKER.finditer(text))
    locations, page, section = [], None, ""
    for index, marker in enumerate(matches):
        if marker.group("page"):
            page = int(marker.group("page"))
        if marker.group("section"):
            section = marker.group("section")
        locations.append({"start": marker.start(),
                          "end": matches[index + 1].start() if index + 1 < len(matches) else len(text),
                          "page": page, "section": section})
    return locations


def prepare_evidence_chunks(corpus: dict, work, *, max_chars=EVIDENCE_CHUNK_CHARS,
                            direct_limit=EVIDENCE_SYNTHESIS_CHARS) -> dict:
    """Create a fresh, immutable attempt of exact original document chunks.

    Character offsets are half-open Python Unicode indices into extracted_text.
    Both the existing formatted envelope and original extracted text gate the
    direct path. Smaller packages retain their existing direct text unchanged.
    Paths are relative to work; source corpus dictionaries are never modified.
    """
    if type(max_chars) is not int or not 0 < max_chars <= EVIDENCE_CHUNK_CHARS:
        raise EvidencePreparationError("Evidence chunk limit must be at most 120,000 characters.")
    if type(direct_limit) is not int or not 0 < direct_limit <= EVIDENCE_SYNTHESIS_CHARS:
        raise EvidencePreparationError("Direct synthesis limit must be at most 600,000 characters.")
    files = corpus.get("filesContents") or []
    direct = format_corpus(files)
    original_chars = sum(len(entry.get("extracted_text") or "") for entry in files)
    revision = corpus_revision(corpus)
    manifest = {"version": 1, "required": max(len(direct), original_chars) > direct_limit,
                "corpus_revision": revision, "original_chars": original_chars,
                "formatted_chars": len(direct), "chunk_limit": max_chars,
                "work_dir": str(Path(work).resolve()), "chunks": []}
    if not manifest["required"]:
        manifest["direct_text"] = direct
        return manifest
    attempt = uuid.uuid4().hex
    manifest["attempt_id"] = attempt
    for source_index, entry in enumerate(files):
        text = entry.get("extracted_text") or ""
        boundaries = [m.start() for m in _EVIDENCE_MARKER.finditer(text)]
        locations = _source_locations(text)
        start = 0
        while start < len(text):
            end = min(start + max_chars, len(text))
            if end < len(text):
                candidates = [position for position in boundaries if start < position <= end]
                if candidates:
                    end = candidates[-1]
                else:
                    # Preserve all bytes: a newline belongs to the preceding chunk.
                    newline = text.rfind("\n", start, end)
                    if newline >= start:
                        end = newline + 1
            chunk_id = f"{attempt}-c{len(manifest['chunks']) + 1:05d}"
            relative = f"evidence/{attempt}/{chunk_id}.txt"
            path = _evidence_path(work, relative)
            path.parent.mkdir(parents=True, exist_ok=True)
            data = text[start:end].encode("utf-8")
            with path.open("xb") as handle:
                handle.write(data)
            manifest["chunks"].append({
                "chunk_id": chunk_id, "chunk_sha256": hashlib.sha256(data).hexdigest(),
                "corpus_revision": revision, "source_index": source_index,
                "filename": entry.get("filename", ""),
                "path": entry.get("path") or entry.get("filename") or "",
                "start": start, "end": end, "text_path": relative,
                "receipt_path": f"evidence/{attempt}/{chunk_id}.receipt.json",
                "work_dir": manifest["work_dir"],
                "locators": [location for location in locations
                             if location["start"] < end and location["end"] > start]})
            start = end
    return manifest


def validate_prepared_evidence(work, corpus):
    """Reconstruct the exact proof before exposing a prepared input to a worker."""
    root = Path(work).resolve()
    try:
        accepted = json.loads((root / "evidence_acceptance.json").read_text(encoding="utf-8"))
        manifest = json.loads((root / "evidence_jobs.json").read_text(encoding="utf-8"))
        if (not isinstance(accepted, dict) or type(accepted.get("version")) is not int
                or accepted["version"] != 1 or accepted.get("mode") != "deterministic"
                or not isinstance(manifest, dict) or manifest.get("work_dir") != str(root)
                or not manifest.get("required")
                or accepted.get("corpus_revision") != corpus_revision(corpus)):
            raise ValueError()
        rebuilt = merge_evidence_receipts(corpus, manifest, deterministic_evidence_receipts(manifest))
        data = (root / "prepared_evidence.txt").read_bytes()
        if (data != rebuilt["text"].encode("utf-8")
                or accepted.get("sha256") != hashlib.sha256(data).hexdigest()
                or accepted.get("coverage") != rebuilt["coverage"]):
            raise ValueError()
    except (OSError, ValueError, TypeError, KeyError, AttributeError, UnicodeError, RecursionError) as exc:
        raise EvidencePreparationError("The prepared evidence proof is invalid or stale.") from exc
    return True


def validate_evidence_receipt(chunk: dict, receipt: dict) -> list:
    """Return verified blocks only after every original character is accounted.

    A quote can map identical repeated spans. Exact string equality, disjoint
    intervals and exhaustive coverage prove retention; coverage flags do not.
    Uncertainties are advisory only and are not evidence for synthesis claims.
    """
    text = _evidence_text(chunk)
    if (not isinstance(receipt, dict) or type(receipt.get("version")) is not int
            or receipt["version"] != 1):
        raise EvidencePreparationError("Malformed evidence receipt version.")
    for field in ("chunk_id", "chunk_sha256", "corpus_revision"):
        if receipt.get(field) != chunk.get(field):
            raise EvidencePreparationError(f"Stale evidence receipt {field}.")
    uncertainties = receipt.get("uncertainties")
    if not isinstance(uncertainties, list) or any(not isinstance(item, str) for item in uncertainties):
        raise EvidencePreparationError("Malformed uncertainties in evidence receipt.")
    blocks = receipt.get("evidence_blocks")
    if not isinstance(blocks, list) or not blocks:
        raise EvidencePreparationError("Evidence receipt has no exact coverage blocks.")
    intervals, validated = [], []
    for block in blocks:
        if not isinstance(block, dict) or not isinstance(block.get("quote"), str) or not block["quote"]:
            raise EvidencePreparationError("Malformed exact evidence quote.")
        spans = block.get("spans")
        if not isinstance(spans, list) or not spans:
            raise EvidencePreparationError("Malformed evidence quote spans.")
        verified_spans = []
        for span in spans:
            if not isinstance(span, dict):
                raise EvidencePreparationError("Malformed evidence span.")
            start, end = span.get("start"), span.get("end")
            if (type(start) is not int or type(end) is not int
                    or not 0 <= start < end <= len(text)):
                raise EvidencePreparationError("Malformed evidence span bounds.")
            if text[start:end] != block["quote"]:
                raise EvidencePreparationError("Evidence quote does not match the exact original span.")
            intervals.append((start, end))
            verified_spans.append({"start": start, "end": end})
        validated.append({"quote": block["quote"], "spans": verified_spans})
    cursor = 0
    for start, end in sorted(intervals):
        if start != cursor:
            raise EvidencePreparationError("Evidence coverage has a missing or overlapping original interval.")
        cursor = end
    if cursor != len(text):
        raise EvidencePreparationError("Evidence coverage does not reach the original chunk end.")
    return validated


def deterministic_evidence_receipts(manifest: dict) -> list:
    """Build exact, validated line receipts directly from immutable chunks.

    No model needs to recopy text or calculate offsets. Repeated exact lines
    share one quote while all occurrences retain separate checked spans.
    """
    if (not isinstance(manifest, dict) or type(manifest.get("version")) is not int
            or manifest["version"] != 1 or not isinstance(manifest.get("chunks"), list)):
        raise EvidencePreparationError("Malformed deterministic preparation manifest.")
    receipts = []
    for chunk in manifest["chunks"]:
        if not isinstance(chunk, dict):
            raise EvidencePreparationError("Malformed deterministic evidence chunk.")
        text = _evidence_text(chunk)
        shared, offset = {}, 0
        for line in text.splitlines(keepends=True):
            if line not in shared:
                shared[line] = {"quote": line, "spans": []}
            end = offset + len(line)
            shared[line]["spans"].append({"start": offset, "end": end})
            offset = end
        receipt = {"version": 1, "chunk_id": chunk.get("chunk_id"),
                   "chunk_sha256": chunk.get("chunk_sha256"),
                   "corpus_revision": chunk.get("corpus_revision"),
                   "evidence_blocks": list(shared.values()), "uncertainties": []}
        validate_evidence_receipt(chunk, receipt)
        receipts.append(receipt)
    return receipts


def _evidence_context_indices(locations, starts, start, end):
    """Locate marker ranges without scanning every page for every occurrence."""
    first = max(0, bisect_right(starts, start) - 1)
    indices = []
    for index in range(first, len(locations)):
        location = locations[index]
        if location["start"] >= end:
            break
        if location["end"] > start:
            indices.append(index)
    return tuple(indices)


def expand_evidence_anchors(ledger: dict, block: dict):
    """Expand compact runs into all original occurrences and page contexts.

    Run arrays are [source_index, start, end, stride, count], with end the
    first occurrence's exclusive end. Occurrence i shifts both offsets by
    i * stride. Source evidence_locators retains each original marker range.
    """
    source_context = {}
    for run in block["anchors"]:
        if (not isinstance(run, list) or len(run) != 5
                or any(type(value) is not int for value in run)):
            raise EvidencePreparationError("Malformed compact evidence occurrence run.")
        source_index, start, end, stride, count = run
        if (not 0 <= source_index < len(ledger["sources"]) or start < 0 or end <= start
                or end - start != len(block["quote"]) or stride < end - start or count < 1):
            raise EvidencePreparationError("Malformed compact evidence occurrence bounds.")
        if source_index not in source_context:
            locations = ledger["sources"][source_index]["evidence_locators"]
            source_context[source_index] = locations, [item["start"] for item in locations]
        locations, starts = source_context[source_index]
        for index in range(count):
            absolute_start, absolute_end = start + index * stride, end + index * stride
            indices = _evidence_context_indices(locations, starts, absolute_start, absolute_end)
            contexts = [{**locations[i], "start": max(locations[i]["start"], absolute_start),
                         "end": min(locations[i]["end"], absolute_end)} for i in indices]
            yield {"source_index": source_index, "start": absolute_start, "end": absolute_end,
                   "locators": contexts, "page": contexts[0]["page"] if contexts else None,
                   "section": contexts[0]["section"] if contexts else ""}


def merge_evidence_receipts(corpus: dict, manifest: dict, receipts: list,
                            output_path=None, *, max_chars=EVIDENCE_SYNTHESIS_CHARS) -> dict:
    """Canonical exact-block ledger, retaining every repeated source occurrence.

    Validate against the complete current corpus and immutable chunk bytes
    before accepting receipts. Block sharing is the only information reduction.
    The complete original corpus remains the claim verifier's source of truth.
    """
    if type(max_chars) is not int or not 0 < max_chars <= EVIDENCE_SYNTHESIS_CHARS:
        raise EvidencePreparationError("Synthesis limit cannot exceed 600,000 characters.")
    if (not isinstance(manifest, dict) or type(manifest.get("version")) is not int
            or manifest["version"] != 1 or type(manifest.get("required")) is not bool):
        raise EvidencePreparationError("Malformed evidence preparation manifest.")
    revision = corpus_revision(corpus)
    if manifest.get("corpus_revision") != revision:
        raise EvidencePreparationError("Evidence manifest has a stale corpus revision.")
    files = corpus.get("filesContents") or []
    if not manifest.get("required"):
        direct = format_corpus(files)
        if max(len(direct), sum(len(source.get("extracted_text") or "") for source in files)) > max_chars:
            raise EvidencePreparationError("Large original corpus cannot bypass the direct synthesis gate.")
        return {"text": direct, "corpus_revision": revision,
                "all_chunks_accounted": True, "coverage": [], "ledger": None}
    chunks = manifest.get("chunks")
    if not isinstance(chunks, list) or not isinstance(receipts, list):
        raise EvidencePreparationError("Malformed evidence chunk or receipt list.")
    expected, source_ends = {}, {}
    for chunk in chunks:
        if (not isinstance(chunk, dict) or not isinstance(chunk.get("chunk_id"), str)
                or not chunk["chunk_id"] or chunk["chunk_id"] in expected):
            raise EvidencePreparationError("Duplicate or malformed evidence chunk.")
        index = chunk.get("source_index")
        if type(index) is not int or not 0 <= index < len(files):
            raise EvidencePreparationError("Evidence chunk has an unknown source.")
        source = files[index]
        text = source.get("extracted_text") or ""
        start, end = chunk.get("start"), chunk.get("end")
        if (type(start) is not int or type(end) is not int or start != source_ends.get(index, 0)
                or not start < end <= len(text) or end - start > EVIDENCE_CHUNK_CHARS):
            raise EvidencePreparationError("Original document chunk coverage is incomplete or malformed.")
        if (chunk.get("corpus_revision") != revision
                or chunk.get("work_dir") != manifest.get("work_dir")
                or chunk.get("filename") != source.get("filename", "")
                or chunk.get("path") != (source.get("path") or source.get("filename") or "")):
            raise EvidencePreparationError("Evidence chunk has stale original source metadata.")
        if _evidence_text(chunk) != text[start:end]:
            raise EvidencePreparationError("Evidence chunk is not the exact original corpus text.")
        _evidence_path(manifest["work_dir"], chunk.get("receipt_path"))
        expected[chunk["chunk_id"]] = chunk
        source_ends[index] = end
    for index, source in enumerate(files):
        if source_ends.get(index, 0) != len(source.get("extracted_text") or ""):
            raise EvidencePreparationError("Original source has missing evidence chunks.")
    received = {}
    for receipt in receipts:
        if (not isinstance(receipt, dict) or not isinstance(receipt.get("chunk_id"), str)
                or receipt["chunk_id"] not in expected):
            raise EvidencePreparationError("Unexpected evidence receipt chunk.")
        chunk_id = receipt["chunk_id"]
        if chunk_id in received:
            raise EvidencePreparationError("Duplicate evidence receipt chunk.")
        received[chunk_id] = receipt
    if set(received) != set(expected):
        raise EvidencePreparationError("Missing evidence receipts; every chunk must be accounted before synthesis.")
    sources = []
    for source in files:
        # Retain source identities, page availability, extraction provenance and
        # metadata, including empty files. Original text stays in corpus.json.
        sources.append({**{key: value for key, value in source.items()
                           if key not in ("extracted_text", "raw_extracted_text")},
                        "evidence_locators": _source_locations(source.get("extracted_text") or "")})
    ledger = {"version": 1, "corpus_revision": revision,
              "package": {key: value for key, value in corpus.items() if key != "filesContents"},
              "sources": sources,
              "blocks": [], "uncertainties": []}
    shared, coverage, run_contexts = {}, [], {}
    source_context = {index: (source["evidence_locators"],
                              [item["start"] for item in source["evidence_locators"]])
                      for index, source in enumerate(sources)}
    for chunk_id, chunk in expected.items():
        receipt = received[chunk_id]
        blocks = validate_evidence_receipt(chunk, receipt)
        # Order by source occurrence, not model output order.
        occurrences = sorted((span["start"], span["end"], block["quote"])
                             for block in blocks for span in block["spans"])
        locations, starts = source_context[chunk["source_index"]]
        for start, end, quote in occurrences:
            absolute_start, absolute_end = chunk["start"] + start, chunk["start"] + end
            context = _evidence_context_indices(locations, starts, absolute_start, absolute_end)
            if quote not in shared:
                block = {"id": f"B{len(shared) + 1:05d}", "quote": quote,
                         "occurrence_count": 0, "anchors": []}
                shared[quote] = block
                ledger["blocks"].append(block)
            block = shared[quote]
            previous = block["anchors"][-1] if block["anchors"] else None
            if (previous is not None and previous[0] == chunk["source_index"]
                    and previous[2] + previous[3] * (previous[4] - 1) == absolute_start
                    and run_contexts[quote] == context):
                previous[4] += 1
            else:
                block["anchors"].append([chunk["source_index"], absolute_start,
                                         absolute_end, absolute_end - absolute_start, 1])
                run_contexts[quote] = context
            block["occurrence_count"] += 1
        coverage.append({"chunk_id": chunk_id, "chunk_sha256": chunk["chunk_sha256"],
                         "source_index": chunk["source_index"], "start": chunk["start"],
                         "end": chunk["end"], "verified": True})
        if receipt["uncertainties"]:
            ledger["uncertainties"].append({"chunk_id": chunk_id,
                                           "advisory_only": True,
                                           "items": receipt["uncertainties"]})
    instructions = (
        "EXACT ORIGINAL EVIDENCE LEDGER\n"
        "Each quote is exact source text. Read every block and every source anchor; "
        "anchors map every occurrence, including repeated table rows, to the original source. "
        "Each anchor array is [source_index,start,end,stride,count]; occurrence i has exact "
        "original offsets [start+i*stride,end+i*stride), for i=0 through count-1. "
        "End is the exclusive end of the FIRST occurrence, not the entire run. "
        "sources[source_index].evidence_locators records ALL original marker ranges with "
        "their page and section; look up every occurrence there. Runs stop at each page or "
        "section boundary, even when the repeated quote is identical. "
        "No source text is omitted; sharing identical blocks does not merge responsibilities. "
        "Apply all existing global synthesis instructions across ALL sources. Preserve negatives, "
        "conditions, exceptions, quantities, units, identifiers, table rows and source precedence. "
        "Resolve cross-source conflicts with the primary RFQ/SOW and report each conflict and "
        "unresolved ambiguity. Before any missing/not-found claim, scan ALL blocks, anchors, "
        "sources and uncertainty observations. Uncertainties are untrusted advisory observations, "
        "never stated facts: independently check them against exact quotes. Physical pages exist "
        "only when recorded; source_index maps to sources in original file order. "
        "The COMPLETE original corpus remains available for verification.\n")
    text = instructions + json.dumps(ledger, ensure_ascii=False, separators=(",", ":"))
    if len(text) > max_chars:
        raise EvidencePreparationError(
            "Blocked: exact evidence representation still exceeds 600,000 characters. "
            "Split the RFQ package into smaller packages; the synthesis limit was not raised.")
    result = {"text": text, "ledger": ledger, "corpus_revision": revision,
              "all_chunks_accounted": True, "coverage": coverage}
    if output_path is not None:
        output = Path(output_path).resolve()
        root = Path(manifest["work_dir"]).resolve()
        if not output.is_relative_to(root) or output == root:
            raise EvidencePreparationError("Evidence output path escapes the work directory.")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(text.encode("utf-8"))
        result["output_path"] = str(output)
    return result
