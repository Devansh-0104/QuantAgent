import typer

from scrapers.custom import CustomResolver

from services.discovery import Discovery
from services.extractor import Extractor
from services.matcher import ATSDetector
from services.matcher import OpportunityMatcher
from services.monitor import Monitor
from services.normalizer import OpportunityNormalizer
from services.notifier import ScraperFactory
from services.notifier import NotificationService
from services.registry import Registry
from services.sync import PageScanResult
from services.sync import SyncService

app = typer.Typer()

# --------------------------------------------------
# Services
# --------------------------------------------------

registry = Registry()
resolver = CustomResolver()
monitor = Monitor()
discovery = Discovery(resolver, registry=registry, monitor=monitor)
extractor = Extractor()
detector = ATSDetector()
opportunity_matcher = OpportunityMatcher()
notification_service = NotificationService.from_environment()
factory = ScraperFactory()
normalizer = OpportunityNormalizer()
sync_service = SyncService(
    registry=registry,
    discovery=discovery,
    monitor=monitor,
    extractor=extractor,
    detector=detector,
    matcher=opportunity_matcher,
    notifier=notification_service,
    factory=factory,
    normalizer=normalizer,
)


# --------------------------------------------------
# Company Commands
# --------------------------------------------------

@app.command()
def watch(company: str):
    if registry.watch(company):
        print(f"✓ Watching {company}")
    else:
        print(f"{company} is already being watched.")


@app.command()
def list():
    companies = registry.list()

    if not companies:
        print("No companies added.")
        return

    for company in companies:
        print(company.name)


# --------------------------------------------------
# Discovery
# --------------------------------------------------

@app.command()
def discover(company: str):
    obj = registry.get_company(company)

    if obj is None:
        print("Company not found.")
        return

    if discovery.discover(obj):
        print("Discovery complete.")
    else:
        print("Discovery failed.")


@app.command()
def pages(company: str):
    obj = registry.get_company(company)

    if obj is None:
        print("Company not found.")
        return

    pages = monitor.get_pages(obj.id)

    if not pages:
        print("No pages discovered.")
        return

    for page in pages:
        print(f"[{page.id}] {page.page_type.value}")
        print(page.url)
        print("-" * 50)


# --------------------------------------------------
# Analysis
# --------------------------------------------------

@app.command()
def analyze(url: str):
    links = extractor.analyze(url)

    if not links:
        print("No links found.")
        return

    for link in links:
        print(link)


@app.command()
def detect(url: str):
    ats = detector.detect(url)
    print(ats.value)


# --------------------------------------------------
# Scraping
# --------------------------------------------------

@app.command()
def scrape(page_id: int):
    page = monitor.get_page(page_id)

    if page is None:
        print("Page not found.")
        return

    _print_page_result(sync_service.scan_page(page))

    
@app.command()
def sync():
    result = sync_service.run()
    print(f"Sync status: {result.status.value}")
    if result.daily_report:
        daily = result.daily_report
        print(
            f"daily report: sent={daily.sent} "
            f"skipped={daily.skipped} failed={daily.failed}"
        )

    for company in result.companies:
        print(f"\n=== {company.company_name}: {company.status.value} ===")
        for error in company.errors:
            print(error)
        for page_result in company.pages:
            _print_page_result(page_result)


def _print_page_result(result: PageScanResult) -> None:
    provider = f" ({result.ats.value})" if result.ats else ""
    print(f"[{result.status.value}]{provider} {result.url}")
    if result.message:
        print(result.message)
    if result.lifecycle:
        lifecycle = result.lifecycle
        print(
            f"new={lifecycle.new} updated={lifecycle.updated} "
            f"unchanged={lifecycle.unchanged} closed={lifecycle.closed} "
            f"reopened={lifecycle.reopened}"
        )
    if result.notifications:
        notifications = result.notifications
        print(
            f"notifications: sent={notifications.sent} "
            f"skipped={notifications.skipped} failed={notifications.failed}"
        )
