"""RFQ Insight slide-plan and analysis schemas.

This is the production contract between the LLM pipeline and the deterministic
renderer (`rfq_insight.renderer`). It is a superset of the legacy contract in
``render_deck.py`` (no longer exposed over HTTP, but still the shape its
sample plan uses): same seven content layouts, plus the three diagram layouts
the RFQ Insight template uses (`phases`, `collab`, `ownership`), a `confidence`
attached by the app layer, an `oppId`, and no `mode` field.
"""

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ------------------------------------------------------------- slide elements
class BulletItem(StrictModel):
    text: str
    inferred: bool | None = None


class Callout(StrictModel):
    tag: str
    text: str


# NOTE — `callout` on the four DATA layouts (bullets/table/panel/ownership) is
# DEAD: the renderer ignores it and gives the whole slide height to the content
# (client requirement: notes and gaps belong in id 11 Risk Detection, not in a
# band stolen from the list). The stage-2 prompt no longer emits one. The field
# stays only because these are `extra="forbid"` models — dropping it would make
# every already-saved run report (which does carry callouts) fail validation and
# break `render_run.py` replay. Only the diagram layouts (timeline/gantt/phases/
# collab) still render theirs.


class KpiItem(StrictModel):
    value: str
    label: str
    unit: str | None = ""


class TimelineStep(StrictModel):
    label: str
    date: str
    desc: str


class GanttBar(StrictModel):
    name: str
    start: str = ""           # e.g. "2026/7/15", "Jul 2026", "Q3 2026"
    end: str = ""


class PhaseItem(StrictModel):
    name: str
    desc: str = ""
    hw: bool | None = None


class PartyItem(StrictModel):
    name: str
    role: str = ""
    type: str = ""            # customer | avl | supplier | third
    dashed: bool | None = None


# ------------------------------------------------------------------ layouts
class BulletsSlide(StrictModel):
    layout: Literal["bullets"]
    title: str
    bullets: list[BulletItem]
    callout: Callout | None = None


class TableSlide(StrictModel):
    layout: Literal["table"]
    title: str
    columns: list[str]
    rows: list[list[str]]
    callout: Callout | None = None


class TwoColumnSlide(StrictModel):
    layout: Literal["twoColumn"]
    title: str
    leftHeading: str
    leftItems: list[str]
    rightHeading: str
    rightItems: list[str]


class PanelSlide(StrictModel):
    """One full-width headed panel — a single item group per slide (the
    client-confirmed Risk Detection format: Project Risks and Document Risks
    each on their own slide)."""
    layout: Literal["panel"]
    title: str
    heading: str
    items: list[str]
    callout: Callout | None = None


class ProsConsSlide(StrictModel):
    layout: Literal["prosCons"]
    title: str
    pros: list[str]
    cons: list[str]


class TimelineSlide(StrictModel):
    layout: Literal["timeline"]
    title: str
    steps: list[TimelineStep]
    callout: Callout | None = None


class GanttSlide(StrictModel):
    """One-slide Gantt: proportional year/quarter time axis, the project (or
    per-phase) bar(s), and every milestone as a marker at its true position —
    the sales-preferred timing picture. Milestones whose dates cannot be
    parsed to a calendar position are disclosed in the callout instead."""
    layout: Literal["gantt"]
    title: str
    steps: list[TimelineStep]              # milestones (label/date/desc)
    bars: list[GanttBar] | None = None     # per-phase bars, when ranges known
    barLabel: str | None = None            # single project-bar label fallback
    callout: Callout | None = None


class KpiSlide(StrictModel):
    layout: Literal["kpi"]
    title: str
    kpis: list[KpiItem]


class ProseSlide(StrictModel):
    layout: Literal["prose"]
    title: str
    caption: str | None = None
    body: str


class PhasesSlide(StrictModel):
    layout: Literal["phases"]
    title: str
    phases: list[PhaseItem]
    callout: Callout | None = None


class CollabSlide(StrictModel):
    layout: Literal["collab"]
    title: str
    hub: str | None = None
    parties: list[PartyItem]
    callout: Callout | None = None


class OwnershipSlide(StrictModel):
    layout: Literal["ownership"]
    title: str
    customerAbbr: str | None = None
    columns: list[str]
    rows: list[list[str]]
    callout: Callout | None = None


Slide = Annotated[
    Union[
        BulletsSlide, TableSlide, TwoColumnSlide, PanelSlide, ProsConsSlide,
        TimelineSlide, GanttSlide, KpiSlide, ProseSlide,
        PhasesSlide, CollabSlide, OwnershipSlide,
    ],
    Field(discriminator="layout"),
]


class Question(StrictModel):
    number: int
    titleEn: str
    titleDe: str
    slides: list[Slide]
    # Attached by the app layer AFTER the slide-plan call (from the stage-1
    # answer), never emitted by the model. Rendered as a chip on every slide.
    confidence: str | None = None


class SlidePlan(StrictModel):
    projectName: str
    oppId: str | None = ""
    date: str
    questions: list[Question]


# ------------------------------------------------- structured-output schemas
# What the two model calls must return. `date`/`oppId` are stamped by the
# pipeline, so the stage-2 draft has no date field.
class EvidenceFile(StrictModel):
    filename: str


class AnswerItem(StrictModel):
    id: int
    answer: str
    tldr: str = ""
    not_found: bool = False
    confidence: str = ""
    evidence_files: list[EvidenceFile] = []


class AnalysisResult(StrictModel):
    answers: list[AnswerItem]


# The 10-type discriminated Slide union compiles into a constrained-decoding
# grammar too large for the API ("compiled grammar is too large"). For the
# structured slide-plan call we therefore parse against this FLAT schema
# (every layout field optional), then drop the unused (None) fields and
# re-validate with the strict SlidePlan union — same guarantees, small grammar.
class LooseSlide(StrictModel):
    layout: str
    title: str = ""
    bullets: list[BulletItem] | None = None
    callout: Callout | None = None
    columns: list[str] | None = None
    rows: list[list[str]] | None = None
    leftHeading: str | None = None
    leftItems: list[str] | None = None
    rightHeading: str | None = None
    rightItems: list[str] | None = None
    heading: str | None = None
    items: list[str] | None = None
    pros: list[str] | None = None
    cons: list[str] | None = None
    steps: list[TimelineStep] | None = None
    bars: list[GanttBar] | None = None
    barLabel: str | None = None
    kpis: list[KpiItem] | None = None
    caption: str | None = None
    body: str | None = None
    phases: list[PhaseItem] | None = None
    hub: str | None = None
    parties: list[PartyItem] | None = None
    customerAbbr: str | None = None


class LooseQuestion(StrictModel):
    number: int
    titleEn: str
    titleDe: str
    slides: list[LooseSlide]


class LoosePlanDraft(StrictModel):
    projectName: str
    questions: list[LooseQuestion]


def tighten_plan(loose: dict) -> dict:
    """LoosePlanDraft dump -> plan dict with unused None fields removed."""
    for q in loose.get("questions", []):
        q["slides"] = [{k: v for k, v in sl.items() if v is not None}
                       for sl in q.get("slides", [])]
    return loose


# ------------------------------------------------------------- canonical titles
# The app layer owns the section titles — the models never invent or vary them.
# Stage 1 is matched on "id" alone; stage 2 receives these verbatim.
TITLES = {
    1: ("Commercial Info", "Kommerzielle Informationen"),
    2: ("Source Material", "Quellenmaterial"),
    3: ("Summary", "Zusammenfassung"),
    4: ("Technical Product Definitions and Targets",
        "Technische Produktdefinitionen und Ziele"),
    5: ("Application Approach", "Anwendungsansatz"),
    6: ("Development Phases", "Entwicklungsphasen"),
    7: ("Scope of Work and Responsibilities",
        "Leistungsumfang und Verantwortlichkeiten"),
    8: ("AVL Deliverables", "AVL-Liefergegenstände"),
    9: ("Timing", "Terminplanung"),
    10: ("Customer Specific Standards", "Kundenspezifische Normen"),
    11: ("Risk Detection", "Risikoerkennung"),
}
