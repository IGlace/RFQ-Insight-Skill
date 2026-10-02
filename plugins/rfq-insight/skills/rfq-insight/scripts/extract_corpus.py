#!/usr/bin/env python3
"""Turn an RFQ folder into the corpus the analysis reads.

    python extract_corpus.py "C:/RFQs/Acme V6" --project "Acme V6"

Walks the folder recursively, extracts every supported file with the
library that understands it, cleans extraction artefacts, unpacks and
filters embedded images, and writes three checkpoints:

    <folder>/output/.work/corpus.json    the corpus + the extraction record
    <folder>/output/.work/images/        pictures awaiting a visual read
    <folder>/output/.work/images.json    the manifest for that read

Exits 0 even when some files could not be read - whether to carry on
without them is the user's decision, and the skill asks. Exits 1 only when
nothing at all could be read.
"""

import argparse
import datetime
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from rfq import extractors                              # noqa: E402
from rfq.images import filter_images, write_images      # noqa: E402
# preprocess.py is a verbatim port and its module docstring still describes
# the corpus as coming from Copilot Studio's GetFileContents over
# SharePoint. It does not: it comes from extractors.py, a few lines below.
# The docstring is left alone deliberately - the golden-run suite pins that
# file byte for byte against its source. Its CLEANERS are what matter and
# they are format-agnostic; the artefacts they strip (page furniture,
# repeated headers, hyphenation) come from the documents, not the transport.
from rfq.preprocess import clean_corpus_files           # noqa: E402

OUTPUT_DIRNAME = "output"
WORK_DIRNAME = ".work"


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


def build_corpus(folder: str, project_name: str):
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
            got = extractors.extract_file(path, key)
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
        files.append({
            "filename": name,
            "extension": ext.lstrip("."),
            "path": rel,
            "file_size": os.path.getsize(path),
            "modified": _stamp(path),
            "category": extractors.CATEGORY[ext],
            "extraction_method": extractors.METHOD[ext],
            "source": "extract_corpus.py",
            "processed_at": datetime.datetime.now().isoformat(
                timespec="seconds"),
            "extracted_text": got.text,
        })

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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Extract an RFQ folder.")
    ap.add_argument("folder", help="the folder holding the RFQ package")
    ap.add_argument("--project", default=None,
                    help="opportunity name (defaults to the folder name)")
    args = ap.parse_args(argv)

    folder = os.path.abspath(args.folder)
    if not os.path.isdir(folder):
        print("I couldn't find that folder - check the path and try again.",
              file=sys.stderr)
        return 1

    project = args.project or os.path.basename(folder.rstrip(os.sep))
    corpus, raw_images = build_corpus(folder, project)

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

    with open(os.path.join(work, "corpus.json"), "w", encoding="utf-8") as fh:
        json.dump(corpus, fh, ensure_ascii=False, indent=2)
    with open(os.path.join(work, "images.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)

    for line in summary_lines(corpus, manifest):
        print(line)

    if corpus["extraction"]["parsed"] == 0:
        print("That folder has nothing I can read. I handle PDF, Word, "
              "Excel, PowerPoint, text, CSV and images.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
