import httpx

from urllib.parse import urlparse


class GreenhouseScraper:

    API = "https://boards-api.greenhouse.io/v1/boards/{}/jobs"

    def scrape(self, url: str):

        board = self._board_name(url)

        api = self.API.format(board)

        response = httpx.get(

            api,

            timeout=20

        )

        response.raise_for_status()

        jobs = response.json()["jobs"]

        opportunities = []

        for job in jobs:

            opportunities.append(

                {

                    "title": job["title"],

                    "location": job["location"]["name"],

                    "url": job["absolute_url"],

                    "id": job["id"]

                }

            )

        return jobs

    def _board_name(self, url):

        path = urlparse(url).path

        return path.strip("/")