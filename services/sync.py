import logging
from dataclasses import dataclass
from enum import Enum

from models.company import Company
from models.page import Page
from scrapers.base import ATS
from scrapers.base import UnsupportedScraperError
from services.discovery import Discovery
from services.extractor import Extractor
from services.matcher import ATSDetector
from services.matcher import OpportunityMatcher
from services.monitor import Monitor
from services.monitor import ScanResult
from services.normalizer import OpportunityNormalizer
from services.notifier import DailyReportMetrics
from services.notifier import NotificationBatchResult
from services.notifier import NotificationService
from services.notifier import ScraperFactory
from services.registry import Registry


logger = logging.getLogger(__name__)


class SyncStatus(Enum):
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


@dataclass
class PageScanResult:
    page_id: int
    url: str
    status: SyncStatus
    ats: ATS | None = None
    lifecycle: ScanResult | None = None
    notifications: NotificationBatchResult | None = None
    message: str | None = None


@dataclass
class CompanySyncResult:
    company_id: int
    company_name: str
    status: SyncStatus
    pages: list[PageScanResult]
    errors: list[str]


@dataclass
class SyncRunResult:
    companies: list[CompanySyncResult]
    daily_report: NotificationBatchResult | None = None

    @property
    def status(self) -> SyncStatus:
        statuses = {company.status for company in self.companies}
        if self.daily_report and self.daily_report.failed:
            if statuses == {SyncStatus.FAILED}:
                return SyncStatus.FAILED
            return SyncStatus.PARTIAL
        if SyncStatus.FAILED in statuses:
            if len(statuses) == 1:
                return SyncStatus.FAILED
            return SyncStatus.PARTIAL
        if SyncStatus.PARTIAL in statuses:
            return SyncStatus.PARTIAL
        if statuses == {SyncStatus.SKIPPED}:
            return SyncStatus.SKIPPED
        return SyncStatus.SUCCESS


class SyncService:
    def __init__(
        self,
        registry: Registry,
        discovery: Discovery,
        monitor: Monitor,
        extractor: Extractor,
        detector: ATSDetector,
        matcher: OpportunityMatcher,
        notifier: NotificationService,
        factory: ScraperFactory,
        normalizer: OpportunityNormalizer,
    ) -> None:
        self.registry = registry
        self.discovery = discovery
        self.monitor = monitor
        self.extractor = extractor
        self.detector = detector
        self.matcher = matcher
        self.notifier = notifier
        self.factory = factory
        self.normalizer = normalizer

    def run(self) -> SyncRunResult:
        try:
            retry_result = self.notifier.retry_failed()
            if retry_result.failed:
                logger.warning(
                    "%s previously failed notifications remain undelivered",
                    retry_result.failed,
                )
        except Exception:
            logger.exception("Unable to retry failed notifications")

        results: list[CompanySyncResult] = []
        for company in self.registry.all_companies():
            try:
                results.append(self.scan_company(company))
            except Exception as exc:
                logger.exception("Unexpected sync failure for %s", company.name)
                results.append(
                    CompanySyncResult(
                        company_id=company.id,
                        company_name=company.name,
                        status=SyncStatus.FAILED,
                        pages=[],
                        errors=[str(exc)],
                    )
                )

        daily_report = self._send_daily_report(results)
        return SyncRunResult(companies=results, daily_report=daily_report)

    def _send_daily_report(
        self,
        companies: list[CompanySyncResult],
    ) -> NotificationBatchResult:
        page_results = [page for company in companies for page in company.pages]
        lifecycles = [
            page.lifecycle for page in page_results if page.lifecycle is not None
        ]
        failures = sum(len(company.errors) for company in companies) + sum(
            page.status == SyncStatus.FAILED for page in page_results
        )
        metrics = DailyReportMetrics(
            companies_checked=len(companies),
            successful_companies=sum(
                company.status == SyncStatus.SUCCESS for company in companies
            ),
            failures=failures,
            new_opportunities=sum(item.new for item in lifecycles),
            updated_opportunities=sum(
                item.updated + item.reopened for item in lifecycles
            ),
            closed_opportunities=sum(item.closed for item in lifecycles),
        )
        try:
            return self.notifier.send_daily_report(metrics)
        except Exception:
            logger.exception("Daily report generation failed")
            return NotificationBatchResult(failed=1)

    def scan_company(self, company: Company) -> CompanySyncResult:
        errors: list[str] = []
        try:
            discovered = self.discovery.discover(company)
            if not discovered:
                errors.append("No new recruiting pages were discovered")
        except Exception as exc:
            logger.exception("Discovery failed for %s", company.name)
            errors.append(f"Discovery failed: {exc}")

        try:
            pages = self.monitor.best_pages(company.id)
        except Exception as exc:
            logger.exception("Unable to load pages for %s", company.name)
            return CompanySyncResult(
                company_id=company.id,
                company_name=company.name,
                status=SyncStatus.FAILED,
                pages=[],
                errors=[*errors, f"Unable to load pages: {exc}"],
            )

        page_results = [self._safe_scan_page(page) for page in pages]
        status = self._company_status(page_results, errors)
        return CompanySyncResult(
            company_id=company.id,
            company_name=company.name,
            status=status,
            pages=page_results,
            errors=errors,
        )

    def scan_page(self, page: Page) -> PageScanResult:
        try:
            candidates = self._candidate_urls(page.url)
        except Exception as exc:
            logger.exception("Candidate extraction failed for %s", page.url)
            return PageScanResult(
                page_id=page.id,
                url=page.url,
                status=SyncStatus.FAILED,
                message=f"Candidate extraction failed: {exc}",
            )

        if not candidates:
            return PageScanResult(
                page_id=page.id,
                url=page.url,
                status=SyncStatus.SKIPPED,
                message="No provider candidates found",
            )

        failures: list[str] = []
        for candidate in candidates:
            ats = self.detector.detect(candidate)
            if ats == ATS.CUSTOM:
                continue

            try:
                scraper = self.factory.get(ats)
                raw_jobs = scraper.scrape(candidate)
                opportunities = self.normalizer.normalize(
                    ats,
                    company_id=page.company_id,
                    page_id=page.id,
                    jobs=raw_jobs,
                )
                if raw_jobs and not opportunities:
                    failures.append(f"{ats.value} payload could not be normalized")
                    continue

                lifecycle = self.monitor.reconcile_opportunities(
                    page.id,
                    opportunities,
                    scan_completed=True,
                )
                try:
                    matches = self.matcher.match_many(opportunities)
                    self.monitor.save_matches(matches)
                except Exception as exc:
                    logger.exception("Matching failed for %s", candidate)
                    matching_failure = f"Matching failed: {exc}"
                    messages = [*failures, matching_failure]
                    return PageScanResult(
                        page_id=page.id,
                        url=page.url,
                        status=SyncStatus.PARTIAL,
                        ats=ats,
                        lifecycle=lifecycle,
                        message="; ".join(messages),
                    )

                new_matches = [
                    match
                    for match in matches
                    if match.provider_id in lifecycle.new_provider_ids
                ]
                try:
                    notifications = self.notifier.send_instant_alerts(new_matches)
                except Exception as exc:
                    logger.exception("Notification processing failed for %s", candidate)
                    messages = [*failures, f"Notification processing failed: {exc}"]
                    return PageScanResult(
                        page_id=page.id,
                        url=page.url,
                        status=SyncStatus.PARTIAL,
                        ats=ats,
                        lifecycle=lifecycle,
                        message="; ".join(messages),
                    )

                if notifications.failed:
                    failures.append(
                        f"{notifications.failed} instant notification(s) failed"
                    )

                return PageScanResult(
                    page_id=page.id,
                    url=page.url,
                    status=(
                        SyncStatus.PARTIAL if failures else SyncStatus.SUCCESS
                    ),
                    ats=ats,
                    lifecycle=lifecycle,
                    notifications=notifications,
                    message="; ".join(failures) if failures else None,
                )
            except UnsupportedScraperError as exc:
                failures.append(str(exc))
            except Exception as exc:
                logger.exception("Provider scan failed for %s", candidate)
                failures.append(f"{ats.value} failed: {exc}")

        if failures:
            return PageScanResult(
                page_id=page.id,
                url=page.url,
                status=SyncStatus.FAILED,
                message="; ".join(failures),
            )

        return PageScanResult(
            page_id=page.id,
            url=page.url,
            status=SyncStatus.SKIPPED,
            message="No supported provider found",
        )

    def _candidate_urls(self, page_url: str) -> list[str]:
        if self.detector.detect(page_url) != ATS.CUSTOM:
            return [page_url]
        return self.extractor.analyze(page_url)

    def _safe_scan_page(self, page: Page) -> PageScanResult:
        try:
            return self.scan_page(page)
        except Exception as exc:
            logger.exception("Unexpected page failure for %s", page.url)
            return PageScanResult(
                page_id=page.id,
                url=page.url,
                status=SyncStatus.FAILED,
                message=f"Unexpected page failure: {exc}",
            )

    @staticmethod
    def _company_status(
        pages: list[PageScanResult],
        errors: list[str],
    ) -> SyncStatus:
        if not pages:
            return SyncStatus.FAILED if errors else SyncStatus.SKIPPED

        statuses = {page.status for page in pages}
        if statuses == {SyncStatus.SUCCESS} and not errors:
            return SyncStatus.SUCCESS
        if SyncStatus.SUCCESS in statuses:
            return SyncStatus.PARTIAL
        if SyncStatus.FAILED in statuses:
            return SyncStatus.FAILED
        if SyncStatus.PARTIAL in statuses:
            return SyncStatus.PARTIAL
        return SyncStatus.PARTIAL if errors else SyncStatus.SKIPPED
