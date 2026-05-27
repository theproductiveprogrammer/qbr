from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

Confidence = Literal["high", "med", "low"]
EvidenceId = str
GoalId = str
Status = Literal["complete", "insufficient_data", "failed"]

SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


class TranscriptLocator(BaseModel):
    kind: Literal["transcript"]
    file: str
    line_start: int
    line_end: int
    timestamp: str


class UsageLocator(BaseModel):
    kind: Literal["usage"]
    column: str


class EmailLocator(BaseModel):
    kind: Literal["email"]
    file: str
    line_start: int
    line_end: int


Locator = Annotated[
    TranscriptLocator | UsageLocator | EmailLocator,
    Field(discriminator="kind"),
]


class Evidence(BaseModel):
    id: EvidenceId
    source: Literal["transcript", "usage", "email"]
    locator: Locator
    quote: str
    context_before: str | None = None
    context_after: str | None = None


class Goal(BaseModel):
    id: GoalId
    statement: str
    category: str
    confidence: Confidence
    evidence_ids: list[EvidenceId]


class WorkingItem(BaseModel):
    feature: str
    summary: str
    signal: str
    confidence: Confidence
    evidence_ids: list[EvidenceId]


class Gap(BaseModel):
    id: str
    feature: str
    severity: int = Field(ge=0, le=100)
    goal_links: list[GoalId]
    summary: str
    recommended_action: str
    confidence: Confidence
    evidence_ids: list[EvidenceId]


class Opportunity(BaseModel):
    id: str
    product: str
    fit_score: int = Field(ge=0, le=100)
    goal_links: list[GoalId]
    rationale: str
    signals: list[str]
    confidence: Confidence
    evidence_ids: list[EvidenceId]


class DeckOutline(BaseModel):
    goals: list[str]
    performance: list[str]
    gaps: list[str]
    recommendations: list[str]


class ConfidenceSummary(BaseModel):
    high: int
    med: int
    low: int


class ReviewBanner(BaseModel):
    severity: Literal["info", "warning"]
    message: str


class Brief(BaseModel):
    account_id: str
    account_name: str
    vertical: str
    run_id: str
    generated_at: str
    pipeline_version: str

    status: Status
    status_reason: str | None = None

    review_banner: ReviewBanner | None = None
    confidence_summary: ConfidenceSummary

    goals: list[Goal]
    whats_working: list[WorkingItem]
    gaps: list[Gap]
    opportunities: list[Opportunity]

    outline: DeckOutline
    evidence: dict[EvidenceId, Evidence]

    @model_validator(mode="after")
    def validate_consistency(self) -> "Brief":
        # The problem is: a brief.json with dangling evidence ids, mismatched confidence counts,
        # or unsorted rankings would render broken UI cards and silently erode AM trust.
        # The way we solve this is: enforce six invariants at every read and write so bad
        # data fails loudly here rather than reaching the UI.
        all_referenced: set[str] = set()
        for goal in self.goals:
            all_referenced.update(goal.evidence_ids)
        for w in self.whats_working:
            all_referenced.update(w.evidence_ids)
        for gap in self.gaps:
            all_referenced.update(gap.evidence_ids)
        for opp in self.opportunities:
            all_referenced.update(opp.evidence_ids)
        missing = all_referenced - set(self.evidence.keys())
        if missing:
            raise ValueError(f"referenced evidence ids missing from registry: {sorted(missing)}")

        goal_ids = {g.id for g in self.goals}
        for gap in self.gaps:
            for gl in gap.goal_links:
                if gl not in goal_ids:
                    raise ValueError(f"gap {gap.id!r} references missing goal id: {gl!r}")
        for opp in self.opportunities:
            for gl in opp.goal_links:
                if gl not in goal_ids:
                    raise ValueError(f"opportunity {opp.id!r} references missing goal id: {gl!r}")

        severities = [g.severity for g in self.gaps]
        if severities != sorted(severities, reverse=True):
            raise ValueError("gaps must be sorted by severity descending")
        scores = [o.fit_score for o in self.opportunities]
        if scores != sorted(scores, reverse=True):
            raise ValueError("opportunities must be sorted by fit_score descending")

        actual = {"high": 0, "med": 0, "low": 0}
        for collection in (self.goals, self.whats_working, self.gaps, self.opportunities):
            for item in collection:
                actual[item.confidence] += 1
        declared = self.confidence_summary.model_dump()
        if actual != declared:
            raise ValueError(
                f"confidence_summary mismatch: declared {declared}, actual {actual}"
            )

        if self.status != "complete":
            if not self.status_reason:
                raise ValueError(f"status={self.status!r} requires a status_reason")
            if any([self.goals, self.whats_working, self.gaps, self.opportunities]):
                raise ValueError(f"status={self.status!r} requires all finding arrays to be empty")

        if not SEMVER_RE.match(self.pipeline_version):
            raise ValueError(f"pipeline_version {self.pipeline_version!r} is not valid semver")

        return self


class AccountSummary(BaseModel):
    id: str
    name: str
    vertical: str
    status: Status | Literal["not_run"]
    last_run_at: str | None = None
    error: str | None = None
