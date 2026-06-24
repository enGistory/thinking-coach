from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse

SourceLevel = Literal["S", "A", "B", "C"]
SupportStatus = Literal["VERIFIED", "CONFLICTED", "UNSUPPORTED"]

LEVEL_RANK: dict[SourceLevel, int] = {"S": 4, "A": 3, "B": 2, "C": 1}
BOOTSTRAP_DEFECTS = ["ALIGN-01", "INFO-01", "DEC-02"]
S_LEVEL_HOST_SUFFIXES = (".gov", ".gov.cn")
A_LEVEL_HOST_SUFFIXES = (".edu", ".edu.cn", ".ac.cn")


@dataclass(frozen=True)
class ClaimGateInput:
    id: str
    text: str
    source_id: str
    level: SourceLevel
    support_status: SupportStatus


def classify_source_level(*, title: str, publisher: str, url: str) -> SourceLevel:
    host = (urlparse(url).hostname or "").lower()
    if _host_matches_suffix(host, S_LEVEL_HOST_SUFFIXES):
        return "S"
    if _host_matches_suffix(host, A_LEVEL_HOST_SUFFIXES):
        return "A"
    haystack = f"{title} {publisher} {host}".lower()
    if any(token in haystack for token in ("forum", "bbs", "weibo", "zhihu", "blog", "自媒体")):
        return "C"
    return "B"


def _host_matches_suffix(host: str, suffixes: Iterable[str]) -> bool:
    return any(host == suffix.removeprefix(".") or host.endswith(suffix) for suffix in suffixes)


def highest_source_level(levels: Iterable[SourceLevel]) -> SourceLevel | None:
    sorted_levels = sorted(levels, key=lambda value: LEVEL_RANK[value], reverse=True)
    return sorted_levels[0] if sorted_levels else None


def usable_claim_ids(claims: Iterable[ClaimGateInput]) -> set[str]:
    verified = [claim for claim in claims if claim.support_status == "VERIFIED"]
    normalized_sources: dict[str, set[str]] = defaultdict(set)
    for claim in verified:
        normalized = normalize_claim_text(claim.text)
        if claim.level == "B" and normalized:
            normalized_sources[normalized].add(claim.source_id)
    result: set[str] = set()
    for claim in verified:
        if claim.level in {"S", "A"}:
            result.add(claim.id)
        elif claim.level == "B" and len(normalized_sources[normalize_claim_text(claim.text)]) >= 2:
            result.add(claim.id)
    return result


def question_ready(
    *,
    mapped_claim_ids: Iterable[str],
    usable_ids: set[str],
    unsupported_claim_count: int,
    fact_mapping_count: int,
) -> bool:
    mapped = set(mapped_claim_ids)
    return (
        bool(mapped)
        and mapped.issubset(usable_ids)
        and unsupported_claim_count == 0
        and (fact_mapping_count > 0)
    )


def normalized_question_hash(prompt: str) -> str:
    normalized = re.sub(r"\s+", "", prompt.lower())
    normalized = re.sub(r"[0-9\uFF10-\uFF19]+", "#", normalized)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def normalize_claim_text(value: str) -> str:
    return re.sub(r"\s+", "", value.strip().lower())
