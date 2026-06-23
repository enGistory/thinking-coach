from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.schemas.evaluation import EvidenceVerification, LogicIssue


@dataclass(frozen=True)
class EvidenceSegment:
    id: UUID
    attempt_id: UUID
    stage: str
    start_ms: int
    end_ms: int
    corrected_text: str


@dataclass(frozen=True)
class VerifiedIssueEvidence:
    verification: EvidenceVerification
    segment_id: UUID | None


def verify_issue_evidence(
    issue: LogicIssue,
    segments: list[EvidenceSegment],
) -> VerifiedIssueEvidence:
    stage_segments = sorted(
        (segment for segment in segments if segment.stage == issue.attempt_stage),
        key=lambda segment: (segment.start_ms, segment.end_ms),
    )
    quote = issue.quote.strip()
    if not quote:
        return _invalid(issue, "quote is empty")

    timestamp_segments = _timestamp_segments(issue, stage_segments)
    timestamp_valid = bool(timestamp_segments)
    if timestamp_valid:
        transcript_text = "".join(segment.corrected_text for segment in timestamp_segments)
    else:
        transcript_text = "".join(segment.corrected_text for segment in stage_segments)
    quote_match = _normalized(quote) in _normalized(transcript_text)
    if quote_match and timestamp_valid:
        return VerifiedIssueEvidence(
            verification=EvidenceVerification(
                issue_code=issue.code,
                evidence_valid=True,
                quote_match=True,
                timestamp_valid=True,
            ),
            segment_id=timestamp_segments[0].id,
        )

    correction_parts: list[str] = []
    if not quote_match:
        if timestamp_valid:
            correction_parts.append("quote not found in cited transcript range")
        else:
            correction_parts.append("quote not found in corrected transcript")
    if not timestamp_valid:
        correction_parts.append("timestamp is outside transcript segments")
    return VerifiedIssueEvidence(
        verification=EvidenceVerification(
            issue_code=issue.code,
            evidence_valid=False,
            quote_match=quote_match,
            timestamp_valid=timestamp_valid,
            correction="; ".join(correction_parts),
        ),
        segment_id=None,
    )


def _timestamp_segments(
    issue: LogicIssue,
    segments: list[EvidenceSegment],
) -> list[EvidenceSegment]:
    covered_until = issue.start_ms
    covering: list[EvidenceSegment] = []
    for segment in segments:
        if segment.end_ms < issue.start_ms:
            continue
        if segment.start_ms > issue.end_ms:
            break
        if segment.start_ms > covered_until:
            return []
        if segment.end_ms > covered_until:
            covering.append(segment)
            covered_until = segment.end_ms
        if covered_until >= issue.end_ms:
            return covering
    return []


def _invalid(issue: LogicIssue, correction: str) -> VerifiedIssueEvidence:
    return VerifiedIssueEvidence(
        verification=EvidenceVerification(
            issue_code=issue.code,
            evidence_valid=False,
            quote_match=False,
            timestamp_valid=False,
            correction=correction,
        ),
        segment_id=None,
    )


def _normalized(value: str) -> str:
    return "".join(char for char in value if not char.isspace())
