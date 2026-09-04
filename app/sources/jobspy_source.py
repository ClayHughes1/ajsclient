from datetime import datetime, timedelta, timezone

from jobspy import scrape_jobs

from app.models.job import Job
from app.sources.job_source import JobSource
from app.utils.html_cleaner import clean_html_description
from app.utils.salary_extractor import extract_salary


class JobSpySource(JobSource):

    def __init__(
        self,
        location: str = "",
        sites: list[str] | None = None,
        posting_age_days: int = 1,
        results_wanted: int = 25,
    ):
        self.location = location

        self.sites = sites or [
            "indeed",
            "linkedin"
        ]

        self.posting_age_days = posting_age_days
        self.results_wanted = results_wanted

    def search(
        self,
        search_term: str = ""
    ) -> list[Job]:

        if not search_term.strip():
            return []

        jobs_dataframe = scrape_jobs(
            site_name=self.sites,
            search_term=search_term,
            location=self.location,
            results_wanted=self.results_wanted,

            # Only retrieve jobs posted within the
            # previous 24 hours.
            hours_old=(
                self.posting_age_days * 24
                if self.posting_age_days is not None
                else None
            ),

            country_indeed="USA",
            description_format="markdown",

            # Do not make additional LinkedIn requests
            # to retrieve full descriptions/direct URLs.
            linkedin_fetch_description=False,

            verbose=0,
        )

        print(
            f"JobSpy returned {len(jobs_dataframe)} raw jobs "
            f"for '{search_term}'"
        )

        if not jobs_dataframe.empty:

            print(
                jobs_dataframe["site"]
                .value_counts()
                .to_string()
            )

        jobs = []

        for _, item in jobs_dataframe.iterrows():

            # -------------------------------------------------
            # Posting date
            # -------------------------------------------------

            posting_date = self._parse_posting_date(
                item.get("date_posted")
            )

            # Apply the same posting-age validation
            # after retrieval.
            if self.posting_age_days is not None:

                if posting_date is None:
                    continue

                now = datetime.now(
                    timezone.utc
                )

                cutoff_date = (
                    now -
                    timedelta(
                        days=self.posting_age_days
                    )
                )

                if posting_date < cutoff_date:
                    continue

            # -------------------------------------------------
            # Basic fields
            # -------------------------------------------------

            title = self._get_string(
                item.get("title")
            )

            company = self._get_string(
                item.get("company")
            )

            posting_url = self._get_string(
                item.get("job_url")
            )

            if not title:
                continue

            if not company:
                continue

            if not posting_url:
                continue

            # -------------------------------------------------
            # Job ID
            # -------------------------------------------------

            job_id = self._get_string(
                item.get("id")
            )

            # -------------------------------------------------
            # Direct application URL
            #
            # JobSpy may provide job_url_direct for sources
            # where a direct employer/application URL is
            # available.
            # -------------------------------------------------

            apply_url = self._get_string(
                item.get("job_url_direct")
            )

            # If JobSpy doesn't provide a direct URL,
            # leave apply_url blank rather than incorrectly
            # assuming the posting URL is an application URL.
            if not apply_url:
                apply_url = ""

            # -------------------------------------------------
            # Employment type
            # -------------------------------------------------

            employment_type = self._get_string(
                item.get("job_type")
            )

            # -------------------------------------------------
            # Description
            # -------------------------------------------------

            description = clean_html_description(
                self._get_string(
                    item.get("description")
                )
            )

            # -------------------------------------------------
            # Salary
            # -------------------------------------------------

            salary = extract_salary(
                description
            )

            # -------------------------------------------------
            # Location
            # -------------------------------------------------

            location = self._build_location(
                item
            )

            # -------------------------------------------------
            # Source
            # -------------------------------------------------

            source = self._get_source(
                item
            )

            # -------------------------------------------------
            # Create common Job object
            # -------------------------------------------------

            job = Job(
                company=company,
                title=title,
                location=location,
                posting_url=posting_url,
                description=description,
                posting_date=posting_date,
                salary=salary,
                source=source,
                apply_url=apply_url,
                employment_type=employment_type,
                job_id=job_id
            )

            jobs.append(job)

        return jobs

    @staticmethod
    def _parse_posting_date(
        value
    ) -> datetime | None:

        if value is None:
            return None

        if isinstance(value, datetime):

            if value.tzinfo is None:

                return value.replace(
                    tzinfo=timezone.utc
                )

            return value

        value = str(
            value
        ).strip()

        if not value:
            return None

        try:

            parsed = datetime.fromisoformat(
                value.replace(
                    "Z",
                    "+00:00"
                )
            )

            if parsed.tzinfo is None:

                parsed = parsed.replace(
                    tzinfo=timezone.utc
                )

            return parsed

        except ValueError:

            return None

    @staticmethod
    def _get_string(
        value
    ) -> str:

        if value is None:
            return ""

        return str(
            value
        ).strip()

    def _build_location(
        self,
        item
    ) -> str:

        city = self._get_string(
            item.get("city")
        )

        state = self._get_string(
            item.get("state")
        )

        country = self._get_string(
            item.get("country")
        )

        parts = [
            value
            for value in [
                city,
                state,
                country
            ]
            if value
        ]

        return ", ".join(
            parts
        )

    def _get_source(
        self,
        item
    ) -> str:

        source = self._get_string(
            item.get("site")
        )

        return source or "JobSpy"



# from datetime import datetime, timedelta, timezone

# from jobspy import scrape_jobs

# from app.models.job import Job
# from app.sources.job_source import JobSource
# from app.utils.html_cleaner import clean_html_description
# from app.utils.salary_extractor import extract_salary


# class JobSpySource(JobSource):

#     def __init__(
#         self,
#         location: str = "",
#         sites: list[str] | None = None,
#         posting_age_days: int = 1,
#         results_wanted: int = 25,
#     ):
#         self.location = location

#         self.sites = sites or [
#             "indeed",
#             "linkedin"
#         ]

#         self.posting_age_days = posting_age_days
#         self.results_wanted = results_wanted

#     def search(self, search_term: str = "") -> list[Job]:

#         if not search_term.strip():
#             return []

#         jobs_dataframe = scrape_jobs(
#             site_name=self.sites,
#             search_term=search_term,
#             location=self.location,
#             results_wanted=self.results_wanted,

#             # Only retrieve jobs posted within the
#             # previous 24 hours.
#             hours_old=(
#                 self.posting_age_days * 24
#                 if self.posting_age_days is not None
#                 else None
#             ),

#             country_indeed="USA",
#             description_format="markdown",

#             # Do not make additional LinkedIn requests
#             # to retrieve full descriptions/direct URLs.
#             linkedin_fetch_description=False,

#             verbose=0,
#         )

#         print(
#             f"JobSpy returned {len(jobs_dataframe)} raw jobs "
#             f"for '{search_term}'"
#         )

#         if not jobs_dataframe.empty:
#             print(
#                 jobs_dataframe["site"]
#                 .value_counts()
#                 .to_string()
#             )

#         jobs = []

#         for _, item in jobs_dataframe.iterrows():

#             posting_date = self._parse_posting_date(
#                 item.get("date_posted")
#             )

#             # Apply the same posting-age validation
#             # after retrieval.
#             if self.posting_age_days is not None:

#                 if posting_date is None:
#                     continue

#                 now = datetime.now(timezone.utc)

#                 cutoff_date = (
#                     now
#                     - timedelta(days=self.posting_age_days)
#                 )

#                 if posting_date < cutoff_date:
#                     continue

#             title = self._get_string(
#                 item.get("title")
#             )

#             company = self._get_string(
#                 item.get("company")
#             )

#             posting_url = self._get_string(
#                 item.get("job_url")
#             )

#             if not title:
#                 continue

#             if not company:
#                 continue

#             if not posting_url:
#                 continue

#             description = clean_html_description(
#                 self._get_string(
#                     item.get("description")
#                 )
#             )

#             salary = extract_salary(
#                 description
#             )

#             location = self._build_location(
#                 item
#             )

#             job = Job(
#                 company=company,
#                 title=title,
#                 location=location,
#                 posting_url=posting_url,
#                 description=description,
#                 posting_date=posting_date,
#                 salary=salary,
#                 source=self._get_source(item),
#             )

#             # print("\n--- JobSpy Job Created ---")
#             # print(f"Company: {job.company}")
#             # print(f"Title: {job.title}")
#             # print(f"Location: {job.location}")
#             # print(f"Posting URL: {job.posting_url}")
#             # print(f"Posting Date: {job.posting_date}")
#             # print(f"Salary: {job.salary}")
#             # print(f"Source: {job.source}")
#             # print("--------------------------\n")

#             jobs.append(job)

#         return jobs

#     @staticmethod
#     def _parse_posting_date(
#         value
#     ) -> datetime | None:

#         if value is None:
#             return None

#         if isinstance(value, datetime):

#             if value.tzinfo is None:
#                 return value.replace(
#                     tzinfo=timezone.utc
#                 )

#             return value

#         value = str(value).strip()

#         if not value:
#             return None

#         try:

#             parsed = datetime.fromisoformat(
#                 value.replace("Z", "+00:00")
#             )

#             if parsed.tzinfo is None:
#                 parsed = parsed.replace(
#                     tzinfo=timezone.utc
#                 )

#             return parsed

#         except ValueError:
#             return None

#     @staticmethod
#     def _get_string(value) -> str:

#         if value is None:
#             return ""

#         return str(value).strip()

#     def _build_location(self, item) -> str:

#         city = self._get_string(
#             item.get("city")
#         )

#         state = self._get_string(
#             item.get("state")
#         )

#         country = self._get_string(
#             item.get("country")
#         )

#         parts = [
#             value
#             for value in [
#                 city,
#                 state,
#                 country
#             ]
#             if value
#         ]

#         return ", ".join(parts)

#     def _get_source(self, item) -> str:

#         source = self._get_string(
#             item.get("site")
#         )

#         return source or "JobSpy"

