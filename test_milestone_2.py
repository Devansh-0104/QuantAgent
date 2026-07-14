import unittest
from dataclasses import dataclass
from unittest.mock import patch

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from models.company import Company
from models.page import Page
from models.page import PageType
from services.discovery import Discovery
from services.discovery import normalize_http_url
from services.monitor import Monitor
from services.registry import Registry


class FakeResolver:
    def __init__(self, website: str | None) -> None:
        self.website = website

    def resolve(self, company_name: str) -> str | None:
        return self.website


class FakeRegistry:
    def __init__(self, result: bool = True) -> None:
        self.result = result
        self.updates: list[tuple[str, str]] = []

    def update_website(self, company_name: str, website: str) -> bool:
        self.updates.append((company_name, website))
        return self.result


class FakeMonitor:
    def __init__(self) -> None:
        self.pages: list[tuple[int, PageType, str]] = []

    def register_page(
        self,
        company_id: int,
        page_type: PageType,
        url: str,
    ) -> None:
        self.pages.append((company_id, page_type, url))


@dataclass
class FakeCompany:
    id: int
    name: str


class FakeResponse:
    def __init__(self, url: str, text: str = "", status_code: int = 200) -> None:
        self.url = url
        self.text = text
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("GET", self.url)
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError(
                "request failed",
                request=request,
                response=response,
            )


class DiscoveryTests(unittest.TestCase):
    def test_normalize_http_url_rejects_unsupported_schemes(self) -> None:
        self.assertIsNone(normalize_http_url("https://example.com", "mailto:a@b.com"))
        self.assertIsNone(normalize_http_url("https://example.com", "javascript:void(0)"))

    def test_normalize_http_url_removes_fragments(self) -> None:
        self.assertEqual(
            normalize_http_url("https://Example.com", "/careers#jobs"),
            "https://example.com/careers",
        )

    def test_discovery_persists_website_through_registry(self) -> None:
        registry = FakeRegistry()
        monitor = FakeMonitor()
        discovery = Discovery(
            FakeResolver("https://Example.com"),
            registry=registry,
            monitor=monitor,
        )

        def fake_get(url: str, **kwargs: object) -> FakeResponse:
            if url == "https://example.com/":
                return FakeResponse(
                    url,
                    '<a href="/careers#openings">Careers</a>',
                )
            raise httpx.ConnectError("unavailable")

        with patch("services.discovery.http_client.get", side_effect=fake_get):
            result = discovery.discover(FakeCompany(id=1, name="Example"))  # type: ignore[arg-type]

        self.assertTrue(result)
        self.assertEqual(registry.updates, [("Example", "https://example.com/")])
        self.assertEqual(
            monitor.pages,
            [(1, PageType.CAREERS, "https://example.com/careers")],
        )

    def test_discovery_returns_false_when_no_pages_are_found(self) -> None:
        registry = FakeRegistry()
        monitor = FakeMonitor()
        discovery = Discovery(
            FakeResolver("https://example.com"),
            registry=registry,
            monitor=monitor,
        )

        with patch(
            "services.discovery.http_client.get",
            side_effect=httpx.ConnectError("unavailable"),
        ):
            result = discovery.discover(FakeCompany(id=1, name="Example"))  # type: ignore[arg-type]

        self.assertFalse(result)
        self.assertEqual(monitor.pages, [])

    def test_discovery_stops_when_website_cannot_be_persisted(self) -> None:
        registry = FakeRegistry(result=False)
        monitor = FakeMonitor()
        discovery = Discovery(
            FakeResolver("https://example.com"),
            registry=registry,
            monitor=monitor,
        )

        with patch("services.discovery.http_client.get") as get:
            result = discovery.discover(FakeCompany(id=1, name="Example"))  # type: ignore[arg-type]

        self.assertFalse(result)
        get.assert_not_called()
        self.assertEqual(monitor.pages, [])


class RepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)

    def tearDown(self) -> None:
        self.engine.dispose()

    def test_registry_persists_website_in_its_own_session(self) -> None:
        with patch("services.registry.SessionLocal", self.session_factory):
            registry = Registry()

        self.assertTrue(registry.watch("Example"))
        self.assertTrue(registry.update_website("Example", "https://example.com/"))

        verification_session = self.session_factory()
        try:
            company = verification_session.query(Company).one()
            self.assertEqual(company.website, "https://example.com/")
        finally:
            verification_session.close()
            registry.db.close()

    def test_page_registration_is_idempotent(self) -> None:
        setup_session = self.session_factory()
        company = Company(name="Example")
        setup_session.add(company)
        setup_session.commit()
        company_id = company.id
        setup_session.close()

        with patch("services.monitor.SessionLocal", self.session_factory):
            monitor = Monitor()

        first = monitor.register_page(
            company_id,
            PageType.CAREERS,
            "https://example.com/careers",
        )
        second = monitor.register_page(
            company_id,
            PageType.CAREERS,
            "https://example.com/careers",
        )

        self.assertEqual(first.id, second.id)
        self.assertEqual(monitor.db.query(Page).count(), 1)
        monitor.db.close()


if __name__ == "__main__":
    unittest.main()
