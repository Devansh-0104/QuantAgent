import httpx


class JaneStreetScraper:

    API = "https://www.janestreet.com/jobs/main.json"

    def scrape(self):

        response = httpx.get(
            self.API,
            timeout=30
        )

        response.raise_for_status()

        return response.json()