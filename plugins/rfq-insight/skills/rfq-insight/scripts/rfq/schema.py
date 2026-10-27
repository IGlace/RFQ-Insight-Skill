"""RFQ Insight slide-plan and analysis schemas.

This is the production contract between the LLM pipeline and the deterministic
renderer (`rfq_insight.renderer`). It is a superset of the legacy contract in
``render_deck.py`` (no longer exposed over HTTP, but still the shape its
sample plan uses): same seven content layouts, plus the three diagram layouts
the RFQ Insight template uses (`phases`, `collab`, `ownership`), a `confidence`
attached by the app layer, an `oppId`, and no `mode` field.
"""

from dataclasses import dataclass
from typing import Annotated, Literal, Union

from pydantic import (BaseModel, ConfigDict, Field, StrictInt,
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
    customer_site is not shown on the slide: it is the customer's own full
    postal address as the RFQ states it, used only to pick the right
    account."""
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
    """Product pictures copied from the RFQ. Retired from client decks:
    rfq/delivery.py strips any such slide; the layout stays so an older
    saved plan still validates and replays."""
    layout: Literal["pictures"]
    title: str
    pictures: list[PictureItem]
    # Set by the app layer: names exactly the pictures on this slide.
    sourceLine: str | None = None


class OpportunitySlide(StrictModel):
    """The Opportunity Info slide: the identity table of facts read from the
    RFQ. The slide-plan model emits only layout + title; rfq/delivery.py fills
    the rest from the analysis' `opportunity` object.

    `products` / `skills` moved to SplitSlide (client requirement,
    15.10.2026) and stay here, always empty, only so that already-saved run
    reports still validate against this extra="forbid" model."""
    layout: Literal["opportunity"]
    title: str
    columns: list[str] = []
    rows: list[list[str]] = []
    products: list[list[str]] = []
    skills: list[list[str]] = []


class SplitSlide(StrictModel):
    """Products (%) and Skills (%) on their own slide, with their OWN
    confidence - normally Low, because the split is an estimate the RFQ does
    not state. Keeping it off the Opportunity Info slide is the point: an
    estimated number must not borrow the rating earned by the customer's
    legal name (client requirement, 15.10.2026).

    The per-slide confidence fields override the question's for this slide
    only; rfq/renderer.py::create_presentation applies them."""
    layout: Literal["split"]
    title: str
    products: list[list[str]] = []
    skills: list[list[str]] = []
    confidence: str | None = None
    confidenceNotes: str | None = None
    score: int | None = None
    deductions: list[dict] | None = None


Slide = Annotated[
    Union[
        BulletsSlide, TableSlide, TwoColumnSlide, PanelSlide, ProsConsSlide,
        TimelineSlide, GanttSlide, KpiSlide, ProseSlide,
        PhasesSlide, CollabSlide, OwnershipSlide, PicturesSlide,
        OpportunitySlide, SplitSlide,
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
    # Attached by rfq/delivery.py (rfq/confidence.py): the 1-10 score and the
    # resolved deductions behind it (run report only, never drawn).
    score: int | None = None
    deductions: list[dict] | None = None
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


class Deduction(StrictModel):
    """One catalogue rule the model applies to its own answer: the code
    (schema.RULES), how many items it covers, the items themselves and the
    file or clause they rest on. Points are computed by rfq/confidence.py,
    never written by the model."""
    rule: str
    count: int = Field(default=1, ge=1)
    items: str = ""
    basis: str = ""


class Shown(StrictModel):
    """How many items a trimmed answer found and how many it shows."""
    found: int
    shown: int


class AnswerItem(StrictModel):
    """One section's answer (CONTRACT section 2): the markdown, whether it
    was found, its sources, the model's deductions and, for a trimmed
    list, how many items it shows."""
    id: int
    answer: str
    not_found: bool = False
    sources: list[SourceRef] = []
    deductions: list[Deduction] = []
    shown: Shown | None = None


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
    # SplitSlide's per-slide confidence override (filled by the app layer,
    # never by the model; present so a saved report re-validates).
    confidence: str | None = None
    confidenceNotes: str | None = None
    score: int | None = None
    deductions: list[dict] | None = None


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

# ---------------------------------------------------------- confidence rules
# How each section's content is obtained. An extracted section copies what
# the documents state; an analysed one reasons over them; Source Material is
# built by Python. Additional Information (13) declares its mode per answer.
SECTION_MODES = {
    OPPORTUNITY: "mixed", DESCRIPTION: "analysed", TECHNICAL: "extracted",
    APPLICATION: "extracted", COLLABORATION: "extracted",
    PHASES: "extracted", SCOPE: "extracted", DELIVERABLES: "extracted",
    TIMING: "extracted", STANDARDS: "extracted", RISKS: "analysed",
    SOURCES: "python",
}
EXTRACTED_SECTIONS = tuple(number for number, mode in SECTION_MODES.items()
                           if mode == "extracted")      # (3, ..., 10)
assert set(SECTION_MODES) == set(SECTION_IDS)


@dataclass(frozen=True)
class Rule:
    """One confidence deduction. `points` are per count, unless `tiers`
    ((up_to_count, points), ...; the last bound None) set them; `cap` is the
    most one section loses to this code, None for a once-rule (fixed points
    whatever the count). `sections` is a tuple of ids or "all" (every
    scored section: 1-11 and 13; Source Material has no rules).
    `source` says who writes it: "model", or "python" (the runner). `mode`
    limits a rule to Additional Information answers of that mode.

    `kind` is the PROVENANCE the rule records, and it caps the SCORE
    (rfq/confidence.py::SCORE_CEILING) so that the number and the band word
    can never disagree:
      "decided"  - the fact IS in the RFQ, but it was unclear or contradictory
                   and the analysis settled it. Score ceiling: 6 (Medium).
      "inferred" - the analysis supplied content the RFQ does not state.
                   Score ceiling: 6 (Medium), or 3 (Low) when `dominant`.
      None       - not a provenance statement at all (V1/V3 are reliability
                   failures), so it moves the score but never the ceiling.
    `dominant` marks an inference the whole slide rests on - a percentage
    split nobody stated, say - which forces Low however small the deduction.
    `plain` is the six-word phrase the hidden methodology slide prints; every
    model rule needs one (see the assert below)."""
    code: str
    label: str
    points: int
    cap: int | None
    sections: tuple | str
    source: str
    tiers: tuple | None = None
    mode: str | None = None
    kind: str | None = None
    dominant: bool = False
    plain: str = ""

    @property
    def once(self) -> bool:
        return self.cap is None


# Only content not taken from the RFQ costs points (client decision): an
# inference, an estimate, a reviewer's refutation, a corpus miss. Honest
# reporting of a gap, a contradiction or an evidence limit never does.
# Section 1 is scored by the same rules: an identity field the RFQ does not
# state is tagged (inferred) under G3.
#
# MISSING INFORMATION IS NEVER PENALISED (client requirement, 15.10.2026).
# A confirmed absence scores 10/10 High: the confidence rating measures how
# reliably the RFQ was READ, not how complete the RFQ IS. A field correctly
# reported as "Info not available" is a successful extraction. V3 ("not found
# in the corpus") is not a counter-example - it penalises content that could
# not be traced back to the documents, i.e. UNVERIFIABLE text, never missing
# RFQ information.
_FACTS_AND_13 = (OPPORTUNITY, *EXTRACTED_SECTIONS, ADDITIONAL_INFO_ID)
_RULE_ROWS = (
    Rule("G3", "{count} inferred item(s)", 1, 4, _FACTS_AND_13, "model",
         mode="extracted", kind="inferred", plain="some items inferred"),
    Rule("V1", "refuted by the reviewer", 4, 8, "all", "python"),
    Rule("V3", "not found in the corpus", 3, 6, _FACTS_AND_13, "python"),
    Rule("S2.1", "{count} sentence(s) rest on no stated fact",
         2, 6, (DESCRIPTION, ADDITIONAL_INFO_ID), "model", mode="analysed",
         kind="inferred", plain="sentences rest on no stated fact"),
    Rule("S3.1", "{count} value(s) estimated or converted",
         2, 6, (TECHNICAL,), "model",
         kind="decided", plain="values converted or estimated"),
    Rule("S5.2", "{count} role(s) or interface(s) inferred",
         1, 3, (COLLABORATION,), "model",
         kind="inferred", plain="roles or interfaces inferred"),
    Rule("S6.1", "phase names assigned by the analysis (RFQ names none)",
         3, None, (PHASES,), "model",
         kind="inferred", dominant=True, plain="RFQ names no phases"),
    Rule("S6.2", "calendar spans derived, not stated",
         1, None, (PHASES,), "model",
         kind="inferred", plain="calendar spans derived"),
    Rule("S6.3", "garbled timing chart; phase membership reconstructed",
         2, None, (PHASES,), "model",
         kind="inferred", plain="timing chart unreadable, rebuilt"),
    Rule("S7.1", "{count} cell(s) placed by inference", 0, 4, (SCOPE,),
         "model", tiers=((3, 1), (8, 2), (None, 4)),
         kind="inferred", plain="task ownership worked out"),
    Rule("S7.2", "{count} RASIC conflict(s) resolved to one executing party",
         1, 3, (SCOPE,), "model",
         kind="decided", plain="conflicting owners settled"),
    Rule("S7.3", "owner propagated across phases for a deliverable-bound "
         "task", 2, None, (SCOPE,), "model",
         kind="inferred", plain="owner carried across phases"),
    Rule("S8.1", "{count} entailed deliverable(s)",
         1, 3, (DELIVERABLES,), "model",
         kind="inferred", plain="deliverables implied, not listed"),
    Rule("S8.2", "phase placement inferred",
         1, None, (DELIVERABLES,), "model",
         kind="inferred", plain="phase placement inferred"),
    Rule("S9.1", "{count} label-date pairing(s) corrected by dependency "
         "logic", 2, 4, (TIMING,), "model",
         kind="decided", plain="mismatched dates corrected"),
    Rule("S9.2", "milestone-phase links inferred",
         1, None, (TIMING,), "model",
         kind="inferred", plain="milestone-phase links inferred"),
    Rule("S10.1", "{count} designation(s) completed from context",
         2, 4, (STANDARDS,), "model",
         kind="decided", plain="partial standard names completed"),
    Rule("S10.2", "{count} standard(s) referenced only indirectly",
         1, 2, (STANDARDS,), "model",
         kind="inferred", plain="standards referenced indirectly"),
    Rule("S11.1", "{count} risk(s) without a locatable trigger",
         2, 6, (RISKS,), "model",
         kind="inferred", plain="risks without a stated trigger"),
    Rule("S11.2", "schedule-feasibility answer rests on no stated date",
         3, None, (RISKS,), "model",
         kind="inferred", plain="schedule judged without dates"),
    # Section 1's percentage split, scored on its own slide. P1 is the normal
    # case and is deliberately `dominant`: a split nobody stated is an AI
    # estimate, and Low is the correct, expected rating for it.
    Rule("P1", "percentage split estimated by the analysis (the RFQ states "
         "none)", 4, None, (OPPORTUNITY,), "model",
         kind="inferred", dominant=True, plain="split estimated, RFQ states none"),
    Rule("P2", "percentage split derived from proportions the RFQ states",
         2, None, (OPPORTUNITY,), "model",
         kind="inferred", plain="split derived from stated proportions"),
)
RULES = {rule.code: rule for rule in _RULE_ROWS}
_ALL_SECTIONS = (*SECTION_IDS, ADDITIONAL_INFO_ID)
# Source Material is built by Python from the read log and always scores
# 10/10; its Read column still says what was read only in part or skipped.
_SCORED_SECTIONS = tuple(number for number in _ALL_SECTIONS
                         if number != SOURCES)


def rule_sections(rule: Rule) -> tuple:
    """The section ids a rule may be applied to."""
    return _SCORED_SECTIONS if rule.sections == "all" else rule.sections


def rule_applies(rule: Rule, section_id, mode=None) -> bool:
    """True if `rule` may stand in `section_id` (for Additional Information,
    an answer of `mode`), whoever writes it."""
    if section_id not in rule_sections(rule):
        return False
    return (section_id != ADDITIONAL_INFO_ID or rule.mode is None
            or rule.mode == mode)


def rules_for(section_id, mode=None) -> list:
    """The rules a MODEL may use for one section, in catalogue order (none
    for Source Material). For Additional Information pass the answer's
    mode."""
    return [rule for rule in _RULE_ROWS
            if rule.source == "model" and rule_applies(rule, section_id, mode)]


def rule_points(rule: Rule, count) -> int:
    """Points one entry of `count` items costs, within the rule's cap."""
    if rule.once:
        return rule.points
    if rule.tiers:
        raw = next(points for bound, points in rule.tiers
                   if bound is None or count <= bound)
    else:
        raw = rule.points * count
    return min(raw, rule.cap)


assert all(set(rule_sections(rule)) <= set(_SCORED_SECTIONS)
           for rule in _RULE_ROWS)
assert len(RULES) == len(_RULE_ROWS)
assert all(rules_for(number) for number in SECTION_IDS if number != SOURCES)
assert not any(SOURCES in rule_sections(rule) for rule in _RULE_ROWS)
assert all(rules_for(ADDITIONAL_INFO_ID, mode)
           for mode in ("extracted", "analysed"))
# Provenance and the methodology slide's wording are part of the contract: a
# new model rule must say what kind of claim it records and how to say it in
# plain words, or the hidden slide would silently omit it.
assert all(rule.kind in ("decided", "inferred") and rule.plain
           for rule in _RULE_ROWS if rule.source == "model")
assert all(rule.kind is None for rule in _RULE_ROWS if rule.source == "python")

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
    # Both stages of section 1: the model writes the `opportunity`
    # placeholder alone (it never authors this section), and
    # rfq/opportunity.py fills it as TWO slides - the facts, then the
    # estimated percentage split carrying its own (normally Low) rating.
    # validation.check_plan pins the model to the first shape and
    # check_final_opportunity pins the finished deck to the second.
    OPPORTUNITY: (("opportunity",), ("opportunity", "split")),
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
