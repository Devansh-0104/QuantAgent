import httpx

from bs4 import BeautifulSoup
from urllib.parse import urljoin

from scrapers.base import Resolver

from models.page import PageType

from services.monitor import Monitor

from app.database import SessionLocal


KEYWORDS = {

    PageType.CAREERS: [
        "career",
        "careers",
        "join",
        "jobs",
        "work-with-us",
        "vacancies"
    ],

    PageType.STUDENTS: [
        "student",
        "students",
        "graduate",
        "intern",
        "internship",
        "campus",
        "university"
    ],

    PageType.EVENTS: [
        "event",
        "events",
        "competition",
        "hackathon",
        "program"
    ]

}


COMMON_PATHS = {

    PageType.CAREERS: [
        "/careers",
        "/career",
        "/jobs",
        "/join",
        "/join-us",
        "/careers/",
        "/jobs/"
    ],

    PageType.STUDENTS: [
        "/students",
        "/student-programs",
        "/graduate",
        "/graduates",
        "/internships",
        "/internship",
        "/campus"
    ],

    PageType.EVENTS: [
        "/events",
        "/event",
        "/programs",
        "/hackathon",
        "/competitions"
    ]

}


class Discovery:

    def __init__(self, resolver: Resolver):

        self.resolver = resolver

        self.db = SessionLocal()

        self.monitor = Monitor()

    def discover(self, company):

        website = self.resolver.resolve(company.name)

        if website is None:
            return False

        company.website = website

        self.db.commit()

        found = {}

        # =====================================================
        # Strategy 1
        # Probe common paths
        # =====================================================

        for page_type, paths in COMMON_PATHS.items():

            for path in paths:

                url = urljoin(
                    website,
                    path
                )

                try:

                    response = httpx.get(
                        url,
                        follow_redirects=True,
                        timeout=10
                    )

                    if response.status_code == 200:

                        found.setdefault(
                            str(response.url),
                            page_type
                        )

                except Exception:

                    pass

        # =====================================================
        # Strategy 2
        # Parse homepage HTML
        # =====================================================

        try:

            response = httpx.get(
                website,
                follow_redirects=True,
                timeout=20
            )

            soup = BeautifulSoup(
                response.text,
                "lxml"
            )

            for tag in soup.find_all(
                "a",
                href=True
            ):

                href = tag["href"]

                url = urljoin(
                    website,
                    href
                )

                text = (
                    href +
                    " " +
                    tag.get_text(strip=True)
                ).lower()

                for page_type, words in KEYWORDS.items():

                    if any(

                        word in text

                        for word in words

                    ):

                        found.setdefault(
                            url,
                            page_type
                        )

        except Exception:

            pass

        # =====================================================
        # Save discovered pages
        # =====================================================

        for url, page_type in found.items():

            self.monitor.register_page(

                company_id=company.id,

                page_type=page_type,

                url=url

            )

        return True