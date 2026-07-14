import typer

from scrapers.base import ATS
from scrapers.base import UnsupportedScraperError
from scrapers.custom import CustomResolver

from services.discovery import Discovery
from services.extractor import Extractor
from services.matcher import ATSDetector
from services.monitor import Monitor
from services.normalizer import OpportunityNormalizer
from services.notifier import ScraperFactory
from services.registry import Registry

app = typer.Typer()

# --------------------------------------------------
# Services
# --------------------------------------------------

registry = Registry()
resolver = CustomResolver()
discovery = Discovery(resolver)
monitor = Monitor()
extractor = Extractor()
detector = ATSDetector()
factory = ScraperFactory()
normalizer = OpportunityNormalizer()


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

    ats = detector.detect(page.url)
    print(f"Detected ATS: {ats.value}")

    try:
        scraper = factory.get(ats)
    except UnsupportedScraperError as exc:
        print(str(exc))
        return

    raw_jobs = scraper.scrape(page.url)

    # Fixed indentation and layout blocks below
    if ats == ATS.GREENHOUSE:
        opportunities = normalizer.greenhouse(
            company_id=page.company_id,
            page_id=page.id,
            jobs=raw_jobs,
        )

    elif ats == ATS.LEVER:
        opportunities = normalizer.lever(
            company_id=page.company_id,
            page_id=page.id,
            jobs=raw_jobs,
        )

    else:
        print(f"{ats.value} scraper not implemented yet.")
        return

    # Moved outside the else: block so it actually runs
    added = monitor.save_opportunities(opportunities)
    print(f"Saved {added} new opportunities.")

    
@app.command()
def sync():

    companies = registry.all_companies()

    for company in companies:

        print(f"\n=== {company.name} ===")

        discovery.discover(company)

        pages = monitor.best_pages(company.id)

        for page in pages:

            print(f"\nScanning page:")

            print(page.url)

            links = extractor.analyze(page.url)

            if not links:

                print("No candidate links found.")

                continue

            scraped = False

            for link in links:

                ats = detector.detect(link)

                if ats == ATS.CUSTOM:
                    continue

                print(f"Detected {ats.value}")

                try:
                    scraper = factory.get(ats)
                except UnsupportedScraperError as exc:
                    print(str(exc))
                    continue

                raw_jobs = scraper.scrape(link)

                if ats == ATS.GREENHOUSE:

                    jobs = normalizer.greenhouse(
                        company.id,
                        page.id,
                        raw_jobs
                    )

                elif ats == ATS.LEVER:

                    jobs = normalizer.lever(
                        company.id,
                        page.id,
                        raw_jobs
                    )

                else:

                    continue

                added = monitor.save_opportunities(jobs)

                print(f"Added {added} opportunities")

                scraped = True

                break

            if not scraped:

                print("No supported ATS found.")
