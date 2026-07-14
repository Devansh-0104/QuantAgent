import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from app.config import PROJECT_ROOT
from models.opportunity import OpportunityPriority
from models.opportunity import OpportunityType
from scrapers.base import ATS


class ATSDetector:
    DOMAINS = {
        "greenhouse.io": ATS.GREENHOUSE,
        "myworkdayjobs.com": ATS.WORKDAY,
        "workday.com": ATS.WORKDAY,
        "lever.co": ATS.LEVER,
        "ashbyhq.com": ATS.ASHBY,
        "smartrecruiters.com": ATS.SMARTRECRUITERS,
    }

    def detect(self, url: str) -> ATS:
        host = urlsplit(url).hostname
        if host is None:
            return ATS.CUSTOM

        normalized_host = host.lower().rstrip(".")
        for domain, ats in self.DOMAINS.items():
            if normalized_host == domain or normalized_host.endswith(f".{domain}"):
                return ats

        return ATS.CUSTOM


class ProfileValidationError(ValueError):
    pass


@dataclass(frozen=True)
class MatchProfile:
    student: bool
    graduation_year: int
    visa_required: bool
    roles: tuple[str, ...]
    locations: tuple[str, ...]
    skills: tuple[str, ...]
    positive_keywords: tuple[str, ...]
    negative_keywords: tuple[str, ...]
    alert_threshold: int = 70


@dataclass(frozen=True)
class MatchResult:
    score: int
    priority: OpportunityPriority
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class OpportunityMatch:
    company_id: int
    provider_id: str
    result: MatchResult


class OpportunityMatcher:
    def __init__(self, profile_path: Path | None = None) -> None:
        self.profile_path = profile_path or PROJECT_ROOT / "profile.yaml"
        self.profile = self._load_profile(self.profile_path)

    def match(self, opportunity: object) -> MatchResult:
        title = self._text(self._get(opportunity, "title"))
        description = self._text(self._get(opportunity, "description"))
        location = self._text(self._get(opportunity, "location"))
        visa = self._text(self._get(opportunity, "visa"))
        opportunity_type = self._get(opportunity, "type")
        searchable = f"{title} {description}".casefold()

        score = 0
        reasons: list[str] = []

        matched_roles = [role for role in self.profile.roles if role in searchable]
        if matched_roles:
            score += 25
            reasons.append(f"Role match: {matched_roles[0]}")
        else:
            reasons.append("Role match: none")

        matched_locations = [
            preferred
            for preferred in self.profile.locations
            if preferred in location.casefold()
        ]
        if matched_locations:
            score += 15
            reasons.append(f"Location match: {matched_locations[0]}")
        else:
            reasons.append("Location match: none")

        matched_skills = [skill for skill in self.profile.skills if skill in searchable]
        if matched_skills:
            skill_score = round(20 * len(matched_skills) / len(self.profile.skills))
            score += skill_score
            reasons.append(f"Skill match: {', '.join(matched_skills)}")
        else:
            reasons.append("Skill match: none")

        normalized_type = (
            opportunity_type.value
            if isinstance(opportunity_type, OpportunityType)
            else str(opportunity_type or "").upper()
        )
        graduation_match = self.profile.student and normalized_type in {
            OpportunityType.INTERNSHIP.value,
            OpportunityType.GRADUATE.value,
        }
        if graduation_match:
            score += 15
            reasons.append(
                f"Graduation match: student graduating {self.profile.graduation_year}"
            )
        else:
            reasons.append("Graduation match: none")

        if not self.profile.visa_required:
            score += 15
            reasons.append("Visa match: sponsorship not required")
        elif any(term in visa.casefold() for term in ("no sponsor", "not available")):
            score -= 15
            reasons.append("Visa match: sponsorship unavailable")
        elif any(term in visa.casefold() for term in ("sponsor", "yes", "available")):
            score += 15
            reasons.append("Visa match: sponsorship indicated")
        else:
            reasons.append("Visa match: unknown")

        matched_positive = [
            keyword
            for keyword in self.profile.positive_keywords
            if self._contains_keyword(searchable, keyword)
        ]
        if matched_positive:
            score += 10
            reasons.append(f"Positive keywords: {', '.join(matched_positive)}")

        matched_negative = [
            keyword
            for keyword in self.profile.negative_keywords
            if self._contains_keyword(searchable, keyword)
        ]
        if matched_negative:
            score -= 40
            reasons.append(f"Negative keywords: {', '.join(matched_negative)}")

        bounded_score = max(0, min(100, score))
        return MatchResult(
            score=bounded_score,
            priority=self._priority(bounded_score),
            reasons=tuple(reasons),
        )

    def match_many(self, opportunities: list[object]) -> list[OpportunityMatch]:
        matches: list[OpportunityMatch] = []
        for opportunity in opportunities:
            company_id = self._get(opportunity, "company_id")
            provider_id = self._get(opportunity, "provider_id")
            if not isinstance(company_id, int) or not provider_id:
                raise ValueError("Opportunity requires company_id and provider_id")
            matches.append(
                OpportunityMatch(
                    company_id=company_id,
                    provider_id=str(provider_id),
                    result=self.match(opportunity),
                )
            )
        return matches

    def _priority(self, score: int) -> OpportunityPriority:
        if score >= self.profile.alert_threshold:
            return OpportunityPriority.HIGH
        if score >= max(40, self.profile.alert_threshold - 25):
            return OpportunityPriority.MEDIUM
        return OpportunityPriority.LOW

    @classmethod
    def _load_profile(cls, path: Path) -> MatchProfile:
        try:
            with path.open(encoding="utf-8") as profile_file:
                data = yaml.safe_load(profile_file)
        except OSError as exc:
            raise ProfileValidationError(f"Unable to read profile: {path}") from exc

        if not isinstance(data, dict):
            raise ProfileValidationError("Profile must contain a YAML mapping")

        student = cls._required(data, "student", bool)
        graduation_year = cls._required(data, "graduation_year", int)
        visa_required = cls._required(data, "visa_required", bool)
        roles = cls._string_list(data, "roles")
        locations = cls._string_list(data, "locations")
        skills = cls._string_list(data, "skills")
        positive_keywords = cls._string_list(data, "positive_keywords")
        negative_keywords = cls._string_list(data, "negative_keywords")
        threshold = data.get("alert_threshold", 70)
        if not isinstance(threshold, int) or isinstance(threshold, bool):
            raise ProfileValidationError("alert_threshold must be an integer")
        if not 0 <= threshold <= 100:
            raise ProfileValidationError("alert_threshold must be between 0 and 100")

        return MatchProfile(
            student=student,
            graduation_year=graduation_year,
            visa_required=visa_required,
            roles=roles,
            locations=locations,
            skills=skills,
            positive_keywords=positive_keywords,
            negative_keywords=negative_keywords,
            alert_threshold=threshold,
        )

    @staticmethod
    def _required(data: dict[str, object], key: str, expected: type) -> object:
        value = data.get(key)
        if not isinstance(value, expected) or (
            expected is int and isinstance(value, bool)
        ):
            raise ProfileValidationError(f"{key} must be {expected.__name__}")
        return value

    @staticmethod
    def _string_list(data: dict[str, object], key: str) -> tuple[str, ...]:
        value = data.get(key)
        if not isinstance(value, list) or not value:
            raise ProfileValidationError(f"{key} must be a non-empty list")
        if not all(isinstance(item, str) and item.strip() for item in value):
            raise ProfileValidationError(f"{key} must contain non-empty strings")
        return tuple(item.strip().casefold() for item in value)

    @staticmethod
    def _get(opportunity: object, field: str) -> object:
        if isinstance(opportunity, Mapping):
            return opportunity.get(field)
        return getattr(opportunity, field, None)

    @staticmethod
    def _text(value: object) -> str:
        return value.strip() if isinstance(value, str) else ""

    @staticmethod
    def _contains_keyword(text: str, keyword: str) -> bool:
        pattern = rf"(?<!\w){re.escape(keyword)}(?!\w)"
        return re.search(pattern, text) is not None
