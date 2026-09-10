import json
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


class GenericCareerScraper:
    """
    Generic scraper for extracting job postings from career pages.

    The scraper does not contain company-specific logic. It attempts
    several generic extraction methods to identify job postings.
    """

    def __init__(self, timeout=30):
        self.timeout = timeout

        self.session = requests.Session()
        self.session.headers.update({
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
        })

        # self.logger = logging.getLogger(__name__)

    def scrape(self, company, url):
        """
        Scrape job postings from a career page.

        Args:
            company: Company name.
            url: Validated career page URL.

        Returns:
            list[dict]: Extracted job postings.
        """

        self.logger.info(
            "Scraping career page: %s - %s",
            company,
            url,
        )

        html = self._fetch_page(url)

        soup = BeautifulSoup(html, "html.parser")

        jobs = []

        # 1. Try structured JobPosting data first.
        jobs.extend(
            self._extract_json_ld_jobs(
                soup,
                company,
                url,
            )
        )

        # 2. If structured data was not available,
        #    attempt generic HTML extraction.
        if not jobs:
            jobs.extend(
                self._extract_html_jobs(
                    soup,
                    company,
                    url,
                )
            )

        jobs = self._deduplicate_jobs(jobs)

        self.logger.info(
            "Scraped %s: %d jobs found",
            company,
            len(jobs),
        )

        return jobs

    def _fetch_page(self, url):
        """Retrieve the career page HTML."""

        response = self.session.get(
            url,
            timeout=self.timeout,
            allow_redirects=True,
        )

        response.raise_for_status()

        print(f"Respoonse from career page html:   {response.text}\n\n\n")

        return response.text

    def _extract_json_ld_jobs(self, soup, company, base_url):
        """
        Extract Schema.org JobPosting objects from JSON-LD.
        """

        jobs = []

        scripts = soup.find_all(
            "script",
            type="application/ld+json",
        )

        for script in scripts:
            try:
                data = json.loads(script.string or script.get_text())
            except (json.JSONDecodeError, TypeError):
                continue

            records = self._flatten_json_ld(data)

            for record in records:
                if record.get("@type") != "JobPosting":
                    continue

                job = self._build_job_from_json_ld(
                    record,
                    company,
                    base_url,
                )

                if job:
                    jobs.append(job)

        return jobs

    def _flatten_json_ld(self, data):
        """
        Flatten JSON-LD structures so that JobPosting objects
        can be found regardless of whether they are stored as
        a single object, list, or @graph.
        """

        if isinstance(data, list):
            records = []

            for item in data:
                records.extend(
                    self._flatten_json_ld(item)
                )

            return records

        if isinstance(data, dict):

            if "@graph" in data:
                return self._flatten_json_ld(
                    data["@graph"]
                )

            return [data]

        return []

    def _build_job_from_json_ld(
        self,
        data,
        company,
        base_url,
    ):
        """Convert a JobPosting JSON-LD object into our standard format."""

        title = data.get("title")

        if not title:
            return None

        job_url = data.get("url")

        if job_url:
            job_url = urljoin(base_url, job_url)
        else:
            job_url = base_url

        location = self._extract_location(
            data.get("jobLocation")
        )

        description = data.get("description", "")

        return {
            "company": company,
            "title": title.strip(),
            "location": location,
            "url": job_url,
            "description": description,
        }

    def _extract_location(self, location_data):
        """Extract a readable location from JobPosting data."""

        if not location_data:
            return ""

        if isinstance(location_data, list):
            locations = []

            for location in location_data:
                value = self._extract_location(location)

                if value:
                    locations.append(value)

            return ", ".join(locations)

        if isinstance(location_data, dict):

            address = location_data.get("address", {})

            if isinstance(address, dict):
                parts = [
                    address.get("addressLocality"),
                    address.get("addressRegion"),
                    address.get("postalCode"),
                    address.get("addressCountry"),
                ]

                return ", ".join(
                    str(part)
                    for part in parts
                    if part
                )

        return ""

    def _extract_html_jobs(
        self,
        soup,
        company,
        base_url,
    ):
        """
        Generic HTML-based job extraction.

        This is intentionally conservative. It looks for links
        that appear to point to job postings rather than treating
        every link on a career page as a job.
        """

        jobs = []

        for link in soup.find_all("a", href=True):

            title = link.get_text(
                " ",
                strip=True,
            )

            href = link.get("href")

            if not title or not href:
                continue

            if not self._looks_like_job_link(
                title,
                href,
            ):
                continue

            job_url = urljoin(
                base_url,
                href,
            )

            jobs.append({
                "company": company,
                "title": title,
                "location": "",
                "url": job_url,
                "description": "",
            })

        return jobs

    def _looks_like_job_link(self, title, href):
        """
        Determine whether a link appears to represent a job posting.
        """

        text = f"{title} {href}".lower()

        job_indicators = [
            "/job/",
            "/jobs/",
            "/job-",
            "/jobs-",
            "/position/",
            "/positions/",
            "/careers/",
            "/career/",
            "jobid=",
            "job_id=",
            "gh_jid=",
            "lever.co/",
        ]

        return any(
            indicator in text
            for indicator in job_indicators
        )

    def _deduplicate_jobs(self, jobs):
        """Remove duplicate jobs based on URL."""

        unique_jobs = {}
        
        for job in jobs:
            url = job.get("url")

            if not url:
                continue

            if url not in unique_jobs:
                unique_jobs[url] = job

        return list(unique_jobs.values())
