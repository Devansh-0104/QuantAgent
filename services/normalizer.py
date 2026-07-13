from models.opportunity import OpportunityType


class OpportunityNormalizer:

    def greenhouse(self, company_id, page_id, jobs):

        opportunities = []

        for job in jobs:

            title = job.get("title", "")

            title_lower = title.lower()

            if "intern" in title_lower:
                opportunity_type = OpportunityType.INTERNSHIP

            elif "graduate" in title_lower:
                opportunity_type = OpportunityType.GRADUATE

            else:
                opportunity_type = OpportunityType.JOB

            # Greenhouse returns location as a dict
            location = ""

            if isinstance(job.get("location"), dict):
                location = job["location"].get("name", "")
            else:
                location = job.get("location", "")

            opportunities.append(
                {
                    "company_id": company_id,
                    "page_id": page_id,
                    "type": opportunity_type,
                    "title": title,
                    "location": location,
                    "url": job.get("absolute_url", ""),
                    "visa": None,
                    "deadline": None,
                }
            )

        return opportunities
    

    def lever(self, company_id, page_id, jobs):

        opportunities = []

        for job in jobs:

            title = job.get("text", "")

            title_lower = title.lower()

            if "intern" in title_lower:
                opportunity_type = OpportunityType.INTERNSHIP

            elif "graduate" in title_lower:
                opportunity_type = OpportunityType.GRADUATE

            else:
                opportunity_type = OpportunityType.JOB

            opportunities.append({

                "company_id": company_id,

                "page_id": page_id,

                "type": opportunity_type,

                "title": title,

                "location": job.get("categories", {}).get("location", ""),

                "url": job.get("hostedUrl", ""),

                "visa": None,

                "deadline": None

            })

        return opportunities