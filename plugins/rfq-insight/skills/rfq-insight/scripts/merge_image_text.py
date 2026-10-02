#!/usr/bin/env python3
"""Fold image transcriptions back into the corpus.

    python merge_image_text.py "C:/RFQs/Acme V6"

extract_corpus.py left a marker wherever a picture was and saved the
picture to .work/images/. The agent looks at each one and writes what it
sees to .work/image_text/<id>.txt. This script puts that text back AT THE
MARKER, so:

  * the chart returns to the position it occupied and keeps its context;
  * `evidence_files` still names the parent file, exactly as its
    `=== FILE: ===` header requires - corpus_text.py builds those headers
    from the same `extracted_text` this script writes into, so a
    transcription lands inside its parent's block;
  * the verifier subagent - which never sees the picture - reads the same
    text as the analysis stage;
  * the run is replayable from the corpus alone.

This is the behaviour the old OCR-the-whole-document path had by accident.
Here it is deliberate.

Running it twice is a no-op: the markers are gone after the first pass.
"""

import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from rfq.extractors import image_key, marker_for        # noqa: E402
from rfq.preprocess import clean_extracted_text         # noqa: E402

TRANSCRIPTION_DIRNAME = "image_text"


def transcription_path(work: str, image_id: str) -> str:
    return os.path.join(work, TRANSCRIPTION_DIRNAME, f"{image_id}.txt")


def transcription_block(image_id: str, text: str) -> str:
    """How a transcription appears in the corpus. Delimited so the model can
    tell a read picture from prose, and never mistake it for a quote."""
    return (f"[BEGIN IMAGE TRANSCRIPTION {image_id}]\n"
            f"{text}\n"
            f"[END IMAGE TRANSCRIPTION]")


def unread_note(image_id: str, locator: str) -> str:
    return f"[[PICTURE {image_id} at {locator} could not be read]]"


def read_transcriptions(work: str, manifest: dict):
    """({image_id: cleaned text}, [ids with nothing saved])."""
    found, missing = {}, []
    for entry in manifest.get("images", []):
        path = transcription_path(work, entry["id"])
        if not os.path.exists(path):
            missing.append(entry["id"])
            continue
        with open(path, encoding="utf-8") as fh:
            text = fh.read().strip()
        if text:
            found[entry["id"]] = text
        else:
            missing.append(entry["id"])
    return found, missing


def _standalone_parent(files: list, image_id: str):
    """The corpus entry a standalone image's id was built from.

    A standalone image leaves no marker in the text — the file IS the
    picture — so the marker-based lookup used for embedded figures does not
    apply. Its id still carries the identity though: everything before
    "__img" is image_key() of the file's path relative to the RFQ folder,
    which is unique where a basename is not.
    """
    key = image_id.rsplit("__img", 1)[0]
    for entry in files:
        if image_key(entry.get("path", "")) == key:
            return entry
    return None


def _parent_for_marker(files: list, marker: str):
    """The corpus entry whose text carries this marker.

    Resolved by marker rather than by filename on purpose: two files in
    different subfolders can share a basename (annexes/Spec.pdf and
    attachments/Spec.pdf), and the corpus keys on basename. The marker
    embeds the image id, which extractors.image_key builds from the path
    relative to the RFQ folder, so it is unique across the whole corpus -
    that uniqueness is what this function depends on, and it is enforced
    there, not here.
    """
    for entry in files:
        if marker in (entry.get("extracted_text") or ""):
            return entry
    return None


def _placeholder_in(files: list, image_id: str, locator: str):
    """(entry, placeholder) for this image's marker, or for the unread note
    a previous run wrote in its place.

    Looking for both is what makes the merge re-runnable. Once an unread
    note has replaced a marker, the marker is gone forever - so a
    transcription added between runs could never be folded in if we only
    searched for markers. The note is a pure function of the image id and
    the manifest's locator, so it can be reconstructed exactly.
    """
    for placeholder in (marker_for(image_id), unread_note(image_id, locator)):
        entry = _parent_for_marker(files, placeholder)
        if entry is not None:
            return entry, placeholder
    return None, None


def merge(corpus: dict, manifest: dict, transcriptions: dict) -> dict:
    """Put every transcription back at its marker. Mutates and returns.

    Nothing is ever dropped without a trace: an image whose parent cannot
    be resolved, or whose marker is not present and which was not merged on
    an earlier run, is recorded in `images_unresolved`.
    """
    files = corpus.get("filesContents", [])
    record = corpus.setdefault("extraction", {})

    # Only the MERGED history needs carrying forward: a merged marker is
    # gone with nothing left to find, so history is the only evidence the
    # work was done. An unread picture still has its note in the text, so
    # it is re-detected each run rather than remembered.
    already = list(record.get("images_merged", []))
    merged, unread, unresolved = list(already), [], []

    by_name: dict = {}
    duplicated = set()
    for entry in files:
        name = entry.get("filename", "")
        if name in by_name:
            duplicated.add(name)
        else:
            by_name[name] = entry

    for entry in manifest.get("images", []):
        image_id = entry["id"]
        raw = transcriptions.get(image_id)
        cleaned = clean_extracted_text(raw) if raw else ""

        if entry.get("kind") == "standalone":
            # Resolve by the image id's own key, not by filename. The id is
            # image_key(<path relative to the RFQ folder>) + "__imgNN", and
            # that path is unique by construction — so two loose images
            # sharing a basename in different subfolders (diagrams/chart.png
            # and annexes/chart.png) each find their own entry instead of
            # both being abandoned as ambiguous.
            parent = _standalone_parent(files, image_id)
            if parent is None:
                parent = by_name.get(entry["source"])
                if parent is None or entry["source"] in duplicated:
                    # Still ambiguous or missing: writing into the wrong file
                    # would put one picture's text on another's entry.
                    unresolved.append(image_id)
                    continue
            if cleaned:
                parent["extracted_text"] = transcription_block(image_id,
                                                               cleaned)
                if image_id not in merged:
                    merged.append(image_id)
            else:
                parent["extracted_text"] = unread_note(
                    image_id, entry.get("locator", "this file"))
                unread.append(image_id)
            continue

        locator = entry.get("locator", "an unknown place")
        parent, placeholder = _placeholder_in(files, image_id, locator)
        if parent is None:
            if image_id in already:
                continue          # merged on an earlier run: a real no-op
            unresolved.append(image_id)
            continue

        if cleaned:
            replacement = transcription_block(image_id, cleaned)
            if image_id not in merged:
                merged.append(image_id)
        else:
            replacement = unread_note(image_id, locator)
            unread.append(image_id)
        parent["extracted_text"] = parent["extracted_text"].replace(
            placeholder, replacement)

    record["images_merged"] = merged
    record["images_unread"] = unread
    record["images_unresolved"] = unresolved
    record["chars"] = sum(len(f.get("extracted_text", "") or "")
                          for f in files)
    return corpus


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Fold transcriptions into the corpus.")
    ap.add_argument("folder", help="the folder holding the RFQ package")
    args = ap.parse_args(argv)

    work = os.path.join(os.path.abspath(args.folder), "output", ".work")
    corpus_path = os.path.join(work, "corpus.json")
    manifest_path = os.path.join(work, "images.json")
    for path in (corpus_path, manifest_path):
        if not os.path.exists(path):
            print("Nothing to add - I haven't read the documents yet.",
                  file=sys.stderr)
            return 0

    with open(corpus_path, encoding="utf-8") as fh:
        corpus = json.load(fh)
    with open(manifest_path, encoding="utf-8") as fh:
        manifest = json.load(fh)

    transcriptions, missing = read_transcriptions(work, manifest)
    before = len(corpus.get("extraction", {}).get("images_merged", []))
    merge(corpus, manifest, transcriptions)
    record = corpus["extraction"]
    added = len(record["images_merged"]) - before

    with open(corpus_path, "w", encoding="utf-8") as fh:
        json.dump(corpus, fh, ensure_ascii=False, indent=2)

    print(f"Added what {added} picture(s) show to the text.")
    if missing:
        print(f"{len(missing)} picture(s) had nothing saved and are marked "
              f"as unread in the report.")
    if record["images_unresolved"]:
        print(f"{len(record['images_unresolved'])} picture(s) couldn't be "
              f"matched back to the document they came from; the report "
              f"lists them.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
