import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from unittest.mock import patch

from typer.testing import CliRunner

from app.cli import app
from services.discovery import Discovery
from services.registry import Registry
from services.sync import SyncRunResult
from services.sync import SyncStatus


class FirstRunWorkflowTests(unittest.TestCase):
    def test_discovery_uses_stored_company_website_before_resolver(self) -> None:
        resolver = Mock()
        registry = Mock()
        monitor = Mock()
        discovery = Discovery(resolver, registry=registry, monitor=monitor)
        monitor.get_pages.return_value = []
        company = SimpleNamespace(
            id=1,
            name="Example",
            website="https://example.com",
        )

        with (
            patch.object(discovery, "_probe_common_paths") as probe,
            patch.object(discovery, "_discover_homepage_links") as homepage,
        ):
            probe.side_effect = lambda _website, found: found.update(
                {"https://example.com/careers": unittest.mock.ANY}
            )
            result = discovery.discover(company)

        self.assertTrue(result)
        resolver.resolve.assert_not_called()
        homepage.assert_called_once()
        registry.update_website.assert_called_once_with(
            "Example",
            "https://example.com/",
        )

    def test_registry_rejects_invalid_website_before_database_access(self) -> None:
        registry = Registry.__new__(Registry)

        with self.assertRaisesRegex(ValueError, "absolute HTTP"):
            registry.watch("Example", website="example.com")

        with self.assertRaisesRegex(ValueError, "embedded credentials"):
            registry.watch(
                "Example",
                website="https://user:password@example.com",
            )

    def test_discovery_rejects_private_network_addresses(self) -> None:
        from services.discovery import normalize_http_url

        self.assertIsNone(normalize_http_url("http://127.0.0.1", "/careers"))
        self.assertIsNone(normalize_http_url("http://localhost", "/careers"))


class ProductionCLITests(unittest.TestCase):
    def test_watch_accepts_official_website(self) -> None:
        with patch("app.cli.registry.watch", return_value=True) as watch:
            result = CliRunner().invoke(
                app,
                ["watch", "Example", "--website", "https://example.com"],
            )

        self.assertEqual(result.exit_code, 0)
        watch.assert_called_once_with(
            "Example",
            website="https://example.com",
        )

    def test_partial_sync_returns_nonzero_exit_code(self) -> None:
        sync_result = SyncRunResult(companies=[])
        sync_result.companies.append(
            SimpleNamespace(
                company_name="Example",
                status=SyncStatus.PARTIAL,
                errors=["provider failed"],
                pages=[],
            )
        )

        with patch("app.cli.sync_service.run", return_value=sync_result):
            result = CliRunner().invoke(app, ["sync"])

        self.assertEqual(result.exit_code, 1)
        self.assertIn("Sync status: PARTIAL", result.stdout)

    def test_empty_sync_is_skipped(self) -> None:
        self.assertEqual(SyncRunResult(companies=[]).status, SyncStatus.SKIPPED)


if __name__ == "__main__":
    unittest.main()
