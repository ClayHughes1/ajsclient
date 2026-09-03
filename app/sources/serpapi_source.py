import os
import requests
from app.models.job import Job
import re
from datetime import date, timedelta

class SerpApiSource:

    BASE_URL = "https://serpapi.com/search"

    def __init__(self):
        self.api_key = os.getenv("SERPAPI_API_KEY")

        if not self.api_key:
            raise ValueError(
                "SERPAPI_API_KEY was not found in the .env file."
            )


    def search(
        self,
        query: str,
        location: str = "Melbourne, Florida"
    ) -> list[Job]:

        params = {
            "engine": "google_jobs",
            "q": query,
            "location": location,
            "hl": "en",
            "gl": "us",
            "api_key": self.api_key
        }

        try:

            response = requests.get(
                self.BASE_URL,
                params=params,
                timeout=30
            )

            response.raise_for_status()

            data = response.json()

        except requests.RequestException as error:

            print(f"SerpApi request failed: {error}")

            return []

        if data.get("error"):

            return []

        results = data.get(
            "jobs_results",
            []
        )

        jobs = []

        # ---------------------------------------------------------
        # Track jobs already seen.
        #
        # Posting URL is the preferred unique identifier.
        # ---------------------------------------------------------

        seen_urls = set()

        duplicate_count = 0

        # ---------------------------------------------------------
        # Normalize every SerpAPI result.
        # ---------------------------------------------------------

        for result in results:

            job = self._normalize_job(result)

            if not job:
                continue

            # -----------------------------------------------------
            # Deduplicate by posting URL.
            # -----------------------------------------------------

            if job.posting_url:

                if job.posting_url in seen_urls:

                    duplicate_count += 1

                    continue

                seen_urls.add(
                    job.posting_url
                )

            # -----------------------------------------------------
            # Keep the job even when posting_date is None.
            #
            # JobValidator will decide whether the job qualifies.
            # -----------------------------------------------------

            jobs.append(job)

        print(
            f"SerpApi returned {len(results)} raw jobs."
        )

        print(
            f"Removed {duplicate_count} duplicate jobs."
        )

        print(
            f"Returning {len(jobs)} unique jobs."
        )

        return jobs

    def _normalize_job(self, result: dict) -> Job | None:

        title = result.get("title", "").strip()

        company = result.get(
            "company_name",
            ""
        ).strip()

        location = result.get(
            "location",
            ""
        ).strip()

        description = result.get(
            "description",
            ""
        ).strip()

        posting_url = self._get_posting_url(result)

        posting_date = self._get_posting_date(result)

        salary = self._get_salary(result)

        if not title or not company:
            return None

        return Job(
            company=company,
            title=title,
            location=location,
            posting_url=posting_url,
            description=description,
            posting_date=posting_date,
            salary=salary,
            source="Google Jobs"
        )

    def _get_posting_url(self, result: dict) -> str:

        apply_options = result.get(
            "apply_options",
            []
        )

        if apply_options:

            link = apply_options[0].get("link")

            if link:
                return link

        return result.get(
            "share_link",
            ""
        )

    def _get_posting_date(self, result: dict):

        detected_extensions = result.get(
            "detected_extensions",
            {}
        )

        posted_at = detected_extensions.get("posted_at")

        if not posted_at:
            return None

        posted_at = str(posted_at).strip()

        if not posted_at:
            return None

        posted_at_lower = posted_at.lower()

        # Google Jobs sometimes returns "today" or "just posted".
        if posted_at_lower in {
            "today",
            "just posted",
            "posted today"
        }:
            return date.today()

        # Handle "1 day ago", "2 days ago", etc.
        match = re.match(
            r"(\d+)\s+day[s]?\s+ago",
            posted_at_lower
        )

        if match:
            days_ago = int(match.group(1))

            return date.today() - timedelta(
                days=days_ago
            )

        # Handle "30+ days ago"
        match = re.match(
            r"(\d+)\+\s+day[s]?\s+ago",
            posted_at_lower
        )

        if match:
            days_ago = int(match.group(1))

            return date.today() - timedelta(
                days=days_ago
            )

        # If SerpApi gives us an actual date, try to preserve it.
        try:
            return date.fromisoformat(posted_at)
        except ValueError:
            pass

        # Unknown/unparseable posting-date format.
        return None

    def _get_salary(self, result: dict) -> str:

        detected_extensions = result.get(
            "detected_extensions",
            {}
        )

        return detected_extensions.get(
            "salary",
            ""
        )