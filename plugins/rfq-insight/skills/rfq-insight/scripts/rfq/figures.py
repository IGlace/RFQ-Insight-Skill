"""Filter images, certify worker outputs and merge transcriptions."""

import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import tempfile
import uuid

from .extractors import image_key, marker_for, clean_extracted_text
from .state import replace_with_retry
from .sources import format_source_line

MIN_IMAGE_BYTES = 8_000
MIN_IMAGE_PIXELS = 40_000          # e.g. 200 x 200
CHROME_REPEAT_THRESHOLD = 3        # identical bytes this often = page furniture
# Raised with the PDF figure floor: chasing label-sized text-as-image
# means far more candidates per package, and a cap that trips turns a
# deliberate trade into silent loss. Repeats are de-duplicated before
# this applies, so the real number is well below the raw figure count.
MAX_FLAGGED_IMAGES = 90

REASONS = {
    "too_small": "too small to carry information (a logo, icon or rule)",
    "chrome": "repeats through the document, so it is page furniture",
    "duplicate": "identical to an image already included",
    "cap_reached": "beyond the limit on pictures read in one run",
    "unreadable": "not a readable image",
}


def image_digest(data: bytes) -> str:
    """Identity for de-duplication: a hash of the bytes.

    Deliberately plain. A thumbnail-based key was tried, on the assumption
    that PDF figure crops of the same logo would render to slightly
    different pixels - and measurement killed it: across 60 figures from a
    real package, byte hashing found 41 distinct and a 24x24 thumbnail found
    40. One merge is not worth a key that can declare two different small
    figures identical.
    """
    return hashlib.sha256(data).hexdigest()


def _image_file(entry, images_dir):
    """(name, path) of the saved image, with a confined local filename."""
    name = entry.get("file")
    if (not isinstance(name, str) or name in ("", ".", "..")
            or PurePosixPath(name).name != name
            or PureWindowsPath(name).name != name or ":" in name):
        raise ValueError("The image filename must be a plain local name.")
    root = Path(images_dir).resolve()
    path = (root / name).resolve()
    if not path.is_relative_to(root):
        raise ValueError("The image path escapes its directory.")
    return name, path


def image_identity(entry, images_dir, digest=None):
    """Identity of the actual saved image, with a confined local filename.
    `digest` is the file's sha256 when the caller already hashed it."""
    name, path = _image_file(entry, images_dir)
    return {"file": name, "source": entry.get("source", ""),
            "locator": entry.get("locator", ""),
            "sha256": digest or image_digest(path.read_bytes())}


def identity_matches(expected, actual):
    """Compare complete identities; missing fields never certify a cache."""
    keys = ("file", "source", "locator", "sha256")
    return (isinstance(expected, dict) and isinstance(actual, dict)
            and all(key in expected and key in actual
                    and expected[key] == actual[key] for key in keys))


def image_pixels(data: bytes) -> int:
    """Pixel count, or 0 when the bytes are not a readable image."""
    from PIL import Image
    try:
        with Image.open(io.BytesIO(data)) as handle:
            return int(handle.width) * int(handle.height)
    except Exception:
        return 0


def _file_pixels(path) -> int:
    """image_pixels for a saved file, reading only its header."""
    from PIL import Image
    try:
        with Image.open(path) as handle:
            return int(handle.width) * int(handle.height)
    except Exception:
        return 0


def _drop(img, reason: str, detail: str = "") -> dict:
    """One filtered-out image, as the run report carries it.

    `reason` is the key the code groups on; `explanation` is the same fact
    in words, carried WITH the record so whoever reads the report - or
    prints it - never has to look the key up. Spec section 6 wants every
    filtered picture listed, and a list of `too_small` tells a salesperson
    nothing.
    """
    return {"id": img.image_id, "source": img.source,
            "locator": img.locator, "reason": reason,
            "explanation": REASONS.get(reason, reason), "detail": detail}


def filter_images(images, max_flagged: int = MAX_FLAGGED_IMAGES):
    """Split unpacked images into (kept, dropped).

    A standalone image - a .png the user put in the RFQ folder - bypasses
    the size, chrome and duplicate filters: that file IS the content, and a
    small one is still the only thing in it. It still respects the cap, so
    a folder of forty screenshots cannot turn into forty visual reads.
    """
    digests = [image_digest(i.data) for i in images]
    for img, digest in zip(images, digests):
        img.digest = digest
    # Chrome means "this picture repeats through the documents". A
    # standalone file is a whole input in its own right, not a repeat of
    # anything, so it must not be counted: a screenshot the user dropped in
    # the folder that happens to be the same bytes as a chart inside the
    # SOR would otherwise inflate that chart's count and get it thrown away
    # as page furniture.
    counts: dict = {}
    for img, digest in zip(images, digests):
        if img.locator != "standalone":
            counts[digest] = counts.get(digest, 0) + 1

    kept, dropped, seen = [], [], set()
    for img, digest in zip(images, digests):
        pixels = image_pixels(img.data)
        if pixels == 0:
            dropped.append(_drop(img, "unreadable"))
            continue
        if img.locator != "standalone":
            # The SIZE test is skipped for a PRESIZED image - and only the
            # size test. A PDF figure crop was already judged against its
            # area ON THE PAGE, which is the meaningful measure; re-judging
            # it on pixel count throws away exactly what the page-area floor
            # was lowered to catch, a single line of text rendered as a
            # picture such as a standard's version number.
            #
            # De-duplication below still applies. Exempting presized images
            # from the whole block left PDF figures never de-duplicated at
            # all: one package flagged 60 figures of which 19 were repeat
            # renders of two logos.
            #
            # AND, not OR. A chart is big on the page and small in bytes -
            # flat fills and few colours compress to almost nothing - so
            # either test alone would throw real content away. Only a
            # picture that is small BOTH ways is furniture.
            if (not getattr(img, "presized", False)
                    and len(img.data) < MIN_IMAGE_BYTES
                    and pixels < MIN_IMAGE_PIXELS):
                dropped.append(_drop(
                    img, "too_small", f"{len(img.data)} bytes, {pixels} pixels"))
                continue
            if digest in seen:
                # Repeats are dropped; the FIRST occurrence is always kept,
                # whether the image repeats twice or on every page.
                #
                # Page furniture used to be dropped outright, which cost
                # nothing until a real package put its only telephone number
                # and the engineering firm's name inside the letterhead strip
                # repeated on all four pages. By definition that is chrome,
                # and by definition it is also where contact details live —
                # the prompt treats a missed contact as a critical error.
                # Reading it once per document is the cheap way to have both.
                reason = ("chrome"
                          if counts.get(digest, 0) >= CHROME_REPEAT_THRESHOLD
                          else "duplicate")
                dropped.append(_drop(
                    img, reason, f"appears {counts.get(digest, 0)} times"))
                continue
        seen.add(digest)
        kept.append(img)
    if len(kept) > max_flagged:
        # Allocate slots across documents before letting a long annex consume
        # the remaining budget. Retain original order within each document.
        from collections import deque
        groups = {}
        for image in kept:
            groups.setdefault(image.key or image.source, deque()).append(image)
        chosen = []
        while len(chosen) < max_flagged:
            for group in groups.values():
                if group and len(chosen) < max_flagged:
                    chosen.append(group.popleft())
        included = {id(image) for image in chosen}
        dropped.extend(_drop(image, "cap_reached", f"limit is {max_flagged}")
                       for image in kept if id(image) not in included)
        kept = chosen
    return kept, dropped


def balanced_figure_batches(entries, image_ids, images_dir, batch_size=6,
                            figs=None):
    """Bound jobs by count and spread estimated pixel work across batches.

    Pixel count is a scheduling heuristic, never a content/skip decision.
    Stable ID tie-breaks make schedules reproducible for the same manifest.
    `figs` (the stage's FigureSet) reuses its hashes and reads only each
    image's header for the pixel count.
    """
    import math
    if type(batch_size) is not int or not 1 <= batch_size <= MAX_FLAGGED_IMAGES:
        raise ValueError("The figure batch size must be an integer from 1 to 90.")
    if len(image_ids) != len(set(image_ids)):
        raise ValueError("Figure IDs must be unique.")
    if not image_ids:
        return []
    by_id = {entry["id"]: entry for entry in entries}
    missing = set(image_ids) - by_id.keys()
    if missing:
        raise ValueError("Figure IDs are missing from the manifest.")
    work = []
    for image_id in image_ids:
        entry = by_id[image_id]
        if figs is not None:
            identity = figs.identity(entry)
            pixels = _file_pixels(Path(images_dir) / identity["file"])
        else:
            identity = image_identity(entry, images_dir)
            pixels = image_pixels((Path(images_dir) / identity["file"]).read_bytes())
        work.append((max(pixels, 1), image_id))
    batches = [[] for _ in range(math.ceil(len(image_ids) / batch_size))]
    loads = [0] * len(batches)
    for pixels, image_id in sorted(work, key=lambda pair: (-pair[0], pair[1])):
        index = min((i for i in range(len(batches)) if len(batches[i]) < batch_size),
                    key=lambda i: (loads[i], len(batches[i]), i))
        batches[index].append(image_id)
        loads[index] += pixels
    return batches


def write_images(kept, dropped, images_dir: str) -> dict:
    """Save every kept image and build the manifest for the visual pass."""
    os.makedirs(images_dir, exist_ok=True)
    entries = []
    for img in kept:
        ext = img.ext if img.ext in (".png", ".jpg", ".jpeg") else ".png"
        name = img.image_id + ext
        with open(os.path.join(images_dir, name), "wb") as fh:
            fh.write(img.data)
        entry = {
            "id": img.image_id,
            "file": name,
            "source": img.source,
            "locator": img.locator,
            "kind": "standalone" if img.locator == "standalone" else "embedded",
        }
        entry["sha256"] = image_identity(
            entry, images_dir, getattr(img, "digest", "") or None)["sha256"]
        entries.append(entry)
    return {"images": entries, "filtered": list(dropped)}


# What the worker writes into the .txt for a legible picture that has no
# text at all (a product photo). An empty .txt means "unread" everywhere else.
NO_TEXT_MARKER = "[No text in this picture]"
# Deck pictures: a camera JPEG keeps its bytes up to this long side; above
# it the picture is scaled down (a 4000 px photo printed 5 inches wide is
# wasted megabytes in every copy of the deck).
MAX_SIDE = 2400
JPEG_QUALITY = 85
EXIF_ORIENTATION = 0x0112


def picture_source(entry: dict) -> str:
    """'SOR.pdf p. 5' / 'Deck.pptx slide 3' / 'SOR.docx' / 'photo.jpg'.

    Word paragraph numbers mean nothing to a reader, so they are left out.
    """
    source = str(entry.get("source", ""))
    locator = str(entry.get("locator", "")).strip()
    page = re.fullmatch(r"page (\d+)", locator)
    if page:
        return f"{source} p. {page.group(1)}"
    slide = re.fullmatch(r"slide (\d+)", locator)
    if slide:
        return f"{source} slide {slide.group(1)}"
    return source


def resolve_picture_file(item, images_dir):
    """Resolve only the saved filename whose bytes this report approved."""
    if not images_dir or not item.get("file") or not item.get("sha256"):
        raise ValueError("Picture provenance is missing; rebuild this RFQ analysis.")
    try:
        identity = image_identity(
            {"file": item["file"], "source": "", "locator": ""}, images_dir)
    except OSError as exc:
        raise ValueError("A saved picture is missing or unreadable; rebuild this RFQ analysis.") from exc
    except ValueError as exc:
        raise ValueError("The saved picture filename is invalid; rebuild this RFQ analysis.") from exc
    if identity["sha256"] != item["sha256"]:
        raise ValueError("A saved picture changed; rebuild this RFQ analysis.")
    return str(Path(images_dir) / item["file"])


def deck_picture(path):
    """(bytes, width px, height px) as the deck embeds the picture, or None
    when Pillow cannot load it.

    A JPEG or PNG that is upright and at most MAX_SIDE px keeps its original
    bytes. Anything else is re-encoded: turned upright first (a phone photo
    stores "rotate 90°" in EXIF, which PowerPoint ignores), scaled down to
    MAX_SIDE, a JPEG stays JPEG (quality JPEG_QUALITY), everything else
    becomes PNG. images.write_images stores any other format (EMF, WMF,
    TIFF, GIF) under a .png name with its ORIGINAL bytes, so the extension
    proves nothing; Pillow's verdict on the content decides.
    """
    from PIL import Image, ImageOps
    try:
        with Image.open(path) as handle:
            handle.load()
            kind = handle.format
            turned = handle.getexif().get(EXIF_ORIENTATION, 1) != 1
            if (kind in ("JPEG", "PNG") and not turned
                    and max(handle.size) <= MAX_SIDE):
                with open(path, "rb") as fh:
                    return fh.read(), int(handle.width), int(handle.height)
            image = ImageOps.exif_transpose(handle) if turned else handle
            if kind == "JPEG":
                fmt, options = "JPEG", {"quality": JPEG_QUALITY}
                if image.mode not in ("RGB", "L"):
                    image = image.convert("RGB")
            else:
                fmt, options = "PNG", {}
                if image.mode not in ("RGB", "RGBA", "L"):
                    image = image.convert("RGBA")
            image.thumbnail((MAX_SIDE, MAX_SIDE))      # only ever shrinks
            buf = io.BytesIO()
            image.save(buf, format=fmt, **options)
            return buf.getvalue(), int(image.width), int(image.height)
    except Exception:
        return None


def slide_source_line(pictures: list, manifest=None) -> str:
    """The slide's grey source line, naming exactly the pictures on it:
    file + page/slide from the manifest, merged per file like every other
    source line. Without the manifest, each picture's printed source."""
    by_id = {e.get("id"): e for e in (manifest or {}).get("images", [])}
    sources = []
    for item in pictures:
        entry = by_id.get(item.get("imageId"))
        if entry is None:
            sources.append({"filename": item.get("source", ""), "locator": ""})
        else:
            sources.append({"filename": entry.get("source", ""),
                            "locator": entry.get("locator", "")})
    return format_source_line(sources, False)


def _local_name(value):
    if (not isinstance(value, str) or value in ("", ".", "..") or
            Path(value).name != value or PureWindowsPath(value).name != value or
            ":" in value):
        raise ValueError("Image identifiers and files must be plain local names.")
    return value


def figure_output(work, image_id):
    """The one output of a figure worker: the picture's transcription."""
    return Path(work) / "image_text" / f"{_local_name(image_id)}.txt"


def _figure_text_valid(work, image_id):
    try:
        text = figure_output(work, image_id)
        return text.is_file() and bool(text.read_text(encoding="utf-8").strip())
    except (OSError, ValueError, TypeError):
        return False


class FigureSet:
    """One stage's view of the pictures: images.json parsed once and each
    saved image hashed at most once. A stage handler builds one and passes
    it to every helper it calls; it never outlives that call, since images
    can change between calls but not within one."""

    def __init__(self, work, manifest=None):
        self.work = Path(work)
        self.images = self.work / "images"
        self.error = None
        if manifest is None:
            try:
                manifest = _read_json(self.work / "images.json")
            except (OSError, ValueError) as exc:
                manifest, self.error = {"images": []}, exc
        if not isinstance(manifest, dict):
            manifest, self.error = {"images": []}, ValueError(
                "The image manifest is not an object.")
        self.manifest = manifest
        self._digests = {}

    def entry(self, image_id):
        """The manifest entry of `image_id`; ValueError unless exactly one."""
        if self.error is not None:
            raise ValueError(f"The image manifest could not be read: {self.error}")
        matches = [entry for entry in self.manifest.get("images", [])
                   if isinstance(entry, dict) and entry.get("id") == image_id]
        if len(matches) != 1:
            raise ValueError(f"Expected one image with id {image_id} in the manifest.")
        return matches[0]

    def identity(self, entry):
        """image_identity(entry), hashing each saved file once."""
        name, path = _image_file(entry, self.images)
        if name not in self._digests:
            self._digests[name] = image_digest(path.read_bytes())
        return image_identity(entry, self.images, self._digests[name])


def _figures(work, figs):
    return FigureSet(work) if figs is None else figs


def _read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(value, handle, ensure_ascii=False, indent=2)
        replace_with_retry(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def figure_metadata(work, image_id):
    return Path(work) / "image_text" / f"{_local_name(image_id)}.meta.json"


def figure_identity(work, image_id, figs=None):
    """Current declared identity, checked against the saved image bytes."""
    figs = _figures(work, figs)
    entry = figs.entry(_local_name(image_id))
    actual = figs.identity(entry)
    if not identity_matches(entry, actual):
        raise ValueError("The saved image does not match its manifest identity.")
    return actual


def figure_reusable(work, image_id, figs=None):
    """Only a non-empty transcription with matching app metadata can be
    reused; the .txt is the whole worker output."""
    try:
        return (_figure_text_valid(work, image_id)
                and identity_matches(_read_json(figure_metadata(work, image_id)),
                                     figure_identity(work, image_id, figs)))
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return False


def _figure_receipts(work):
    try:
        data = _read_json(Path(work) / "figure_requests.json")
        if isinstance(data, dict):
            return data
    except (OSError, ValueError):
        pass
    return {}


def invalidate_figure_requests(work):
    """A deliberate reset ends all outstanding worker acceptance rights."""
    (Path(work) / "figure_requests.json").unlink(missing_ok=True)


def accept_figure_outputs(work, image_ids, figs=None):
    """Certify only valid transcriptions for an active, still-current app
    dispatch."""
    receipts = _figure_receipts(work)
    accepted = []
    for image_id in dict.fromkeys(image_ids):
        expected = receipts.get(image_id)
        if expected is None or not _figure_text_valid(work, image_id):
            continue
        try:
            actual = figure_identity(work, image_id, figs)
            if not identity_matches(expected, actual):
                continue
            _write_json(figure_metadata(work, image_id), actual)
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            continue
        accepted.append(image_id)
        del receipts[image_id]
    if accepted:
        _write_json(Path(work) / "figure_requests.json", receipts)
    return accepted


def prepare_figure_receipts(work, image_ids, figs=None):
    """Grant a worker each picture that is not reusable: archive its
    obsolete files, then record its identity as the receipt the returned
    transcription is certified against. images.json and
    figure_requests.json are written once for the whole list."""
    work = Path(work)
    figs = _figures(work, figs)
    receipts = _figure_receipts(work)
    history = work / "history" / uuid.uuid4().hex / "image_text"
    granted = declared = False
    for image_id in dict.fromkeys(image_ids):
        if figure_reusable(work, image_id, figs):
            continue
        for path in (figure_output(work, image_id), figure_metadata(work, image_id)):
            if not path.exists():
                continue
            target = history / path.name
            if (not path.is_file() or path.is_symlink()
                    or not path.resolve().is_relative_to(work.resolve())
                    or not target.resolve().is_relative_to(work.resolve())):
                raise ValueError("A figure output is not a regular file inside the work directory.")
            history.mkdir(parents=True, exist_ok=True)
            replace_with_retry(path, target)
        entry = figs.entry(image_id)
        actual = figs.identity(entry)
        # Work images can change between calls. Only a new dispatch updates
        # the app-owned declaration; the old receipt is never certified
        # against it.
        if entry.get("sha256") != actual["sha256"]:
            entry["sha256"] = actual["sha256"]
            declared = True
        receipts[image_id] = actual
        granted = True
    if declared:
        _write_json(work / "images.json", figs.manifest)
    if granted:
        _write_json(work / "figure_requests.json", receipts)


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


def read_transcriptions(work: str, manifest: dict, figs=None):
    """({image_id: cleaned text}, [ids with nothing saved])."""
    figs = FigureSet(work, manifest) if figs is None else figs
    found, missing = {}, []
    for entry in manifest.get("images", []):
        path = transcription_path(work, entry["id"])
        if not figure_reusable(work, entry["id"], figs):
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


def run_merge(folder: str, figs=None):
    """Fold every saved transcription into corpus.json. `figs` is the
    calling stage's FigureSet (its manifest and hashes are reused).

    Returns {"added", "missing", "record"}, or None when the documents have
    not been extracted yet (no corpus.json / images.json).
    """
    work = os.path.join(os.path.abspath(folder), "output", ".work")
    corpus_path = os.path.join(work, "corpus.json")
    manifest_path = os.path.join(work, "images.json")
    if not (os.path.exists(corpus_path) and os.path.exists(manifest_path)):
        return None

    with open(corpus_path, encoding="utf-8") as fh:
        corpus = json.load(fh)
    if figs is None or figs.error is not None:
        figs = FigureSet(work)
    manifest = figs.manifest

    transcriptions, missing = read_transcriptions(work, manifest, figs)
    before = len(corpus.get("extraction", {}).get("images_merged", []))
    merge(corpus, manifest, transcriptions)
    record = corpus["extraction"]

    with open(corpus_path, "w", encoding="utf-8") as fh:
        json.dump(corpus, fh, ensure_ascii=False, indent=2)
    return {"added": len(record["images_merged"]) - before,
            "missing": missing, "record": record}
