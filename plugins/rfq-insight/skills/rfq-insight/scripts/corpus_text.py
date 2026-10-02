#!/usr/bin/env python3
"""Render the corpus as the delimited text the prompts describe.

    python corpus_text.py "C:/RFQs/Acme V6"
    python corpus_text.py "C:/RFQs/Acme V6" --out corpus.txt

Reads  .work/corpus.json
Prints (or writes) one `=== FILE: <name> ===` block per document.

This is not presentation. It is a contract the prompts state and depend on:

  * RFQ_QA_Extraction_Prompt_v12.md line 30 tells the model the corpus is
    delimited by `=== FILE: <name> ===` lines and to use content from ALL
    of them;
  * line 101 requires every `evidence_files` entry be a name "copied
    EXACTLY from a `=== FILE: === ` header";
  * the verifier prompt reads the same corpus and applies the same rule.

The container app built these blocks in pipeline.py and fed the model the
result. Handing the model raw corpus.json instead leaves both of those
instructions pointing at something that does not exist, which undermines
the determinism clause (v12 line 22) as much as the evidence rule. The
block format below is carried over from pipeline._format_corpus unchanged,
so the text the model reads is the text it read before.

`merge_image_text.py` folds image transcriptions into `extracted_text`
before this runs, so a transcribed chart appears inside its parent file's
block - which is what keeps `evidence_files` naming the parent.
"""

import argparse
import json
import os
import sys


# Hosts hand the corpus to a worker through a file-reading tool, and such
# tools cut a line off after roughly 2 000 characters. A long paragraph or a
# wide pipe-table row from a native extraction easily runs past that, and the
# cut is silent: the worker never learns that the end of the line is missing.
# Wrapping at whitespace below that limit keeps every character readable.
# Nothing is added or removed except the line break, which is content-neutral
# for prose and leaves a table row readable in context.
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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Print the corpus as delimited === FILE: === blocks.")
    ap.add_argument("folder", help="the folder holding the RFQ package")
    ap.add_argument("--out", default=None,
                    help="write to this file instead of printing")
    args = ap.parse_args(argv)

    corpus_path = os.path.join(os.path.abspath(args.folder), "output",
                               ".work", "corpus.json")
    if not os.path.exists(corpus_path):
        print("I haven't read the documents yet - there's nothing to show.",
              file=sys.stderr)
        return 2

    with open(corpus_path, encoding="utf-8") as fh:
        corpus = json.load(fh)
    text = format_corpus(corpus.get("filesContents", []))

    if args.out:
        out_path = os.path.abspath(args.out)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"Wrote {len(corpus.get('filesContents', []))} document(s), "
              f"{len(text):,} characters, to {out_path}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
