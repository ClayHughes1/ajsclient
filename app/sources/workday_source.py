import asyncio
import re
import httpx

from datetime import datetime, timedelta, timezone

from app.models.job import Job
from app.sources.job_source import JobSource
from app.utils.html_cleaner import clean_html_description
from app.utils.salary_extractor import extract_salary


class WorkdaySource(JobSource):

    def __init__(
        self,
        company_name: str,
        base_url: str,
        posting_age_days: int = 2,
        request_delay_seconds: float = 1.5,
        max_retries: int = 1
    ):
        self.company_name = company_name
        self.base_url = base_url.rstrip("/")
        self.posting_age_days = posting_age_days

        self.request_delay_seconds = (
            request_delay_seconds
        )

        self.max_retries = max_retries

        # ---------------------------------------------------------
        # Async HTTP client.
        #
        # The client is created once and reused for all requests
        # made by this WorkdaySource instance.
        # ---------------------------------------------------------

        self.session = httpx.AsyncClient(
            timeout=30.0,
            headers={
                "Accept": "application/json",
                "User-Agent": (
                    "Mozilla/5.0 "
                    "(Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 "
                    "(KHTML, like Gecko) "
                    "Chrome/140.0 Safari/537.36"
                )
            }
        )

        # ---------------------------------------------------------
        # Limit concurrent detail requests.
        #
        # This prevents one Workday company from generating a
        # large burst of requests.
        # ---------------------------------------------------------

        self.detail_semaphore = asyncio.Semaphore(5)

        # ---------------------------------------------------------
        # Parse Workday URL.
        # ---------------------------------------------------------

        (
            self.tenant,
            self.site,
            self.locale
        ) = self._parse_base_url()

        self.origin = self._get_origin()

        self.jobs_url = (
            f"{self.origin}"
            f"/wday/cxs/"
            f"{self.tenant}/"
            f"{self.site}/jobs"
        )

    # =============================================================
    # CLOSE
    # =============================================================

    async def close(self):
        """
        Close the reusable async HTTP client.
        """

        if not self.session.is_closed:

            await self.session.aclose()

    # =============================================================
    # SEARCH
    # =============================================================

    async def search(
        self,
        search_terms: list[str] | None = None
    ) -> list[Job]:

        jobs = []

        search_terms = self._normalize_search_terms(
            search_terms
        )

        offset = 0
        limit = 20

        while True:

            payload = {
                "appliedFacets": {},
                "limit": limit,
                "offset": offset
            }

            try:

                response = await self._request(
                    "POST",
                    self.jobs_url,
                    json=payload,
                    headers={
                        "Content-Type": "application/json"
                    }
                )

                data = response.json()

            except httpx.RequestError as error:

                print(
                    f"Workday request failed for "
                    f"{self.company_name}: {error}"
                )

                return jobs

            except ValueError as error:

                print(
                    f"Workday returned invalid JSON for "
                    f"{self.company_name}: {error}"
                )

                return jobs

            job_postings = data.get(
                "jobPostings",
                []
            )

            if not job_postings:
                break

            # -----------------------------------------------------
            # Perform inexpensive local filtering first.
            #
            # We do NOT request job details until a posting:
            #
            #   1. Is recent
            #   2. Has a title
            #   3. Matches the configured search terms
            # -----------------------------------------------------

            matching_items = []

            for item in job_postings:

                # -------------------------------------------------
                # 1. Posting age filter.
                # -------------------------------------------------

                if not self._posting_is_recent(
                    item
                ):
                    continue

                # -------------------------------------------------
                # 2. Extract title.
                # -------------------------------------------------

                title = self._get_string(
                    item.get("title")
                )

                if not title:
                    continue

                # -------------------------------------------------
                # 3. Search-term/title filter.
                # -------------------------------------------------

                if not self._title_matches_search_terms(
                    title,
                    search_terms
                ):
                    continue

                matching_items.append(
                    item
                )

            # -----------------------------------------------------
            # Retrieve matching job details concurrently.
            # -----------------------------------------------------

            if matching_items:

                detail_tasks = [
                    self._normalize_job_async(
                        item
                    )
                    for item in matching_items
                ]

                detail_results = await asyncio.gather(
                    *detail_tasks,
                    return_exceptions=True
                )

                for job in detail_results:

                    if isinstance(
                        job,
                        Exception
                    ):

                        print(
                            f"Workday detail request failed "
                            f"for {self.company_name}: "
                            f"{job}"
                        )

                        continue

                    if job:
                        jobs.append(job)

            # -----------------------------------------------------
            # Pagination.
            # -----------------------------------------------------

            offset += limit

            total = data.get(
                "total"
            )

            if total is not None:

                if offset >= total:
                    break

            # -----------------------------------------------------
            # If Workday returned fewer than requested, there is
            # normally no additional page.
            # -----------------------------------------------------

            if len(job_postings) < limit:
                break

        # print(
        #     f"Workday returned {len(jobs)} matching jobs "
        #     f"for {self.company_name}."
        # )

        return jobs

    # =============================================================
    # NORMALIZE JOB
    # =============================================================

    async def _normalize_job_async(
        self,
        item: dict
    ) -> Job | None:

        title = self._get_string(
            item.get("title")
        )

        if not title:
            return None

        external_path = self._get_string(
            item.get("externalPath")
        )

        if not external_path:
            return None

        # ---------------------------------------------------------
        # Job ID
        # ---------------------------------------------------------

        job_id = self._extract_job_id(
            external_path
        )

        # ---------------------------------------------------------
        # Location
        # ---------------------------------------------------------

        location = self._get_string(
            item.get("locationsText")
        )

        # ---------------------------------------------------------
        # Posting date
        # ---------------------------------------------------------

        posting_date = self._parse_posted_on(
            item.get("postedOn")
        )

        if self.posting_age_days is not None:

            if posting_date is None:
                return None

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
                return None

        # ---------------------------------------------------------
        # Public posting URL
        # ---------------------------------------------------------

        posting_url = (
            f"{self.origin}"
            f"{external_path}"
        )

        # ---------------------------------------------------------
        # Retrieve full job detail asynchronously.
        # ---------------------------------------------------------

        detail = await self._get_job_detail(
            external_path
        )

        # ---------------------------------------------------------
        # Resolve actual locations.
        # ---------------------------------------------------------

        location = self._extract_locations(
            item,
            detail
        )

        description = ""
        employment_type = ""
        salary = ""
        apply_url = posting_url

        if detail:

            job_info = detail.get(
                "jobPostingInfo",
                {}
            )

            description = clean_html_description(
                self._get_string(
                    job_info.get(
                        "jobDescription"
                    )
                )
            )

            employment_type = self._get_string(
                job_info.get(
                    "timeType"
                )
            )

            salary = self._get_string(
                job_info.get(
                    "salary"
                )
            )

            apply_url = (
                self._get_string(
                    job_info.get(
                        "applyUrl"
                    )
                )
                or self._get_string(
                    job_info.get(
                        "externalApplicationUrl"
                    )
                )
                or posting_url
            )

        # ---------------------------------------------------------
        # Salary fallback.
        # ---------------------------------------------------------

        if not salary:

            salary = extract_salary(
                description
            )

        return Job(
            company=self.company_name,
            title=title,
            location=location,
            posting_url=posting_url,
            description=description,
            posting_date=posting_date,
            salary=salary,
            source="Workday",
            apply_url=apply_url,
            employment_type=employment_type,
            job_id=job_id
        )

    # =============================================================
    # JOB DETAIL
    # =============================================================

    # async def _get_job_detail(
    #     self,
    #     external_path: str
    # ) -> dict | None:

    #     detail_url = (
    #         f"{self.origin}"
    #         f"/wday/cxs/"
    #         f"{self.tenant}/"
    #         f"{self.site}"
    #         f"{external_path}"
    #     )

    #     try:

    #         async with self._detail_slot():

    #             response = await self._request(
    #                 "GET",
    #                 detail_url
    #             )

    #         return response.json()

    #     except httpx.RequestError as error:

    #         print(
    #             f"Workday detail request failed for "
    #             f"{self.company_name}: {error}"
    #         )

    #         return None

    #     except ValueError as error:

    #         print(
    #             f"Workday detail returned invalid JSON for "
    #             f"{self.company_name}: {error}"
    #         )

    #         return None

    async def _get_job_detail(
        self,
        external_path: str
    ) -> dict | None:

        detail_url = (
            f"{self.origin}"
            f"/wday/cxs/"
            f"{self.tenant}/"
            f"{self.site}"
            f"{external_path}"
        )

        try:

            async with self.detail_semaphore:

                response = await self._request(
                    "GET",
                    detail_url
                )

            return response.json()

        except httpx.RequestError as error:

            print(
                f"Workday detail request failed for "
                f"{self.company_name}: {error}"
            )

            return None

        except ValueError as error:

            print(
                f"Workday detail returned invalid JSON for "
                f"{self.company_name}: {error}"
            )

            return None


    # =============================================================
    # DETAIL REQUEST CONCURRENCY
    # =============================================================

    class _detail_slot:

        def __init__(self):
            self.source = None

        async def __aenter__(self):
            return self

        async def __aexit__(
            self,
            exc_type,
            exc,
            traceback
        ):
            return False

    # =============================================================
    # HTTP REQUEST
    # =============================================================

    async def _request(
        self,
        method: str,
        url: str,
        **kwargs
    ):

        for attempt in range(
            self.max_retries + 1
        ):

            try:

                response = await self.session.request(
                    method,
                    url,
                    **kwargs
                )

                # -------------------------------------------------
                # 429 = rate limited.
                # -------------------------------------------------

                if response.status_code == 429:

                    if attempt >= self.max_retries:
                        response.raise_for_status()

                    retry_after = response.headers.get(
                        "Retry-After"
                    )

                    if retry_after:

                        try:

                            wait_seconds = float(
                                retry_after
                            )

                        except ValueError:

                            wait_seconds = (
                                2 ** attempt
                            )

                    else:

                        wait_seconds = (
                            2 ** attempt
                        )

                    print(
                        f"Workday rate limit (429) for "
                        f"{self.company_name}. "
                        f"Waiting {wait_seconds} seconds..."
                    )

                    await asyncio.sleep(
                        wait_seconds
                    )

                    continue

                # -------------------------------------------------
                # 4xx errors other than 429.
                # -------------------------------------------------

                if 400 <= response.status_code < 500:

                    response.raise_for_status()

                # -------------------------------------------------
                # 5xx errors.
                # -------------------------------------------------

                if 500 <= response.status_code <= 599:

                    if attempt >= self.max_retries:
                        response.raise_for_status()

                    wait_seconds = (
                        2 ** attempt
                    )

                    print(
                        f"Workday server error "
                        f"({response.status_code}) for "
                        f"{self.company_name}. "
                        f"Retrying in {wait_seconds} seconds..."
                    )

                    await asyncio.sleep(
                        wait_seconds
                    )

                    continue

                response.raise_for_status()

                return response

            except httpx.RequestError as error:

                if attempt >= self.max_retries:
                    raise

                wait_seconds = (
                    2 ** attempt
                )

                print(
                    f"Workday connection error for "
                    f"{self.company_name}: "
                    f"{error}. "
                    f"Retrying in {wait_seconds} seconds..."
                )

                await asyncio.sleep(
                    wait_seconds
                )

        return None

    # =============================================================
    # POSTING AGE
    # =============================================================

    def _posting_is_recent(
        self,
        item: dict
    ) -> bool:

        if self.posting_age_days is None:
            return True

        posting_date = self._parse_posted_on(
            item.get("postedOn")
        )

        if posting_date is None:
            return False

        now = datetime.now(
            timezone.utc
        )

        cutoff_date = (
            now -
            timedelta(
                days=self.posting_age_days
            )
        )

        return posting_date >= cutoff_date

    # =============================================================
    # TITLE FILTER
    # =============================================================

    @staticmethod
    def _normalize_search_terms(
        search_terms: list[str] | None
    ) -> list[str]:

        if not search_terms:
            return []

        normalized = []

        for term in search_terms:

            if term is None:
                continue

            term = str(
                term
            ).strip().lower()

            if term and term not in normalized:
                normalized.append(
                    term
                )

        return normalized

    @staticmethod
    def _title_matches_search_terms(
        title: str,
        search_terms: list[str]
    ) -> bool:

        if not search_terms:
            return True

        title_lower = title.lower()

        for search_term in search_terms:

            # -----------------------------------------------------
            # Direct phrase match.
            # -----------------------------------------------------

            if search_term in title_lower:
                return True

            # -----------------------------------------------------
            # All words in the search term must appear.
            # -----------------------------------------------------

            words = search_term.split()

            if all(
                word in title_lower
                for word in words
            ):
                return True

        return False

    # =============================================================
    # URL PARSING
    # =============================================================

    def _parse_base_url(self):

        match = re.match(
            r"https://"
            r"(?P<tenant>[^.]+)"
            r"\.(?P<shard>wd\d+)"
            r"\.myworkdayjobs\.com"
            r"(?:/(?P<locale>[^/]+))?"
            r"/(?P<site>[^/?#]+)",
            self.base_url,
            re.IGNORECASE
        )

        if not match:

            raise ValueError(
                "Invalid Workday base URL: "
                f"{self.base_url}"
            )

        tenant = match.group(
            "tenant"
        )

        site = match.group(
            "site"
        )

        locale = match.group(
            "locale"
        ) or ""

        return (
            tenant,
            site,
            locale
        )

    def _get_origin(self):

        match = re.match(
            r"(https://"
            r"[^/]+)",
            self.base_url
        )

        if not match:

            raise ValueError(
                "Unable to determine Workday origin "
                f"from URL: {self.base_url}"
            )

        return match.group(1)

    # =============================================================
    # HELPERS
    # =============================================================

    @staticmethod
    def _get_string(
        value
    ) -> str:

        if value is None:
            return ""

        return str(
            value
        ).strip()

    @staticmethod
    def _extract_job_id(
        external_path: str
    ) -> str:

        match = re.search(
            r"(JR\d+|R-\d+)",
            external_path,
            re.IGNORECASE
        )

        if match:
            return match.group(1)

        return ""

    @staticmethod
    def _parse_posted_on(
        value
    ) -> datetime | None:

        if not value:
            return None

        value = str(
            value
        ).strip().lower()

        now = datetime.now(
            timezone.utc
        )

        if "today" in value:
            return now

        if "yesterday" in value:
            return (
                now -
                timedelta(days=1)
            )

        match = re.search(
            r"(\d+)\s+day[s]?\s+ago",
            value
        )

        if match:

            days_ago = int(
                match.group(1)
            )

            return (
                now -
                timedelta(days=days_ago)
            )

        return None

    def _extract_locations(
        self,
        item: dict,
        detail: dict | None
    ) -> str:

        location_text = self._get_string(
            item.get("locationsText")
        )

        if not detail:
            return location_text

        job_info = detail.get(
            "jobPostingInfo",
            {}
        )

        locations = []

        primary_location = self._get_string(
            job_info.get("location")
        )

        if primary_location:
            locations.append(
                primary_location
            )

        additional_locations = job_info.get(
            "additionalLocations",
            []
        )

        if isinstance(
            additional_locations,
            list
        ):

            for location in additional_locations:

                location = self._get_string(
                    location
                )

                if (
                    location
                    and location not in locations
                ):

                    locations.append(
                        location
                    )

        if locations:

            return "; ".join(
                locations
            )

        return location_text
