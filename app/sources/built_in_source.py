import re
import time
import threading

from concurrent.futures import (
    ThreadPoolExecutor,
    as_completed,
)

from datetime import (
    datetime,
    timedelta,
    timezone,
)

from urllib.parse import quote

import requests

from bs4 import BeautifulSoup

from app.models.job import Job
from app.sources.job_source import JobSource
from app.utils.html_cleaner import clean_html_description
from app.utils.salary_extractor import extract_salary


class RateLimiter:
    """
    Global thread-safe request rate limiter.

    Important:
        max_workers controls concurrency.

        requests_per_second controls total request rate.

    Example:

        max_workers=8
        requests_per_second=4

    means up to 8 jobs can be processed concurrently,
    but HTTP requests are still limited to approximately
    4 requests per second globally.
    """

    def __init__(
        self,
        requests_per_second: float = 4.0,
    ):
        if requests_per_second <= 0:
            raise ValueError(
                "requests_per_second must be > 0"
            )

        self.interval = (
            1.0 / requests_per_second
        )

        self.lock = threading.Lock()
        self.last_request_time = 0.0

    def wait(self):
        """
        Wait until the next request is allowed.
        """

        with self.lock:

            now = time.monotonic()

            elapsed = (
                now -
                self.last_request_time
            )

            remaining = (
                self.interval -
                elapsed
            )

            if remaining > 0:

                time.sleep(
                    remaining
                )

            self.last_request_time = (
                time.monotonic()
            )


class BuiltInSource(JobSource):

    def __init__(
        self,
        posting_age_days: int = 2,
        requests_per_second: float = 4.0,
        max_workers: int = 8,
        max_retries: int = 2,
        results_per_page: int = 20,
        max_pages: int = 50,
    ):

        self.posting_age_days = (
            posting_age_days
        )

        self.requests_per_second = (
            requests_per_second
        )

        self.max_workers = max_workers

        self.max_retries = max_retries

        self.results_per_page = (
            results_per_page
        )

        self.max_pages = max_pages

        self.base_url = (
            "https://builtin.com"
        )

        # --------------------------------------------------------
        # Thread-local sessions.
        #
        # requests.Session is not shared between workers.
        # Each worker gets its own connection pool/session.
        # --------------------------------------------------------

        self._thread_local = (
            threading.local()
        )

        # --------------------------------------------------------
        # One global rate limiter.
        # --------------------------------------------------------

        self.rate_limiter = RateLimiter(
            requests_per_second
        )

        # --------------------------------------------------------
        # Current search cutoff.
        # Recalculated for every search().
        # --------------------------------------------------------

        self._cutoff = None

    # ============================================================
    # SEARCH
    # ============================================================

    def search(
        self,
        search_terms: list[str] | None = None,
        location: str | None = None,
    ) -> list[Job]:

        search_terms = (
            self._normalize_search_terms(
                search_terms
            )
        )

        # --------------------------------------------------------
        # Recalculate cutoff for every search.
        # --------------------------------------------------------

        if self.posting_age_days is not None:

            self._cutoff = (
                datetime.now(timezone.utc)
                -
                timedelta(
                    days=self.posting_age_days
                )
            )

        else:

            self._cutoff = None

        print(
            "Built In search starting | "
            f"location={location!r} | "
            f"terms={search_terms or 'BROAD'}"
        )

        # --------------------------------------------------------
        # PHASE 1
        #
        # Discover URLs.
        #
        # Search pages remain sequential because:
        #
        #   - pagination is inherently sequential
        #   - this minimizes pressure on Built In
        #   - one global rate limiter protects requests
        # --------------------------------------------------------

        job_urls = (
            self._discover_jobs(
                location=location,
                search_terms=search_terms,
            )
        )

        print(
            f"Built In discovered "
            f"{len(job_urls)} unique job URLs."
        )

        if not job_urls:
            return []

        # --------------------------------------------------------
        # PHASE 2
        #
        # Fetch individual job pages concurrently.
        # --------------------------------------------------------

        jobs = self._fetch_jobs(
            job_urls=job_urls,
            search_terms=search_terms,
        )

        print(
            f"Built In returned "
            f"{len(jobs)} matching jobs."
        )

        return jobs

    # ============================================================
    # DISCOVER JOBS
    # ============================================================

    def _discover_jobs(
        self,
        location: str | None,
        search_terms: list[str],
    ) -> list[str]:

        discovered = []
        seen = set()

        for page in range(
            1,
            self.max_pages + 1,
        ):

            search_url = (
                self._build_search_url(
                    search_terms=None,
                    location=location,
                    page=page,
                )
            )

            print(
                f"Built In search page "
                f"{page}: {search_url}"
            )

            try:

                response = self._request(
                    "GET",
                    search_url,
                )

            except requests.RequestException as error:

                print(
                    f"Built In search failed "
                    f"on page {page}: "
                    f"{error}"
                )

                break

            soup = BeautifulSoup(
                response.text,
                "html.parser",
            )

            page_links = (
                self._extract_job_links(
                    soup
                )
            )

            if not page_links:

                print(
                    f"Built In page {page}: "
                    "no job links found."
                )

                break

            new_count = 0

            for url in page_links:

                if url in seen:
                    continue

                seen.add(url)
                discovered.append(url)
                new_count += 1

            print(
                f"Built In page {page}: "
                f"{len(page_links)} links | "
                f"{new_count} new"
            )

            # ----------------------------------------------------
            # Stop if this is the final partial page.
            # ----------------------------------------------------

            if (
                len(page_links)
                <
                self.results_per_page
            ):
                break

        return discovered

    # ============================================================
    # FETCH JOBS CONCURRENTLY
    # ============================================================

    def _fetch_jobs(
        self,
        job_urls: list[str],
        search_terms: list[str],
    ) -> list[Job]:

        jobs = []

        print(
            f"Fetching {len(job_urls)} "
            f"unique Built In jobs "
            f"with {self.max_workers} workers..."
        )

        with ThreadPoolExecutor(
            max_workers=self.max_workers
        ) as executor:

            futures = {
                executor.submit(
                    self._get_job,
                    job_url,
                    search_terms,
                ): job_url
                for job_url in job_urls
            }

            for future in as_completed(
                futures
            ):

                job_url = futures[
                    future
                ]

                try:

                    job = future.result()

                except Exception as error:

                    print(
                        f"Built In job failed: "
                        f"{job_url}: {error}"
                    )

                    continue

                if job is not None:
                    jobs.append(job)

        return jobs

    # ============================================================
    # SEARCH URL
    # ============================================================

    def _build_search_url(
        self,
        search_terms: list[str] | None,
        location: str | None,
        page: int,
    ) -> str:

        if search_terms:

            search_text = "-".join(
                search_terms
            )

            search_text = re.sub(
                r"[^a-zA-Z0-9\-]+",
                "-",
                search_text,
            ).strip("-").lower()

            path = (
                f"/jobs/{search_text}"
            )

        else:

            path = "/jobs"

        url = (
            f"{self.base_url}"
            f"{path}"
        )

        params = []

        if location:

            params.append(
                f"location={quote(location)}"
            )

        if page > 1:

            params.append(
                f"page={page}"
            )

        if params:

            url += "?" + "&".join(
                params
            )

        return url

    # ============================================================
    # JOB LINKS
    # ============================================================

    @staticmethod
    def _extract_job_links(
        soup: BeautifulSoup,
    ) -> list[str]:

        links = []
        seen = set()
        base_url = "https://builtin.com"
        for anchor in soup.find_all(
            "a",
            href=True,
        ):

            href = anchor.get("href")

            if not href:
                continue

            # ----------------------------------------------------
            # Normalize query strings/fragments.
            # ----------------------------------------------------

            href = (
                href
                .split("?")[0]
                .split("#")[0]
                .rstrip("/")
            )

            # ----------------------------------------------------
            # Built In job URL:
            #
            # /job/software-engineer/123456
            # ----------------------------------------------------

            if not re.match(
                r"^/job/"
                r"[^/]+/"
                r"\d+$",
                href,
            ):
                continue

            if href in seen:
                continue

            seen.add(href)

            links.append(f"{base_url}{href}")

        return links

    # ============================================================
    # JOB
    # ============================================================

    def _get_job(
        self,
        job_url: str,
        search_terms: list[str],
    ) -> Job | None:

        try:

            response = self._request(
                "GET",
                job_url,
            )

        except requests.RequestException as error:

            print(
                f"Built In job request failed: "
                f"{job_url}: {error}"
            )

            return None

        soup = BeautifulSoup(
            response.text,
            "html.parser",
        )

        # --------------------------------------------------------
        # Extract page text ONCE.
        #
        # This avoids repeatedly traversing the entire DOM.
        # --------------------------------------------------------

        page_text = soup.get_text(
            " ",
            strip=True,
        )

        page_text_lower = page_text.lower()

        # --------------------------------------------------------
        # TITLE
        # --------------------------------------------------------

        title = self._extract_title(
            soup
        )

        if not title:
            return None

        # --------------------------------------------------------
        # TITLE FILTER
        #
        # Extremely cheap compared with full extraction.
        # --------------------------------------------------------

        if not self._title_matches_search_terms(
            title,
            search_terms,
        ):
            return None

        # --------------------------------------------------------
        # POSTING DATE
        #
        # Reject old jobs before description processing.
        # --------------------------------------------------------

        posting_date = (
            self._extract_posting_date(
                page_text_lower
            )
        )

        if self._cutoff is not None:

            if posting_date is None:
                return None

            if posting_date < self._cutoff:
                return None

        # --------------------------------------------------------
        # COMPANY
        # --------------------------------------------------------

        company = self._extract_company(
            soup
        )

        if not company:
            return None

        # --------------------------------------------------------
        # LOCATION
        # --------------------------------------------------------

        location = self._extract_location(
            page_text
        )

        # --------------------------------------------------------
        # DESCRIPTION
        #
        # This is one of the more expensive operations, so it
        # happens only after cheap filters pass.
        # --------------------------------------------------------

        description = (
            self._extract_description(
                soup
            )
        )

        # --------------------------------------------------------
        # SALARY
        # --------------------------------------------------------

        salary = self._extract_salary(
            page_text,
            description,
        )

        # --------------------------------------------------------
        # EMPLOYMENT TYPE
        # --------------------------------------------------------

        employment_type = (
            self._extract_employment_type(
                page_text_lower
            )
        )

        # --------------------------------------------------------
        # APPLY URL
        # --------------------------------------------------------

        apply_url = (
            self._extract_apply_url(
                soup
            )
            or job_url
        )

        # --------------------------------------------------------
        # JOB ID
        # --------------------------------------------------------

        job_id = self._extract_job_id(
            job_url
        )

        return Job(
            company=company,
            title=title,
            location=location,
            posting_url=job_url,
            description=description,
            posting_date=posting_date,
            salary=salary,
            source="Built In",
            apply_url=apply_url,
            employment_type=employment_type,
            job_id=job_id,
        )

    # ============================================================
    # TITLE
    # ============================================================

    @staticmethod
    def _extract_title(
        soup: BeautifulSoup,
    ) -> str:

        heading = soup.find("h1")

        if heading:

            title = heading.get_text(
                " ",
                strip=True,
            )

            if title:
                return title

        if soup.title:

            title = soup.title.get_text(
                " ",
                strip=True,
            )

            title = re.sub(
                r"\s*-\s*Built In.*$",
                "",
                title,
                flags=re.IGNORECASE,
            )

            return title.strip()

        return ""

    # ============================================================
    # COMPANY
    # ============================================================

    @staticmethod
    def _extract_company(
        soup: BeautifulSoup,
    ) -> str:

        for anchor in soup.find_all(
            "a",
            href=True,
        ):

            href = anchor.get(
                "href",
                "",
            )

            if "/company/" not in href:
                continue

            company = anchor.get_text(
                " ",
                strip=True,
            )

            if company:
                return company

        return ""

    # ============================================================
    # LOCATION
    # ============================================================

    @staticmethod
    def _extract_location(
        text: str,
    ) -> str:

        locations = re.findall(
            r"\b"
            r"[A-Z][A-Za-z .'-]+,"
            r"\s*"
            r"[A-Z]{2}"
            r"(?:,\s*USA)?"
            r"\b",
            text,
        )

        cleaned = []
        seen = set()

        for location in locations:

            location = location.strip()

            if location in seen:
                continue

            seen.add(location)
            cleaned.append(location)

        return "; ".join(
            cleaned[:5]
        )

    # ============================================================
    # DESCRIPTION
    # ============================================================

    @staticmethod
    def _extract_description(
        soup: BeautifulSoup,
    ) -> str:

        for element in soup.find_all(
            [
                "script",
                "style",
                "noscript",
            ]
        ):
            element.decompose()

        article = soup.find(
            "article"
        )

        if article:

            return clean_html_description(
                str(article)
            )

        body = soup.find(
            "body"
        )

        if not body:
            return ""

        return clean_html_description(
            str(body)
        )

    # ============================================================
    # POSTING DATE
    # ============================================================

    @staticmethod
    def _extract_posting_date(
        text: str,
    ) -> datetime | None:

        now = datetime.now(
            timezone.utc
        )

        if "today" in text:
            return now

        if "yesterday" in text:
            return (
                now -
                timedelta(days=1)
            )

        # --------------------------------------------------------
        # Minutes
        # --------------------------------------------------------

        match = re.search(
            r"(\d+)\s+"
            r"(?:minute|minutes|min)"
            r"\s+ago",
            text,
        )

        if match:

            return (
                now -
                timedelta(
                    minutes=int(
                        match.group(1)
                    )
                )
            )

        # --------------------------------------------------------
        # Hours
        # --------------------------------------------------------

        match = re.search(
            r"(\d+)\s+"
            r"(?:hour|hours)"
            r"\s+ago",
            text,
        )

        if match:

            return (
                now -
                timedelta(
                    hours=int(
                        match.group(1)
                    )
                )
            )

        # --------------------------------------------------------
        # Reposted X days ago.
        #
        # Check this BEFORE the generic day pattern.
        # --------------------------------------------------------

        match = re.search(
            r"reposted\s+"
            r"(\d+)\s+"
            r"(?:day|days)"
            r"\s+ago",
            text,
        )

        if match:

            return (
                now -
                timedelta(
                    days=int(
                        match.group(1)
                    )
                )
            )

        # --------------------------------------------------------
        # X days ago.
        # --------------------------------------------------------

        match = re.search(
            r"(\d+)\s+"
            r"(?:day|days)"
            r"\s+ago",
            text,
        )

        if match:

            return (
                now -
                timedelta(
                    days=int(
                        match.group(1)
                    )
                )
            )

        return None

    # ============================================================
    # SALARY
    # ============================================================

    @staticmethod
    def _extract_salary(
        page_text: str,
        description: str,
    ) -> str:

        salary_match = re.search(
            r"\$[\d,]+"
            r"(?:\s*-\s*\$[\d,]+)?"
            r"(?:\s+(?:Annually|Hourly|Yearly))?",
            page_text,
            re.IGNORECASE,
        )

        if salary_match:

            return (
                salary_match.group(0)
                .strip()
            )

        return extract_salary(
            description
        )

    # ============================================================
    # EMPLOYMENT TYPE
    # ============================================================

    @staticmethod
    def _extract_employment_type(
        text: str,
    ) -> str:

        employment_types = (
            "full-time",
            "full time",
            "part-time",
            "part time",
            "contract",
            "internship",
            "temporary",
        )

        for employment_type in (
            employment_types
        ):

            if employment_type in text:
                return employment_type

        return ""

    # ============================================================
    # APPLY URL
    # ============================================================

    @staticmethod
    def _extract_apply_url(
        soup: BeautifulSoup,
    ) -> str:

        for anchor in soup.find_all(
            "a",
            href=True,
        ):

            text = anchor.get_text(
                " ",
                strip=True,
            ).lower()

            href = anchor.get(
                "href"
            )

            if not href:
                continue

            if (
                "apply" in text
                or "apply" in href.lower()
            ):

                if href.startswith(
                    (
                        "http://",
                        "https://",
                    )
                ):
                    return href

        return ""

    # ============================================================
    # JOB ID
    # ============================================================

    @staticmethod
    def _extract_job_id(
        job_url: str,
    ) -> str:

        match = re.search(
            r"/job/[^/]+/(\d+)",
            job_url,
        )

        if match:
            return match.group(1)

        return ""

    # ============================================================
    # SEARCH TERMS
    # ============================================================

    @staticmethod
    def _normalize_search_terms(
        search_terms: list[str] | None,
    ) -> list[str]:

        if not search_terms:
            return []

        normalized = []
        seen = set()

        for term in search_terms:

            if term is None:
                continue

            term = str(
                term
            ).strip().lower()

            if not term:
                continue

            if term in seen:
                continue

            seen.add(term)
            normalized.append(term)

        return normalized

    @staticmethod
    def _title_matches_search_terms(
        title: str,
        search_terms: list[str],
    ) -> bool:

        if not search_terms:
            return True

        title_lower = (
            title.lower()
        )

        for search_term in search_terms:

            # ----------------------------------------------------
            # Exact phrase.
            # ----------------------------------------------------

            if search_term in title_lower:
                return True

            # ----------------------------------------------------
            # All words present.
            # ----------------------------------------------------

            words = search_term.split()

            if all(
                word in title_lower
                for word in words
            ):
                return True

        return False

    # ============================================================
    # HTTP SESSION
    # ============================================================

    def _get_session(self):
        """
        One requests.Session per worker thread.

        This avoids sharing a Session across threads while still
        getting connection reuse inside each worker.
        """

        session = getattr(
            self._thread_local,
            "session",
            None,
        )

        if session is None:

            session = requests.Session()

            session.headers.update({
                "Accept": (
                    "text/html,"
                    "application/xhtml+xml,"
                    "application/xml;q=0.9,"
                    "*/*;q=0.8"
                ),
                "Accept-Language": (
                    "en-US,en;q=0.9"
                ),
                "User-Agent": (
                    "Mozilla/5.0 "
                    "(Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 "
                    "(KHTML, like Gecko) "
                    "Chrome/140.0 Safari/537.36"
                ),
                "Connection": "keep-alive",
            })

            self._thread_local.session = (
                session
            )

        return session

    # ============================================================
    # HTTP REQUEST
    # ============================================================

    def _request(
        self,
        method: str,
        url: str,
        **kwargs,
    ):

        for attempt in range(
            self.max_retries + 1
        ):

            try:

                # ------------------------------------------------
                # GLOBAL RATE LIMIT.
                #
                # This happens before every HTTP request,
                # including requests made by worker threads.
                # ------------------------------------------------

                self.rate_limiter.wait()

                session = (
                    self._get_session()
                )

                response = session.request(
                    method,
                    url,
                    timeout=30,
                    **kwargs,
                )

                # ------------------------------------------------
                # 429.
                # ------------------------------------------------

                if response.status_code == 429:

                    if (
                        attempt
                        >= self.max_retries
                    ):
                        response.raise_for_status()

                    wait_seconds = min(
                        30,
                        2 ** attempt,
                    )

                    print(
                        "Built In rate limited "
                        f"(429). Waiting "
                        f"{wait_seconds}s..."
                    )

                    time.sleep(
                        wait_seconds
                    )

                    continue

                # ------------------------------------------------
                # Server errors.
                # ------------------------------------------------

                if response.status_code >= 500:

                    if (
                        attempt
                        >= self.max_retries
                    ):
                        response.raise_for_status()

                    wait_seconds = min(
                        30,
                        2 ** attempt,
                    )

                    print(
                        f"Built In server error "
                        f"({response.status_code}). "
                        f"Retrying in "
                        f"{wait_seconds}s..."
                    )

                    time.sleep(
                        wait_seconds
                    )

                    continue

                response.raise_for_status()

                return response

            except requests.RequestException as error:

                if (
                    attempt
                    >= self.max_retries
                ):
                    raise

                wait_seconds = min(
                    30,
                    2 ** attempt,
                )

                print(
                    f"Built In request error: "
                    f"{error}. "
                    f"Retrying in "
                    f"{wait_seconds}s..."
                )

                time.sleep(
                    wait_seconds
                )

        return None



# import asyncio
# import re
# import time
# from datetime import datetime, timedelta, timezone
# from urllib.parse import quote

# import requests
# from bs4 import BeautifulSoup

# from app.models.job import Job
# from app.sources.job_source import JobSource
# from app.utils.html_cleaner import clean_html_description
# from app.utils.salary_extractor import extract_salary


# class BuiltInSource(JobSource):
#     """
#     Optimized Built In scraper.

#     IMPORTANT:
#     This class should NOT be called once for every filter.

#     Instead:

#         1. Perform one broad Built In search.
#         2. Retrieve the available job pages.
#         3. Parse each job once.
#         4. Filter the resulting jobs locally.

#     This prevents 108 filter criteria from causing 108 separate
#     Built In crawls.
#     """

#     def __init__(
#         self,
#         posting_age_days: int = 2,
#         request_delay_seconds: float = 0.25,
#         max_retries: int = 2,
#         results_per_page: int = 20,
#         max_pages: int = 50,
#         max_concurrent_jobs: int = 8,
#     ):
#         self.posting_age_days = posting_age_days
#         self.request_delay_seconds = request_delay_seconds
#         self.max_retries = max_retries
#         self.results_per_page = results_per_page
#         self.max_pages = max_pages
#         self.max_concurrent_jobs = max_concurrent_jobs

#         self.base_url = "https://builtin.com"

#         self.session = requests.Session()

#         self.session.headers.update({
#             "Accept": (
#                 "text/html,"
#                 "application/xhtml+xml,"
#                 "application/xml;q=0.9,"
#                 "*/*;q=0.8"
#             ),
#             "Accept-Language": "en-US,en;q=0.9",
#             "User-Agent": (
#                 "Mozilla/5.0 "
#                 "(Windows NT 10.0; Win64; x64) "
#                 "AppleWebKit/537.36 "
#                 "(KHTML, like Gecko) "
#                 "Chrome/140.0 Safari/537.36"
#             ),
#             "Connection": "keep-alive",
#         })

#         self._last_request_time = None

#         self._cutoff = None

#         if posting_age_days is not None:
#             self._cutoff = (
#                 datetime.now(timezone.utc)
#                 - timedelta(days=posting_age_days)
#             )

#     # ============================================================
#     # PUBLIC SEARCH
#     # ============================================================

#     def search(
#         self,
#         search_terms: list[str] | None = None,
#         location: str | None = None,
#     ) -> list[Job]:

#         search_terms = self._normalize_search_terms(search_terms)

#         print(
#             f"Built In search starting | "
#             f"location={location!r} | "
#             f"terms={search_terms}"
#         )

#         # --------------------------------------------------------
#         # IMPORTANT:
#         #
#         # We deliberately do NOT construct a highly specific URL
#         # for every search term.
#         #
#         # The caller should normally use:
#         #
#         #     search_terms=None
#         #
#         # and perform filtering locally.
#         # --------------------------------------------------------

#         all_links = []
#         seen_links = set()

#         page = 1

#         while page <= self.max_pages:

#             search_url = self._build_search_url(
#                 search_terms=None,
#                 location=location,
#                 page=page,
#             )

#             print(
#                 f"Built In search page {page}: "
#                 f"{search_url}"
#             )

#             try:
#                 response = self._request(
#                     "GET",
#                     search_url,
#                 )
#             except requests.RequestException as error:
#                 print(
#                     f"Built In search failed on page "
#                     f"{page}: {error}"
#                 )
#                 break

#             soup = BeautifulSoup(
#                 response.text,
#                 "html.parser",
#             )

#             job_links = self._extract_job_links(soup)

#             if not job_links:
#                 print(
#                     f"Built In page {page}: "
#                     "no job links found. Stopping."
#                 )
#                 break

#             new_links = []

#             for job_url in job_links:
#                 if job_url not in seen_links:
#                     seen_links.add(job_url)
#                     new_links.append(job_url)

#             all_links.extend(new_links)

#             print(
#                 f"Built In page {page}: "
#                 f"{len(job_links)} links, "
#                 f"{len(new_links)} new"
#             )

#             # ----------------------------------------------------
#             # Normal pagination termination.
#             # ----------------------------------------------------

#             if len(job_links) < self.results_per_page:
#                 break

#             page += 1

#         print(
#             f"Built In discovered "
#             f"{len(all_links)} unique job URLs."
#         )

#         # --------------------------------------------------------
#         # Retrieve jobs concurrently.
#         #
#         # This is the major performance improvement.
#         # --------------------------------------------------------

#         jobs = self._get_jobs_concurrently(
#             job_urls=all_links,
#             search_terms=search_terms,
#         )

#         print(
#             f"Built In returned "
#             f"{len(jobs)} matching jobs."
#         )

#         return jobs

#     # ============================================================
#     # CONCURRENT JOB FETCHING
#     # ============================================================

#     def _get_jobs_concurrently(
#         self,
#         job_urls: list[str],
#         search_terms: list[str],
#     ) -> list[Job]:

#         if not job_urls:
#             return []

#         semaphore = asyncio.Semaphore(
#             self.max_concurrent_jobs
#         )

#         async def fetch(job_url: str):
#             async with semaphore:

#                 # requests is synchronous, so execute it in a
#                 # worker thread rather than blocking asyncio.
#                 return await asyncio.to_thread(
#                     self._get_job,
#                     job_url,
#                     search_terms,
#                 )

#         async def run():

#             tasks = [
#                 asyncio.create_task(
#                     fetch(job_url)
#                 )
#                 for job_url in job_urls
#             ]

#             results = await asyncio.gather(
#                 *tasks,
#                 return_exceptions=True,
#             )

#             jobs = []

#             for job_url, result in zip(
#                 job_urls,
#                 results,
#             ):

#                 if isinstance(
#                     result,
#                     Exception,
#                 ):
#                     print(
#                         f"Built In job failed: "
#                         f"{job_url}: {result}"
#                     )
#                     continue

#                 if result is not None:
#                     jobs.append(result)

#             return jobs

#         return asyncio.run(run())

#     # ============================================================
#     # SEARCH URL
#     # ============================================================

#     def _build_search_url(
#         self,
#         search_terms: list[str] | None,
#         location: str | None,
#         page: int,
#     ) -> str:

#         if search_terms:

#             search_text = "-".join(
#                 search_terms
#             )

#             search_text = re.sub(
#                 r"[^a-zA-Z0-9\-]+",
#                 "-",
#                 search_text,
#             ).strip("-").lower()

#             path = f"/jobs/{search_text}"

#         else:
#             path = "/jobs"

#         url = f"{self.base_url}{path}"

#         params = []

#         if location:
#             params.append(
#                 f"location={quote(location)}"
#             )

#         if page > 1:
#             params.append(
#                 f"page={page}"
#             )

#         if params:
#             url += "?" + "&".join(params)

#         return url

#     # ============================================================
#     # JOB LINKS
#     # ============================================================

#     @staticmethod
#     def _extract_job_links(
#         soup: BeautifulSoup,
#     ) -> list[str]:

#         links = []
#         seen = set()

#         for anchor in soup.find_all(
#             "a",
#             href=True,
#         ):

#             href = anchor.get("href")

#             if not href:
#                 continue

#             # Accept both normal Built In job URLs and URLs
#             # containing query strings.
#             match = re.match(
#                 r"^/job/"
#                 r"[^/]+/"
#                 r"\d+"
#                 r"(?:[/?#].*)?$",
#                 href,
#             )

#             if not match:
#                 continue

#             clean_href = href.split("?")[0].split("#")[0]

#             if clean_href in seen:
#                 continue

#             seen.add(clean_href)

#             links.append(
#                 f"https://builtin.com{clean_href}"
#             )

#         return links

#     # ============================================================
#     # JOB
#     # ============================================================

#     def _get_job(
#         self,
#         job_url: str,
#         search_terms: list[str],
#     ) -> Job | None:

#         try:

#             response = self._request(
#                 "GET",
#                 job_url,
#             )

#         except requests.RequestException as error:

#             print(
#                 f"Built In job request failed: "
#                 f"{job_url}: {error}"
#             )

#             return None

#         soup = BeautifulSoup(
#             response.text,
#             "html.parser",
#         )

#         # --------------------------------------------------------
#         # Extract title first.
#         # --------------------------------------------------------

#         title = self._extract_title(soup)

#         if not title:
#             return None

#         # --------------------------------------------------------
#         # Filter title before doing expensive extraction.
#         # --------------------------------------------------------

#         if (
#             search_terms
#             and not self._title_matches_search_terms(
#                 title,
#                 search_terms,
#             )
#         ):
#             return None

#         # --------------------------------------------------------
#         # Posting date.
#         #
#         # Do this early so old jobs are discarded before expensive
#         # description/salary processing.
#         # --------------------------------------------------------

#         posting_date = self._extract_posting_date(
#             soup
#         )

#         if self._cutoff is not None:

#             if posting_date is None:
#                 return None

#             if posting_date < self._cutoff:
#                 return None

#         # --------------------------------------------------------
#         # Extract remaining fields.
#         # --------------------------------------------------------

#         company = self._extract_company(soup)

#         if not company:
#             return None

#         location = self._extract_location(soup)

#         description = self._extract_description(soup)

#         salary = self._extract_salary(
#             soup,
#             description,
#         )

#         employment_type = (
#             self._extract_employment_type(
#                 soup
#             )
#         )

#         apply_url = (
#             self._extract_apply_url(soup)
#             or job_url
#         )

#         job_id = self._extract_job_id(
#             job_url
#         )

#         return Job(
#             company=company,
#             title=title,
#             location=location,
#             posting_url=job_url,
#             description=description,
#             posting_date=posting_date,
#             salary=salary,
#             source="Built In",
#             apply_url=apply_url,
#             employment_type=employment_type,
#             job_id=job_id,
#         )

#     # ============================================================
#     # TITLE
#     # ============================================================

#     @staticmethod
#     def _extract_title(
#         soup: BeautifulSoup,
#     ) -> str:

#         heading = soup.find("h1")

#         if heading:

#             title = heading.get_text(
#                 " ",
#                 strip=True,
#             )

#             if title:
#                 return title

#         if soup.title:

#             title = soup.title.get_text(
#                 " ",
#                 strip=True,
#             )

#             title = re.sub(
#                 r"\s*-\s*Built In.*$",
#                 "",
#                 title,
#                 flags=re.IGNORECASE,
#             )

#             return title.strip()

#         return ""

#     # ============================================================
#     # COMPANY
#     # ============================================================

#     @staticmethod
#     def _extract_company(
#         soup: BeautifulSoup,
#     ) -> str:

#         for anchor in soup.find_all(
#             "a",
#             href=True,
#         ):

#             href = anchor.get("href", "")

#             if "/company/" not in href:
#                 continue

#             company = anchor.get_text(
#                 " ",
#                 strip=True,
#             )

#             if company:
#                 return company

#         return ""

#     # ============================================================
#     # LOCATION
#     # ============================================================

#     @staticmethod
#     def _extract_location(
#         soup: BeautifulSoup,
#     ) -> str:

#         text = soup.get_text(
#             "\n",
#             strip=True,
#         )

#         locations = re.findall(
#             r"\b"
#             r"[A-Z][A-Za-z .'-]+,"
#             r"\s*"
#             r"[A-Z]{2}"
#             r"(?:,\s*USA)?"
#             r"\b",
#             text,
#         )

#         cleaned = []

#         for location in locations:

#             location = location.strip()

#             if location not in cleaned:
#                 cleaned.append(location)

#         return "; ".join(cleaned[:5])

#     # ============================================================
#     # DESCRIPTION
#     # ============================================================

#     @staticmethod
#     def _extract_description(
#         soup: BeautifulSoup,
#     ) -> str:

#         # Work on a copy-like parse tree by removing only
#         # non-content tags.

#         for element in soup.find_all(
#             [
#                 "script",
#                 "style",
#                 "noscript",
#             ]
#         ):
#             element.decompose()

#         article = soup.find("article")

#         if article:

#             return clean_html_description(
#                 str(article)
#             )

#         body = soup.find("body")

#         if not body:
#             return ""

#         return clean_html_description(
#             str(body)
#         )

#     # ============================================================
#     # POSTING DATE
#     # ============================================================

#     @staticmethod
#     def _extract_posting_date(
#         soup: BeautifulSoup,
#     ) -> datetime | None:

#         text = soup.get_text(
#             " ",
#             strip=True,
#         ).lower()

#         now = datetime.now(
#             timezone.utc
#         )

#         if "today" in text:
#             return now

#         if "yesterday" in text:
#             return now - timedelta(days=1)

#         match = re.search(
#             r"(\d+)\s+"
#             r"(?:minute|minutes|min)"
#             r"\s+ago",
#             text,
#         )

#         if match:

#             minutes = int(
#                 match.group(1)
#             )

#             return now - timedelta(
#                 minutes=minutes
#             )

#         match = re.search(
#             r"(\d+)\s+"
#             r"(?:hour|hours)"
#             r"\s+ago",
#             text,
#         )

#         if match:

#             hours = int(
#                 match.group(1)
#             )

#             return now - timedelta(
#                 hours=hours
#             )

#         match = re.search(
#             r"(\d+)\s+"
#             r"(?:day|days)"
#             r"\s+ago",
#             text,
#         )

#         if match:

#             days = int(
#                 match.group(1)
#             )

#             return now - timedelta(
#                 days=days
#             )

#         match = re.search(
#             r"reposted\s+"
#             r"(\d+)\s+"
#             r"(?:day|days)"
#             r"\s+ago",
#             text,
#         )

#         if match:

#             days = int(
#                 match.group(1)
#             )

#             return now - timedelta(
#                 days=days
#             )

#         return None

#     # ============================================================
#     # SALARY
#     # ============================================================

#     @staticmethod
#     def _extract_salary(
#         soup: BeautifulSoup,
#         description: str,
#     ) -> str:

#         text = soup.get_text(
#             " ",
#             strip=True,
#         )

#         salary_match = re.search(
#             r"\$[\d,]+"
#             r"(?:\s*-\s*\$[\d,]+)?"
#             r"(?:\s+(?:Annually|Hourly|Yearly))?",
#             text,
#             re.IGNORECASE,
#         )

#         if salary_match:

#             return salary_match.group(0).strip()

#         return extract_salary(description)

#     # ============================================================
#     # EMPLOYMENT TYPE
#     # ============================================================

#     @staticmethod
#     def _extract_employment_type(
#         soup: BeautifulSoup,
#     ) -> str:

#         text = soup.get_text(
#             " ",
#             strip=True,
#         ).lower()

#         employment_types = [
#             "full-time",
#             "full time",
#             "part-time",
#             "part time",
#             "contract",
#             "internship",
#             "temporary",
#         ]

#         for employment_type in employment_types:

#             if employment_type in text:
#                 return employment_type

#         return ""

#     # ============================================================
#     # APPLY URL
#     # ============================================================

#     @staticmethod
#     def _extract_apply_url(
#         soup: BeautifulSoup,
#     ) -> str:

#         for anchor in soup.find_all(
#             "a",
#             href=True,
#         ):

#             text = anchor.get_text(
#                 " ",
#                 strip=True,
#             ).lower()

#             href = anchor.get("href")

#             if not href:
#                 continue

#             if (
#                 "apply" in text
#                 or "apply" in href.lower()
#             ):

#                 if href.startswith(
#                     (
#                         "http://",
#                         "https://",
#                     )
#                 ):
#                     return href

#         return ""

#     # ============================================================
#     # JOB ID
#     # ============================================================

#     @staticmethod
#     def _extract_job_id(
#         job_url: str,
#     ) -> str:

#         match = re.search(
#             r"/job/[^/]+/(\d+)",
#             job_url,
#         )

#         if match:
#             return match.group(1)

#         return ""

#     # ============================================================
#     # SEARCH TERMS
#     # ============================================================

#     @staticmethod
#     def _normalize_search_terms(
#         search_terms: list[str] | None,
#     ) -> list[str]:

#         if not search_terms:
#             return []

#         normalized = []

#         for term in search_terms:

#             if term is None:
#                 continue

#             term = str(term).strip().lower()

#             if (
#                 term
#                 and term not in normalized
#             ):
#                 normalized.append(term)

#         return normalized

#     @staticmethod
#     def _title_matches_search_terms(
#         title: str,
#         search_terms: list[str],
#     ) -> bool:

#         if not search_terms:
#             return True

#         title_lower = title.lower()

#         for search_term in search_terms:

#             # Exact phrase.
#             if search_term in title_lower:
#                 return True

#             # All words present.
#             words = search_term.split()

#             if all(
#                 word in title_lower
#                 for word in words
#             ):
#                 return True

#         return False

#     # ============================================================
#     # HTTP
#     # ============================================================

#     def _request(
#         self,
#         method: str,
#         url: str,
#         **kwargs,
#     ):

#         for attempt in range(
#             self.max_retries + 1
#         ):

#             try:

#                 self._wait_before_request()

#                 response = self.session.request(
#                     method,
#                     url,
#                     timeout=30,
#                     **kwargs,
#                 )

#                 self._last_request_time = (
#                     time.monotonic()
#                 )

#                 if response.status_code == 429:

#                     if attempt >= self.max_retries:
#                         response.raise_for_status()

#                     wait_seconds = min(
#                         30,
#                         2 ** attempt,
#                     )

#                     print(
#                         "Built In rate limited. "
#                         f"Waiting {wait_seconds}s..."
#                     )

#                     time.sleep(wait_seconds)

#                     continue

#                 if response.status_code >= 500:

#                     if attempt >= self.max_retries:
#                         response.raise_for_status()

#                     wait_seconds = min(
#                         30,
#                         2 ** attempt,
#                     )

#                     time.sleep(wait_seconds)

#                     continue

#                 response.raise_for_status()

#                 return response

#             except requests.RequestException:

#                 if attempt >= self.max_retries:
#                     raise

#                 wait_seconds = min(
#                     30,
#                     2 ** attempt,
#                 )

#                 time.sleep(wait_seconds)

#         return None

#     # ============================================================
#     # REQUEST DELAY
#     # ============================================================

#     def _wait_before_request(self):

#         if self._last_request_time is None:
#             return

#         elapsed = (
#             time.monotonic()
#             - self._last_request_time
#         )

#         remaining = (
#             self.request_delay_seconds
#             - elapsed
#         )

#         if remaining > 0:
#             time.sleep(remaining)


# # import re
# # import time
# # import threading

# # from concurrent.futures import (
# #     ThreadPoolExecutor,
# #     as_completed,
# # )

# # from datetime import (
# #     datetime,
# #     timedelta,
# #     timezone,
# # )

# # from urllib.parse import (
# #     quote,
# # )

# # import requests

# # from bs4 import BeautifulSoup

# # from app.models.job import Job
# # from app.sources.job_source import JobSource
# # from app.utils.html_cleaner import clean_html_description
# # from app.utils.salary_extractor import extract_salary


# # class RateLimiter:

# #     def __init__(
# #         self,
# #         requests_per_second: float = 3.0,
# #     ):
# #         if requests_per_second <= 0:
# #             raise ValueError(
# #                 "requests_per_second must be > 0"
# #             )

# #         self.interval = (
# #             1.0 / requests_per_second
# #         )

# #         self.lock = threading.Lock()

# #         self.last_request_time = 0.0

# #     def wait(self):

# #         with self.lock:

# #             now = time.monotonic()

# #             elapsed = (
# #                 now -
# #                 self.last_request_time
# #             )

# #             remaining = (
# #                 self.interval -
# #                 elapsed
# #             )

# #             if remaining > 0:

# #                 time.sleep(
# #                     remaining
# #                 )

# #             self.last_request_time = (
# #                 time.monotonic()
# #             )


# # class BuiltInSource(JobSource):

# #     def __init__(
# #         self,
# #         posting_age_days: int = 2,
# #         requests_per_second: float = 3.0,
# #         max_workers: int = 6,
# #         max_retries: int = 2,
# #         results_per_page: int = 20,
# #         max_pages: int = 50,
# #     ):

# #         self.posting_age_days = (
# #             posting_age_days
# #         )

# #         self.max_workers = (
# #             max_workers
# #         )

# #         self.max_retries = (
# #             max_retries
# #         )

# #         self.results_per_page = (
# #             results_per_page
# #         )

# #         self.max_pages = (
# #             max_pages
# #         )

# #         self.base_url = (
# #             "https://builtin.com"
# #         )

# #         # -----------------------------------------------------
# #         # Each worker thread gets its own requests.Session.
# #         # -----------------------------------------------------

# #         self._thread_local = (
# #             threading.local()
# #         )

# #         # -----------------------------------------------------
# #         # Global rate limiter shared by all workers.
# #         #
# #         # Example:
# #         #
# #         # 3 requests/sec total
# #         #
# #         # NOT:
# #         #
# #         # 3 requests/sec × 6 workers
# #         # -----------------------------------------------------

# #         self.rate_limiter = RateLimiter(
# #             requests_per_second
# #         )

# #     # =========================================================
# #     # SEARCH
# #     # =========================================================

# #     def search(
# #         self,
# #         search_terms: list[str] | None = None,
# #         location: str | None = None,
# #     ) -> list[Job]:

# #         search_terms = (
# #             self._normalize_search_terms(
# #                 search_terms
# #             )
# #         )

# #         # -----------------------------------------------------
# #         # No criteria means nothing to search.
# #         # -----------------------------------------------------

# #         if not search_terms:

# #             print(
# #                 "Built In: no search criteria."
# #             )

# #             return []

# #         print(
# #             f"Built In: processing "
# #             f"{len(search_terms)} search criteria."
# #         )

# #         # -----------------------------------------------------
# #         # PHASE 1
# #         #
# #         # Discover job URLs.
# #         #
# #         # IMPORTANT:
# #         #
# #         # We do NOT fetch individual job pages here.
# #         #
# #         # This allows the same job to be discovered by multiple
# #         # criteria but fetched only once.
# #         # -----------------------------------------------------

# #         job_urls = (
# #             self._discover_all_jobs(
# #                 search_terms=search_terms,
# #                 location=location,
# #             )
# #         )

# #         print(
# #             f"\nBuilt In discovery complete."
# #         )

# #         print(
# #             f"Unique job URLs discovered: "
# #             f"{len(job_urls)}"
# #         )

# #         if not job_urls:
# #             return []

# #         # -----------------------------------------------------
# #         # PHASE 2
# #         #
# #         # Fetch each unique job page once.
# #         # -----------------------------------------------------

# #         jobs = (
# #             self._fetch_jobs(
# #                 job_urls=job_urls,
# #                 search_terms=search_terms,
# #             )
# #         )

# #         print(
# #             f"\nBuilt In returned "
# #             f"{len(jobs)} matching jobs."
# #         )

# #         return jobs

# #     # =========================================================
# #     # DISCOVER ALL JOBS
# #     # =========================================================

# #     def _discover_all_jobs(
# #         self,
# #         search_terms: list[str],
# #         location: str | None,
# #     ) -> set[str]:

# #         all_job_urls = set()

# #         # -----------------------------------------------------
# #         # Search criteria are independent.
# #         #
# #         # Therefore they can be discovered concurrently.
# #         # -----------------------------------------------------

# #         with ThreadPoolExecutor(
# #             max_workers=self.max_workers
# #         ) as executor:

# #             futures = {
# #                 executor.submit(
# #                     self._discover_search,
# #                     search_term,
# #                     location,
# #                 ): search_term
# #                 for search_term in search_terms
# #             }

# #             for future in as_completed(
# #                 futures
# #             ):

# #                 search_term = futures[
# #                     future
# #                 ]

# #                 try:

# #                     discovered = (
# #                         future.result()
# #                     )

# #                     before = len(
# #                         all_job_urls
# #                     )

# #                     all_job_urls.update(
# #                         discovered
# #                     )

# #                     new_count = (
# #                         len(all_job_urls)
# #                         -
# #                         before
# #                     )

# #                     print(
# #                         f"Discovery complete: "
# #                         f"'{search_term}' | "
# #                         f"{len(discovered)} URLs | "
# #                         f"{new_count} new"
# #                     )

# #                 except Exception as error:

# #                     print(
# #                         f"Discovery failed: "
# #                         f"'{search_term}': "
# #                         f"{error}"
# #                     )

# #         return all_job_urls

# #     # =========================================================
# #     # DISCOVER ONE SEARCH
# #     # =========================================================

# #     def _discover_search(
# #         self,
# #         search_term: str,
# #         location: str | None,
# #     ) -> set[str]:

# #         discovered = set()

# #         page = 1

# #         while page <= self.max_pages:

# #             search_url = (
# #                 self._build_search_url(
# #                     search_terms=[
# #                         search_term
# #                     ],
# #                     location=location,
# #                     page=page,
# #                 )
# #             )

# #             try:

# #                 response = self._request(
# #                     "GET",
# #                     search_url,
# #                 )

# #             except requests.RequestException as error:

# #                 print(
# #                     f"Built In search failed: "
# #                     f"'{search_term}', "
# #                     f"page {page}: "
# #                     f"{error}"
# #                 )

# #                 break

# #             soup = BeautifulSoup(
# #                 response.text,
# #                 "html.parser",
# #             )

# #             page_links = (
# #                 self._extract_job_links(
# #                     soup
# #                 )
# #             )

# #             if not page_links:
# #                 break

# #             previous_count = len(
# #                 discovered
# #             )

# #             discovered.update(
# #                 page_links
# #             )

# #             new_count = (
# #                 len(discovered)
# #                 -
# #                 previous_count
# #             )

# #             print(
# #                 f"Built In discovery: "
# #                 f"'{search_term}' | "
# #                 f"page={page} | "
# #                 f"found={len(page_links)} | "
# #                 f"new={new_count}"
# #             )

# #             # -------------------------------------------------
# #             # If an entire page contains only URLs we already
# #             # discovered, there is no value continuing.
# #             # -------------------------------------------------

# #             if new_count == 0:
# #                 break

# #             # -------------------------------------------------
# #             # Last page.
# #             # -------------------------------------------------

# #             if (
# #                 len(page_links)
# #                 <
# #                 self.results_per_page
# #             ):
# #                 break

# #             page += 1

# #         return discovered

# #     # =========================================================
# #     # FETCH JOBS
# #     # =========================================================

# #     def _fetch_jobs(
# #         self,
# #         job_urls: set[str],
# #         search_terms: list[str],
# #     ) -> list[Job]:

# #         jobs = []

# #         print(
# #             f"\nFetching "
# #             f"{len(job_urls)} unique job pages "
# #             f"with {self.max_workers} workers..."
# #         )

# #         with ThreadPoolExecutor(
# #             max_workers=self.max_workers
# #         ) as executor:

# #             futures = {
# #                 executor.submit(
# #                     self._get_job,
# #                     job_url,
# #                     search_terms,
# #                 ): job_url
# #                 for job_url in job_urls
# #             }

# #             for future in as_completed(
# #                 futures
# #             ):

# #                 job_url = futures[
# #                     future
# #                 ]

# #                 try:

# #                     job = future.result()

# #                     if job is None:
# #                         continue

# #                     jobs.append(job)

# #                 except Exception as error:

# #                     print(
# #                         f"Built In job failed: "
# #                         f"{job_url}: "
# #                         f"{error}"
# #                     )

# #         return jobs

# #     # =========================================================
# #     # SEARCH URL
# #     # =========================================================

# #     def _build_search_url(
# #         self,
# #         search_terms: list[str],
# #         location: str | None,
# #         page: int,
# #     ) -> str:

# #         if search_terms:

# #             search_text = "-".join(
# #                 search_terms
# #             )

# #             search_text = re.sub(
# #                 r"[^a-zA-Z0-9\-]+",
# #                 "-",
# #                 search_text,
# #             ).strip("-").lower()

# #             path = (
# #                 f"/jobs/{search_text}"
# #             )

# #         else:

# #             path = "/jobs"

# #         url = (
# #             f"{self.base_url}"
# #             f"{path}"
# #         )

# #         params = []

# #         if location:

# #             params.append(
# #                 f"location={quote(location)}"
# #             )

# #         if page > 1:

# #             params.append(
# #                 f"page={page}"
# #             )

# #         if params:

# #             url += "?" + "&".join(
# #                 params
# #             )

# #         return url

# #     # =========================================================
# #     # JOB LINKS
# #     # =========================================================

# #     @staticmethod
# #     def _extract_job_links(
# #         soup: BeautifulSoup,
# #     ) -> set[str]:

# #         links = set()

# #         for anchor in soup.find_all(
# #             "a",
# #             href=True,
# #         ):

# #             href = anchor.get(
# #                 "href"
# #             )

# #             if not href:
# #                 continue

# #             match = re.match(
# #                 r"^/job/"
# #                 r"[^/]+/"
# #                 r"\d+/?$",
# #                 href,
# #             )

# #             if not match:
# #                 continue

# #             # -------------------------------------------------
# #             # Normalize trailing slash.
# #             # -------------------------------------------------

# #             href = href.rstrip("/")

# #             links.add(
# #                 f"{self_base_url()}{href}"
# #             )

# #         return links

# #     # =========================================================
# #     # JOB
# #     # =========================================================

# #     def _get_job(
# #         self,
# #         job_url: str,
# #         search_terms: list[str],
# #     ) -> Job | None:

# #         try:

# #             response = self._request(
# #                 "GET",
# #                 job_url,
# #             )

# #         except requests.RequestException as error:

# #             print(
# #                 f"Built In job request failed: "
# #                 f"{job_url}: "
# #                 f"{error}"
# #             )

# #             return None

# #         soup = BeautifulSoup(
# #             response.text,
# #             "html.parser",
# #         )

# #         # -----------------------------------------------------
# #         # Extract page text ONCE.
# #         #
# #         # Multiple soup.get_text() calls were unnecessarily
# #         # traversing the entire document.
# #         # -----------------------------------------------------

# #         page_text = soup.get_text(
# #             " ",
# #             strip=True,
# #         )

# #         # -----------------------------------------------------
# #         # TITLE
# #         # -----------------------------------------------------

# #         title = self._extract_title(
# #             soup
# #         )

# #         if not title:
# #             return None

# #         # -----------------------------------------------------
# #         # TITLE MATCH
# #         #
# #         # This happens immediately so irrelevant jobs are
# #         # discarded before expensive processing.
# #         # -----------------------------------------------------

# #         if not self._title_matches_search_terms(
# #             title,
# #             search_terms,
# #         ):
# #             return None

# #         # -----------------------------------------------------
# #         # POSTING DATE
# #         #
# #         # Do this early because old jobs can be discarded before
# #         # description/salary processing.
# #         # -----------------------------------------------------

# #         posting_date = (
# #             self._extract_posting_date(
# #                 page_text
# #             )
# #         )

# #         if self.posting_age_days is not None:

# #             if posting_date is None:
# #                 return None

# #             cutoff = (
# #                 datetime.now(
# #                     timezone.utc
# #                 )
# #                 -
# #                 timedelta(
# #                     days=self.posting_age_days
# #                 )
# #             )

# #             if posting_date < cutoff:
# #                 return None

# #         # -----------------------------------------------------
# #         # COMPANY
# #         # -----------------------------------------------------

# #         company = (
# #             self._extract_company(
# #                 soup
# #             )
# #         )

# #         if not company:
# #             return None

# #         # -----------------------------------------------------
# #         # LOCATION
# #         # -----------------------------------------------------

# #         location = (
# #             self._extract_location(
# #                 page_text
# #             )
# #         )

# #         # -----------------------------------------------------
# #         # DESCRIPTION
# #         # -----------------------------------------------------

# #         description = (
# #             self._extract_description(
# #                 soup
# #             )
# #         )

# #         # -----------------------------------------------------
# #         # SALARY
# #         # -----------------------------------------------------

# #         salary = (
# #             self._extract_salary(
# #                 page_text,
# #                 description,
# #             )
# #         )

# #         # -----------------------------------------------------
# #         # EMPLOYMENT TYPE
# #         # -----------------------------------------------------

# #         employment_type = (
# #             self._extract_employment_type(
# #                 page_text
# #             )
# #         )

# #         # -----------------------------------------------------
# #         # APPLY URL
# #         # -----------------------------------------------------

# #         apply_url = (
# #             self._extract_apply_url(
# #                 soup
# #             )
# #             or job_url
# #         )

# #         # -----------------------------------------------------
# #         # JOB ID
# #         # -----------------------------------------------------

# #         job_id = (
# #             self._extract_job_id(
# #                 job_url
# #             )
# #         )

# #         return Job(
# #             company=company,
# #             title=title,
# #             location=location,
# #             posting_url=job_url,
# #             description=description,
# #             posting_date=posting_date,
# #             salary=salary,
# #             source="Built In",
# #             apply_url=apply_url,
# #             employment_type=employment_type,
# #             job_id=job_id,
# #         )

# #     # =========================================================
# #     # TITLE
# #     # =========================================================

# #     @staticmethod
# #     def _extract_title(
# #         soup: BeautifulSoup,
# #     ) -> str:

# #         heading = soup.find("h1")

# #         if heading:

# #             title = heading.get_text(
# #                 " ",
# #                 strip=True,
# #             )

# #             if title:
# #                 return title

# #         if soup.title:

# #             title = soup.title.get_text(
# #                 " ",
# #                 strip=True,
# #             )

# #             title = re.sub(
# #                 r"\s*-\s*Built In.*$",
# #                 "",
# #                 title,
# #                 flags=re.IGNORECASE,
# #             )

# #             return title.strip()

# #         return ""

# #     # =========================================================
# #     # COMPANY
# #     # =========================================================

# #     @staticmethod
# #     def _extract_company(
# #         soup: BeautifulSoup,
# #     ) -> str:

# #         for anchor in soup.find_all(
# #             "a",
# #             href=True,
# #         ):

# #             href = anchor.get(
# #                 "href"
# #             )

# #             if not href:
# #                 continue

# #             if "/company/" not in href:
# #                 continue

# #             company = anchor.get_text(
# #                 " ",
# #                 strip=True,
# #             )

# #             if company:
# #                 return company

# #         return ""

# #     # =========================================================
# #     # LOCATION
# #     # =========================================================

# #     @staticmethod
# #     def _extract_location(
# #         text: str,
# #     ) -> str:

# #         locations = re.findall(
# #             r"\b"
# #             r"[A-Z][A-Za-z .'-]+,"
# #             r"\s*"
# #             r"[A-Z]{2}"
# #             r"(?:,\s*USA)?"
# #             r"\b",
# #             text,
# #         )

# #         cleaned = []

# #         for location in locations:

# #             location = location.strip()

# #             if location not in cleaned:

# #                 cleaned.append(
# #                     location
# #                 )

# #         return "; ".join(
# #             cleaned[:5]
# #         )

# #     # =========================================================
# #     # DESCRIPTION
# #     # =========================================================

# #     @staticmethod
# #     def _extract_description(
# #         soup: BeautifulSoup,
# #     ) -> str:

# #         # -----------------------------------------------------
# #         # Work on a copy-like parse tree by removing unwanted
# #         # elements before extracting HTML.
# #         # -----------------------------------------------------

# #         for element in soup.find_all(
# #             [
# #                 "script",
# #                 "style",
# #                 "noscript",
# #             ]
# #         ):

# #             element.decompose()

# #         article = soup.find(
# #             "article"
# #         )

# #         if article:

# #             return clean_html_description(
# #                 str(article)
# #             )

# #         body = soup.find(
# #             "body"
# #         )

# #         if not body:
# #             return ""

# #         return clean_html_description(
# #             str(body)
# #         )

# #     # =========================================================
# #     # POSTING DATE
# #     # =========================================================

# #     @staticmethod
# #     def _extract_posting_date(
# #         text: str,
# #     ) -> datetime | None:

# #         text = text.lower()

# #         now = datetime.now(
# #             timezone.utc
# #         )

# #         if "today" in text:

# #             return now

# #         if "yesterday" in text:

# #             return (
# #                 now -
# #                 timedelta(
# #                     days=1
# #                 )
# #             )

# #         match = re.search(
# #             r"(\d+)\s+"
# #             r"hours?\s+ago",
# #             text,
# #         )

# #         if match:

# #             return (
# #                 now -
# #                 timedelta(
# #                     hours=int(
# #                         match.group(1)
# #                     )
# #                 )
# #             )

# #         match = re.search(
# #             r"(\d+)\s+"
# #             r"days?\s+ago",
# #             text,
# #         )

# #         if match:

# #             return (
# #                 now -
# #                 timedelta(
# #                     days=int(
# #                         match.group(1)
# #                     )
# #                 )
# #             )

# #         match = re.search(
# #             r"reposted\s+"
# #             r"(\d+)\s+"
# #             r"days?\s+ago",
# #             text,
# #         )

# #         if match:

# #             return (
# #                 now -
# #                 timedelta(
# #                     days=int(
# #                         match.group(1)
# #                     )
# #                 )
# #             )

# #         return None

# #     # =========================================================
# #     # SALARY
# #     # =========================================================

# #     @staticmethod
# #     def _extract_salary(
# #         page_text: str,
# #         description: str,
# #     ) -> str:

# #         salary_match = re.search(
# #             r"\$[\d,]+"
# #             r"(?:\s*-\s*\$[\d,]+)?"
# #             r"(?:\s+(?:Annually|Hourly|Yearly))?",
# #             page_text,
# #             re.IGNORECASE,
# #         )

# #         if salary_match:

# #             return salary_match.group(
# #                 0
# #             ).strip()

# #         return extract_salary(
# #             description
# #         )

# #     # =========================================================
# #     # EMPLOYMENT TYPE
# #     # =========================================================

# #     @staticmethod
# #     def _extract_employment_type(
# #         text: str,
# #     ) -> str:

# #         text = text.lower()

# #         employment_types = [
# #             "full-time",
# #             "full time",
# #             "part-time",
# #             "part time",
# #             "contract",
# #             "internship",
# #             "temporary",
# #         ]

# #         for employment_type in (
# #             employment_types
# #         ):

# #             if employment_type in text:

# #                 return employment_type

# #         return ""

# #     # =========================================================
# #     # APPLY URL
# #     # =========================================================

# #     @staticmethod
# #     def _extract_apply_url(
# #         soup: BeautifulSoup,
# #     ) -> str:

# #         for anchor in soup.find_all(
# #             "a",
# #             href=True,
# #         ):

# #             text = anchor.get_text(
# #                 " ",
# #                 strip=True,
# #             ).lower()

# #             href = anchor.get(
# #                 "href"
# #             )

# #             if not href:
# #                 continue

# #             if (
# #                 "apply" in text
# #                 or "apply" in href.lower()
# #             ):

# #                 if (
# #                     href.startswith(
# #                         "http://"
# #                     )
# #                     or
# #                     href.startswith(
# #                         "https://"
# #                     )
# #                 ):

# #                     return href

# #         return ""

# #     # =========================================================
# #     # JOB ID
# #     # =========================================================

# #     @staticmethod
# #     def _extract_job_id(
# #         job_url: str,
# #     ) -> str:

# #         match = re.search(
# #             r"/job/[^/]+/(\d+)",
# #             job_url,
# #         )

# #         if match:

# #             return match.group(1)

# #         return ""

# #     # =========================================================
# #     # SEARCH TERMS
# #     # =========================================================

# #     @staticmethod
# #     def _normalize_search_terms(
# #         search_terms: list[str] | None,
# #     ) -> list[str]:

# #         if not search_terms:
# #             return []

# #         normalized = []

# #         for term in search_terms:

# #             if term is None:
# #                 continue

# #             term = str(
# #                 term
# #             ).strip().lower()

# #             if (
# #                 term
# #                 and term not in normalized
# #             ):

# #                 normalized.append(
# #                     term
# #                 )

# #         return normalized

# #     # =========================================================
# #     # TITLE MATCHING
# #     # =========================================================

# #     @staticmethod
# #     def _title_matches_search_terms(
# #         title: str,
# #         search_terms: list[str],
# #     ) -> bool:

# #         if not search_terms:
# #             return True

# #         title_lower = (
# #             title.lower()
# #         )

# #         for search_term in search_terms:

# #             # -------------------------------------------------
# #             # Exact phrase.
# #             # -------------------------------------------------

# #             if search_term in title_lower:
# #                 return True

# #             # -------------------------------------------------
# #             # All words.
# #             # -------------------------------------------------

# #             words = search_term.split()

# #             if all(
# #                 word in title_lower
# #                 for word in words
# #             ):

# #                 return True

# #         return False

# #     # =========================================================
# #     # HTTP SESSION
# #     # =========================================================

# #     def _get_session(self):

# #         session = getattr(
# #             self._thread_local,
# #             "session",
# #             None,
# #         )

# #         if session is None:

# #             session = requests.Session()

# #             session.headers.update({
# #                 "Accept": (
# #                     "text/html,"
# #                     "application/xhtml+xml,"
# #                     "application/xml;q=0.9,"
# #                     "*/*;q=0.8"
# #                 ),
# #                 "User-Agent": (
# #                     "Mozilla/5.0 "
# #                     "(Windows NT 10.0; Win64; x64) "
# #                     "AppleWebKit/537.36 "
# #                     "(KHTML, like Gecko) "
# #                     "Chrome/140.0 Safari/537.36"
# #                 ),
# #             })

# #             self._thread_local.session = (
# #                 session
# #             )

# #         return session

# #     # =========================================================
# #     # HTTP REQUEST
# #     # =========================================================

# #     def _request(
# #         self,
# #         method: str,
# #         url: str,
# #         **kwargs,
# #     ):

# #         for attempt in range(
# #             self.max_retries + 1
# #         ):

# #             try:

# #                 # -------------------------------------------------
# #                 # Global rate limit.
# #                 # -------------------------------------------------

# #                 self.rate_limiter.wait()

# #                 session = (
# #                     self._get_session()
# #                 )

# #                 response = (
# #                     session.request(
# #                         method,
# #                         url,
# #                         timeout=30,
# #                         **kwargs,
# #                     )
# #                 )

# #                 # -------------------------------------------------
# #                 # Rate limited.
# #                 # -------------------------------------------------

# #                 if response.status_code == 429:

# #                     if (
# #                         attempt
# #                         >= self.max_retries
# #                     ):

# #                         response.raise_for_status()

# #                     wait_seconds = (
# #                         2 ** attempt
# #                     )

# #                     print(
# #                         "Built In rate limit "
# #                         "(429). Waiting "
# #                         f"{wait_seconds}s..."
# #                     )

# #                     time.sleep(
# #                         wait_seconds
# #                     )

# #                     continue

# #                 # -------------------------------------------------
# #                 # Server error.
# #                 # -------------------------------------------------

# #                 if response.status_code >= 500:

# #                     if (
# #                         attempt
# #                         >= self.max_retries
# #                     ):

# #                         response.raise_for_status()

# #                     wait_seconds = (
# #                         2 ** attempt
# #                     )

# #                     print(
# #                         f"Built In server error "
# #                         f"({response.status_code}). "
# #                         f"Retrying in "
# #                         f"{wait_seconds}s..."
# #                     )

# #                     time.sleep(
# #                         wait_seconds
# #                     )

# #                     continue

# #                 response.raise_for_status()

# #                 return response

# #             except requests.RequestException:

# #                 if (
# #                     attempt
# #                     >= self.max_retries
# #                 ):

# #                     raise

# #                 wait_seconds = (
# #                     2 ** attempt
# #                 )

# #                 time.sleep(
# #                     wait_seconds
# #                 )

# #         return None


# # def self_base_url():
# #     return "https://builtin.com"


# # # import re
# # # import time
# # # from datetime import datetime, timedelta, timezone
# # # from urllib.parse import quote

# # # import requests
# # # from bs4 import BeautifulSoup

# # # from app.models.job import Job
# # # from app.sources.job_source import JobSource
# # # from app.utils.html_cleaner import clean_html_description
# # # from app.utils.salary_extractor import extract_salary


# # # class BuiltInSource(JobSource):

# # #     def __init__(
# # #         self,
# # #         posting_age_days: int = 2,
# # #         request_delay_seconds: float = 2.0,
# # #         max_retries: int = 1,
# # #         results_per_page: int = 20
# # #     ):

# # #         self.posting_age_days = posting_age_days

# # #         self.request_delay_seconds = (
# # #             request_delay_seconds
# # #         )

# # #         self.max_retries = max_retries

# # #         self.results_per_page = (
# # #             results_per_page
# # #         )

# # #         self.base_url = "https://builtin.com"

# # #         self.session = requests.Session()

# # #         self.session.headers.update({
# # #             "Accept": (
# # #                 "text/html,"
# # #                 "application/xhtml+xml,"
# # #                 "application/xml;q=0.9,"
# # #                 "*/*;q=0.8"
# # #             ),
# # #             "User-Agent": (
# # #                 "Mozilla/5.0 "
# # #                 "(Windows NT 10.0; Win64; x64) "
# # #                 "AppleWebKit/537.36 "
# # #                 "(KHTML, like Gecko) "
# # #                 "Chrome/140.0 Safari/537.36"
# # #             )
# # #         })

# # #         self._last_request_time = None

# # #     # =============================================================
# # #     # SEARCH
# # #     # =============================================================

# # #     def search(
# # #         self,
# # #         search_terms: list[str] | None = None,
# # #         location: str | None = None
# # #     ) -> list[Job]:

# # #         jobs = []

# # #         search_terms = (
# # #             self._normalize_search_terms(
# # #                 search_terms
# # #             )
# # #         )

# # #         # ---------------------------------------------------------
# # #         # Built In search pages.
# # #         #
# # #         # Example:
# # #         #
# # #         # https://builtin.com/jobs/developer
# # #         #
# # #         # We start with the general job search and perform the
# # #         # search-term filtering locally.
# # #         # ---------------------------------------------------------

# # #         page = 1

# # #         while True:

# # #             search_url = (
# # #                 self._build_search_url(
# # #                     search_terms=search_terms,
# # #                     location=location,
# # #                     page=page
# # #                 )
# # #             )

# # #             print(
# # #                 f"Built In search page {page}: "
# # #                 f"{search_url}"
# # #             )

# # #             try:

# # #                 response = self._request(
# # #                     "GET",
# # #                     search_url
# # #                 )

# # #             except requests.RequestException as error:

# # #                 print(
# # #                     f"Built In search failed: "
# # #                     f"{error}"
# # #                 )

# # #                 break

# # #             soup = BeautifulSoup(
# # #                 response.text,
# # #                 "html.parser"
# # #             )

# # #             job_links = (
# # #                 self._extract_job_links(
# # #                     soup
# # #                 )
# # #             )

# # #             if not job_links:
# # #                 break

# # #             jobs_found_on_page = 0

# # #             for job_url in job_links:

# # #                 # -------------------------------------------------
# # #                 # Retrieve individual job page.
# # #                 # -------------------------------------------------

# # #                 try:

# # #                     job = self._get_job(
# # #                         job_url=job_url,
# # #                         search_terms=search_terms
# # #                     )

# # #                 except Exception as error:

# # #                     print(
# # #                         f"Built In job failed: "
# # #                         f"{job_url}: {error}"
# # #                     )

# # #                     continue

# # #                 if job is None:
# # #                     continue

# # #                 jobs.append(job)
# # #                 jobs_found_on_page += 1

# # #             print(
# # #                 f"Built In page {page}: "
# # #                 f"{jobs_found_on_page} matching jobs"
# # #             )

# # #             # -----------------------------------------------------
# # #             # Stop if the page contains fewer jobs than expected.
# # #             #
# # #             # Built In can change its pagination, so this is only
# # #             # one of the stopping conditions.
# # #             # -----------------------------------------------------

# # #             if len(job_links) < self.results_per_page:
# # #                 break

# # #             page += 1

# # #             # -----------------------------------------------------
# # #             # Safety limit.
# # #             # -----------------------------------------------------

# # #             if page > 50:
# # #                 print(
# # #                     "Built In pagination safety limit reached."
# # #                 )
# # #                 break

# # #         print(
# # #             f"Built In returned {len(jobs)} jobs."
# # #         )

# # #         return jobs

# # #     # =============================================================
# # #     # SEARCH URL
# # #     # =============================================================

# # #     def _build_search_url(
# # #         self,
# # #         search_terms: list[str],
# # #         location: str | None,
# # #         page: int
# # #     ) -> str:

# # #         # ---------------------------------------------------------
# # #         # Built In has category/search pages such as:
# # #         #
# # #         # /jobs/developer
# # #         #
# # #         # We use a broad page and filter the actual title locally.
# # #         # ---------------------------------------------------------

# # #         if search_terms:

# # #             search_text = "-".join(
# # #                 search_terms
# # #             )

# # #             search_text = re.sub(
# # #                 r"[^a-zA-Z0-9\-]+",
# # #                 "-",
# # #                 search_text
# # #             ).strip("-").lower()

# # #             path = (
# # #                 f"/jobs/{search_text}"
# # #             )

# # #         else:

# # #             path = "/jobs"

# # #         url = (
# # #             f"{self.base_url}"
# # #             f"{path}"
# # #         )

# # #         if location:

# # #             url = (
# # #                 f"{url}"
# # #                 f"?location={quote(location)}"
# # #             )

# # #         if page > 1:

# # #             separator = (
# # #                 "&"
# # #                 if "?" in url
# # #                 else "?"
# # #             )

# # #             url = (
# # #                 f"{url}"
# # #                 f"{separator}"
# # #                 f"page={page}"
# # #             )

# # #         return url

# # #     # =============================================================
# # #     # JOB LINKS
# # #     # =============================================================

# # #     @staticmethod
# # #     def _extract_job_links(
# # #         soup: BeautifulSoup
# # #     ) -> list[str]:

# # #         links = []
# # #         seen = set()

# # #         for anchor in soup.find_all(
# # #             "a",
# # #             href=True
# # #         ):

# # #             href = anchor.get(
# # #                 "href"
# # #             )

# # #             if not href:
# # #                 continue

# # #             # -----------------------------------------------------
# # #             # Built In job URLs look like:
# # #             #
# # #             # /job/software-engineer/1234567
# # #             # -----------------------------------------------------

# # #             match = re.match(
# # #                 r"^/job/"
# # #                 r"[^/]+/"
# # #                 r"\d+/?$",
# # #                 href
# # #             )

# # #             if not match:
# # #                 continue

# # #             if href in seen:
# # #                 continue

# # #             seen.add(href)

# # #             links.append(
# # #                 f"https://builtin.com{href}"
# # #             )

# # #         return links

# # #     # =============================================================
# # #     # JOB
# # #     # =============================================================

# # #     def _get_job(
# # #         self,
# # #         job_url: str,
# # #         search_terms: list[str]
# # #     ) -> Job | None:

# # #         try:

# # #             response = self._request(
# # #                 "GET",
# # #                 job_url
# # #             )

# # #         except requests.RequestException as error:

# # #             print(
# # #                 f"Built In job request failed: "
# # #                 f"{job_url}: {error}"
# # #             )

# # #             return None

# # #         soup = BeautifulSoup(
# # #             response.text,
# # #             "html.parser"
# # #         )

# # #         # ---------------------------------------------------------
# # #         # Title
# # #         # ---------------------------------------------------------

# # #         title = self._extract_title(
# # #             soup
# # #         )

# # #         if not title:
# # #             return None

# # #         # ---------------------------------------------------------
# # #         # Title filtering.
# # #         #
# # #         # Do this before doing any expensive processing.
# # #         # ---------------------------------------------------------

# # #         if not self._title_matches_search_terms(
# # #             title,
# # #             search_terms
# # #         ):
# # #             return None

# # #         # ---------------------------------------------------------
# # #         # Company
# # #         # ---------------------------------------------------------

# # #         company = self._extract_company(
# # #             soup
# # #         )

# # #         if not company:
# # #             return None

# # #         # ---------------------------------------------------------
# # #         # Location
# # #         # ---------------------------------------------------------

# # #         location = self._extract_location(
# # #             soup
# # #         )

# # #         # ---------------------------------------------------------
# # #         # Description
# # #         # ---------------------------------------------------------

# # #         description = self._extract_description(
# # #             soup
# # #         )

# # #         # ---------------------------------------------------------
# # #         # Posting date
# # #         # ---------------------------------------------------------

# # #         posting_date = self._extract_posting_date(
# # #             soup
# # #         )

# # #         if self.posting_age_days is not None:

# # #             if posting_date is None:
# # #                 return None

# # #             cutoff = (
# # #                 datetime.now(
# # #                     timezone.utc
# # #                 )
# # #                 -
# # #                 timedelta(
# # #                     days=self.posting_age_days
# # #                 )
# # #             )

# # #             if posting_date < cutoff:
# # #                 return None

# # #         # ---------------------------------------------------------
# # #         # Salary
# # #         # ---------------------------------------------------------

# # #         salary = self._extract_salary(
# # #             soup,
# # #             description
# # #         )

# # #         # ---------------------------------------------------------
# # #         # Employment type
# # #         # ---------------------------------------------------------

# # #         employment_type = (
# # #             self._extract_employment_type(
# # #                 soup
# # #             )
# # #         )

# # #         # ---------------------------------------------------------
# # #         # Apply URL
# # #         # ---------------------------------------------------------

# # #         apply_url = (
# # #             self._extract_apply_url(
# # #                 soup
# # #             )
# # #             or job_url
# # #         )

# # #         # ---------------------------------------------------------
# # #         # Job ID
# # #         # ---------------------------------------------------------

# # #         job_id = self._extract_job_id(
# # #             job_url
# # #         )

# # #         return Job(
# # #             company=company,
# # #             title=title,
# # #             location=location,
# # #             posting_url=job_url,
# # #             description=description,
# # #             posting_date=posting_date,
# # #             salary=salary,
# # #             source="Built In",
# # #             apply_url=apply_url,
# # #             employment_type=employment_type,
# # #             job_id=job_id
# # #         )

# # #     # =============================================================
# # #     # TITLE
# # #     # =============================================================

# # #     @staticmethod
# # #     def _extract_title(
# # #         soup: BeautifulSoup
# # #     ) -> str:

# # #         # ---------------------------------------------------------
# # #         # The job page has the job title as the main heading.
# # #         # ---------------------------------------------------------

# # #         heading = soup.find("h1")

# # #         if heading:

# # #             title = heading.get_text(
# # #                 " ",
# # #                 strip=True
# # #             )

# # #             if title:
# # #                 return title

# # #         # ---------------------------------------------------------
# # #         # Fallback to title tag.
# # #         # ---------------------------------------------------------

# # #         if soup.title:

# # #             title = soup.title.get_text(
# # #                 " ",
# # #                 strip=True
# # #             )

# # #             title = re.sub(
# # #                 r"\s*-\s*Built In.*$",
# # #                 "",
# # #                 title,
# # #                 flags=re.IGNORECASE
# # #             )

# # #             return title.strip()

# # #         return ""

# # #     # =============================================================
# # #     # COMPANY
# # #     # =============================================================

# # #     @staticmethod
# # #     def _extract_company(
# # #         soup: BeautifulSoup
# # #     ) -> str:

# # #         # ---------------------------------------------------------
# # #         # Look for company links pointing to /company/.
# # #         # ---------------------------------------------------------

# # #         for anchor in soup.find_all(
# # #             "a",
# # #             href=True
# # #         ):

# # #             href = anchor.get(
# # #                 "href"
# # #             )

# # #             if "/company/" not in href:
# # #                 continue

# # #             company = anchor.get_text(
# # #                 " ",
# # #                 strip=True
# # #             )

# # #             if company:
# # #                 return company

# # #         # ---------------------------------------------------------
# # #         # Fallback.
# # #         # ---------------------------------------------------------

# # #         text = soup.get_text(
# # #             " ",
# # #             strip=True
# # #         )

# # #         return ""

# # #     # =============================================================
# # #     # LOCATION
# # #     # =============================================================

# # #     @staticmethod
# # #     def _extract_location(
# # #         soup: BeautifulSoup
# # #     ) -> str:

# # #         text = soup.get_text(
# # #             "\n",
# # #             strip=True
# # #         )

# # #         # ---------------------------------------------------------
# # #         # Common US location pattern.
# # #         # ---------------------------------------------------------

# # #         locations = re.findall(
# # #             r"\b"
# # #             r"[A-Z][A-Za-z .'-]+,"
# # #             r"\s*"
# # #             r"[A-Z]{2}"
# # #             r"(?:,\s*USA)?"
# # #             r"\b",
# # #             text
# # #         )

# # #         cleaned = []

# # #         for location in locations:

# # #             location = location.strip()

# # #             if location not in cleaned:
# # #                 cleaned.append(
# # #                     location
# # #                 )

# # #         return "; ".join(
# # #             cleaned[:5]
# # #         )

# # #     # =============================================================
# # #     # DESCRIPTION
# # #     # =============================================================

# # #     @staticmethod
# # #     def _extract_description(
# # #         soup: BeautifulSoup
# # #     ) -> str:

# # #         # ---------------------------------------------------------
# # #         # Remove elements that aren't part of the job description.
# # #         # ---------------------------------------------------------

# # #         for element in soup.find_all(
# # #             [
# # #                 "script",
# # #                 "style",
# # #                 "noscript"
# # #             ]
# # #         ):
# # #             element.decompose()

# # #         # ---------------------------------------------------------
# # #         # Look for the main article.
# # #         # ---------------------------------------------------------

# # #         article = soup.find(
# # #             "article"
# # #         )

# # #         if article:

# # #             html = str(
# # #                 article
# # #             )

# # #             return clean_html_description(
# # #                 html
# # #             )

# # #         # ---------------------------------------------------------
# # #         # Fallback to page body.
# # #         # ---------------------------------------------------------

# # #         body = soup.find(
# # #             "body"
# # #         )

# # #         if not body:
# # #             return ""

# # #         return clean_html_description(
# # #             str(body)
# # #         )

# # #     # =============================================================
# # #     # POSTING DATE
# # #     # =============================================================

# # #     def _extract_posting_date(
# # #         self,
# # #         soup: BeautifulSoup
# # #     ) -> datetime | None:

# # #         text = soup.get_text(
# # #             " ",
# # #             strip=True
# # #         ).lower()

# # #         now = datetime.now(
# # #             timezone.utc
# # #         )

# # #         # ---------------------------------------------------------
# # #         # Examples:
# # #         #
# # #         # "4 Hours Ago"
# # #         # "Yesterday"
# # #         # "3 Days Ago"
# # #         # ---------------------------------------------------------

# # #         if "today" in text:

# # #             return now

# # #         if "yesterday" in text:

# # #             return (
# # #                 now -
# # #                 timedelta(
# # #                     days=1
# # #                 )
# # #             )

# # #         match = re.search(
# # #             r"(\d+)\s+"
# # #             r"(?:hour|hours)"
# # #             r"\s+ago",
# # #             text
# # #         )

# # #         if match:

# # #             hours = int(
# # #                 match.group(1)
# # #             )

# # #             return (
# # #                 now -
# # #                 timedelta(
# # #                     hours=hours
# # #                 )
# # #             )

# # #         match = re.search(
# # #             r"(\d+)\s+"
# # #             r"(?:day|days)"
# # #             r"\s+ago",
# # #             text
# # #         )

# # #         if match:

# # #             days = int(
# # #                 match.group(1)
# # #             )

# # #             return (
# # #                 now -
# # #                 timedelta(
# # #                     days=days
# # #                 )
# # #             )

# # #         # ---------------------------------------------------------
# # #         # "Reposted 2 Days Ago"
# # #         # ---------------------------------------------------------

# # #         match = re.search(
# # #             r"reposted\s+"
# # #             r"(\d+)\s+"
# # #             r"(?:day|days)"
# # #             r"\s+ago",
# # #             text
# # #         )

# # #         if match:

# # #             days = int(
# # #                 match.group(1)
# # #             )

# # #             return (
# # #                 now -
# # #                 timedelta(
# # #                     days=days
# # #                 )
# # #             )

# # #         return None

# # #     # =============================================================
# # #     # SALARY
# # #     # =============================================================

# # #     @staticmethod
# # #     def _extract_salary(
# # #         soup: BeautifulSoup,
# # #         description: str
# # #     ) -> str:

# # #         text = soup.get_text(
# # #             " ",
# # #             strip=True
# # #         )

# # #         # ---------------------------------------------------------
# # #         # First try Built In's displayed salary.
# # #         # ---------------------------------------------------------

# # #         salary_match = re.search(
# # #             r"\$[\d,]+"
# # #             r"(?:\s*-\s*\$[\d,]+)?"
# # #             r"(?:\s+(?:Annually|Hourly|Yearly))?",
# # #             text,
# # #             re.IGNORECASE
# # #         )

# # #         if salary_match:

# # #             return salary_match.group(
# # #                 0
# # #             ).strip()

# # #         # ---------------------------------------------------------
# # #         # Existing project salary extractor as fallback.
# # #         # ---------------------------------------------------------

# # #         return extract_salary(
# # #             description
# # #         )

# # #     # =============================================================
# # #     # EMPLOYMENT TYPE
# # #     # =============================================================

# # #     @staticmethod
# # #     def _extract_employment_type(
# # #         soup: BeautifulSoup
# # #     ) -> str:

# # #         text = soup.get_text(
# # #             " ",
# # #             strip=True
# # #         ).lower()

# # #         employment_types = [
# # #             "full-time",
# # #             "full time",
# # #             "part-time",
# # #             "part time",
# # #             "contract",
# # #             "internship",
# # #             "temporary"
# # #         ]

# # #         for employment_type in (
# # #             employment_types
# # #         ):

# # #             if employment_type in text:

# # #                 return employment_type

# # #         return ""

# # #     # =============================================================
# # #     # APPLY URL
# # #     # =============================================================

# # #     @staticmethod
# # #     def _extract_apply_url(
# # #         soup: BeautifulSoup
# # #     ) -> str:

# # #         for anchor in soup.find_all(
# # #             "a",
# # #             href=True
# # #         ):

# # #             text = anchor.get_text(
# # #                 " ",
# # #                 strip=True
# # #             ).lower()

# # #             href = anchor.get(
# # #                 "href"
# # #             )

# # #             if not href:
# # #                 continue

# # #             if (
# # #                 "apply" in text
# # #                 or "apply" in href.lower()
# # #             ):

# # #                 if href.startswith(
# # #                     "http://"
# # #                 ) or href.startswith(
# # #                     "https://"
# # #                 ):

# # #                     return href

# # #         return ""

# # #     # =============================================================
# # #     # JOB ID
# # #     # =============================================================

# # #     @staticmethod
# # #     def _extract_job_id(
# # #         job_url: str
# # #     ) -> str:

# # #         match = re.search(
# # #             r"/job/[^/]+/(\d+)",
# # #             job_url
# # #         )

# # #         if match:

# # #             return match.group(1)

# # #         return ""

# # #     # =============================================================
# # #     # SEARCH TERMS
# # #     # =============================================================

# # #     @staticmethod
# # #     def _normalize_search_terms(
# # #         search_terms: list[str] | None
# # #     ) -> list[str]:

# # #         if not search_terms:
# # #             return []

# # #         normalized = []

# # #         for term in search_terms:

# # #             if term is None:
# # #                 continue

# # #             term = str(
# # #                 term
# # #             ).strip().lower()

# # #             if (
# # #                 term
# # #                 and term not in normalized
# # #             ):

# # #                 normalized.append(
# # #                     term
# # #                 )

# # #         return normalized

# # #     @staticmethod
# # #     def _title_matches_search_terms(
# # #         title: str,
# # #         search_terms: list[str]
# # #     ) -> bool:

# # #         if not search_terms:
# # #             return True

# # #         title_lower = title.lower()

# # #         for search_term in search_terms:

# # #             # -----------------------------------------------------
# # #             # Direct phrase match.
# # #             # -----------------------------------------------------

# # #             if search_term in title_lower:
# # #                 return True

# # #             # -----------------------------------------------------
# # #             # All words must exist in title.
# # #             # -----------------------------------------------------

# # #             words = search_term.split()

# # #             if all(
# # #                 word in title_lower
# # #                 for word in words
# # #             ):

# # #                 return True

# # #         return False

# # #     # =============================================================
# # #     # HTTP REQUEST
# # #     # =============================================================

# # #     def _request(
# # #         self,
# # #         method: str,
# # #         url: str,
# # #         **kwargs
# # #     ):

# # #         for attempt in range(
# # #             self.max_retries + 1
# # #         ):

# # #             try:

# # #                 self._wait_before_request()

# # #                 response = self.session.request(
# # #                     method,
# # #                     url,
# # #                     timeout=30,
# # #                     **kwargs
# # #                 )

# # #                 self._last_request_time = (
# # #                     time.monotonic()
# # #                 )

# # #                 # -------------------------------------------------
# # #                 # Rate limit.
# # #                 # -------------------------------------------------

# # #                 if response.status_code == 429:

# # #                     if (
# # #                         attempt
# # #                         >= self.max_retries
# # #                     ):

# # #                         response.raise_for_status()

# # #                     wait_seconds = (
# # #                         2 ** attempt
# # #                     )

# # #                     print(
# # #                         "Built In rate limit "
# # #                         f"(429). Waiting "
# # #                         f"{wait_seconds} seconds..."
# # #                     )

# # #                     time.sleep(
# # #                         wait_seconds
# # #                     )

# # #                     continue

# # #                 # -------------------------------------------------
# # #                 # Server error.
# # #                 # -------------------------------------------------

# # #                 if (
# # #                     response.status_code
# # #                     >= 500
# # #                 ):

# # #                     if (
# # #                         attempt
# # #                         >= self.max_retries
# # #                     ):

# # #                         response.raise_for_status()

# # #                     wait_seconds = (
# # #                         2 ** attempt
# # #                     )

# # #                     print(
# # #                         f"Built In server error "
# # #                         f"({response.status_code}). "
# # #                         f"Retrying in "
# # #                         f"{wait_seconds} seconds..."
# # #                     )

# # #                     time.sleep(
# # #                         wait_seconds
# # #                     )

# # #                     continue

# # #                 response.raise_for_status()

# # #                 return response

# # #             except requests.RequestException:

# # #                 if (
# # #                     attempt
# # #                     >= self.max_retries
# # #                 ):

# # #                     raise

# # #                 wait_seconds = (
# # #                     2 ** attempt
# # #                 )

# # #                 time.sleep(
# # #                     wait_seconds
# # #                 )

# # #         return None

# # #     # =============================================================
# # #     # REQUEST DELAY
# # #     # =============================================================

# # #     def _wait_before_request(self):

# # #         if self._last_request_time is None:
# # #             return

# # #         elapsed = (
# # #             time.monotonic()
# # #             -
# # #             self._last_request_time
# # #         )

# # #         remaining = (
# # #             self.request_delay_seconds
# # #             -
# # #             elapsed
# # #         )

# # #         if remaining > 0:

# # #             time.sleep(
# # #                 remaining
# # #             )
