import requests

from time import sleep
from datetime import datetime
from typing import Optional

from app.models.job import Job
from app.sources.job_source import JobSource
from app.utils.html_cleaner import clean_html_description
from app.utils.salary_extractor import extract_salary


class AshbySource(JobSource):

    BASE_URL = (
        "https://api.ashbyhq.com/"
        "posting-api/job-board"
    )

    def __init__(
        self,
        company_name: str,
        job_board: str,
        posting_age_days: int,
        request_delay_seconds: int = 10
    ):
        self.company_name = company_name
        self.job_board = job_board
        self.posting_age_days = posting_age_days
        self.request_delay_seconds = request_delay_seconds

    # =============================================================
    # SEARCH
    # =============================================================

    def search(
        self,
        search_term: Optional[str] = None
    ) -> list[Job]:

        try:

            jobs = self._get_jobs(
                company_name=self.company_name,
                job_board=self.job_board,
                search_term=search_term
            )

            print(
                f"Ashby returned "
                f"{len(jobs)} jobs "
                f"for {self.company_name}"
            )

            return jobs

        except requests.RequestException as error:

            print(
                f"Ashby request failed for "
                f"{self.company_name}: {error}"
            )

            return []

        except Exception as error:

            print(
                f"Unexpected error processing "
                f"{self.company_name}: {error}"
            )

            return []

        finally:

            sleep(
                self.request_delay_seconds
            )

    # =============================================================
    # GET JOBS
    # =============================================================

    def _get_jobs(
        self,
        company_name: str,
        job_board: str,
        search_term: Optional[str] = None
    ) -> list[Job]:

        url = (
            f"{self.BASE_URL}/{job_board}"
        )

        response = requests.get(
            url,
            timeout=30
        )

        response.raise_for_status()

        data = response.json()

        postings = data.get(
            "jobs",
            []
        )

        jobs = []

        for posting in postings:

            job = self._normalize_job(
                posting=posting,
                company_name=company_name,
                search_term=search_term
            )

            if job:

                jobs.append(job)

        return jobs

    # =============================================================
    # NORMALIZE JOB
    # =============================================================

    def _normalize_job(
        self,
        posting: dict,
        company_name: str,
        search_term: Optional[str] = None
    ) -> Job | None:

        # ---------------------------------------------------------
        # Title
        # ---------------------------------------------------------

        title = posting.get(
            "title",
            ""
        )

        # ---------------------------------------------------------
        # Description
        #
        # Preserves the original logic exactly.
        # ---------------------------------------------------------

        description = (
            posting.get(
                "descriptionPlain"
            )
            or posting.get(
                "descriptionHtml"
            )
            or ""
        )

        # ---------------------------------------------------------
        # Search filtering
        #
        # Preserves the original logic exactly.
        # ---------------------------------------------------------

        if search_term:

            searchable_text = (
                f"{title} {description}"
            ).lower()

            if (
                search_term.lower()
                not in searchable_text
            ):
                return None

        # ---------------------------------------------------------
        # Location
        # ---------------------------------------------------------

        location = self._extract_location(
            posting
        )

        # ---------------------------------------------------------
        # Posting URL
        # ---------------------------------------------------------

        posting_url = (
            posting.get("jobUrl")
            or posting.get("applyUrl")
            or ""
        )

        # ---------------------------------------------------------
        # Posting date
        # ---------------------------------------------------------

        posting_date = self._parse_posting_date(
            posting.get("publishedAt")
            or posting.get("createdAt")
        )

        # ---------------------------------------------------------
        # Salary
        #
        # Try salary/compensation returned directly by Ashby first.
        # ---------------------------------------------------------

        salary = self._extract_salary_from_posting(
            posting
        )

        # ---------------------------------------------------------
        # Salary fallback
        #
        # Match the Workday approach.
        # ---------------------------------------------------------

        if not salary:

            clean_description = clean_html_description(
                description
            )

            salary = extract_salary(
                clean_description
            )

        # ---------------------------------------------------------
        # Create Job
        #
        # company_name is explicitly passed into this method,
        # preserving the original working logic.
        # ---------------------------------------------------------

        return Job(
            title=title,
            company=company_name,
            location=location,
            description=description,
            posting_url=posting_url,
            posting_date=posting_date,
            salary=salary,
            source="ashby"
        )

    # =============================================================
    # ASHBY SALARY
    # =============================================================

    def _extract_salary_from_posting(
        self,
        posting: dict
    ) -> str:

        # ---------------------------------------------------------
        # Direct salary field.
        # ---------------------------------------------------------

        salary = posting.get(
            "salary"
        )

        if salary:

            return str(
                salary
            ).strip()

        # ---------------------------------------------------------
        # Compensation object.
        # ---------------------------------------------------------

        compensation = posting.get(
            "compensation"
        )

        if isinstance(
            compensation,
            dict
        ):

            for key in [
                "description",
                "summary"
            ]:

                value = compensation.get(
                    key
                )

                if value:

                    return str(
                        value
                    ).strip()

        return ""

    # =============================================================
    # LOCATION
    # =============================================================

    def _extract_location(
        self,
        posting: dict
    ) -> str:

        location = posting.get(
            "location"
        )

        if isinstance(
            location,
            str
        ):

            return location

        if isinstance(
            location,
            dict
        ):

            parts = []

            for key in [
                "name",
                "city",
                "region",
                "country"
            ]:

                value = location.get(
                    key
                )

                if value:

                    parts.append(
                        str(value)
                    )

            return ", ".join(parts)

        workplace_type = posting.get(
            "workplaceType"
        )

        if workplace_type:

            return str(
                workplace_type
            )

        return ""

    # =============================================================
    # POSTING DATE
    # =============================================================

    def _parse_posting_date(
        self,
        date_value
    ) -> Optional[datetime]:

        if not date_value:

            return None

        try:

            if isinstance(
                date_value,
                datetime
            ):

                return date_value

            date_value = date_value.replace(
                "Z",
                "+00:00"
            )

            return datetime.fromisoformat(
                date_value
            )

        except (
            ValueError,
            AttributeError
        ):

            return None


# import requests

# from time import sleep
# from datetime import datetime
# from typing import Optional

# from app.models.job import Job
# from app.sources.job_source import JobSource
# from app.utils.html_cleaner import clean_html_description
# from app.utils.salary_extractor import extract_salary


# class AshbySource(JobSource):

#     BASE_URL = (
#         "https://api.ashbyhq.com/"
#         "posting-api/job-board"
#     )

#     def __init__(
#         self,
#         company_name: str,
#         job_board: str,
#         posting_age_days: int,
#         request_delay_seconds: int = 10
#     ):
#         self.company_name = company_name
#         self.job_board = job_board
#         self.posting_age_days = posting_age_days
#         self.request_delay_seconds = request_delay_seconds

#     def search(
#         self,
#         search_term: Optional[str] = None
#     ) -> list[Job]:

#         try:

#             jobs = self._get_jobs(
#                 company_name=self.company_name,
#                 job_board=self.job_board,
#                 search_term=search_term
#             )

#             print(
#                 f"Ashby returned "
#                 f"{len(jobs)} jobs "
#                 f"for {self.company_name}"
#             )

#             return jobs

#         except requests.RequestException as error:

#             print(
#                 f"Ashby request failed for "
#                 f"{self.company_name}: {error}"
#             )

#             return []

#         except Exception as error:

#             print(
#                 f"Unexpected error processing "
#                 f"{self.company_name}: {error}"
#             )

#             return []

#         finally:

#             sleep(
#                 self.request_delay_seconds
#             )

#     def _get_jobs(
#         self,
#         company_name: str,
#         job_board: str,
#         search_term: Optional[str] = None
#     ) -> list[Job]:

#         url = (
#             f"{self.BASE_URL}/{job_board}"
#         )

#         response = requests.get(
#             url,
#             timeout=30
#         )

#         response.raise_for_status()

#         data = response.json()

#         postings = data.get(
#             "jobs",
#             []
#         )

#         jobs = []

#         for posting in postings:

#             title = posting.get(
#                 "title",
#                 ""
#             )

#             description = (
#                 posting.get(
#                     "descriptionPlain"
#                 )
#                 or posting.get(
#                     "descriptionHtml"
#                 )
#                 or ""
#             )

#             location = self._extract_location(
#                 posting
#             )

#             posting_url = (
#                 posting.get("jobUrl")
#                 or posting.get("applyUrl")
#                 or ""
#             )

#             posting_date = self._parse_posting_date(
#                 posting.get("publishedAt")
#                 or posting.get("createdAt")
#             )

#             if search_term:

#                 searchable_text = (
#                     f"{title} {description}"
#                 ).lower()

#                 if (
#                     search_term.lower()
#                     not in searchable_text
#                 ):
#                     continue

#             jobs.append(
#                 Job(
#                     title=title,
#                     company=company_name,
#                     location=location,
#                     description=description,
#                     posting_url=posting_url,
#                     posting_date=posting_date,
#                     source="ashby"
#                 )
#             )

#         return jobs

#     def _extract_location(
#         self,
#         posting: dict
#     ) -> str:

#         location = posting.get(
#             "location"
#         )

#         if isinstance(location, str):

#             return location

#         if isinstance(location, dict):

#             parts = []

#             for key in [
#                 "name",
#                 "city",
#                 "region",
#                 "country"
#             ]:

#                 value = location.get(
#                     key
#                 )

#                 if value:

#                     parts.append(
#                         str(value)
#                     )

#             return ", ".join(parts)

#         workplace_type = posting.get(
#             "workplaceType"
#         )

#         if workplace_type:

#             return str(workplace_type)

#         return ""

#     def _parse_posting_date(
#         self,
#         date_value
#     ) -> Optional[datetime]:

#         if not date_value:

#             return None

#         try:

#             if isinstance(
#                 date_value,
#                 datetime
#             ):

#                 return date_value

#             date_value = date_value.replace(
#                 "Z",
#                 "+00:00"
#             )

#             return datetime.fromisoformat(
#                 date_value
#             )

#         except (
#             ValueError,
#             AttributeError
#         ):

#             return None