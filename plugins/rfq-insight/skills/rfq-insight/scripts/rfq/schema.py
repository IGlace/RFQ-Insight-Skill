"""RFQ Insight slide-plan and analysis schemas.

This is the production contract between the LLM pipeline and the deterministic
renderer (`rfq_insight.renderer`). It is a superset of the legacy contract in
``render_deck.py`` (no longer exposed over HTTP, but still the shape its
sample plan uses): same seven content layouts, plus the three diagram layouts
the RFQ Insight template uses (`phases`, `collab`, `ownership`), a `confidence`
attached by the app layer, an `oppId`, and no `mode` field.
"""

from typing import Annotated, Literal, Union

from pydantic import (BaseModel, ConfigDict, Field, StrictInt, TypeAdapter,
                      model_validator)


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
# break `rfq_run.py render` replay. Only the diagram layouts (timeline/gantt/phases/
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


class PercentItem(StrictModel):
    name: str                 # an official Guidance product / skill name
    percent: int


class OpportunityInfo(StrictModel):
    """Section 1 as structured data (client format 18.09.2026). The deck's
    Opportunity Info slide is built from this object, never by a model.
    account_name / kam_pte are filled by the app layer from the Salesforce
    account list; stage 1 always writes "Info not available".
    customer_site is not shown on the slide: it is the city of the
    customer's own address, used only to pick the right account."""
    customer: str
    customer_site: str = "Info not available"
    customer_contact: str
    quotation_due_date: str
    customer_short: str
    project_title: str
    opportunity_name: str          # "<customer_short> – <project_title>"
    account_name: str = "Info not available"
    kam_pte: str = "Info not available"
    project_type: str
    lead_product: str
    technology: str
    industry: str
    products: list[PercentItem]
    skills: list[PercentItem]


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
    # Set by the app layer, never by the model: an Additional Information
    # slide names its own follow-up's sources instead of the section's line.
    sourceLine: str | None = None

    # Complete references in the notes of this follow-up and its continuations.
    sourceDetails: str | None = None


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


class PictureItem(StrictModel):
    imageId: str
    caption: str
    source: str
    file: str | None = None
    sha256: str | None = None


class PicturesSlide(StrictModel):
    """Product pictures copied from the RFQ. Built by the application layer
    (rfq/delivery.py) from the figure workers' classifications, never by the
    slide-plan model."""
    layout: Literal["pictures"]
    title: str
    pictures: list[PictureItem]
    # Set by the app layer: names exactly the pictures on this slide.
    sourceLine: str | None = None


class OpportunitySlide(StrictModel):
    """The Opportunity Info slide: main table + Products (%) + Skills (%).
    The slide-plan model emits only layout + title; rfq/delivery.py fills the
    rest from the analysis' `opportunity` object."""
    layout: Literal["opportunity"]
    title: str
    columns: list[str] = []
    rows: list[list[str]] = []
    products: list[list[str]] = []
    skills: list[list[str]] = []


Slide = Annotated[
    Union[
        BulletsSlide, TableSlide, TwoColumnSlide, PanelSlide, ProsConsSlide,
        TimelineSlide, GanttSlide, KpiSlide, ProseSlide,
        PhasesSlide, CollabSlide, OwnershipSlide, PicturesSlide,
        OpportunitySlide,
    ],
    Field(discriminator="layout"),
]


class Question(StrictModel):
    number: StrictInt
    titleEn: str
    titleDe: str
    slides: list[Slide]
    # Attached by the app layer AFTER the slide-plan call (from the stage-1
    # answer), never emitted by the model. Rendered as a chip on every slide.
    confidence: str | None = None
    # Attached by rfq/delivery.py (rfq/verification.py): the rating explained,
    # written into the notes of the first slide of the section.
    confidenceNotes: str | None = None
    # Attached by the app layer (rfq/delivery.py via rfq.sources.attach_sources),
    # never emitted by the model. Retained for saved-report compatibility.
    sourceLine: str | None = None

    # Complete references for every content slide's speaker notes.
    sourceDetails: str | None = None


class SlidePlan(StrictModel):
    projectName: str
    oppId: str | None = ""
    date: str
    questions: list[Question]

    @model_validator(mode="after")
    def unique_canonical_sections(self):
        errors = section_number_errors(
            [question.number for question in self.questions], allow_additional=True)
        if errors:
            raise ValueError(" ".join(errors))
        return self


# ------------------------------------------------- structured-output schemas
# What the two model calls must return. `date`/`oppId` are stamped by the
# pipeline, so the stage-2 draft has no date field.
class SourceRef(StrictModel):
    """Where an answer comes from: a corpus file and a location inside it
    ("p. 12", "slide 3", "sheet 'Plan'", "section 3.2 Timing" or "")."""
    filename: str
    locator: str = ""


class AnswerItem(StrictModel):
    id: int
    answer: str
    tldr: str = ""
    not_found: bool = False
    confidence: str = ""
    confidence_reason: str = ""      # shown in the slide notes (finalize.py)
    sources: list[SourceRef] = []
    # Optional lossless presentation produced with the analysis. Older prose
    # checkpoints keep using the slide worker. Forward reference avoids adding
    # a second copy of the flat slide schema to the analysis grammar.
    presentation: "PresentationContent | None" = None


class AnalysisResult(StrictModel):
    answers: list[AnswerItem]
    opportunity: OpportunityInfo | None = None


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
    products: list[list[str]] | None = None
    skills: list[list[str]] | None = None


class PresentationContent(StrictModel):
    """Flat API grammar, validated against the strict layout union first.

    Validating the raw input prevents LooseSlide's permissive scalar coercion
    from hiding malformed typed data (for example hw="false"). Coverage of
    the authoritative answer is checked by planning.deterministic_plan.
    """
    slides: list[LooseSlide]

    @model_validator(mode="before")
    @classmethod
    def strict_layout_fields(cls, value):
        if isinstance(value, dict) and isinstance(value.get("slides"), list):
            adapter = TypeAdapter(Slide)
            for raw in value["slides"]:
                if isinstance(raw, dict):
                    slide = {key: item for key, item in raw.items()
                             if item is not None}
                    slide.setdefault("title", "")
                    adapter.validate_python(slide, strict=True)
        return value


AnswerItem.model_rebuild()
AnalysisResult.model_rebuild()


class LooseQuestion(StrictModel):
    number: StrictInt
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
# Order = deck order (client format 18.09.2026). references/sections.md and the
# two prompts repeat this table; the test suite fails if the two ever disagree.
TITLES = {
    1: ("Opportunity Info", "Opportunity-Informationen"),
    2: ("Description", "Beschreibung"),
    3: ("Technical Product Definitions and Targets",
        "Technische Produktdefinitionen und Ziele"),
    4: ("Application Approach", "Anwendungsansatz"),
    5: ("Collaboration Approach", "Kooperationsansatz"),
    6: ("Development Phases", "Entwicklungsphasen"),
    7: ("Scope of Work and Responsibilities",
        "Leistungsumfang und Verantwortlichkeiten"),
    8: ("AVL Deliverables", "AVL-Liefergegenstände"),
    9: ("Timing", "Terminplanung"),
    10: ("Customer Specific Standards", "Kundenspezifische Normen"),
    11: ("Risk Detection", "Risikoerkennung"),
    12: ("Source Material", "Quellenmaterial"),
}
SECTION_IDS = tuple(TITLES)          # (1, ..., 12)
OPPORTUNITY, DESCRIPTION, TECHNICAL, APPLICATION, COLLABORATION, PHASES, \
    SCOPE, DELIVERABLES, TIMING, STANDARDS, RISKS, SOURCES = SECTION_IDS

# Optional extra section (follow-up answers, Plan 4). Rendered BEFORE
# Source Material; never part of the model contract above.
ADDITIONAL_INFO_ID = 13
ADDITIONAL_INFO_TITLE = ("Additional Information", "Zusätzliche Informationen")

# The slide shapes each canonical section may take, as layout tuples in slide
# order. The deck stays one slide per section wherever the content allows it,
# so a section's plan may never carry a slide the shape below does not name -
# that is how "Timing — TIMING BASIS" and "Scope of Work — HORSE Review
# Inputs" reached a client deck (client feedback 14.10.2026).
#
# This is a PLAN-level contract, not a rendered-page count. A long table or
# risk panel still paginates at draw time; the renderer owns those "(cont.)"
# pages and they are not slides the model may write.
SECTION_SHAPES = {
    OPPORTUNITY: (("opportunity",),),
    DESCRIPTION: (("prose",), ("prose", "prose")),
    TECHNICAL: (("table",),),
    APPLICATION: (("table",),),
    COLLABORATION: (("collab",),),
    PHASES: (("phases",), ("table",)),
    SCOPE: (("ownership",),),
    DELIVERABLES: (("table",),),
    TIMING: (("gantt", "table"), ("timeline", "table")),
    STANDARDS: (("table",), ("bullets",)),
    RISKS: (("panel", "panel"),),
    SOURCES: (("table",), ("bullets",)),
}


# Every canonical section has a shape; a new id must add one rather than
# silently matching nothing.
assert set(SECTION_SHAPES) == set(SECTION_IDS)


def describe_shapes(number) -> str:
    """The permitted shapes of one section, for a repair message."""
    return " or ".join(" + ".join(shape)
                       for shape in SECTION_SHAPES[number])


def section_number_errors(numbers, allow_additional=False):
    if any(type(number) is not int for number in numbers):
        return ["Section numbers must be integers."]
    repeated = sorted({number for number in numbers if numbers.count(number) > 1})
    if repeated:
        return ["Duplicate section number(s): " + ", ".join(map(str, repeated))]
    expected = list(SECTION_IDS)
    if ADDITIONAL_INFO_ID in numbers and allow_additional:
        expected.insert(expected.index(SOURCES), ADDITIONAL_INFO_ID)
    if numbers != expected:
        return ["Sections must appear once each in the canonical order"
                + ("; Additional Information may appear before Source Material."
                   if allow_additional else ".")]
    return []
