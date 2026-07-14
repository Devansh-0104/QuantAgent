import unittest
from unittest.mock import Mock
from unittest.mock import patch

import httpx

from models.company import Company
from scrapers.base import RetryingHTTPClient
from services.discovery import Discovery


class RetryingHTTPClientTests(unittest.TestCase):
    def test_retries_transient_network_failures(self) -> None:
        client = Mock()
        client.get.side_effect = [
            httpx.ConnectError("connection refused"),
            httpx.Response(200, request=httpx.Request("GET", "https://example.com")),
        ]
        retrying = RetryingHTTPClient(
            attempts=2,
            backoff_seconds=0,
            client=client,
        )

        response = retrying.get("https://example.com", timeout=5)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(client.get.call_count, 2)

    def test_retries_transient_server_statuses(self) -> None:
        request = httpx.Request("GET", "https://example.com")
        client = Mock()
        client.get.side_effect = [
            httpx.Response(503, request=request),
            httpx.Response(200, request=request),
        ]
        retrying = RetryingHTTPClient(
            attempts=2,
            backoff_seconds=0,
            client=client,
        )

        response = retrying.get("https://example.com", timeout=5)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(client.get.call_count, 2)

    def test_does_not_retry_permanent_client_statuses(self) -> None:
        request = httpx.Request("GET", "https://example.com/missing")
        client = Mock()
        client.get.return_value = httpx.Response(404, request=request)
        retrying = RetryingHTTPClient(
            attempts=3,
            backoff_seconds=0,
            client=client,
        )

        response = retrying.get("https://example.com/missing", timeout=5)

        self.assertEqual(response.status_code, 404)
        client.get.assert_called_once_with(
            "https://example.com/missing",
            timeout=5,
            follow_redirects=False,
        )


class DiscoveryHTTPClientIntegrationTests(unittest.TestCase):
    def test_discovery_uses_shared_http_client_for_network_reads(self) -> None:
        resolver = Mock()
        resolver.resolve.return_value = "https://example.com"
        registry = Mock()
        registry.update_website.return_value = True
        monitor = Mock()
        company = Company(id=1, name="Example")
        response = httpx.Response(
            200,
            request=httpx.Request("GET", "https://example.com"),
            text="<html></html>",
        )

        with patch("services.discovery.http_client.get", return_value=response) as get:
            Discovery(resolver, registry=registry, monitor=monitor).discover(company)

        self.assertGreater(get.call_count, 1)


if __name__ == "__main__":
    unittest.main()
