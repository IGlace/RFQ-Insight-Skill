"""Which unpacked images earn a visual read, and where they go.

A timing chart pasted into SOR.docx was OCR'd by the old system - badly,
but present - and the Timing section depends on that content. Native
parsing would skip it silently, so every embedded picture is unpacked.

Most of them are not content: a logo in a header, a rule, an icon repeated
on every page. Filtering keeps the visual pass proportionate to the value.
Everything dropped is listed in the run report, so nothing disappears
untraced.

The four constants below are the tuning surface. They are deliberately
conservative: a missed chart is a wrong answer, a transcribed logo is a
few wasted seconds.
"""

import hashlib
import io
import os

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


def image_pixels(data: bytes) -> int:
    """Pixel count, or 0 when the bytes are not a readable image."""
    from PIL import Image
    try:
        with Image.open(io.BytesIO(data)) as handle:
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
        if len(kept) >= max_flagged:
            dropped.append(_drop(img, "cap_reached", f"limit is {max_flagged}"))
            continue
        seen.add(digest)
        kept.append(img)
    return kept, dropped


def write_images(kept, dropped, images_dir: str) -> dict:
    """Save every kept image and build the manifest for the visual pass."""
    os.makedirs(images_dir, exist_ok=True)
    entries = []
    for img in kept:
        ext = img.ext if img.ext in (".png", ".jpg", ".jpeg") else ".png"
        name = img.image_id + ext
        with open(os.path.join(images_dir, name), "wb") as fh:
            fh.write(img.data)
        entries.append({
            "id": img.image_id,
            "file": name,
            "source": img.source,
            "locator": img.locator,
            "kind": "standalone" if img.locator == "standalone" else "embedded",
        })
    return {"images": entries, "filtered": list(dropped)}
