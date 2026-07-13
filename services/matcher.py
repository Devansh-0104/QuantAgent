from urllib.parse import urlparse

from scrapers.base import ATS


class ATSDetector:

    DOMAINS = {
        "greenhouse.io": ATS.GREENHOUSE,
        "boards.greenhouse.io": ATS.GREENHOUSE,

        "myworkdayjobs.com": ATS.WORKDAY,
        "workday.com": ATS.WORKDAY,

        "jobs.lever.co": ATS.LEVER,

        "ashbyhq.com": ATS.ASHBY,

        "smartrecruiters.com": ATS.SMARTRECRUITERS,
    }

    def detect(self, url: str):

        host = urlparse(url).netloc.lower()

        for domain, ats in self.DOMAINS.items():

            if domain in host:
                return ats

        return ATS.CUSTOM