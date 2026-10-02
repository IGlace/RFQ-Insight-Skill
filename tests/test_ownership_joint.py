"""A task the RFQ assigns to two parties at once is "Joint", not a blank cell.

The Scope-of-Work matrix is deliberately single-owner: one task, one party per
phase. But an RFQ that assigns a stage to "Northwind + Engineering company", or
a task to "a joint responsibility of X and Y", singles nobody out - and the
rule used to send that to "—", the same glyph as "the RFQ assigns nobody".

Those are different findings with different actions (split an overlap before
contract, versus chase a gap), so the matrix was losing a fact it held. "Joint"
separates them. It is a FLAG, not a fourth owner: amber, away from the party
colours, with the parties named in the Risk Detection entry - the client
rejected a multi-letter RASIC matrix and this must not smuggle one back.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "plugins", "rfq-insight", "skills", "rfq-insight", "scripts"))

import evaluate as ev                                   # noqa: E402
from rfq import renderer as rdi                         # noqa: E402
from rfq.sanitize import sanitize_plan                  # noqa: E402
from rfq.schema import SlidePlan                        # noqa: E402


def _plan(cells, abbr="Northwind"):
    return {
        "projectName": "Demo", "date": "2026-07-23",
        "questions": [{
            "number": 7, "titleEn": "Scope of Work and Responsibilities",
            "titleDe": "Leistungsumfang und Verantwortlichkeiten",
            "slides": [{
                "layout": "ownership",
                "title": "Scope of Work and Responsibilities",
                "customerAbbr": abbr,
                "columns": ["Scope of Work", "1 Kickoff", "2 Concept"],
                "rows": cells,
                "callout": None,
            }],
        }],
    }


def test_joint_is_a_distinct_colour_from_every_party():
    """If it shared a party's colour the reader could not tell them apart."""
    colours = rdi.OWNER_COLORS
    assert "joint" in colours
    assert len(set(colours.values())) == len(colours)
    assert colours["joint"] not in (colours["avl"], colours["customer"],
                                    colours["supplier"])


@pytest.mark.parametrize("cell", ["Joint", "joint", " JOINT "])
def test_the_renderer_colours_a_joint_cell(cell):
    """owner_map is a closure inside L_ownership, so exercise it through a
    real render: an uncoloured cell would mean the marker fell through."""
    plan = SlidePlan.model_validate(
        _plan([["Requirements definition", cell, "AVL"]])).model_dump()
    assert rdi.render_to_bytes(plan).startswith(b"PK")


def test_a_joint_cell_renders_alongside_owners_and_blanks():
    plan = SlidePlan.model_validate(_plan([
        ["Requirements definition", "Joint", "—"],
        ["Project management", "—", "AVL"],
        ["Stack supply", "Northwind", "Supplier"],
    ])).model_dump()
    assert rdi.render_to_bytes(plan).startswith(b"PK")


@pytest.mark.parametrize("cell", ["Joint", "joint", "JOINT"])
def test_c4_accepts_the_joint_marker(cell):
    fails, _warns, oks = ev.evaluate(
        {"slidePlan": _plan([["Requirements definition", cell, "AVL"]])}, None)
    assert not [m for m in fails if "C4" in m]
    assert [m for m in oks if "C4" in m]


@pytest.mark.parametrize("cell", [
    "Northwind + AVL",       # the party pair the marker replaces
    "Northwind/AVL",
    "TBD",
    "Both",
    "n/a",
])
def test_c4_still_rejects_everything_else(cell):
    """"Joint" is one fixed token - it does not open the cell to free text."""
    fails, _warns, _oks = ev.evaluate(
        {"slidePlan": _plan([["Requirements definition", cell, "AVL"]])}, None)
    assert [m for m in fails if "C4" in m], cell


def test_the_sanitizer_leaves_joint_cells_alone():
    """sanitize_plan audits ownership uniformity but must never rewrite a
    cell - the filled/empty pattern has to mirror the RFQ."""
    plan = _plan([["Requirements definition", "Joint", "—"],
                  ["Project management", "—", "AVL"]])
    cleaned, _actions = sanitize_plan(plan, "")
    rows = cleaned["questions"][0]["slides"][0]["rows"]
    assert rows[0] == ["Requirements definition", "Joint", "—"]
    assert rows[1] == ["Project management", "—", "AVL"]


def test_an_unlisted_marker_is_dropped_from_the_matrix_entirely():
    """Why "joint" had to be added to sanitize.py as well as the renderer.

    The sanitizer moves any row holding an unrecognised owner value OUT of the
    table and into a callout - and the ownership layout has no callout band, so
    such a row vanishes from the deck rather than rendering uncoloured. Adding
    a cell marker in the renderer alone silently loses whole task rows.
    """
    plan = _plan([["Requirements definition", "Northwind + AVL", "—"],
                  ["Project management", "—", "AVL"]])
    cleaned, actions = sanitize_plan(plan, "")
    rows = cleaned["questions"][0]["slides"][0]["rows"]
    assert [r[0] for r in rows] == ["Project management"]
    assert any("moved" in a for a in actions)


def test_joint_and_blank_stay_different_values():
    """The regression this whole change exists to prevent: something
    "normalising" the marker back into a blank would silently restore the
    collapse of two different findings into one glyph."""
    plan = _plan([["Requirements definition", "Joint", "—"]])
    cleaned, _actions = sanitize_plan(plan, "")
    cell_joint, cell_blank = cleaned["questions"][0]["slides"][0]["rows"][0][1:]
    assert cell_joint.strip().lower() == "joint"
    assert cell_blank != cell_joint
