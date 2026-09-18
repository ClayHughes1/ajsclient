import asyncio

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
        results_wanted: int = 50,
    ):

        self.location = location
        self.sites = sites
        self.posting_age_days = posting_age_days
        self.results_wanted = results_wanted

        #Original working right now
        # self.location = location

        # self.sites = sites or [
        #     "indeed",
        #     "linkedin"
        # ]

        # self.posting_age_days = posting_age_days
        # self.results_wanted = results_wanted

    #Original working right now
    def search(
        self,
        search_term: str = ""
    ) -> list[Job]:

        if not search_term.strip():
            return []

        jobs = []

        for site in self.sites:

            try:

                # print(
                #     f"JobSpy {site} search: "
                #     f"{search_term}"
                # )

                jobs_dataframe = scrape_jobs(
                    site_name=[site],
                    search_term=search_term,
                    location=self.location,
                    results_wanted=self.results_wanted,

                    hours_old=(
                        self.posting_age_days * 24
                        if self.posting_age_days is not None
                        else None
                    ),

                    country_indeed="USA",
                    description_format="markdown",

                    linkedin_fetch_description=False,

                    verbose=0,
                )

            except Exception as e:

                print(
                    f"JobSpy {site} FAILED for "
                    f"'{search_term}': "
                    f"{type(e).__name__}: {e}"
                )

                continue

            if jobs_dataframe.empty:
                continue

            # print(
            #     f"{site}      "
            #     f"{len(jobs_dataframe)}"
            # )

            for _, item in jobs_dataframe.iterrows():

                # -------------------------------------------------
                # Posting date
                # -------------------------------------------------

                posting_date = self._parse_posting_date(
                    item.get("date_posted")
                )

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
                # -------------------------------------------------

                apply_url = self._get_string(
                    item.get("job_url_direct")
                )

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

                location = self._get_string(
                    item.get("location")
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

    async def search_all(
        self,
        search_terms: list[str],
        max_concurrency: int = 10,
    ) -> list[Job]:

        # ---------------------------------------------------------
        # Normalize and remove duplicate search terms.
        # ---------------------------------------------------------

        normalized_terms = []
        seen_terms = set()

        for term in search_terms:

            if not term:
                continue

            term = term.strip()

            if not term:
                continue

            term_key = term.lower()

            if term_key in seen_terms:
                continue

            seen_terms.add(
                term_key
            )

            normalized_terms.append(
                term
            )

        if not normalized_terms:
            return []

        # ---------------------------------------------------------
        # Limit the number of synchronous JobSpy searches running
        # simultaneously.
        # ---------------------------------------------------------

        semaphore = asyncio.Semaphore(
            max_concurrency
        )

        async def run_search(
            search_term: str
        ):

            async with semaphore:

                # print(
                #     f"Starting JobSpy search: "
                #     f"{search_term}"
                # )

                try:

                    return await asyncio.to_thread(
                        self.search,
                        search_term
                    )

                except Exception as error:

                    print(
                        f"JobSpy search FAILED for "
                        f"'{search_term}': "
                        f"{type(error).__name__}: {error}"
                    )

                    return []

        # ---------------------------------------------------------
        # Start all searches concurrently.
        #
        # The semaphore controls how many actually execute at once.
        # ---------------------------------------------------------

        results = await asyncio.gather(
            *(
                run_search(term)
                for term in normalized_terms
            )
        )

        # ---------------------------------------------------------
        # Combine results.
        # ---------------------------------------------------------

        jobs = []

        for result in results:

            if result:
                jobs.extend(
                    result
                )

        return jobs


    # async def search_all(
    #         self,
    #         search_terms: list[str],
    #         max_concurrency: int = 4,
    #     ) -> list[Job]:

    #         semaphore = asyncio.Semaphore(
    #             max_concurrency
    #         )

    #         async def run_search(search_term):

    #             if not search_term.strip():
    #                 return []

    #             async with semaphore:

    #                 return await asyncio.to_thread(
    #                     self.search,
    #                     search_term
    #                 )

    #         tasks = [
    #             run_search(search_term)
    #             for search_term in search_terms
    #             if search_term.strip()
    #         ]

    #         results = await asyncio.gather(
    #             *tasks,
    #             return_exceptions=True,
    #         )

    #         jobs = []

    #         for search_term, result in zip(
    #             [
    #                 term
    #                 for term in search_terms
    #                 if term.strip()
    #             ],
    #             results,
    #         ):

    #             if isinstance(result, Exception):

    #                 print(
    #                     f"JobSpy search FAILED for "
    #                     f"'{search_term}': "
    #                     f"{type(result).__name__}: {result}"
    #                 )

    #                 continue

    #             if result:
    #                 jobs.extend(result)

    #         return jobs

    #Probably needs ot be deleted dplicate mehtod
    # def search(
    #     self,
    #     search_term: str = ""
    # ) -> list[Job]:

    #     if not search_term.strip():
    #         return []

    #     jobs = []

    #     for site in self.sites:

    #         try:

    #             jobs_dataframe = scrape_jobs(
    #                 site_name=[site],
    #                 search_term=search_term,
    #                 location=self.location,
    #                 results_wanted=self.results_wanted,

    #                 hours_old=(
    #                     self.posting_age_days * 24
    #                     if self.posting_age_days is not None
    #                     else None
    #                 ),

    #                 country_indeed="USA",
    #                 description_format="markdown",
    #                 linkedin_fetch_description=False,
    #                 verbose=0,
    #             )

    #         except Exception as e:

    #             print(
    #                 f"JobSpy {site} FAILED for "
    #                 f"'{search_term}': "
    #                 f"{type(e).__name__}: {e}"
    #             )

    #             continue

    #         if jobs_dataframe.empty:
    #             continue

    #         print(
    #             f"JobSpy | "
    #             f"site={site} | "
    #             f"term={search_term} | "
    #             f"jobs={len(jobs_dataframe)}"
    #         )

    #         for _, item in jobs_dataframe.iterrows():

    #             posting_date = self._parse_posting_date(
    #                 item.get("date_posted")
    #             )

    #             if self.posting_age_days is not None:

    #                 if posting_date is None:
    #                     continue

    #                 now = datetime.now(
    #                     timezone.utc
    #                 )

    #                 cutoff_date = (
    #                     now -
    #                     timedelta(
    #                         days=self.posting_age_days
    #                     )
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

    #             job_id = self._get_string(
    #                 item.get("id")
    #             )

    #             apply_url = self._get_string(
    #                 item.get("job_url_direct")
    #             )

    #             employment_type = self._get_string(
    #                 item.get("job_type")
    #             )

    #             description = clean_html_description(
    #                 self._get_string(
    #                     item.get("description")
    #                 )
    #             )

    #             salary = extract_salary(
    #                 description
    #             )

    #             location = self._get_string(
    #                 item.get("location")
    #             )

    #             source = self._get_source(
    #                 item
    #             )

    #             jobs.append(
    #                 Job(
    #                     company=company,
    #                     title=title,
    #                     location=location,
    #                     posting_url=posting_url,
    #                     description=description,
    #                     posting_date=posting_date,
    #                     salary=salary,
    #                     source=source,
    #                     apply_url=apply_url or "",
    #                     employment_type=employment_type,
    #                     job_id=job_id,
    #                 )
    #             )

    #     return jobs

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

