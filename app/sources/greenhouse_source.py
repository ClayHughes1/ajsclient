from datetime import datetime

import requests
from app.models.job import Job
from app.sources.job_source import JobSource


class GreenhouseSource(JobSource):

    BASE_URL = "https://boards-api.greenhouse.io/v1/boards"

    def __init__(self, company_name: str, board_token: str):
        self.company_name = company_name
        self.board_token = board_token

    def search(self, search_term: str = "") -> list[Job]:

        url = (
            f"{self.BASE_URL}/"
            f"{self.board_token}/jobs"
        )

        response = requests.get(
            url,
            params={"content": "true"},
            timeout=30
        )

        response.raise_for_status()

        data = response.json()

        jobs = []

        for item in data.get("jobs", []):

            title = item.get("title", "")

            description = item.get(
                "content",
                ""
            )

            location_data = item.get(
                "location",
                {}
            )

            location = location_data.get(
                "name",
                ""
            )

            posting_url = item.get(
                "absolute_url",
                ""
            )

            job = Job(
                company=self.company_name,
                title=title,
                location=location,
                posting_url=posting_url,
                description=description,
                posting_date=datetime.fromisoformat(
                    item["first_published"]
                ) if item.get("first_published") else None,
                salary="",
                source="Greenhouse"
            )

            jobs.append(job)

        return jobs