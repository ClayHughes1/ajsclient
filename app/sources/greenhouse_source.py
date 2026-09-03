from datetime import datetime, timedelta, timezone
from app.utils.html_cleaner import clean_html_description
import requests
from app.utils.salary_extractor import extract_salary

from app.models.job import Job
from app.sources.job_source import JobSource


class GreenhouseSource(JobSource):

    BASE_URL = "https://boards-api.greenhouse.io/v1/boards"

    def __init__(
        self,
        company_name: str,
        board_token: str,
        posting_age_days: int = 2
    ):
        self.company_name = company_name
        self.board_token = board_token
        self.posting_age_days = posting_age_days

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

            if self.posting_age_days is not None:

                first_published = item.get("first_published")

                if not first_published:
                    continue

                posting_date = datetime.fromisoformat(
                    first_published
                )

                now = datetime.now(timezone.utc)

                cutoff_date = (
                    now -
                    timedelta(days=self.posting_age_days)
                )

                if posting_date < cutoff_date:
                    continue

            description = clean_html_description(
                item.get("content", "")
            )

            salary = extract_salary(description)

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
                salary=salary,
                source="Greenhouse"
            )

            jobs.append(job)

        return jobs

