from urllib.parse import urlsplit

from scrapers.base import ATS


class ATSDetector:
    DOMAINS = {
        "greenhouse.io": ATS.GREENHOUSE,
        "myworkdayjobs.com": ATS.WORKDAY,
        "workday.com": ATS.WORKDAY,
        "lever.co": ATS.LEVER,
        "ashbyhq.com": ATS.ASHBY,
        "smartrecruiters.com": ATS.SMARTRECRUITERS,
    }

    def detect(self, url: str) -> ATS:
        host = urlsplit(url).hostname
        if host is None:
            return ATS.CUSTOM

        normalized_host = host.lower().rstrip(".")
        for domain, ats in self.DOMAINS.items():
            if normalized_host == domain or normalized_host.endswith(f".{domain}"):
                return ats

        return ATS.CUSTOM
