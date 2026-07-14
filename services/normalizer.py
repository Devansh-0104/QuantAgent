import logging
from collections.abc import Callable
from typing import TypedDict
from urllib.parse import urlsplit

from models.opportunity import OpportunityType
from scrapers.base import ATS
from scrapers.base import RawJob


logger = logging.getLogger(__name__)


class NormalizedOpportunity(TypedDict):
    company_id: int
    page_id: int
    provider_id: str
    type: OpportunityType
    title: str
    description: str | None
    location: str
    url: str
    visa: str | None
    deadline: str | None


class OpportunityNormalizer:
    def normalize(
        self,
        ats: ATS,
        company_id: int,
        page_id: int,
        jobs: list[RawJob],
    ) -> list[NormalizedOpportunity]:
        normalizers: dict[
            ATS,
            Callable[[int, int, list[RawJob]], list[NormalizedOpportunity]],
        ] = {
            ATS.GREENHOUSE: self.greenhouse,
            ATS.LEVER: self.lever,
            ATS.CUSTOM: self.generic,
            ATS.ASHBY: self.ashby,
            ATS.WORKDAY: self.workday,
            ATS.SMARTRECRUITERS: self.smartrecruiters,
            ATS.PINPOINT: self.pinpoint,
        }
        normalizer = normalizers.get(ats)
        if normalizer is None:
            raise ValueError(f"No normalizer is implemented for {ats.value}")

        return normalizer(company_id, page_id, jobs)

    def greenhouse(
        self,
        company_id: int,
        page_id: int,
        jobs: list[RawJob],
    ) -> list[NormalizedOpportunity]:
        opportunities: list[NormalizedOpportunity] = []

        for job in jobs:
            location_value = job.get("location")
            if isinstance(location_value, dict):
                location = self._text(location_value.get("name"))
            else:
                location = self._text(location_value)

            opportunity = self._build(
                company_id=company_id,
                page_id=page_id,
                provider_id=job.get("id"),
                title=job.get("title"),
                description=job.get("content"),
                location=location,
                url=job.get("absolute_url"),
            )
            if opportunity is not None:
                opportunities.append(opportunity)

        return opportunities

    def generic(
        self,
        company_id: int,
        page_id: int,
        jobs: list[RawJob],
    ) -> list[NormalizedOpportunity]:
        opportunities: list[NormalizedOpportunity] = []
        for job in jobs:
            opportunity = self._build(
                company_id=company_id,
                page_id=page_id,
                provider_id=job.get("id"),
                title=job.get("title"),
                description=job.get("description"),
                location=self._text(job.get("location")),
                url=job.get("url"),
                deadline=self._text(job.get("deadline")) or None,
                forced_type=None,
            )
            if opportunity is not None:
                opportunities.append(opportunity)
        return opportunities

    def ashby(self, company_id: int, page_id: int, jobs: list[RawJob]) -> list[NormalizedOpportunity]:
        opportunities: list[NormalizedOpportunity] = []
        for job in jobs:
            location = job.get("location")
            if isinstance(location, dict):
                location = location.get("name")
            opportunity = self._build(
                company_id, page_id, job.get("id") or job.get("jobUrl"),
                job.get("title"), job.get("descriptionPlain") or job.get("descriptionHtml"),
                self._text(location), job.get("jobUrl") or job.get("applyUrl"),
            )
            if opportunity:
                opportunities.append(opportunity)
        return opportunities

    def workday(self, company_id: int, page_id: int, jobs: list[RawJob]) -> list[NormalizedOpportunity]:
        opportunities: list[NormalizedOpportunity] = []
        for job in jobs:
            opportunity = self._build(
                company_id, page_id, job.get("externalPath"),
                job.get("title"), job.get("description"), self._text(job.get("locationsText")), job.get("url"),
            )
            if opportunity:
                opportunities.append(opportunity)
        return opportunities

    def smartrecruiters(self, company_id: int, page_id: int, jobs: list[RawJob]) -> list[NormalizedOpportunity]:
        opportunities: list[NormalizedOpportunity] = []
        for job in jobs:
            location_value = job.get("location")
            location = ""
            if isinstance(location_value, dict):
                location = ", ".join(filter(None, (self._text(location_value.get(key)) for key in ("city", "region", "country"))))
            identifier = job.get("id")
            url = job.get("ref")
            if not isinstance(url, str) and identifier:
                url = f"https://jobs.smartrecruiters.com/job/{identifier}"
            opportunity = self._build(company_id, page_id, identifier, job.get("name"), job.get("jobAd"), location, url)
            if opportunity:
                opportunities.append(opportunity)
        return opportunities

    def pinpoint(self, company_id: int, page_id: int, jobs: list[RawJob]) -> list[NormalizedOpportunity]:
        opportunities: list[NormalizedOpportunity] = []
        for job in jobs:
            location = job.get("location")
            if isinstance(location, dict):
                location = location.get("name") or location.get("text")
            opportunity = self._build(
                company_id, page_id, job.get("id") or job.get("url"),
                job.get("title") or job.get("name"),
                job.get("description") or job.get("description_plain"),
                self._text(location), job.get("url") or job.get("apply_url"),
                deadline=self._text(job.get("closing_date")) or None,
            )
            if opportunity:
                opportunities.append(opportunity)
        return opportunities

    def lever(
        self,
        company_id: int,
        page_id: int,
        jobs: list[RawJob],
    ) -> list[NormalizedOpportunity]:
        opportunities: list[NormalizedOpportunity] = []

        for job in jobs:
            categories = job.get("categories")
            location = ""
            if isinstance(categories, dict):
                location = self._text(categories.get("location"))

            opportunity = self._build(
                company_id=company_id,
                page_id=page_id,
                provider_id=job.get("id"),
                title=job.get("text"),
                description=job.get("descriptionPlain"),
                location=location,
                url=job.get("hostedUrl"),
            )
            if opportunity is not None:
                opportunities.append(opportunity)

        return opportunities

    def classify(self, title: str) -> OpportunityType:
        normalized_title = title.casefold()

        if "competition" in normalized_title or "hackathon" in normalized_title:
            return OpportunityType.COMPETITION
        if "intern" in normalized_title:
            return OpportunityType.INTERNSHIP
        if "graduate" in normalized_title or "new grad" in normalized_title:
            return OpportunityType.GRADUATE
        if any(
            term in normalized_title
            for term in (
                "event", "program", "insight day", "open house",
                "campus talk", "networking", "workshop",
            )
        ):
            return OpportunityType.EVENT

        return OpportunityType.JOB

    def _build(
        self,
        company_id: int,
        page_id: int,
        provider_id: object,
        title: object,
        description: object,
        location: str,
        url: object,
        deadline: str | None = None,
        forced_type: OpportunityType | None = None,
    ) -> NormalizedOpportunity | None:
        normalized_provider_id = self._text(provider_id)
        normalized_title = self._text(title)
        normalized_description = self._text(description) or None
        normalized_url = self._text(url)

        if not normalized_provider_id:
            logger.warning("Skipping opportunity without a provider identity")
            return None
        if not normalized_title:
            logger.warning(
                "Skipping opportunity %s without a title",
                normalized_provider_id,
            )
            return None
        if not self._is_http_url(normalized_url):
            logger.warning(
                "Skipping opportunity %s with an invalid URL",
                normalized_provider_id,
            )
            return None

        return {
            "company_id": company_id,
            "page_id": page_id,
            "provider_id": normalized_provider_id,
            "type": forced_type or self.classify(normalized_title),
            "title": normalized_title,
            "description": normalized_description,
            "location": location,
            "url": normalized_url,
            "visa": None,
            "deadline": deadline,
        }

    @staticmethod
    def _text(value: object) -> str:
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, int):
            return str(value)
        return ""

    @staticmethod
    def _is_http_url(url: str) -> bool:
        parsed = urlsplit(url)
        return (
            parsed.scheme.lower() in {"http", "https"}
            and parsed.hostname is not None
        )
