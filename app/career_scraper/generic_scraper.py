import html
import json
import re
import time
from collections import deque
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

# Adjust this import to wherever your Job class actually lives.
from app.models.job import Job


class GenericCareerScraper:
    """
    Generic career-site scraper.

    Purpose:
        Discover actual job postings from company career pages and
        normalize them into the application's common Job object.

    The scraper intentionally does not assume that every company
    uses Workday, Greenhouse, Lever, Ashby, etc.

    Process:

        1. Fetch career page.
        2. Discover job-search/listing pages.
        3. Discover individual job URLs.
        4. Fetch individual job pages.
        5. Extract job information.
        6. Normalize into Job objects.
        7. Return list[Job].

    Posting-date detection is intentionally multi-layered.

    It searches:

        - Schema.org JSON-LD
        - <time datetime="">
        - HTML attributes
        - data-* attributes
        - meta tags
        - raw HTML / JavaScript
        - serialized application state
        - visible page text

    Different companies use different variable names for posting
    dates, so the scraper recognizes many naming conventions and
    scores candidates by confidence.
    """

    # -------------------------------------------------------------
    # Configuration
    # -------------------------------------------------------------

    MAX_DISCOVERY_PAGES = 10

    MAX_JOB_PAGES = 250

    MAX_CONSECUTIVE_429 = 3

    REQUEST_DELAY_SECONDS = 1.5

    RETRY_DELAY_SECONDS = 10

    REQUEST_TIMEOUT = 30

    # -------------------------------------------------------------
    # Constructor
    # -------------------------------------------------------------

    def __init__(
        self,
        timeout=REQUEST_TIMEOUT,
        request_delay=REQUEST_DELAY_SECONDS,
    ):

        self.timeout = timeout

        self.request_delay = request_delay

        self.session = requests.Session()

        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 "
                    "(KHTML, like Gecko) "
                    "Chrome/140.0.0.0 Safari/537.36"
                ),
                "Accept": (
                    "text/html,application/xhtml+xml,"
                    "application/xml;q=0.9,image/avif,"
                    "image/webp,*/*;q=0.8"
                ),
                "Accept-Language": "en-US,en;q=0.9",
                "Connection": "keep-alive",
            }
        )

    # =============================================================
    # PUBLIC SCRAPE METHOD
    # =============================================================

    def scrape(
        self,
        company,
        url,
    ):
        """
        Scrape a company career site.

        Returns:
            list[Job]
        """

        print()
        print("=" * 80)
        print(f"SCRAPING: {company}")
        print(f"CAREER URL: {url}")
        print("=" * 80)

        jobs = []

        discovered_job_urls = set()

        discovered_pages = set()

        discovery_queue = deque()

        normalized_url = self._normalize_url(
            url
        )

        discovery_queue.append(
            normalized_url
        )

        consecutive_429 = 0

        # =========================================================
        # DISCOVERY PHASE
        # =========================================================

        while (
            discovery_queue
            and len(discovered_pages)
            < self.MAX_DISCOVERY_PAGES
        ):

            page_url = discovery_queue.popleft()

            if page_url in discovered_pages:
                continue

            discovered_pages.add(
                page_url
            )

            print()
            print(
                f"Checking discovery page "
                f"{len(discovered_pages)}/"
                f"{self.MAX_DISCOVERY_PAGES}:"
            )

            print(
                f"  {page_url}"
            )

            try:

                response = self._fetch_page(
                    page_url
                )

            except requests.HTTPError as exc:

                status = (
                    exc.response.status_code
                    if exc.response is not None
                    else None
                )

                if status == 429:

                    consecutive_429 += 1

                    print(
                        "  HTTP 429 - "
                        "Too many requests."
                    )

                    if (
                        consecutive_429
                        >= self.MAX_CONSECUTIVE_429
                    ):

                        print(
                            "  Too many consecutive "
                            "429 responses."
                        )

                        print(
                            f"  Stopping discovery "
                            f"for {company}."
                        )

                        break

                else:

                    print(
                        f"  HTTP error: {exc}"
                    )

                continue

            except requests.RequestException as exc:

                print(
                    f"  Request error: {exc}"
                )

                continue

            consecutive_429 = 0

            soup = BeautifulSoup(
                response.text,
                "html.parser",
            )

            # -----------------------------------------------------
            # Structured JobPosting records.
            # -----------------------------------------------------

            structured_jobs = (
                self._extract_json_ld_jobs(
                    soup,
                    company,
                    page_url,
                )
            )

            if structured_jobs:

                print(
                    f"  Found "
                    f"{len(structured_jobs)} "
                    f"structured JobPosting "
                    f"records."
                )

                jobs.extend(
                    structured_jobs
                )

            # -----------------------------------------------------
            # Discover links.
            # -----------------------------------------------------

            links = self._discover_links(
                soup,
                page_url,
            )

            job_count = 0

            search_count = 0

            for link in links:

                link_type = link["type"]

                link_url = link["url"]

                if link_type == "job":

                    if (
                        link_url
                        not in discovered_job_urls
                    ):

                        discovered_job_urls.add(
                            link_url
                        )

                        job_count += 1

                elif link_type == "job_search":

                    if (
                        link_url
                        not in discovered_pages
                        and link_url
                        not in discovery_queue
                    ):

                        discovery_queue.append(
                            link_url
                        )

                        search_count += 1

            print(
                f"  New job links discovered: "
                f"{job_count}"
            )

            print(
                f"  New search/listing pages: "
                f"{search_count}"
            )

        # =========================================================
        # DISCOVERY SUMMARY
        # =========================================================

        print()
        print("-" * 80)

        print(
            f"Discovery complete for "
            f"{company}"
        )

        print(
            f"Pages examined: "
            f"{len(discovered_pages)}"
        )

        print(
            f"Individual job URLs discovered: "
            f"{len(discovered_job_urls)}"
        )

        print(
            f"Structured jobs discovered: "
            f"{len(jobs)}"
        )

        print("-" * 80)

        # =========================================================
        # FETCH INDIVIDUAL JOB PAGES
        # =========================================================

        job_urls_to_fetch = list(
            discovered_job_urls
        )

        if (
            len(job_urls_to_fetch)
            > self.MAX_JOB_PAGES
        ):

            print(
                f"WARNING: "
                f"{len(job_urls_to_fetch)} "
                f"job URLs discovered."
            )

            print(
                f"Only the first "
                f"{self.MAX_JOB_PAGES} "
                f"will be fetched."
            )

            job_urls_to_fetch = (
                job_urls_to_fetch[
                    : self.MAX_JOB_PAGES
                ]
            )

        print()
        print(
            f"Fetching "
            f"{len(job_urls_to_fetch)} "
            f"individual job pages."
        )

        consecutive_429 = 0

        # =========================================================
        # INDIVIDUAL JOB REQUESTS
        # =========================================================

        for index, job_url in enumerate(
            job_urls_to_fetch,
            start=1,
        ):

            print()
            print(
                f"[{index}/"
                f"{len(job_urls_to_fetch)}] "
                f"{job_url}"
            )

            try:

                response = self._fetch_page(
                    job_url
                )

            except requests.HTTPError as exc:

                status = (
                    exc.response.status_code
                    if exc.response is not None
                    else None
                )

                if status == 429:

                    consecutive_429 += 1

                    print(
                        "  HTTP 429."
                    )

                    print(
                        f"  Sleeping "
                        f"{self.RETRY_DELAY_SECONDS} "
                        f"seconds."
                    )

                    time.sleep(
                        self.RETRY_DELAY_SECONDS
                    )

                    if (
                        consecutive_429
                        >= self.MAX_CONSECUTIVE_429
                    ):

                        print(
                            "  Too many "
                            "consecutive 429s."
                        )

                        print(
                            "  Stopping job "
                            "requests."
                        )

                        break

                else:

                    print(
                        f"  HTTP error: "
                        f"{exc}"
                    )

                continue

            except requests.RequestException as exc:

                print(
                    f"  Request error: "
                    f"{exc}"
                )

                continue

            consecutive_429 = 0

            soup = BeautifulSoup(
                response.text,
                "html.parser",
            )

            # -----------------------------------------------------
            # Structured JobPosting.
            # -----------------------------------------------------

            detail_jobs = (
                self._extract_json_ld_jobs(
                    soup,
                    company,
                    job_url,
                )
            )

            if detail_jobs:

                for job in detail_jobs:

                    print(
                        f"Job detail:     {job}\n"
                    )

                    jobs.append(
                        job
                    )

                    print(
                        f"  Job found: "
                        f"{job.title}"
                    )

            else:

                # -------------------------------------------------
                # Generic HTML extraction.
                # -------------------------------------------------

                job = (
                    self._extract_job_from_html(
                        soup,
                        company,
                        job_url,
                    )
                )

                if job:

                    jobs.append(
                        job
                    )

                    print(
                        f"  Job found: "
                        f"{job.title}"
                    )

                else:

                    print(
                        "  Could not extract "
                        "job details."
                    )

        # =========================================================
        # DEDUPLICATE
        # =========================================================

        jobs = self._deduplicate_jobs(
            jobs
        )

        # =========================================================
        # FINAL RESULT
        # =========================================================

        print()
        print("=" * 80)

        print(
            f"FINAL RESULT: "
            f"{company} -> "
            f"{len(jobs)} jobs discovered"
        )

        print("=" * 80)

        for job in jobs:

            self._print_job(
                job
            )

        return jobs

    # =============================================================
    # HTTP
    # =============================================================

    def _fetch_page(
        self,
        url,
    ):
        """
        Fetch a page.
        """

        time.sleep(
            self.request_delay
        )

        response = self.session.get(
            url,
            timeout=self.timeout,
            allow_redirects=True,
        )

        print(
            f"  HTTP {response.status_code}: "
            f"{response.url}"
        )

        response.raise_for_status()

        return response

    # =============================================================
    # LINK DISCOVERY
    # =============================================================

    def _discover_links(
        self,
        soup,
        base_url,
    ):
        """
        Discover likely job and job-search links.
        """

        results = []

        seen = set()

        for link in soup.find_all(
            "a",
            href=True,
        ):

            href = link.get(
                "href"
            )

            text = link.get_text(
                " ",
                strip=True,
            )

            if not href:
                continue

            if not text:
                continue

            absolute_url = urljoin(
                base_url,
                href,
            )

            absolute_url = (
                self._normalize_url(
                    absolute_url
                )
            )

            if absolute_url in seen:
                continue

            seen.add(
                absolute_url
            )

            if not self._same_domain(
                base_url,
                absolute_url,
            ):

                if not self._looks_like_ats_url(
                    absolute_url
                ):

                    continue

            link_type = (
                self._classify_link(
                    text,
                    absolute_url,
                )
            )

            if link_type:

                results.append(
                    {
                        "type": link_type,
                        "url": absolute_url,
                        "text": text,
                    }
                )

        return results

    # =============================================================
    # LINK CLASSIFICATION
    # =============================================================

    def _classify_link(
        self,
        text,
        url,
    ):
        """
        Determine whether a link is:

            job
            job_search
            None
        """

        text_lower = text.lower()

        url_lower = url.lower()

        job_patterns = [

            r"/jobs?/\d+",

            r"/jobs?/[a-z0-9\-]+/[a-z0-9\-]+",

            r"/position/\d+",

            r"/positions/\d+",

            r"/job/[a-z0-9\-]+",

            r"/job-\d+",

            r"/jobs-\d+",

            r"gh_jid=",

            r"jobid=",

            r"job_id=",

            r"lever\.co/.+",

            r"greenhouse\.io/.+/jobs/\d+",

            r"ashbyhq\.com/.*/job/",

            r"myworkdayjobs\.com/.*/job/",
        ]

        for pattern in job_patterns:

            if re.search(
                pattern,
                url_lower,
            ):

                return "job"

        search_patterns = [

            "/careers/search",

            "/careers/jobs",

            "/careers/positions",

            "/jobs",

            "/jobs/search",

            "/jobs/search-results",

            "/job-search",

            "/search/jobs",

            "/open-roles",

            "/open-positions",

            "/careers/open-roles",

            "/careers/openings",

            "/careers/opportunities",

            "/careers#job",

            "?q=",

            "?query=",

            "?search=",

        ]

        for pattern in search_patterns:

            if pattern in url_lower:

                return "job_search"

        search_text = (
            " ".join(
                [
                    text_lower,
                    url_lower,
                ]
            )
        )

        search_indicators = [

            "view open jobs",

            "view open roles",

            "view all jobs",

            "view all roles",

            "see open positions",

            "see open jobs",

            "search jobs",

            "search open roles",

            "search opportunities",

            "open roles",

            "open positions",

            "job search",

            "career opportunities",

            "view opportunities",
        ]

        if any(
            indicator in search_text
            for indicator in search_indicators
        ):

            return "job_search"

        return None

    # =============================================================
    # JSON-LD
    # =============================================================

    def _extract_json_ld_jobs(
        self,
        soup,
        company,
        base_url,
    ):
        """
        Extract Schema.org JobPosting objects.
        """

        jobs = []

        scripts = soup.find_all(
            "script",
            type="application/ld+json",
        )

        for script in scripts:

            try:

                raw = (
                    script.string
                    or script.get_text()
                )

                data = json.loads(
                    raw
                )

            except (
                json.JSONDecodeError,
                TypeError,
            ):

                continue

            records = (
                self._flatten_json_ld(
                    data
                )
            )

            for record in records:

                if not isinstance(
                    record,
                    dict,
                ):

                    continue

                record_type = (
                    record.get(
                        "@type"
                    )
                )

                if isinstance(
                    record_type,
                    list,
                ):

                    is_job = (
                        "JobPosting"
                        in record_type
                    )

                else:

                    is_job = (
                        record_type
                        == "JobPosting"
                    )

                if not is_job:
                    continue

                job = (
                    self._build_job_from_json_ld(
                        record,
                        company,
                        base_url,
                    )
                )

                if job:

                    jobs.append(
                        job
                    )

        return jobs

    # =============================================================
    # JSON-LD FLATTEN
    # =============================================================

    def _flatten_json_ld(
        self,
        data,
    ):

        if isinstance(
            data,
            list,
        ):

            records = []

            for item in data:

                records.extend(
                    self._flatten_json_ld(
                        item
                    )
                )

            return records

        if isinstance(
            data,
            dict,
        ):

            if "@graph" in data:

                return self._flatten_json_ld(
                    data["@graph"]
                )

            return [data]

        return []

    # =============================================================
    # BUILD JOB FROM JSON-LD
    # =============================================================

    def _build_job_from_json_ld(
        self,
        data,
        company,
        base_url,
    ):
        """
        Convert Schema.org JobPosting into our Job object.
        """

        title = self._get_string(
            data.get(
                "title"
            )
        )

        if not title:

            return None

        posting_url = (
            self._get_string(
                data.get(
                    "url"
                )
            )
            or base_url
        )

        posting_url = urljoin(
            base_url,
            posting_url,
        )

        location = (
            self._extract_location(
                data.get(
                    "jobLocation"
                )
            )
        )

        description = (
            self._clean_html(
                self._get_string(
                    data.get(
                        "description"
                    )
                )
            )
        )

        posting_date = (
            self._parse_date(
                data.get(
                    "datePosted"
                )
            )
        )

        # ---------------------------------------------------------
        # Important:
        #
        # If JSON-LD contains a JobPosting but datePosted is empty,
        # inspect the raw page as well.
        # ---------------------------------------------------------

        if not posting_date:

            posting_date = (
                self._extract_posting_date_from_page_data(
                    base_url,
                    data,
                )
            )

        employment_type = (
            self._get_string(
                data.get(
                    "employmentType"
                )
            )
        )

        salary = (
            self._extract_salary(
                data
            )
        )

        job_id = (
            self._extract_job_id(
                posting_url
            )
        )

        return Job(
            company=company,
            title=title,
            location=location,
            posting_url=posting_url,
            description=description,
            posting_date=posting_date,
            salary=salary,
            source="Generic",
            apply_url=posting_url,
            employment_type=employment_type,
            job_id=job_id,
        )

    # =============================================================
    # HTML JOB EXTRACTION
    # =============================================================

    def _extract_job_from_html(
        self,
        soup,
        company,
        job_url,
    ):
        """
        Extract a job from a job-detail page when JSON-LD is
        unavailable.
        """

        title = ""

        h1 = soup.find(
            "h1"
        )

        if h1:

            title = h1.get_text(
                " ",
                strip=True,
            )

        if not title:

            meta_title = soup.find(
                "meta",
                property="og:title",
            )

            if meta_title:

                title = self._get_string(
                    meta_title.get(
                        "content"
                    )
                )

        if not title and soup.title:

            title = soup.title.get_text(
                " ",
                strip=True,
            )

        if not title:

            return None

        if self._looks_like_non_job_page(
            title,
            job_url,
        ):

            return None

        description = (
            self._extract_description(
                soup
            )
        )

        location = (
            self._extract_html_location(
                soup
            )
        )

        posting_date = (
            self._extract_html_posting_date(
                soup
            )
        )

        employment_type = (
            self._extract_html_employment_type(
                soup
            )
        )

        salary = (
            self._extract_salary_from_text(
                description
            )
        )

        job_id = (
            self._extract_job_id(
                job_url
            )
        )

        return Job(
            company=company,
            title=title,
            location=location,
            posting_url=job_url,
            description=description,
            posting_date=posting_date,
            salary=salary,
            source="Generic",
            apply_url=job_url,
            employment_type=employment_type,
            job_id=job_id,
        )

    # =============================================================
    # DESCRIPTION
    # =============================================================

    def _extract_description(
        self,
        soup,
    ):

        selectors = [

            "[class*='description']",

            "[class*='job-description']",

            "[id*='description']",

            "[class*='posting']",

            "[class*='content']",

            "main",
        ]

        for selector in selectors:

            element = soup.select_one(
                selector
            )

            if not element:
                continue

            text = element.get_text(
                "\n",
                strip=True,
            )

            if len(text) >= 200:

                return text

        if soup.body:

            return soup.body.get_text(
                "\n",
                strip=True,
            )

        return ""

    # =============================================================
    # LOCATION
    # =============================================================

    def _extract_location(
        self,
        location_data,
    ):

        if not location_data:

            return ""

        if isinstance(
            location_data,
            list,
        ):

            locations = []

            for item in location_data:

                value = (
                    self._extract_location(
                        item
                    )
                )

                if value:

                    locations.append(
                        value
                    )

            return ", ".join(
                locations
            )

        if isinstance(
            location_data,
            dict,
        ):

            address = (
                location_data.get(
                    "address",
                    {},
                )
            )

            if isinstance(
                address,
                dict,
            ):

                parts = [

                    address.get(
                        "addressLocality"
                    ),

                    address.get(
                        "addressRegion"
                    ),

                    address.get(
                        "postalCode"
                    ),

                    address.get(
                        "addressCountry"
                    ),
                ]

                return ", ".join(
                    str(part)
                    for part in parts
                    if part
                )

        return ""

    # =============================================================
    # HTML LOCATION
    # =============================================================

    def _extract_html_location(
        self,
        soup,
    ):

        selectors = [

            "[class*='location']",

            "[id*='location']",

            "[class*='office']",

            "[class*='job-location']",

            "[data-testid*='location']",
        ]

        for selector in selectors:

            elements = soup.select(
                selector
            )

            for element in elements:

                text = element.get_text(
                    " ",
                    strip=True,
                )

                if (
                    text
                    and len(text) < 300
                ):

                    return text

        return ""

    # =============================================================
    # POSTING DATE
    # =============================================================

    def _extract_html_posting_date(
        self,
        soup,
    ):
        """
        Aggressively detect a job posting date.

        Detection order:

            1. <time>
            2. semantic HTML attributes
            3. data-* attributes
            4. meta tags
            5. raw HTML / JavaScript
            6. visible text

        Candidates are scored and the strongest date is returned.
        """

        # ---------------------------------------------------------
        # 1. <time datetime="">
        # ---------------------------------------------------------

        candidates = []

        for time_element in soup.find_all(
            "time"
        ):

            value = (
                time_element.get(
                    "datetime"
                )
                or time_element.get(
                    "date"
                )
            )

            if value:

                parsed = self._parse_date(
                    value
                )

                if parsed:

                    candidates.append(
                        {
                            "date": parsed,
                            "score": 100,
                            "source": "time_datetime",
                            "key": "datetime",
                        }
                    )

            text = time_element.get_text(
                " ",
                strip=True,
            )

            parsed = self._parse_date(
                text
            )

            if parsed:

                candidates.append(
                    {
                        "date": parsed,
                        "score": 90,
                        "source": "time_text",
                        "key": "time",
                    }
                )

        # ---------------------------------------------------------
        # 2. Semantic HTML attributes.
        # ---------------------------------------------------------

        date_attribute_names = {

            "dateposted",
            "date-posted",
            "date_posted",

            "postingdate",
            "posting-date",
            "posting_date",

            "posteddate",
            "posted-date",
            "posted_date",

            "publisheddate",
            "published-date",
            "published_date",

            "publishdate",
            "publish-date",
            "publish_date",

            "jobposteddate",
            "job-posted-date",
            "job_posted_date",

            "jobpostingdate",
            "job-posting-date",
            "job_posting_date",

            "datecreated",
            "date-created",
            "date_created",

            "createddate",
            "created-date",
            "created_date",

            "postedat",
            "posted-at",
            "posted_at",

            "postingat",
            "posting-at",
            "posting_at",

            "publishedat",
            "published-at",
            "published_at",

            "publishat",
            "publish-at",
            "publish_at",

            "createdat",
            "created-at",
            "created_at",

            "jobdate",
            "job-date",
            "job_date",
        }

        for element in soup.find_all(True):

            for attr_name, attr_value in element.attrs.items():

                normalized_attr = (
                    str(attr_name)
                    .lower()
                    .strip()
                )

                if normalized_attr.startswith(
                    "data-"
                ):

                    normalized_attr = (
                        normalized_attr[5:]
                    )

                if (
                    normalized_attr
                    not in date_attribute_names
                ):

                    continue

                if isinstance(
                    attr_value,
                    list,
                ):

                    attr_value = " ".join(
                        str(x)
                        for x in attr_value
                    )

                parsed = self._parse_date(
                    attr_value
                )

                if not parsed:

                    parsed = (
                        self._parse_date_fragment(
                            attr_value
                        )
                    )

                if parsed:

                    candidates.append(
                        {
                            "date": parsed,
                            "score": (
                                self._posting_date_key_score(
                                    normalized_attr
                                )
                                + 10
                            ),
                            "source": "html_attribute",
                            "key": normalized_attr,
                        }
                    )

        # ---------------------------------------------------------
        # 3. Meta tags.
        # ---------------------------------------------------------

        meta_names = {

            "dateposted",

            "date-posted",

            "postingdate",

            "posteddate",

            "publisheddate",

            "publishdate",

            "datecreated",

            "createddate",

            "article:published_time",

            "article:modified_time",

            "og:published_time",

            "published_time",
        }

        for meta in soup.find_all(
            "meta"
        ):

            names = [

                meta.get(
                    "name"
                ),

                meta.get(
                    "property"
                ),

                meta.get(
                    "itemprop"
                ),

                meta.get(
                    "key"
                ),
            ]

            content = meta.get(
                "content"
            )

            if not content:

                continue

            for name in names:

                if not name:

                    continue

                normalized = (
                    str(name)
                    .lower()
                    .strip()
                )

                if normalized not in meta_names:

                    continue

                parsed = self._parse_date(
                    content
                )

                if not parsed:

                    parsed = (
                        self._parse_date_fragment(
                            content
                        )
                    )

                if parsed:

                    candidates.append(
                        {
                            "date": parsed,
                            "score": (
                                self._posting_date_key_score(
                                    normalized
                                )
                                + 5
                            ),
                            "source": "meta",
                            "key": normalized,
                        }
                    )

        # ---------------------------------------------------------
        # 4. RAW HTML / JavaScript.
        # ---------------------------------------------------------

        raw_html = str(
            soup
        )

        raw_html = html.unescape(
            raw_html
        )

        raw_candidates = (
            self._extract_posting_dates_from_raw_html(
                raw_html
            )
        )

        candidates.extend(
            raw_candidates
        )

        # ---------------------------------------------------------
        # 5. Visible text.
        # ---------------------------------------------------------

        visible_text = soup.get_text(
            " ",
            strip=True,
        )

        visible_candidates = (
            self._extract_posting_dates_from_text(
                visible_text
            )
        )

        candidates.extend(
            visible_candidates
        )

        # ---------------------------------------------------------
        # Select best candidate.
        # ---------------------------------------------------------

        best = (
            self._select_best_posting_date(
                candidates
            )
        )

        if best:

            return best["date"]

        return None

    # =============================================================
    # POSTING DATE FROM PAGE DATA
    # =============================================================

    def _extract_posting_date_from_page_data(
        self,
        base_url,
        json_ld_data,
    ):
        """
        This method exists primarily for the situation where a page
        contains valid JSON-LD JobPosting data but datePosted is
        missing.

        The base_url itself cannot provide HTML, so this method
        currently returns None.

        Raw HTML date detection is performed by
        _extract_job_from_html(), where the complete page is
        available.

        Kept as a separate method so that future implementations can
        pass response HTML into the JSON-LD processing path.
        """

        return None

    # =============================================================
    # RAW HTML POSTING DATE DETECTION
    # =============================================================

    def _extract_posting_dates_from_raw_html(
        self,
        raw_html,
    ):
        """
        Search raw HTML for many possible posting-date variable names.

        Examples:

            "datePosted": "2026-08-01"

            "postingDate": "2026-08-01"

            "postedAt": "2026-08-01T14:20:00Z"

            "created_at": "2026-08-01"

            data-posted-date="2026-08-01"
        """

        if not raw_html:

            return []

        candidates = []

        # ---------------------------------------------------------
        # Common date keys.
        # ---------------------------------------------------------

        date_keys = [

            # Schema.org
            "datePosted",

            # Strong posting-date semantics
            "postingDate",
            "postedDate",

            "jobPostedDate",
            "jobPostingDate",

            "posting_date",
            "posted_date",

            "job_posted_date",
            "job_posting_date",

            # Publishing
            "publishedDate",
            "publishDate",

            "published_date",
            "publish_date",

            # Timestamp variants
            "postedAt",
            "postingAt",

            "publishedAt",
            "publishAt",

            "createdAt",

            "posted_at",
            "posting_at",

            "published_at",
            "publish_at",

            "created_at",

            # Created/date variants
            "dateCreated",
            "date_created",

            "createdDate",
            "created_date",

            # Other common names
            "jobDate",
            "job_date",

            "postingTimestamp",
            "posting_timestamp",

            "publishedTimestamp",
            "published_timestamp",

            "jobPostedAt",
            "job_posted_at",

            "jobPostingAt",
            "job_posting_at",
        ]

        # ---------------------------------------------------------
        # Direct JSON / JS key:value detection.
        # ---------------------------------------------------------

        for key in date_keys:

            escaped_key = re.escape(
                key
            )

            pattern = re.compile(
                rf"""
                (?:
                    ["']?
                    {escaped_key}
                    ["']?
                )
                \s*
                :
                \s*
                (?:
                    ["']
                    (?P<quoted>
                        [^"']{{1,120}}
                    )
                    ["']
                    |
                    (?P<unquoted>
                        [A-Za-z0-9:+./,\- ]{{4,120}}
                    )
                )
                """,
                re.IGNORECASE
                | re.VERBOSE,
            )

            for match in pattern.finditer(
                raw_html
            ):

                value = (
                    match.group(
                        "quoted"
                    )
                    or match.group(
                        "unquoted"
                    )
                )

                if not value:

                    continue

                parsed = self._parse_date(
                    value
                )

                if not parsed:

                    parsed = (
                        self._parse_date_fragment(
                            value
                        )
                    )

                if not parsed:

                    continue

                candidates.append(
                    {
                        "date": parsed,
                        "score": (
                            self._posting_date_key_score(
                                key
                            )
                        ),
                        "source": "raw_html",
                        "key": key,
                    }
                )

        # ---------------------------------------------------------
        # data-* attributes.
        # ---------------------------------------------------------

        data_attribute_pattern = re.compile(
            r"""
            data-
            (?P<key>
                [a-zA-Z0-9_-]*
                (?:
                    posted
                    |
                    posting
                    |
                    published
                    |
                    publish
                    |
                    created
                )
                [a-zA-Z0-9_-]*
            )
            \s*=\s*
            ["']
            (?P<value>
                [^"']+
            )
            ["']
            """,
            re.IGNORECASE
            | re.VERBOSE,
        )

        for match in data_attribute_pattern.finditer(
            raw_html
        ):

            key = match.group(
                "key"
            )

            value = match.group(
                "value"
            )

            parsed = self._parse_date(
                value
            )

            if not parsed:

                parsed = (
                    self._parse_date_fragment(
                        value
                    )
                )

            if not parsed:

                continue

            score = (
                self._posting_date_key_score(
                    key
                )
                + 5
            )

            candidates.append(
                {
                    "date": parsed,
                    "score": score,
                    "source": "data_attribute",
                    "key": key,
                }
            )

        # ---------------------------------------------------------
        # Schema.org datePosted direct raw search.
        # ---------------------------------------------------------

        schema_pattern = re.compile(
            r"""
            ["']datePosted["']
            \s*:\s*
            ["']
            (?P<value>
                [^"']+
            )
            ["']
            """,
            re.IGNORECASE
            | re.VERBOSE,
        )

        for match in schema_pattern.finditer(
            raw_html
        ):

            value = match.group(
                "value"
            )

            parsed = self._parse_date(
                value
            )

            if not parsed:

                parsed = (
                    self._parse_date_fragment(
                        value
                    )
                )

            if parsed:

                candidates.append(
                    {
                        "date": parsed,
                        "score": 100,
                        "source": "schema_raw_html",
                        "key": "datePosted",
                    }
                )

        return candidates

    # =============================================================
    # VISIBLE TEXT POSTING DATE DETECTION
    # =============================================================

    def _extract_posting_dates_from_text(
        self,
        text,
    ):
        """
        Search human-readable page text for posting-date phrases.
        """

        if not text:

            return []

        candidates = []

        date_expression = (
            r"""
            (?:
                \d{4}-\d{1,2}-\d{1,2}

                |

                \d{1,2}/\d{1,2}/\d{4}

                |

                \d{1,2}-\d{1,2}-\d{4}

                |

                (?:Jan(?:uary)?|
                   Feb(?:ruary)?|
                   Mar(?:ch)?|
                   Apr(?:il)?|
                   May|
                   Jun(?:e)?|
                   Jul(?:y)?|
                   Aug(?:ust)?|
                   Sep(?:t(?:ember)?)?|
                   Oct(?:ober)?|
                   Nov(?:ember)?|
                   Dec(?:ember)?)
                \s+\d{1,2},
                \s+\d{4}
            )
            """
        )

        patterns = [

            (
                rf"\bposted\s+(?:on\s+)?"
                rf"({date_expression})"
            ),

            (
                rf"\bdate\s+posted\s*:?\s*"
                rf"({date_expression})"
            ),

            (
                rf"\bposting\s+date\s*:?\s*"
                rf"({date_expression})"
            ),

            (
                rf"\bposted\s+date\s*:?\s*"
                rf"({date_expression})"
            ),

            (
                rf"\bpublished\s*:?\s*"
                rf"({date_expression})"
            ),

            (
                rf"\bpublication\s+date\s*:?\s*"
                rf"({date_expression})"
            ),

            (
                rf"\bjob\s+posted\s*:?\s*"
                rf"({date_expression})"
            ),

            (
                rf"\bjob\s+posting\s+date\s*:?\s*"
                rf"({date_expression})"
            ),

            (
                rf"\bdate\s+published\s*:?\s*"
                rf"({date_expression})"
            ),

            (
                rf"\bpublished\s+date\s*:?\s*"
                rf"({date_expression})"
            ),

            (
                rf"\badded\s*:?\s*"
                rf"({date_expression})"
            ),

            (
                rf"\bopened\s*:?\s*"
                rf"({date_expression})"
            ),
        ]

        for pattern in patterns:

            for match in re.finditer(
                pattern,
                text,
                re.IGNORECASE
                | re.VERBOSE,
            ):

                value = match.group(
                    1
                )

                parsed = self._parse_date(
                    value
                )

                if parsed:

                    candidates.append(
                        {
                            "date": parsed,
                            "score": 50,
                            "source": "visible_text",
                            "key": "visible_text",
                        }
                    )

        return candidates

    # =============================================================
    # POSTING DATE KEY SCORING
    # =============================================================

    def _posting_date_key_score(
        self,
        key,
    ):
        """
        Score how strongly a variable name indicates that the value
        represents the original job posting date.

        Higher = stronger evidence.
        """

        if not key:

            return 0

        normalized = (
            str(key)
            .lower()
            .replace("-", "")
            .replace("_", "")
            .replace(" ", "")
        )

        scores = {

            # -----------------------------------------------------
            # Strongest.
            # -----------------------------------------------------

            "dateposted": 100,

            "postingdate": 95,

            "posteddate": 95,

            "jobposteddate": 95,

            "jobpostingdate": 95,

            # -----------------------------------------------------
            # Strong.
            # -----------------------------------------------------

            "postingdateutc": 90,

            "postedat": 85,

            "postingat": 85,

            "jobpostedat": 85,

            "jobpostingat": 85,

            # -----------------------------------------------------
            # Moderate.
            # -----------------------------------------------------

            "publisheddate": 75,

            "publishdate": 70,

            "publishedat": 65,

            "publishat": 60,

            # -----------------------------------------------------
            # Weak.
            #
            # A created timestamp may indicate when the ATS record
            # was created, which is not necessarily when the job
            # became public.
            # -----------------------------------------------------

            "datecreated": 45,

            "createddate": 40,

            "createdat": 35,

            "jobdate": 30,
        }

        if normalized in scores:

            return scores[
                normalized
            ]

        # ---------------------------------------------------------
        # Generic semantic scoring.
        # ---------------------------------------------------------

        score = 0

        if "posted" in normalized:

            score += 80

        elif "posting" in normalized:

            score += 75

        elif "published" in normalized:

            score += 60

        elif "publish" in normalized:

            score += 55

        elif "created" in normalized:

            score += 25

        if "job" in normalized:

            score += 10

        if "date" in normalized:

            score += 5

        return score

    # =============================================================
    # SELECT BEST POSTING DATE
    # =============================================================

    def _select_best_posting_date(
        self,
        candidates,
    ):
        """
        Select the most credible posting date.

        The algorithm considers:

            - semantic strength of variable name
            - extraction source
            - duplicate agreement
            - independent-source agreement
            - future dates
            - absurdly old dates

        Returns:

            {
                "date": datetime,
                "score": int,
                "source": str,
                "key": str,
            }

        or None.
        """

        if not candidates:

            return None

        now = datetime.now(
            timezone.utc
        )

        valid = []

        for candidate in candidates:

            date = candidate.get(
                "date"
            )

            if not date:

                continue

            if date.tzinfo is None:

                date = date.replace(
                    tzinfo=timezone.utc
                )

                candidate["date"] = date

            # -----------------------------------------------------
            # Don't accept future posting dates.
            #
            # Allow a tiny amount of clock skew.
            # -----------------------------------------------------

            if date > now:

                continue

            # -----------------------------------------------------
            # Don't accept absurdly old dates.
            # -----------------------------------------------------

            if date.year < 1990:

                continue

            valid.append(
                candidate
            )

        if not valid:

            return None

        # ---------------------------------------------------------
        # Group dates by calendar day.
        #
        # If raw HTML says:
        #
        # datePosted = 2026-08-14
        #
        # and visible text says:
        #
        # Posted Aug 14, 2026
        #
        # that's strong evidence.
        # ---------------------------------------------------------

        groups = {}

        for candidate in valid:

            date = candidate[
                "date"
            ]

            key = (
                date.year,
                date.month,
                date.day,
            )

            groups.setdefault(
                key,
                [],
            ).append(
                candidate
            )

        scored_groups = []

        for date_key, group in groups.items():

            strongest_candidate = max(
                group,
                key=lambda item: item.get(
                    "score",
                    0,
                ),
            )

            strongest_score = (
                strongest_candidate.get(
                    "score",
                    0,
                )
            )

            # -----------------------------------------------------
            # Multiple occurrences of the same date increase
            # confidence.
            # -----------------------------------------------------

            agreement_bonus = (
                min(
                    len(group),
                    5,
                )
                * 5
            )

            # -----------------------------------------------------
            # Agreement between different extraction mechanisms is
            # particularly useful.
            # -----------------------------------------------------

            sources = {
                candidate.get(
                    "source"
                )
                for candidate in group
            }

            source_bonus = 0

            if len(sources) >= 2:

                source_bonus += 15

            if len(sources) >= 3:

                source_bonus += 10

            total_score = (
                strongest_score
                + agreement_bonus
                + source_bonus
            )

            scored_groups.append(
                {
                    "total_score": total_score,
                    "date_key": date_key,
                    "group": group,
                    "best_candidate": (
                        strongest_candidate
                    ),
                }
            )

        if not scored_groups:

            return None

        # ---------------------------------------------------------
        # Highest-confidence date wins.
        # ---------------------------------------------------------

        scored_groups.sort(
            key=lambda item: (
                item["total_score"],
                item["date_key"],
            ),
            reverse=True,
        )

        best_group = scored_groups[
            0
        ]

        best_candidate = (
            best_group[
                "best_candidate"
            ]
        )

        print(
            "  Posting date detection:"
        )

        print(
            f"    Date: "
            f"{best_candidate['date']}"
        )

        print(
            f"    Source: "
            f"{best_candidate.get('source', '')}"
        )

        print(
            f"    Key: "
            f"{best_candidate.get('key', '')}"
        )

        print(
            f"    Confidence score: "
            f"{best_group['total_score']}"
        )

        return best_candidate

    # =============================================================
    # DATE FRAGMENT
    # =============================================================

    def _parse_date_fragment(
        self,
        value,
    ):
        """
        Extract a date from a larger timestamp.

        Examples:

            2026-08-15T13:22:31.000Z

            2026-08-15 13:22:31

            2026-08-15T13:22:31+00:00
        """

        if not value:

            return None

        value = str(
            value
        ).strip()

        # ---------------------------------------------------------
        # ISO date.
        # ---------------------------------------------------------

        match = re.search(
            r"\b(\d{4}-\d{2}-\d{2})"
            r"(?:T|\s|$)",
            value,
        )

        if match:

            return self._parse_date(
                match.group(1)
            )

        # ---------------------------------------------------------
        # US date.
        # ---------------------------------------------------------

        match = re.search(
            r"\b(\d{1,2}/\d{1,2}/\d{4})\b",
            value,
        )

        if match:

            return self._parse_date(
                match.group(1)
            )

        # ---------------------------------------------------------
        # Month-name date.
        # ---------------------------------------------------------

        match = re.search(
            r"\b("
            r"(?:Jan(?:uary)?|"
            r"Feb(?:ruary)?|"
            r"Mar(?:ch)?|"
            r"Apr(?:il)?|"
            r"May|"
            r"Jun(?:e)?|"
            r"Jul(?:y)?|"
            r"Aug(?:ust)?|"
            r"Sep(?:t(?:ember)?)?|"
            r"Oct(?:ober)?|"
            r"Nov(?:ember)?|"
            r"Dec(?:ember)?)"
            r"\s+\d{1,2},"
            r"\s+\d{4}"
            r")\b",
            value,
            re.IGNORECASE,
        )

        if match:

            return self._parse_date(
                match.group(1)
            )

        return None

    # =============================================================
    # EMPLOYMENT TYPE
    # =============================================================

    def _extract_html_employment_type(
        self,
        soup,
    ):

        selectors = [

            "[class*='employment']",

            "[class*='job-type']",

            "[class*='employment-type']",

            "[data-testid*='employment']",
        ]

        for selector in selectors:

            element = soup.select_one(
                selector
            )

            if element:

                value = element.get_text(
                    " ",
                    strip=True,
                )

                if value:

                    return value

        return ""

    # =============================================================
    # SALARY
    # =============================================================

    def _extract_salary(
        self,
        data,
    ):

        salary_data = data.get(
            "baseSalary"
        )

        if not salary_data:

            return ""

        if isinstance(
            salary_data,
            dict,
        ):

            value = salary_data.get(
                "value"
            )

            currency = salary_data.get(
                "currency"
            )

            if isinstance(
                value,
                dict,
            ):

                minimum = value.get(
                    "minValue"
                )

                maximum = value.get(
                    "maxValue"
                )

                if (
                    minimum
                    and maximum
                ):

                    return (
                        f"{currency or ''} "
                        f"{minimum} - "
                        f"{maximum}"
                    ).strip()

                if minimum:

                    return (
                        f"{currency or ''} "
                        f"{minimum}"
                    ).strip()

            if value:

                return str(
                    value
                )

        return ""

    def _extract_salary_from_text(
        self,
        text,
    ):

        if not text:

            return ""

        pattern = (
            r"\$[\d,]+"
            r"(?:\s*-\s*\$[\d,]+)?"
            r"(?:\s*(?:per year|annually|/year))?"
        )

        match = re.search(
            pattern,
            text,
            re.IGNORECASE,
        )

        if match:

            return match.group(
                0
            )

        return ""

    # =============================================================
    # JOB ID
    # =============================================================

    def _extract_job_id(
        self,
        url,
    ):

        if not url:

            return ""

        parsed = urlparse(
            url
        )

        path = parsed.path.rstrip(
            "/"
        )

        # ---------------------------------------------------------
        # Numeric ID at end of path.
        # ---------------------------------------------------------

        match = re.search(
            r"/(\d+)$",
            path,
        )

        if match:

            return match.group(
                1
            )

        # ---------------------------------------------------------
        # gh_jid.
        # ---------------------------------------------------------

        match = re.search(
            r"gh_jid=(\d+)",
            url,
            re.IGNORECASE,
        )

        if match:

            return match.group(
                1
            )

        # ---------------------------------------------------------
        # jobid.
        # ---------------------------------------------------------

        match = re.search(
            r"job[_-]?id[=/](\w+)",
            url,
            re.IGNORECASE,
        )

        if match:

            return match.group(
                1
            )

        return ""

    # =============================================================
    # DATE
    # =============================================================

    def _parse_date(
        self,
        value,
    ):
        """
        Parse common job-posting date formats.

        Supports:

            YYYY-MM-DD

            YYYY-MM-DDTHH:MM:SS

            YYYY-MM-DDTHH:MM:SSZ

            YYYY-MM-DDTHH:MM:SS.000Z

            YYYY-MM-DDTHH:MM:SS+00:00

            Unix seconds

            Unix milliseconds

            Month-name dates

            US dates
        """

        if not value:

            return None

        if isinstance(
            value,
            datetime,
        ):

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

        # ---------------------------------------------------------
        # Unix timestamp - seconds.
        # ---------------------------------------------------------

        if re.fullmatch(
            r"\d{10}(?:\.\d+)?",
            value,
        ):

            try:

                return datetime.fromtimestamp(
                    float(value),
                    tz=timezone.utc,
                )

            except (
                ValueError,
                OverflowError,
                OSError,
            ):

                pass

        # ---------------------------------------------------------
        # Unix timestamp - milliseconds.
        # ---------------------------------------------------------

        if re.fullmatch(
            r"\d{13}",
            value,
        ):

            try:

                return datetime.fromtimestamp(
                    int(value) / 1000,
                    tz=timezone.utc,
                )

            except (
                ValueError,
                OverflowError,
                OSError,
            ):

                pass

        # ---------------------------------------------------------
        # ISO 8601.
        # ---------------------------------------------------------

        iso_value = value

        if iso_value.endswith(
            "Z"
        ):

            iso_value = (
                iso_value[:-1]
                + "+00:00"
            )

        try:

            parsed = datetime.fromisoformat(
                iso_value
            )

            if parsed.tzinfo is None:

                parsed = parsed.replace(
                    tzinfo=timezone.utc
                )

            return parsed

        except ValueError:

            pass

        # ---------------------------------------------------------
        # Common formats.
        # ---------------------------------------------------------

        formats = [

            "%Y-%m-%d",

            "%Y/%m/%d",

            "%m/%d/%Y",

            "%m-%d-%Y",

            "%d/%m/%Y",

            "%d-%m-%Y",

            "%B %d, %Y",

            "%b %d, %Y",

            "%B %d %Y",

            "%b %d %Y",

            "%Y-%m-%d %H:%M:%S",

            "%Y/%m/%d %H:%M:%S",
        ]

        for fmt in formats:

            try:

                return datetime.strptime(
                    value,
                    fmt,
                ).replace(
                    tzinfo=timezone.utc
                )

            except ValueError:

                continue

        return None

    # =============================================================
    # NON-JOB PAGE DETECTION
    # =============================================================

    def _looks_like_non_job_page(
        self,
        title,
        url,
    ):

        combined = (
            f"{title} {url}"
        ).lower()

        indicators = [

            "career benefits",

            "benefits",

            "emerging talent",

            "campus",

            "internships",

            "university",

            "about careers",

            "careers home",

            "open roles",

            "view open roles",

            "search jobs",

            "job search",

            "careers",
        ]

        title_lower = title.lower()

        for indicator in indicators:

            if indicator in title_lower:

                return True

        return False

    # =============================================================
    # DOMAIN
    # =============================================================

    def _same_domain(
        self,
        url1,
        url2,
    ):

        domain1 = urlparse(
            url1
        ).netloc.lower()

        domain2 = urlparse(
            url2
        ).netloc.lower()

        return (
            domain1
            == domain2
        )

    # =============================================================
    # ATS DOMAIN
    # =============================================================

    def _looks_like_ats_url(
        self,
        url,
    ):

        domain = urlparse(
            url
        ).netloc.lower()

        ats_domains = [

            "greenhouse.io",

            "lever.co",

            "ashbyhq.com",

            "myworkdayjobs.com",

            "icims.com",

            "smartrecruiters.com",

            "jobvite.com",

            "breezy.hr",
        ]

        return any(
            ats in domain
            for ats in ats_domains
        )

    # =============================================================
    # NORMALIZE URL
    # =============================================================

    def _normalize_url(
        self,
        url,
    ):

        if not url:

            return ""

        url = url.strip()

        parsed = urlparse(
            url
        )

        parsed = parsed._replace(
            fragment=""
        )

        return parsed.geturl()

    # =============================================================
    # STRING
    # =============================================================

    def _get_string(
        self,
        value,
    ):

        if value is None:

            return ""

        return str(
            value
        ).strip()

    # =============================================================
    # CLEAN HTML
    # =============================================================

    def _clean_html(
        self,
        value,
    ):

        if not value:

            return ""

        soup = BeautifulSoup(
            value,
            "html.parser",
        )

        return soup.get_text(
            "\n",
            strip=True,
        )

    # =============================================================
    # DEDUPLICATE
    # =============================================================

    def _deduplicate_jobs(
        self,
        jobs,
    ):
        """
        Remove duplicate Job objects.

        Primary key:
            posting_url

        Secondary key:
            company + title

        If the same job was discovered multiple times and one copy
        has a posting date while another does not, prefer the copy
        containing the date.
        """

        unique = {}

        for job in jobs:

            if not job:

                continue

            posting_url = (
                getattr(
                    job,
                    "posting_url",
                    "",
                )
                or ""
            )

            title = (
                getattr(
                    job,
                    "title",
                    "",
                )
                or ""
            )

            company = (
                getattr(
                    job,
                    "company",
                    "",
                )
                or ""
            )

            if posting_url:

                key = (
                    posting_url
                    .strip()
                    .lower()
                )

            else:

                key = (
                    f"{company}|"
                    f"{title}"
                ).lower()

            if key not in unique:

                unique[key] = job

                continue

            # -----------------------------------------------------
            # Prefer the duplicate with a posting date.
            # -----------------------------------------------------

            existing = unique[key]

            existing_date = getattr(
                existing,
                "posting_date",
                None,
            )

            new_date = getattr(
                job,
                "posting_date",
                None,
            )

            if (
                not existing_date
                and new_date
            ):

                unique[key] = job

        return list(
            unique.values()
        )

    # =============================================================
    # PRINT JOB
    # =============================================================

    def _print_job(
        self,
        job,
    ):

        print()

        print(
            "The job returned "
            "from scraper:"
        )

        print(
            f"  Company: "
            f"{getattr(job, 'company', '')}"
        )

        print(
            f"  Title: "
            f"{getattr(job, 'title', '')}"
        )

        print(
            f"  Location: "
            f"{getattr(job, 'location', '')}"
        )

        print(
            f"  Posted: "
            f"{getattr(job, 'posting_date', '')}"
        )

        print(
            f"  URL: "
            f"{getattr(job, 'posting_url', '')}"
        )

        print(
            f"  Apply URL: "
            f"{getattr(job, 'apply_url', '')}"
        )

        print(
            f"  Employment Type: "
            f"{getattr(job, 'employment_type', '')}"
        )

        print(
            f"  Job ID: "
            f"{getattr(job, 'job_id', '')}"
        )

        print(
            f"  Source: "
            f"{getattr(job, 'source', '')}"
        )

        description = (
            getattr(
                job,
                "description",
                "",
            )
            or ""
        )

        print(
            f"  Description: "
            f"{description[:500]}"
        )




# import json
# import re
# import time
# from collections import deque
# from datetime import datetime, timezone
# from urllib.parse import urljoin, urlparse

# import requests
# from bs4 import BeautifulSoup

# # Adjust this import to wherever your Job class actually lives.
# from app.models.job import Job


# class GenericCareerScraper:
#     """
#     Generic career-site scraper.

#     Purpose:
#         Discover actual job postings from company career pages and
#         normalize them into the application's common Job object.

#     The scraper is intentionally generic. It does not assume that
#     every company uses Workday, Greenhouse, Lever, etc.

#     Process:

#         1. Fetch career page.
#         2. Discover job-search/listing pages.
#         3. Discover individual job URLs.
#         4. Fetch individual job pages.
#         5. Extract job information.
#         6. Normalize into Job objects.
#         7. Return list[Job].

#     This allows the downstream validation/filtering process to use
#     the exact same Job object regardless of scraper source.
#     """

#     # -------------------------------------------------------------
#     # Configuration
#     # -------------------------------------------------------------

#     MAX_DISCOVERY_PAGES = 10

#     MAX_JOB_PAGES = 250

#     MAX_CONSECUTIVE_429 = 3

#     # Delay between normal requests.
#     REQUEST_DELAY_SECONDS = 1.5

#     # Additional delay after a 429.
#     RETRY_DELAY_SECONDS = 10

#     # Don't immediately hammer a site.
#     REQUEST_TIMEOUT = 30

#     # -------------------------------------------------------------
#     # Constructor
#     # -------------------------------------------------------------

#     def __init__(
#         self,
#         timeout=REQUEST_TIMEOUT,
#         request_delay=REQUEST_DELAY_SECONDS,
#     ):

#         self.timeout = timeout

#         self.request_delay = request_delay

#         self.session = requests.Session()

#         self.session.headers.update(
#             {
#                 "User-Agent": (
#                     "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
#                     "AppleWebKit/537.36 "
#                     "(KHTML, like Gecko) "
#                     "Chrome/140.0.0.0 Safari/537.36"
#                 ),
#                 "Accept": (
#                     "text/html,application/xhtml+xml,"
#                     "application/xml;q=0.9,image/avif,"
#                     "image/webp,*/*;q=0.8"
#                 ),
#                 "Accept-Language": (
#                     "en-US,en;q=0.9"
#                 ),
#                 "Connection": "keep-alive",
#             }
#         )

#     # =============================================================
#     # PUBLIC SCRAPE METHOD
#     # =============================================================

#     def scrape(
#         self,
#         company,
#         url,
#     ):
#         """
#         Scrape a company career site.

#         Returns:
#             list[Job]

#         Every returned record is a Job object so that the existing
#         validation/filtering pipeline can process it.
#         """

#         print()
#         print("=" * 80)
#         print(f"SCRAPING: {company}")
#         print(f"CAREER URL: {url}")
#         print("=" * 80)

#         jobs = []

#         discovered_job_urls = set()

#         discovered_pages = set()

#         discovery_queue = deque()

#         # ---------------------------------------------------------
#         # Start with supplied career page.
#         # ---------------------------------------------------------

#         normalized_url = self._normalize_url(url)

#         discovery_queue.append(normalized_url)

#         consecutive_429 = 0

#         # =========================================================
#         # DISCOVERY PHASE
#         # =========================================================

#         while (
#             discovery_queue
#             and len(discovered_pages)
#             < self.MAX_DISCOVERY_PAGES
#         ):

#             page_url = discovery_queue.popleft()

#             if page_url in discovered_pages:
#                 continue

#             discovered_pages.add(page_url)

#             print()
#             print(
#                 f"Checking discovery page "
#                 f"{len(discovered_pages)}/"
#                 f"{self.MAX_DISCOVERY_PAGES}:"
#             )

#             print(f"  {page_url}")

#             try:

#                 response = self._fetch_page(
#                     page_url
#                 )

#             except requests.HTTPError as exc:

#                 status = (
#                     exc.response.status_code
#                     if exc.response is not None
#                     else None
#                 )

#                 if status == 429:

#                     consecutive_429 += 1

#                     print(
#                         "  HTTP 429 - "
#                         "Too many requests."
#                     )

#                     if (
#                         consecutive_429
#                         >= self.MAX_CONSECUTIVE_429
#                     ):

#                         print(
#                             "  Too many consecutive "
#                             "429 responses."
#                         )

#                         print(
#                             f"  Stopping discovery "
#                             f"for {company}."
#                         )

#                         break

#                 else:

#                     print(
#                         f"  HTTP error: {exc}"
#                     )

#                 continue

#             except requests.RequestException as exc:

#                 print(
#                     f"  Request error: {exc}"
#                 )

#                 continue

#             consecutive_429 = 0

#             soup = BeautifulSoup(
#                 response.text,
#                 "html.parser",
#             )

#             # -----------------------------------------------------
#             # First: look for structured JobPosting records.
#             # -----------------------------------------------------

#             structured_jobs = (
#                 self._extract_json_ld_jobs(
#                     soup,
#                     company,
#                     page_url,
#                 )
#             )

#             if structured_jobs:

#                 print(
#                     f"  Found "
#                     f"{len(structured_jobs)} "
#                     f"structured JobPosting "
#                     f"records."
#                 )

#                 jobs.extend(
#                     structured_jobs
#                 )

#             # -----------------------------------------------------
#             # Discover links.
#             # -----------------------------------------------------

#             links = self._discover_links(
#                 soup,
#                 page_url,
#             )

#             job_count = 0
#             search_count = 0

#             for link in links:

#                 link_type = link["type"]

#                 link_url = link["url"]

#                 # -------------------------------------------------
#                 # Individual job.
#                 # -------------------------------------------------

#                 if link_type == "job":

#                     if link_url not in discovered_job_urls:

#                         discovered_job_urls.add(
#                             link_url
#                         )

#                         job_count += 1

#                 # -------------------------------------------------
#                 # Search/listing page.
#                 # -------------------------------------------------

#                 elif link_type == "job_search":

#                     if (
#                         link_url
#                         not in discovered_pages
#                         and link_url
#                         not in discovery_queue
#                     ):

#                         discovery_queue.append(
#                             link_url
#                         )

#                         search_count += 1

#             print(
#                 f"  New job links discovered: "
#                 f"{job_count}"
#             )

#             print(
#                 f"  New search/listing pages: "
#                 f"{search_count}"
#             )

#         # =========================================================
#         # DISCOVERY SUMMARY
#         # =========================================================

#         print()
#         print("-" * 80)

#         print(
#             f"Discovery complete for "
#             f"{company}"
#         )

#         print(
#             f"Pages examined: "
#             f"{len(discovered_pages)}"
#         )

#         print(
#             f"Individual job URLs discovered: "
#             f"{len(discovered_job_urls)}"
#         )

#         print(
#             f"Structured jobs discovered: "
#             f"{len(jobs)}"
#         )

#         print("-" * 80)

#         # =========================================================
#         # FETCH INDIVIDUAL JOB PAGES
#         # =========================================================

#         job_urls_to_fetch = list(
#             discovered_job_urls
#         )

#         if len(job_urls_to_fetch) > self.MAX_JOB_PAGES:

#             print(
#                 f"WARNING: "
#                 f"{len(job_urls_to_fetch)} "
#                 f"job URLs discovered."
#             )

#             print(
#                 f"Only the first "
#                 f"{self.MAX_JOB_PAGES} "
#                 f"will be fetched."
#             )

#             job_urls_to_fetch = (
#                 job_urls_to_fetch[
#                     : self.MAX_JOB_PAGES
#                 ]
#             )

#         print()
#         print(
#             f"Fetching "
#             f"{len(job_urls_to_fetch)} "
#             f"individual job pages."
#         )

#         consecutive_429 = 0

#         # =========================================================
#         # INDIVIDUAL JOB REQUESTS
#         # =========================================================

#         for index, job_url in enumerate(
#             job_urls_to_fetch,
#             start=1,
#         ):

#             print()
#             print(
#                 f"[{index}/"
#                 f"{len(job_urls_to_fetch)}] "
#                 f"{job_url}"
#             )

#             try:

#                 response = self._fetch_page(
#                     job_url
#                 )

#             except requests.HTTPError as exc:

#                 status = (
#                     exc.response.status_code
#                     if exc.response is not None
#                     else None
#                 )

#                 if status == 429:

#                     consecutive_429 += 1

#                     print(
#                         "  HTTP 429."
#                     )

#                     print(
#                         f"  Sleeping "
#                         f"{self.RETRY_DELAY_SECONDS} "
#                         f"seconds."
#                     )

#                     time.sleep(
#                         self.RETRY_DELAY_SECONDS
#                     )

#                     if (
#                         consecutive_429
#                         >= self.MAX_CONSECUTIVE_429
#                     ):

#                         print(
#                             "  Too many "
#                             "consecutive 429s."
#                         )

#                         print(
#                             "  Stopping job "
#                             "requests."
#                         )

#                         break

#                 else:

#                     print(
#                         f"  HTTP error: "
#                         f"{exc}"
#                     )

#                 continue

#             except requests.RequestException as exc:

#                 print(
#                     f"  Request error: "
#                     f"{exc}"
#                 )

#                 continue

#             consecutive_429 = 0

#             soup = BeautifulSoup(
#                 response.text,
#                 "html.parser",
#             )

#             # -----------------------------------------------------
#             # Try structured JobPosting first.
#             # -----------------------------------------------------

#             detail_jobs = (
#                 self._extract_json_ld_jobs(
#                     soup,
#                     company,
#                     job_url,
#                 )
#             )

#             if detail_jobs:

#                 for job in detail_jobs:
#                     print(f"Job detail:     {job}\n")
#                     jobs.append(job)

#                     print(
#                         f"  Job found: "
#                         f"{job.title}"
#                     )
#                     # print(f"{job.}")

#             else:

#                 # -------------------------------------------------
#                 # Fall back to generic HTML extraction.
#                 # -------------------------------------------------

#                 job = (
#                     self._extract_job_from_html(
#                         soup,
#                         company,
#                         job_url,
#                     )
#                 )

#                 if job:

#                     jobs.append(job)

#                     print(
#                         f"  Job found: "
#                         f"{job.title}"
#                     )

#                 else:

#                     print(
#                         "  Could not extract "
#                         "job details."
#                     )

#         # =========================================================
#         # DEDUPLICATE
#         # =========================================================

#         jobs = self._deduplicate_jobs(
#             jobs
#         )

#         # =========================================================
#         # FINAL RESULT
#         # =========================================================

#         print()
#         print("=" * 80)

#         print(
#             f"FINAL RESULT: "
#             f"{company} -> "
#             f"{len(jobs)} jobs discovered"
#         )

#         print("=" * 80)

#         # ---------------------------------------------------------
#         # Print normalized Job objects.
#         # ---------------------------------------------------------

#         for job in jobs:

#             self._print_job(
#                 job
#             )

#         return jobs

#     # =============================================================
#     # HTTP
#     # =============================================================

#     def _fetch_page(
#         self,
#         url,
#     ):
#         """
#         Fetch a page.

#         HTTP 200 means the request succeeded.

#         A delay is applied before each request so that the scraper
#         does not hammer a career site.
#         """

#         time.sleep(
#             self.request_delay
#         )

#         response = self.session.get(
#             url,
#             timeout=self.timeout,
#             allow_redirects=True,
#         )

#         print(
#             f"  HTTP {response.status_code}: "
#             f"{response.url}"
#         )

#         response.raise_for_status()

#         return response

#     # =============================================================
#     # LINK DISCOVERY
#     # =============================================================

#     def _discover_links(
#         self,
#         soup,
#         base_url,
#     ):
#         """
#         Discover likely job and job-search links.

#         Important:

#         A career page often contains links such as:

#             View open roles
#             Emerging talent
#             Benefits
#             Teams
#             Locations

#         Those are NOT necessarily jobs.

#         We therefore classify links separately as:

#             job
#             job_search
#         """

#         results = []

#         seen = set()

#         for link in soup.find_all(
#             "a",
#             href=True,
#         ):

#             href = link.get(
#                 "href"
#             )

#             text = link.get_text(
#                 " ",
#                 strip=True,
#             )

#             if not href:
#                 continue

#             if not text:
#                 continue

#             absolute_url = urljoin(
#                 base_url,
#                 href,
#             )

#             absolute_url = (
#                 self._normalize_url(
#                     absolute_url
#                 )
#             )

#             if absolute_url in seen:
#                 continue

#             seen.add(
#                 absolute_url
#             )

#             if not self._same_domain(
#                 base_url,
#                 absolute_url,
#             ):

#                 # External ATS domains can be valid.
#                 if not self._looks_like_ats_url(
#                     absolute_url
#                 ):
#                     continue

#             link_type = (
#                 self._classify_link(
#                     text,
#                     absolute_url,
#                 )
#             )

#             if link_type:

#                 results.append(
#                     {
#                         "type": link_type,
#                         "url": absolute_url,
#                         "text": text,
#                     }
#                 )

#         return results

#     # =============================================================
#     # LINK CLASSIFICATION
#     # =============================================================

#     def _classify_link(
#         self,
#         text,
#         url,
#     ):
#         """
#         Determine whether a link is:

#             job
#             job_search
#             None
#         """

#         text_lower = text.lower()

#         url_lower = url.lower()

#         # ---------------------------------------------------------
#         # Strong individual-job URL patterns.
#         # ---------------------------------------------------------

#         job_patterns = [

#             r"/jobs?/\d+",
#             r"/jobs?/[a-z0-9\-]+/[a-z0-9\-]+",

#             r"/position/\d+",
#             r"/positions/\d+",

#             r"/job/[a-z0-9\-]+",

#             r"/job-\d+",

#             r"/jobs-\d+",

#             r"gh_jid=",

#             r"jobid=",

#             r"job_id=",

#             r"lever\.co/.+",

#             r"greenhouse\.io/.+/jobs/\d+",

#             r"ashbyhq\.com/.*/job/",

#             r"myworkdayjobs\.com/.*/job/",
#         ]

#         for pattern in job_patterns:

#             if re.search(
#                 pattern,
#                 url_lower,
#             ):

#                 return "job"

#         # ---------------------------------------------------------
#         # Search/listing pages.
#         # ---------------------------------------------------------

#         search_patterns = [

#             "/careers/search",

#             "/careers/jobs",

#             "/careers/positions",

#             "/jobs",

#             "/jobs/search",

#             "/jobs/search-results",

#             "/job-search",

#             "/search/jobs",

#             "/open-roles",

#             "/open-positions",

#             "/careers/open-roles",

#             "/careers/openings",

#             "/careers/opportunities",

#             "/careers#job",

#             "?q=",

#             "?query=",

#             "?search=",

#         ]

#         for pattern in search_patterns:

#             if pattern in url_lower:

#                 return "job_search"

#         # ---------------------------------------------------------
#         # Text indicating a job-search page.
#         # ---------------------------------------------------------

#         search_text = (

#             " ".join(
#                 [
#                     text_lower,
#                     url_lower,
#                 ]
#             )
#         )

#         search_indicators = [

#             "view open jobs",
#             "view open roles",
#             "view all jobs",
#             "view all roles",
#             "see open positions",
#             "see open jobs",
#             "search jobs",
#             "search open roles",
#             "search opportunities",
#             "open roles",
#             "open positions",
#             "job search",
#             "career opportunities",
#             "view opportunities",
#         ]

#         if any(
#             indicator in search_text
#             for indicator
#             in search_indicators
#         ):

#             return "job_search"

#         return None

#     # =============================================================
#     # JSON-LD
#     # =============================================================

#     def _extract_json_ld_jobs(
#         self,
#         soup,
#         company,
#         base_url,
#     ):
#         """
#         Extract Schema.org JobPosting objects.
#         """

#         jobs = []

#         scripts = soup.find_all(
#             "script",
#             type="application/ld+json",
#         )

#         for script in scripts:

#             try:

#                 raw = (
#                     script.string
#                     or script.get_text()
#                 )

#                 data = json.loads(
#                     raw
#                 )

#             except (
#                 json.JSONDecodeError,
#                 TypeError,
#             ):

#                 continue

#             records = (
#                 self._flatten_json_ld(
#                     data
#                 )
#             )

#             for record in records:

#                 if not isinstance(
#                     record,
#                     dict,
#                 ):
#                     continue

#                 record_type = (
#                     record.get(
#                         "@type"
#                     )
#                 )

#                 if isinstance(
#                     record_type,
#                     list,
#                 ):

#                     is_job = (
#                         "JobPosting"
#                         in record_type
#                     )

#                 else:

#                     is_job = (
#                         record_type
#                         == "JobPosting"
#                     )

#                 if not is_job:
#                     continue

#                 job = (
#                     self._build_job_from_json_ld(
#                         record,
#                         company,
#                         base_url,
#                     )
#                 )

#                 if job:
#                     jobs.append(
#                         job
#                     )

#         return jobs

#     # =============================================================
#     # JSON-LD FLATTEN
#     # =============================================================

#     def _flatten_json_ld(
#         self,
#         data,
#     ):

#         if isinstance(
#             data,
#             list,
#         ):

#             records = []

#             for item in data:

#                 records.extend(
#                     self._flatten_json_ld(
#                         item
#                     )
#                 )

#             return records

#         if isinstance(
#             data,
#             dict,
#         ):

#             if "@graph" in data:

#                 return self._flatten_json_ld(
#                     data["@graph"]
#                 )

#             return [data]

#         return []

#     # =============================================================
#     # BUILD JOB FROM JSON-LD
#     # =============================================================

#     def _build_job_from_json_ld(
#         self,
#         data,
#         company,
#         base_url,
#     ):
#         """
#         Convert Schema.org JobPosting into our Job object.
#         """

#         title = self._get_string(
#             data.get(
#                 "title"
#             )
#         )

#         if not title:
#             return None

#         posting_url = (
#             self._get_string(
#                 data.get(
#                     "url"
#                 )
#             )
#             or base_url
#         )

#         posting_url = urljoin(
#             base_url,
#             posting_url,
#         )

#         location = (
#             self._extract_location(
#                 data.get(
#                     "jobLocation"
#                 )
#             )
#         )

#         description = (
#             self._clean_html(
#                 self._get_string(
#                     data.get(
#                         "description"
#                     )
#                 )
#             )
#         )

#         posting_date = (
#             self._parse_date(
#                 data.get(
#                     "datePosted"
#                 )
#             )
#         )

#         employment_type = (
#             self._get_string(
#                 data.get(
#                     "employmentType"
#                 )
#             )
#         )

#         salary = (
#             self._extract_salary(
#                 data
#             )
#         )

#         job_id = (
#             self._extract_job_id(
#                 posting_url
#             )
#         )

#         return Job(
#             company=company,
#             title=title,
#             location=location,
#             posting_url=posting_url,
#             description=description,
#             posting_date=posting_date,
#             salary=salary,
#             source="Generic",
#             apply_url=posting_url,
#             employment_type=employment_type,
#             job_id=job_id,
#         )

#     # =============================================================
#     # HTML JOB EXTRACTION
#     # =============================================================

#     def _extract_job_from_html(
#         self,
#         soup,
#         company,
#         job_url,
#     ):
#         """
#         Extract a job from a job-detail page when JSON-LD is
#         unavailable.

#         This deliberately examines the individual job page rather
#         than trying to guess job information from the career
#         landing page.
#         """

#         title = ""

#         # ---------------------------------------------------------
#         # <h1>
#         # ---------------------------------------------------------

#         h1 = soup.find(
#             "h1"
#         )

#         if h1:

#             title = h1.get_text(
#                 " ",
#                 strip=True,
#             )

#         # ---------------------------------------------------------
#         # OpenGraph title fallback.
#         # ---------------------------------------------------------

#         if not title:

#             meta_title = soup.find(
#                 "meta",
#                 property="og:title",
#             )

#             if meta_title:

#                 title = self._get_string(
#                     meta_title.get(
#                         "content"
#                     )
#                 )

#         # ---------------------------------------------------------
#         # HTML <title> fallback.
#         # ---------------------------------------------------------

#         if not title and soup.title:

#             title = soup.title.get_text(
#                 " ",
#                 strip=True,
#             )

#         if not title:
#             return None

#         # ---------------------------------------------------------
#         # Remove obvious non-job pages.
#         # ---------------------------------------------------------

#         if self._looks_like_non_job_page(
#             title,
#             job_url,
#         ):

#             return None

#         # ---------------------------------------------------------
#         # Description.
#         # ---------------------------------------------------------

#         description = (
#             self._extract_description(
#                 soup
#             )
#         )

#         # ---------------------------------------------------------
#         # Location.
#         # ---------------------------------------------------------

#         location = (
#             self._extract_html_location(
#                 soup
#             )
#         )

#         # ---------------------------------------------------------
#         # Posting date.
#         # ---------------------------------------------------------

#         posting_date = (
#             self._extract_html_posting_date(
#                 soup
#             )
#         )

#         # ---------------------------------------------------------
#         # Employment type.
#         # ---------------------------------------------------------

#         employment_type = (
#             self._extract_html_employment_type(
#                 soup
#             )
#         )

#         # ---------------------------------------------------------
#         # Salary.
#         # ---------------------------------------------------------

#         salary = (
#             self._extract_salary_from_text(
#                 description
#             )
#         )

#         # ---------------------------------------------------------
#         # Job ID.
#         # ---------------------------------------------------------

#         job_id = (
#             self._extract_job_id(
#                 job_url
#             )
#         )

#         return Job(
#             company=company,
#             title=title,
#             location=location,
#             posting_url=job_url,
#             description=description,
#             posting_date=posting_date,
#             salary=salary,
#             source="Generic",
#             apply_url=job_url,
#             employment_type=employment_type,
#             job_id=job_id,
#         )

#     # =============================================================
#     # DESCRIPTION
#     # =============================================================

#     def _extract_description(
#         self,
#         soup,
#     ):

#         # Try common description containers.

#         selectors = [

#             "[class*='description']",

#             "[class*='job-description']",

#             "[id*='description']",

#             "[class*='posting']",

#             "[class*='content']",

#             "main",

#         ]

#         for selector in selectors:

#             element = soup.select_one(
#                 selector
#             )

#             if not element:
#                 continue

#             text = element.get_text(
#                 "\n",
#                 strip=True,
#             )

#             if len(text) >= 200:

#                 return text

#         # Last resort.

#         if soup.body:

#             return soup.body.get_text(
#                 "\n",
#                 strip=True,
#             )

#         return ""

#     # =============================================================
#     # LOCATION
#     # =============================================================

#     def _extract_location(
#         self,
#         location_data,
#     ):

#         if not location_data:
#             return ""

#         if isinstance(
#             location_data,
#             list,
#         ):

#             locations = []

#             for item in location_data:

#                 value = (
#                     self._extract_location(
#                         item
#                     )
#                 )

#                 if value:

#                     locations.append(
#                         value
#                     )

#             return ", ".join(
#                 locations
#             )

#         if isinstance(
#             location_data,
#             dict,
#         ):

#             address = (
#                 location_data.get(
#                     "address",
#                     {},
#                 )
#             )

#             if isinstance(
#                 address,
#                 dict,
#             ):

#                 parts = [

#                     address.get(
#                         "addressLocality"
#                     ),

#                     address.get(
#                         "addressRegion"
#                     ),

#                     address.get(
#                         "postalCode"
#                     ),

#                     address.get(
#                         "addressCountry"
#                     ),
#                 ]

#                 return ", ".join(
#                     str(part)
#                     for part in parts
#                     if part
#                 )

#         return ""

#     # =============================================================
#     # HTML LOCATION
#     # =============================================================

#     def _extract_html_location(
#         self,
#         soup,
#     ):

#         selectors = [

#             "[class*='location']",

#             "[id*='location']",

#             "[class*='office']",

#             "[class*='job-location']",

#             "[data-testid*='location']",

#         ]

#         for selector in selectors:

#             elements = soup.select(
#                 selector
#             )

#             for element in elements:

#                 text = element.get_text(
#                     " ",
#                     strip=True,
#                 )

#                 if (
#                     text
#                     and len(text) < 300
#                 ):

#                     return text

#         return ""

#     # =============================================================
#     # POSTING DATE
#     # =============================================================

#     def _extract_html_posting_date(
#         self,
#         soup,
#     ):

#         # ---------------------------------------------------------
#         # <time datetime="">
#         # ---------------------------------------------------------

#         time_element = soup.find(
#             "time"
#         )

#         if time_element:

#             value = (
#                 time_element.get(
#                     "datetime"
#                 )
#             )

#             if value:

#                 parsed = (
#                     self._parse_date(
#                         value
#                     )
#                 )

#                 if parsed:
#                     return parsed

#             text = time_element.get_text(
#                 " ",
#                 strip=True,
#             )

#             parsed = (
#                 self._parse_date(
#                     text
#                 )
#             )

#             if parsed:
#                 return parsed

#         # ---------------------------------------------------------
#         # Search visible text.
#         # ---------------------------------------------------------

#         text = soup.get_text(
#             " ",
#             strip=True,
#         )

#         patterns = [

#             r"posted\s+(\w+\s+\d{1,2},\s+\d{4})",

#             r"posted\s+on\s+(\w+\s+\d{1,2},\s+\d{4})",

#             r"date\s+posted\s*:?\s*(\w+\s+\d{1,2},\s+\d{4})",

#         ]

#         for pattern in patterns:

#             match = re.search(
#                 pattern,
#                 text,
#                 re.IGNORECASE,
#             )

#             if match:

#                 parsed = (
#                     self._parse_date(
#                         match.group(1)
#                     )
#                 )

#                 if parsed:
#                     return parsed

#         return None

#     # =============================================================
#     # EMPLOYMENT TYPE
#     # =============================================================

#     def _extract_html_employment_type(
#         self,
#         soup,
#     ):

#         selectors = [

#             "[class*='employment']",

#             "[class*='job-type']",

#             "[class*='employment-type']",

#             "[data-testid*='employment']",

#         ]

#         for selector in selectors:

#             element = soup.select_one(
#                 selector
#             )

#             if element:

#                 value = element.get_text(
#                     " ",
#                     strip=True,
#                 )

#                 if value:

#                     return value

#         return ""

#     # =============================================================
#     # SALARY
#     # =============================================================

#     def _extract_salary(
#         self,
#         data,
#     ):

#         salary_data = data.get(
#             "baseSalary"
#         )

#         if not salary_data:
#             return ""

#         if isinstance(
#             salary_data,
#             dict,
#         ):

#             value = salary_data.get(
#                 "value"
#             )

#             currency = salary_data.get(
#                 "currency"
#             )

#             if isinstance(
#                 value,
#                 dict,
#             ):

#                 minimum = value.get(
#                     "minValue"
#                 )

#                 maximum = value.get(
#                     "maxValue"
#                 )

#                 if (
#                     minimum
#                     and maximum
#                 ):

#                     return (
#                         f"{currency or ''} "
#                         f"{minimum} - "
#                         f"{maximum}"
#                     ).strip()

#                 if minimum:

#                     return (
#                         f"{currency or ''} "
#                         f"{minimum}"
#                     ).strip()

#             if value:

#                 return str(
#                     value
#                 )

#         return ""

#     def _extract_salary_from_text(
#         self,
#         text,
#     ):

#         if not text:
#             return ""

#         pattern = (
#             r"\$[\d,]+"
#             r"(?:\s*-\s*\$[\d,]+)?"
#             r"(?:\s*(?:per year|annually|/year))?"
#         )

#         match = re.search(
#             pattern,
#             text,
#             re.IGNORECASE,
#         )

#         if match:

#             return match.group(
#                 0
#             )

#         return ""

#     # =============================================================
#     # JOB ID
#     # =============================================================

#     def _extract_job_id(
#         self,
#         url,
#     ):

#         if not url:
#             return ""

#         parsed = urlparse(
#             url
#         )

#         path = parsed.path.rstrip(
#             "/"
#         )

#         # Numeric ID at end of path.

#         match = re.search(
#             r"/(\d+)$",
#             path,
#         )

#         if match:

#             return match.group(
#                 1
#             )

#         # gh_jid

#         match = re.search(
#             r"gh_jid=(\d+)",
#             url,
#             re.IGNORECASE,
#         )

#         if match:

#             return match.group(
#                 1
#             )

#         # jobid

#         match = re.search(
#             r"job[_-]?id[=/](\w+)",
#             url,
#             re.IGNORECASE,
#         )

#         if match:

#             return match.group(
#                 1
#             )

#         return ""

#     # =============================================================
#     # DATE
#     # =============================================================

#     def _parse_date(
#         self,
#         value,
#     ):

#         if not value:
#             return None

#         if isinstance(
#             value,
#             datetime,
#         ):

#             return value

#         value = str(
#             value
#         ).strip()

#         formats = [

#             "%Y-%m-%d",

#             "%Y-%m-%dT%H:%M:%S",

#             "%Y-%m-%dT%H:%M:%SZ",

#             "%B %d, %Y",

#             "%b %d, %Y",

#             "%m/%d/%Y",

#         ]

#         for fmt in formats:

#             try:

#                 return datetime.strptime(
#                     value,
#                     fmt,
#                 ).replace(
#                     tzinfo=timezone.utc
#                 )

#             except ValueError:

#                 continue

#         return None

#     # =============================================================
#     # NON-JOB PAGE DETECTION
#     # =============================================================

#     def _looks_like_non_job_page(
#         self,
#         title,
#         url,
#     ):

#         combined = (
#             f"{title} {url}"
#         ).lower()

#         indicators = [

#             "career benefits",

#             "benefits",

#             "emerging talent",

#             "campus",

#             "internships",

#             "university",

#             "about careers",

#             "careers home",

#             "open roles",

#             "view open roles",

#             "search jobs",

#             "job search",

#             "careers",

#         ]

#         # Don't reject a page simply because
#         # the URL contains /careers/.
#         #
#         # A real job can legitimately be under
#         # /careers/jobs/....

#         title_lower = title.lower()

#         for indicator in indicators:

#             if indicator in title_lower:

#                 return True

#         return False

#     # =============================================================
#     # DOMAIN
#     # =============================================================

#     def _same_domain(
#         self,
#         url1,
#         url2,
#     ):

#         domain1 = urlparse(
#             url1
#         ).netloc.lower()

#         domain2 = urlparse(
#             url2
#         ).netloc.lower()

#         return (
#             domain1
#             == domain2
#         )

#     # =============================================================
#     # ATS DOMAIN
#     # =============================================================

#     def _looks_like_ats_url(
#         self,
#         url,
#     ):

#         domain = urlparse(
#             url
#         ).netloc.lower()

#         ats_domains = [

#             "greenhouse.io",

#             "lever.co",

#             "ashbyhq.com",

#             "myworkdayjobs.com",

#             "icims.com",

#             "smartrecruiters.com",

#             "jobvite.com",

#             "breezy.hr",

#         ]

#         return any(
#             ats in domain
#             for ats in ats_domains
#         )

#     # =============================================================
#     # NORMALIZE URL
#     # =============================================================

#     def _normalize_url(
#         self,
#         url,
#     ):

#         if not url:
#             return ""

#         url = url.strip()

#         parsed = urlparse(
#             url
#         )

#         # Remove fragment.

#         parsed = parsed._replace(
#             fragment=""
#         )

#         return parsed.geturl()

#     # =============================================================
#     # STRING
#     # =============================================================

#     def _get_string(
#         self,
#         value,
#     ):

#         if value is None:
#             return ""

#         return str(
#             value
#         ).strip()

#     # =============================================================
#     # CLEAN HTML
#     # =============================================================

#     def _clean_html(
#         self,
#         value,
#     ):

#         if not value:
#             return ""

#         soup = BeautifulSoup(
#             value,
#             "html.parser",
#         )

#         return soup.get_text(
#             "\n",
#             strip=True,
#         )

#     # =============================================================
#     # DEDUPLICATE
#     # =============================================================

#     def _deduplicate_jobs(
#         self,
#         jobs,
#     ):
#         """
#         Remove duplicate Job objects.

#         Primary key:
#             posting_url

#         Secondary key:
#             company + title
#         """

#         unique = {}

#         for job in jobs:

#             if not job:
#                 continue

#             posting_url = (
#                 getattr(
#                     job,
#                     "posting_url",
#                     ""
#                 )
#                 or ""
#             )

#             title = (
#                 getattr(
#                     job,
#                     "title",
#                     ""
#                 )
#                 or ""
#             )

#             company = (
#                 getattr(
#                     job,
#                     "company",
#                     ""
#                 )
#                 or ""
#             )

#             if posting_url:

#                 key = (
#                     posting_url
#                     .strip()
#                     .lower()
#                 )

#             else:

#                 key = (
#                     f"{company}|"
#                     f"{title}"
#                 ).lower()

#             if key not in unique:

#                 unique[key] = job

#         return list(
#             unique.values()
#         )

#     # =============================================================
#     # PRINT JOB
#     # =============================================================

#     def _print_job(
#         self,
#         job,
#     ):

#         print()

#         print(
#             "The job returned "
#             "from scraper:"
#         )

#         print(
#             f"  Company: "
#             f"{getattr(job, 'company', '')}"
#         )

#         print(
#             f"  Title: "
#             f"{getattr(job, 'title', '')}"
#         )

#         print(
#             f"  Location: "
#             f"{getattr(job, 'location', '')}"
#         )

#         print(
#             f"  Posted: "
#             f"{getattr(job, 'posting_date', '')}"
#         )

#         print(
#             f"  URL: "
#             f"{getattr(job, 'posting_url', '')}"
#         )

#         print(
#             f"  Apply URL: "
#             f"{getattr(job, 'apply_url', '')}"
#         )

#         print(
#             f"  Employment Type: "
#             f"{getattr(job, 'employment_type', '')}"
#         )

#         print(
#             f"  Job ID: "
#             f"{getattr(job, 'job_id', '')}"
#         )

#         print(
#             f"  Source: "
#             f"{getattr(job, 'source', '')}"
#         )

#         description = (
#             getattr(
#                 job,
#                 "description",
#                 ""
#             )
#             or ""
#         )

#         print(
#             f"  Description: "
#             f"{description[:500]}"
#         )


# import json
# import time
# from collections import deque
# from urllib.parse import urljoin, urlparse, urldefrag

# import requests
# from bs4 import BeautifulSoup


# class GenericCareerScraper:
#     """
#     Generic scraper for discovering job postings from company career pages.

#     The scraper is intentionally generic. It attempts to discover:

#         Career Page
#             |
#             +--> JobPosting JSON-LD
#             |
#             +--> Job Search / Open Roles page
#                     |
#                     +--> Individual Job Links
#                             |
#                             +--> Job Detail Page

#     The scraper is designed for periodic/daily monitoring rather than
#     high-speed crawling.
#     """

#     # Maximum number of pages used for discovering jobs.
#     MAX_DISCOVERY_PAGES = 10

#     # Maximum number of individual job pages to fetch.
#     # This prevents a company with thousands of jobs from causing
#     # hundreds/thousands of requests.
#     MAX_JOB_PAGES = 100

#     # Number of seconds to wait between HTTP requests.
#     REQUEST_DELAY = 1.0

#     # Number of consecutive 429 responses before stopping.
#     MAX_CONSECUTIVE_429 = 3

#     # Common words used to identify links to job-search pages.
#     JOB_SEARCH_TERMS = [
#         "open roles",
#         "open jobs",
#         "view jobs",
#         "view open jobs",
#         "view open roles",
#         "search jobs",
#         "search roles",
#         "search openings",
#         "job search",
#         "careers search",
#         "job opportunities",
#         "see open positions",
#         "see open roles",
#         "see jobs",
#         "find jobs",
#         "find opportunities",
#         "all jobs",
#         "all openings",
#         "all positions",
#         "current openings",
#         "job openings",
#         "job listings",
#         "positions",
#     ]

#     # URL patterns that strongly suggest an individual job.
#     JOB_URL_INDICATORS = [
#         "/job/",
#         "/jobs/",
#         "/job-",
#         "/jobs-",
#         "/position/",
#         "/positions/",
#         "/opening/",
#         "/openings/",
#         "/opportunity/",
#         "/opportunities/",
#         "/vacancy/",
#         "/vacancies/",
#         "jobid=",
#         "job_id=",
#         "gh_jid=",
#         "lever.co/",
#         "greenhouse.io/",
#         "myworkdayjobs.com/",
#     ]

#     # URL patterns that suggest a job-search/listing page.
#     JOB_SEARCH_URL_INDICATORS = [
#         "/jobs",
#         "/careers/search",
#         "/jobs/search",
#         "/search/jobs",
#         "/search?job",
#         "/open-roles",
#         "/open-roles/",
#         "/openings",
#         "/positions",
#         "/job-search",
#         "/jobsearch",
#         "/opportunities",
#     ]

#     def __init__(
#         self,
#         timeout=30,
#         request_delay=3.0,
#         max_discovery_pages=10,
#         max_job_pages=100,
#     ):
#         self.timeout = timeout

#         self.request_delay = request_delay

#         self.MAX_DISCOVERY_PAGES = max_discovery_pages
#         self.MAX_JOB_PAGES = max_job_pages

#         self.session = requests.Session()

#         self.session.headers.update(
#             {
#                 "User-Agent": (
#                     "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
#                     "AppleWebKit/537.36 "
#                     "(KHTML, like Gecko) "
#                     "Chrome/140.0.0.0 Safari/537.36"
#                 ),
#                 "Accept": (
#                     "text/html,application/xhtml+xml,"
#                     "application/xml;q=0.9,image/avif,"
#                     "image/webp,*/*;q=0.8"
#                 ),
#                 "Accept-Language": (
#                     "en-US,en;q=0.9"
#                 ),
#                 "Accept-Encoding": (
#                     "gzip, deflate"
#                 ),
#                 "Connection": "keep-alive",
#             }
#         )

#     # ============================================================
#     # PUBLIC API
#     # ============================================================

#     def scrape(self, company, url):
#         """
#         Scrape a company's career site.

#         Returns:
#             list[dict]: Job records.
#         """

#         print()
#         print("=" * 80)
#         print(f"SCRAPING: {company}")
#         print(f"CAREER URL: {url}")
#         print("=" * 80)

#         jobs = []

#         discovered_job_urls = set()
#         discovered_pages = set()

#         discovery_queue = deque()

#         # --------------------------------------------------------
#         # Start with the company's career page.
#         # --------------------------------------------------------

#         discovery_queue.append(
#             self._normalize_url(url)
#         )

#         consecutive_429 = 0

#         # --------------------------------------------------------
#         # DISCOVERY PHASE
#         # --------------------------------------------------------

#         while (
#             discovery_queue
#             and len(discovered_pages)
#             < self.MAX_DISCOVERY_PAGES
#         ):
#             page_url = discovery_queue.popleft()

#             if page_url in discovered_pages:
#                 continue

#             discovered_pages.add(page_url)

#             print()
#             print(
#                 f"Checking page "
#                 f"{len(discovered_pages)}/"
#                 f"{self.MAX_DISCOVERY_PAGES}: "
#                 f"{page_url}"
#             )

#             try:
#                 response = self._fetch_page(
#                     page_url
#                 )

#             except requests.HTTPError as exc:

#                 if (
#                     exc.response is not None
#                     and exc.response.status_code == 429
#                 ):
#                     consecutive_429 += 1

#                     print(
#                         "  HTTP 429 - Too many requests."
#                     )

#                     if (
#                         consecutive_429
#                         >= self.MAX_CONSECUTIVE_429
#                     ):
#                         print(
#                             "  Too many consecutive "
#                             "429 responses."
#                         )
#                         print(
#                             "  Stopping discovery for "
#                             f"{company}."
#                         )
#                         break

#                 else:
#                     print(
#                         f"  Error fetching page: {exc}"
#                     )

#                 continue

#             except requests.RequestException as exc:

#                 print(
#                     f"  Error fetching page: {exc}"
#                 )

#                 continue

#             consecutive_429 = 0

#             soup = BeautifulSoup(
#                 response.text,
#                 "html.parser",
#             )

#             # ----------------------------------------------------
#             # 1. Extract JobPosting JSON-LD.
#             # ----------------------------------------------------

#             json_ld_jobs = (
#                 self._extract_json_ld_jobs(
#                     soup,
#                     company,
#                     page_url,
#                 )
#             )

#             if json_ld_jobs:

#                 print(
#                     f"  Found "
#                     f"{len(json_ld_jobs)} "
#                     f"structured JobPosting "
#                     f"records."
#                 )

#                 jobs.extend(
#                     json_ld_jobs
#                 )

#             # ----------------------------------------------------
#             # 2. Discover links.
#             # ----------------------------------------------------

#             links = self._discover_links(
#                 soup,
#                 page_url,
#             )

#             print(
#                 f"  Discovered "
#                 f"{len(links)} "
#                 f"potential job/search links."
#             )

#             for link in links:

#                 link_type = link["type"]
#                 link_url = link["url"]

#                 # ----------------------------------------------
#                 # Individual job
#                 # ----------------------------------------------

#                 if link_type == "job":

#                     if (
#                         link_url
#                         not in discovered_job_urls
#                     ):

#                         discovered_job_urls.add(
#                             link_url
#                         )

#                         print(
#                             f"    JOB: "
#                             f"{link_url}"
#                         )

#                 # ----------------------------------------------
#                 # Job search/listing page
#                 # ----------------------------------------------

#                 elif (
#                     link_type
#                     == "job_search"
#                 ):

#                     if (
#                         link_url
#                         not in discovered_pages
#                     ):

#                         discovery_queue.append(
#                             link_url
#                         )

#                         print(
#                             f"    SEARCH: "
#                             f"{link_url}"
#                         )

#         # --------------------------------------------------------
#         # DISCOVERY SUMMARY
#         # --------------------------------------------------------

#         print()
#         print("-" * 80)
#         print(
#             f"Discovery complete for {company}"
#         )
#         print(
#             f"Pages examined: "
#             f"{len(discovered_pages)}"
#         )
#         print(
#             f"Individual job URLs discovered: "
#             f"{len(discovered_job_urls)}"
#         )
#         print("-" * 80)

#         # --------------------------------------------------------
#         # FETCH INDIVIDUAL JOB PAGES
#         # --------------------------------------------------------

#         job_urls_to_fetch = list(
#             discovered_job_urls
#         )

#         # Don't fetch more than our configured limit.
#         job_urls_to_fetch = (
#             job_urls_to_fetch[
#                 : self.MAX_JOB_PAGES
#             ]
#         )

#         print()
#         print(
#             f"Preparing to fetch "
#             f"{len(job_urls_to_fetch)} "
#             f"individual job pages."
#         )

#         if (
#             len(discovered_job_urls)
#             > self.MAX_JOB_PAGES
#         ):
#             print(
#                 f"WARNING: "
#                 f"{len(discovered_job_urls)} "
#                 f"jobs were discovered, but "
#                 f"only {self.MAX_JOB_PAGES} "
#                 f"will be fetched."
#             )

#         # --------------------------------------------------------
#         # Fetch each individual job page slowly.
#         # --------------------------------------------------------

#         consecutive_429 = 0

#         for index, job_url in enumerate(
#             job_urls_to_fetch,
#             start=1,
#         ):

#             print()
#             print(
#                 f"[{index}/"
#                 f"{len(job_urls_to_fetch)}] "
#                 f"Fetching job: "
#                 f"{job_url}"
#             )

#             try:

#                 response = self._fetch_page(
#                     job_url
#                 )

#             except requests.HTTPError as exc:

#                 if (
#                     exc.response is not None
#                     and exc.response.status_code == 429
#                 ):

#                     consecutive_429 += 1

#                     print(
#                         "  HTTP 429 - "
#                         "Too many requests."
#                     )

#                     if (
#                         consecutive_429
#                         >= self.MAX_CONSECUTIVE_429
#                     ):

#                         print(
#                             "  Too many consecutive "
#                             "429 responses."
#                         )

#                         print(
#                             "  Stopping job-page "
#                             "requests for "
#                             f"{company}."
#                         )

#                         break

#                 else:

#                     print(
#                         f"  Error fetching job "
#                         f"page: {exc}"
#                     )

#                 continue

#             except requests.RequestException as exc:

#                 print(
#                     f"  Error fetching job "
#                     f"page: {exc}"
#                 )

#                 continue

#             consecutive_429 = 0

#             soup = BeautifulSoup(
#                 response.text,
#                 "html.parser",
#             )

#             # ----------------------------------------------------
#             # Try JobPosting JSON-LD on the individual page.
#             # ----------------------------------------------------

#             detail_jobs = (
#                 self._extract_json_ld_jobs(
#                     soup,
#                     company,
#                     job_url,
#                 )
#             )

#             if detail_jobs:

#                 for job in detail_jobs:

#                     # Make sure the actual job URL
#                     # is the individual URL.
#                     if not job.get("url"):
#                         job["url"] = job_url

#                     jobs.append(job)

#                     print(
#                         f"  Job found: "
#                         f"{job.get('title')}"
#                     )

#             else:

#                 # ------------------------------------------------
#                 # Fallback: build a job from page HTML.
#                 # ------------------------------------------------

#                 job = (
#                     self._extract_job_from_html(
#                         soup,
#                         company,
#                         job_url,
#                     )
#                 )

#                 if job:

#                     jobs.append(job)

#                     print(
#                         f"  Job found: "
#                         f"{job.get('title')}"
#                     )

#                 else:

#                     print(
#                         "  Could not extract "
#                         "job details."
#                     )

#         # --------------------------------------------------------
#         # Remove duplicates.
#         # --------------------------------------------------------

#         jobs = self._deduplicate_jobs(
#             jobs
#         )

#         # --------------------------------------------------------
#         # FINAL RESULT
#         # --------------------------------------------------------

#         print()
#         print("=" * 80)
#         print(
#             f"FINAL RESULT: "
#             f"{company} -> "
#             f"{len(jobs)} jobs discovered"
#         )
#         print("=" * 80)

#         # --------------------------------------------------------
#         # Print each job.
#         # --------------------------------------------------------

#         for job in jobs:

#             print(
#                 f"\nThe job returned "
#                 f"from scraper:"
#             )

#             print(
#                 f"  Company: "
#                 f"{job.get('company', '')}"
#             )

#             print(
#                 f"  Title: "
#                 f"{job.get('title', '')}"
#             )

#             print(
#                 f"  Location: "
#                 f"{job.get('location', '')}"
#             )

#             print(
#                 f"  Posted: "
#                 f"{job.get('date_posted', '')}"
#             )

#             print(
#                 f"  URL: "
#                 f"{job.get('url', '')}"
#             )

#             description = (
#                 job.get(
#                     "description",
#                     "",
#                 )
#             )

#             print(
#                 f"  Description: "
#                 f"{description[:500]}"
#             )

#         return jobs

#     # ============================================================
#     # HTTP
#     # ============================================================

#     def _fetch_page(self, url):
#         """
#         Fetch a page.

#         A delay is applied before the request to avoid hammering
#         the company's website.
#         """

#         # --------------------------------------------------------
#         # Wait before every request.
#         # --------------------------------------------------------

#         if self.request_delay > 0:

#             print(
#                 f"  Sleeping "
#                 f"{self.request_delay:.1f}s "
#                 f"before request..."
#             )

#             time.sleep(
#                 self.request_delay
#             )

#         response = self.session.get(
#             url,
#             timeout=self.timeout,
#             allow_redirects=True,
#         )

#         print(
#             f"  HTTP "
#             f"{response.status_code}: "
#             f"{response.url}"
#         )

#         # --------------------------------------------------------
#         # Handle 429 specifically.
#         # --------------------------------------------------------

#         if response.status_code == 429:

#             retry_after = (
#                 response.headers.get(
#                     "Retry-After"
#                 )
#             )

#             if retry_after:

#                 try:

#                     retry_seconds = float(
#                         retry_after
#                     )

#                     print(
#                         f"  Server requested "
#                         f"retry after "
#                         f"{retry_seconds} seconds."
#                     )

#                     time.sleep(
#                         retry_seconds
#                     )

#                 except ValueError:
#                     pass

#             response.raise_for_status()

#         response.raise_for_status()

#         return response

#     # ============================================================
#     # LINK DISCOVERY
#     # ============================================================

#     def _discover_links(
#         self,
#         soup,
#         base_url,
#     ):
#         """
#         Discover potential job and job-search links.

#         Returns:

#             [
#                 {
#                     "type": "job",
#                     "url": "...",
#                 },
#                 {
#                     "type": "job_search",
#                     "url": "...",
#                 }
#             ]
#         """

#         discovered = {}

#         base_domain = (
#             urlparse(base_url)
#             .netloc
#             .lower()
#         )

#         for link in soup.find_all(
#             "a",
#             href=True,
#         ):

#             href = link.get(
#                 "href"
#             )

#             if not href:
#                 continue

#             href = href.strip()

#             if href.startswith(
#                 (
#                     "#",
#                     "javascript:",
#                     "mailto:",
#                     "tel:",
#                 )
#             ):
#                 continue

#             title = link.get_text(
#                 " ",
#                 strip=True,
#             )

#             job_url = self._normalize_url(
#                 urljoin(
#                     base_url,
#                     href,
#                 )
#             )

#             parsed = urlparse(
#                 job_url
#             )

#             domain = (
#                 parsed.netloc
#                 .lower()
#             )

#             # ----------------------------------------------------
#             # Ignore obvious non-HTTP links.
#             # ----------------------------------------------------

#             if parsed.scheme not in (
#                 "http",
#                 "https",
#             ):
#                 continue

#             # ----------------------------------------------------
#             # Determine whether this is an individual job.
#             #
#             # Allow external domains because companies frequently
#             # use Greenhouse, Lever, Workday, etc.
#             # ----------------------------------------------------

#             if self._looks_like_job_link(
#                 title,
#                 job_url,
#             ):

#                 discovered[job_url] = {
#                     "type": "job",
#                     "url": job_url,
#                 }

#                 continue

#             # ----------------------------------------------------
#             # Determine whether this is a job-search page.
#             # ----------------------------------------------------

#             if self._looks_like_job_search_link(
#                 title,
#                 job_url,
#             ):

#                 discovered[job_url] = {
#                     "type": "job_search",
#                     "url": job_url,
#                 }

#         return list(
#             discovered.values()
#         )

#     def _looks_like_job_link(
#         self,
#         title,
#         href,
#     ):
#         """
#         Determine whether a link looks like an individual
#         job posting.
#         """

#         href_lower = href.lower()

#         # Strong URL indicators.
#         for indicator in (
#             self.JOB_URL_INDICATORS
#         ):

#             if indicator in href_lower:
#                 return True

#         # --------------------------------------------------------
#         # Some ATS systems use query parameters.
#         # --------------------------------------------------------

#         parsed = urlparse(
#             href_lower
#         )

#         query = parsed.query

#         if any(
#             value in query
#             for value in [
#                 "gh_jid=",
#                 "jobid=",
#                 "job_id=",
#                 "jobnumber=",
#                 "requisitionid=",
#                 "reqid=",
#             ]
#         ):
#             return True

#         return False

#     def _looks_like_job_search_link(
#         self,
#         title,
#         href,
#     ):
#         """
#         Determine whether a link appears to lead to a job
#         search/listing page.
#         """

#         text = (
#             f"{title} {href}"
#             .lower()
#         )

#         for term in (
#             self.JOB_SEARCH_TERMS
#         ):

#             if term in text:
#                 return True

#         for indicator in (
#             self.JOB_SEARCH_URL_INDICATORS
#         ):

#             if indicator in href.lower():
#                 return True

#         return False

#     # ============================================================
#     # JSON-LD
#     # ============================================================

#     def _extract_json_ld_jobs(
#         self,
#         soup,
#         company,
#         base_url,
#     ):
#         """
#         Extract Schema.org JobPosting objects from JSON-LD.
#         """

#         jobs = []

#         scripts = soup.find_all(
#             "script",
#             type="application/ld+json",
#         )

#         for script in scripts:

#             try:

#                 raw = (
#                     script.string
#                     or script.get_text()
#                 )

#                 data = json.loads(
#                     raw
#                 )

#             except (
#                 json.JSONDecodeError,
#                 TypeError,
#             ):

#                 continue

#             records = (
#                 self._flatten_json_ld(
#                     data
#                 )
#             )

#             for record in records:

#                 if not isinstance(
#                     record,
#                     dict,
#                 ):
#                     continue

#                 record_type = record.get(
#                     "@type"
#                 )

#                 if isinstance(
#                     record_type,
#                     list,
#                 ):

#                     is_job = (
#                         "JobPosting"
#                         in record_type
#                     )

#                 else:

#                     is_job = (
#                         record_type
#                         == "JobPosting"
#                     )

#                 if not is_job:
#                     continue

#                 job = (
#                     self._build_job_from_json_ld(
#                         record,
#                         company,
#                         base_url,
#                     )
#                 )

#                 if job:
#                     jobs.append(job)

#         return jobs

#     def _flatten_json_ld(
#         self,
#         data,
#     ):
#         """
#         Flatten JSON-LD structures so JobPosting objects
#         can be found inside lists and @graph.
#         """

#         if isinstance(
#             data,
#             list,
#         ):

#             records = []

#             for item in data:

#                 records.extend(
#                     self._flatten_json_ld(
#                         item
#                     )
#                 )

#             return records

#         if isinstance(
#             data,
#             dict,
#         ):

#             records = []

#             if "@graph" in data:

#                 records.extend(
#                     self._flatten_json_ld(
#                         data["@graph"]
#                     )
#                 )

#             else:

#                 records.append(
#                     data
#                 )

#             return records

#         return []

#     def _build_job_from_json_ld(
#         self,
#         data,
#         company,
#         base_url,
#     ):
#         """
#         Convert a JobPosting JSON-LD object into our standard
#         job structure.
#         """

#         title = data.get(
#             "title"
#         )

#         if not title:
#             return None

#         job_url = data.get(
#             "url"
#         )

#         if job_url:

#             job_url = urljoin(
#                 base_url,
#                 job_url,
#             )

#         else:

#             job_url = base_url

#         location = (
#             self._extract_location(
#                 data.get(
#                     "jobLocation"
#                 )
#             )
#         )

#         description = data.get(
#             "description",
#             "",
#         )

#         date_posted = data.get(
#             "datePosted",
#             "",
#         )

#         employment_type = data.get(
#             "employmentType",
#             "",
#         )

#         return {
#             "company": company,
#             "title": str(
#                 title
#             ).strip(),
#             "location": location,
#             "url": job_url,
#             "description": self._clean_text(
#                 description
#             ),
#             "date_posted": date_posted,
#             "employment_type": (
#                 employment_type
#             ),
#         }

#     # ============================================================
#     # HTML JOB EXTRACTION
#     # ============================================================

#     def _extract_job_from_html(
#         self,
#         soup,
#         company,
#         job_url,
#     ):
#         """
#         Fallback extraction for an individual job page when
#         JobPosting JSON-LD is not available.
#         """

#         title = ""

#         # --------------------------------------------------------
#         # Try <h1>
#         # --------------------------------------------------------

#         h1 = soup.find("h1")

#         if h1:

#             title = h1.get_text(
#                 " ",
#                 strip=True,
#             )

#         # --------------------------------------------------------
#         # Try page title.
#         # --------------------------------------------------------

#         if not title:

#             page_title = soup.find(
#                 "title"
#             )

#             if page_title:

#                 title = page_title.get_text(
#                     " ",
#                     strip=True,
#                 )

#         if not title:
#             return None

#         # --------------------------------------------------------
#         # Extract visible text.
#         # --------------------------------------------------------

#         text = soup.get_text(
#             "\n",
#             strip=True,
#         )

#         text = self._clean_text(
#             text
#         )

#         # --------------------------------------------------------
#         # Try to find a location.
#         # --------------------------------------------------------

#         location = (
#             self._extract_location_from_html(
#                 soup
#             )
#         )

#         return {
#             "company": company,
#             "title": title,
#             "location": location,
#             "url": job_url,
#             "description": text,
#             "date_posted": "",
#             "employment_type": "",
#         }

#     def _extract_location_from_html(
#         self,
#         soup,
#     ):
#         """
#         Generic location extraction from HTML.

#         This is deliberately conservative.
#         """

#         location_terms = [
#             "location",
#             "locations",
#             "remote",
#             "hybrid",
#             "onsite",
#             "on-site",
#         ]

#         for element in soup.find_all(
#             [
#                 "div",
#                 "span",
#                 "p",
#                 "li",
#             ]
#         ):

#             text = element.get_text(
#                 " ",
#                 strip=True,
#             )

#             if not text:
#                 continue

#             text_lower = text.lower()

#             if any(
#                 term in text_lower
#                 for term in location_terms
#             ):

#                 # Avoid returning huge sections of page text.
#                 if len(text) <= 200:
#                     return text

#         return ""

#     # ============================================================
#     # LOCATION
#     # ============================================================

#     def _extract_location(
#         self,
#         location_data,
#     ):
#         """
#         Extract a readable location from JobPosting data.
#         """

#         if not location_data:
#             return ""

#         if isinstance(
#             location_data,
#             list,
#         ):

#             locations = []

#             for location in location_data:

#                 value = (
#                     self._extract_location(
#                         location
#                     )
#                 )

#                 if value:
#                     locations.append(
#                         value
#                     )

#             return ", ".join(
#                 locations
#             )

#         if isinstance(
#             location_data,
#             dict,
#         ):

#             address = location_data.get(
#                 "address",
#                 {},
#             )

#             if isinstance(
#                 address,
#                 dict,
#             ):

#                 parts = [
#                     address.get(
#                         "addressLocality"
#                     ),
#                     address.get(
#                         "addressRegion"
#                     ),
#                     address.get(
#                         "postalCode"
#                     ),
#                     address.get(
#                         "addressCountry"
#                     ),
#                 ]

#                 return ", ".join(
#                     str(part)
#                     for part in parts
#                     if part
#                 )

#         return ""

#     # ============================================================
#     # UTILITIES
#     # ============================================================

#     def _normalize_url(
#         self,
#         url,
#     ):
#         """
#         Normalize URLs for deduplication.
#         """

#         url = urldefrag(
#             url
#         )[0]

#         return url.rstrip("/")

#     def _clean_text(
#         self,
#         text,
#     ):
#         """
#         Clean excessive whitespace.
#         """

#         if not text:
#             return ""

#         lines = []

#         for line in str(
#             text
#         ).splitlines():

#             line = " ".join(
#                 line.split()
#             )

#             if line:
#                 lines.append(
#                     line
#                 )

#         return "\n".join(
#             lines
#         )

#     def _deduplicate_jobs(
#         self,
#         jobs,
#     ):
#         """
#         Remove duplicate jobs based on URL.
#         """

#         unique_jobs = {}

#         for job in jobs:

#             url = job.get(
#                 "url"
#             )

#             if not url:
#                 continue

#             url = self._normalize_url(
#                 url
#             )

#             job["url"] = url

#             if url not in unique_jobs:

#                 unique_jobs[url] = job

#             else:

#                 # ------------------------------------------------
#                 # Merge missing fields from duplicate records.
#                 # ------------------------------------------------

#                 existing = (
#                     unique_jobs[url]
#                 )

#                 for key, value in job.items():

#                     if not existing.get(
#                         key
#                     ) and value:

#                         existing[key] = value

#         return list(
#             unique_jobs.values()
#         )



# import json
# from urllib.parse import urljoin

# import requests
# from bs4 import BeautifulSoup


# class GenericCareerScraper:
#     """
#     Generic scraper for extracting job postings from career pages.

#     The scraper does not contain company-specific logic. It attempts
#     several generic extraction methods to identify job postings.
#     """

#     def __init__(self, timeout=30):
#         self.timeout = timeout

#         self.session = requests.Session()
#         self.session.headers.update({
#             "User-Agent": (
#                 "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
#                 "AppleWebKit/537.36 "
#                 "(KHTML, like Gecko) "
#                 "Chrome/140.0.0.0 Safari/537.36"
#             ),
#             "Accept": (
#                 "text/html,application/xhtml+xml,"
#                 "application/xml;q=0.9,image/avif,"
#                 "image/webp,*/*;q=0.8"
#             ),
#             "Accept-Language": "en-US,en;q=0.9",
#         })

#         # self.logger = logging.getLogger(__name__)

#     def scrape(self, company, url):
#         """
#         Scrape job postings from a career page.

#         Args:
#             company: Company name.
#             url: Validated career page URL.

#         Returns:
#             list[dict]: Extracted job postings.
#         """
#         print("In scraper")
#         # self.logger.info(
#         #     "Scraping career page: %s - %s",
#         #     company,
#         #     url,
#         # )

#         html = self._fetch_page(url)

#         soup = BeautifulSoup(html, "html.parser")

#         jobs = []

#         # 1. Try structured JobPosting data first.
#         jobs.extend(
#             self._extract_json_ld_jobs(
#                 soup,
#                 company,
#                 url,
#             )
#         )

#         # 2. If structured data was not available,
#         #    attempt generic HTML extraction.
#         if not jobs:
#             jobs.extend(
#                 self._extract_html_jobs(
#                     soup,
#                     company,
#                     url,
#                 )
#             )

#         jobs = self._deduplicate_jobs(jobs)

#         # self.logger.info(
#         #     "Scraped %s: %d jobs found",
#         #     company,
#         #     len(jobs),
#         # )

#         return jobs

#     def _fetch_page(self, url):
#         """Retrieve the career page HTML."""
#         # print(f"Starting scrape for following url: {url}\n")
#         response = self.session.get(
#             url,
#             timeout=self.timeout,
#             allow_redirects=True,
#         )

#         response.raise_for_status()
#         # if url == "https://www.coinbase.com/careers":
#         #     print(f"Respoonse from career page html:   {response.text}\n\n\n")

#         return response.text

#     def _extract_json_ld_jobs(self, soup, company, base_url):
#         """
#         Extract Schema.org JobPosting objects from JSON-LD.
#         """

#         jobs = []

#         scripts = soup.find_all(
#             "script",
#             type="application/ld+json",
#         )

#         for script in scripts:
#             try:
#                 data = json.loads(script.string or script.get_text())
#             except (json.JSONDecodeError, TypeError):
#                 continue

#             records = self._flatten_json_ld(data)

#             for record in records:
#                 if record.get("@type") != "JobPosting":
#                     continue

#                 job = self._build_job_from_json_ld(
#                     record,
#                     company,
#                     base_url,
#                 )

#                 if job:
#                     jobs.append(job)

#         return jobs

#     def _flatten_json_ld(self, data):
#         """
#         Flatten JSON-LD structures so that JobPosting objects
#         can be found regardless of whether they are stored as
#         a single object, list, or @graph.
#         """

#         if isinstance(data, list):
#             records = []

#             for item in data:
#                 records.extend(
#                     self._flatten_json_ld(item)
#                 )

#             return records

#         if isinstance(data, dict):

#             if "@graph" in data:
#                 return self._flatten_json_ld(
#                     data["@graph"]
#                 )

#             return [data]

#         return []

#     def _build_job_from_json_ld(
#         self,
#         data,
#         company,
#         base_url,
#     ):
#         """Convert a JobPosting JSON-LD object into our standard format."""

#         title = data.get("title")

#         if not title:
#             return None

#         job_url = data.get("url")

#         if job_url:
#             job_url = urljoin(base_url, job_url)
#         else:
#             job_url = base_url

#         location = self._extract_location(
#             data.get("jobLocation")
#         )

#         description = data.get("description", "")

#         return {
#             "company": company,
#             "title": title.strip(),
#             "location": location,
#             "url": job_url,
#             "description": description,
#         }

#     def _extract_location(self, location_data):
#         """Extract a readable location from JobPosting data."""

#         if not location_data:
#             return ""

#         if isinstance(location_data, list):
#             locations = []

#             for location in location_data:
#                 value = self._extract_location(location)

#                 if value:
#                     locations.append(value)

#             return ", ".join(locations)

#         if isinstance(location_data, dict):

#             address = location_data.get("address", {})

#             if isinstance(address, dict):
#                 parts = [
#                     address.get("addressLocality"),
#                     address.get("addressRegion"),
#                     address.get("postalCode"),
#                     address.get("addressCountry"),
#                 ]

#                 return ", ".join(
#                     str(part)
#                     for part in parts
#                     if part
#                 )

#         return ""

#     def _extract_html_jobs(
#         self,
#         soup,
#         company,
#         base_url,
#     ):
#         """
#         Generic HTML-based job extraction.

#         This is intentionally conservative. It looks for links
#         that appear to point to job postings rather than treating
#         every link on a career page as a job.
#         """

#         jobs = []

#         for link in soup.find_all("a", href=True):

#             title = link.get_text(
#                 " ",
#                 strip=True,
#             )

#             href = link.get("href")

#             if not title or not href:
#                 continue

#             if not self._looks_like_job_link(
#                 title,
#                 href,
#             ):
#                 continue

#             job_url = urljoin(
#                 base_url,
#                 href,
#             )

#             jobs.append({
#                 "company": company,
#                 "title": title,
#                 "location": "",
#                 "url": job_url,
#                 "description": "",
#             })

#         return jobs

#     def _looks_like_job_link(self, title, href):
#         """
#         Determine whether a link appears to represent a job posting.
#         """

#         text = f"{title} {href}".lower()

#         job_indicators = [
#             "/job/",
#             "/jobs/",
#             "/job-",
#             "/jobs-",
#             "/position/",
#             "/positions/",
#             "/careers/",
#             "/career/",
#             "jobid=",
#             "job_id=",
#             "gh_jid=",
#             "lever.co/",
#         ]

#         return any(
#             indicator in text
#             for indicator in job_indicators
#         )

#     def _deduplicate_jobs(self, jobs):
#         """Remove duplicate jobs based on URL."""

#         unique_jobs = {}
        
#         for job in jobs:
#             url = job.get("url")

#             if not url:
#                 continue

#             if url not in unique_jobs:
#                 unique_jobs[url] = job

#         return list(unique_jobs.values())
