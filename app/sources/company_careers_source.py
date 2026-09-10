import re
import requests
import json
import os
from app.utils.career_pages_storage import (load_career_pages)


class CompanyCareersSource:
    """
    Finds and validates company career pages.

    Career-page discovery is performed once per distinct company
    name rather than once per rejected posting.
    """

    def __init__(self, timeout=(3, 5)):

        self.timeout = timeout

        self.session = requests.Session()

        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/140.0 Safari/537.36"
            ),
            "Accept": (
                "text/html,application/xhtml+xml,"
                "application/xml;q=0.9,image/avif,"
                "image/webp,*/*;q=0.8"
            ),
            "Accept-Language": "en-US,en;q=0.9"
        })

        # Validated career links
        self.validated_career_links = []

        # company name -> career URL or None
        self.cache = {}

    # =============================================================
    # Find career pages for DISTINCT companies
    # =============================================================

    def find_careers_pages(
        self,
        rejected_postings,
        company_field="companyName"
    ):
        """
        Find career pages for distinct companies represented in
        the rejected posting list.

        Each company is processed only once.

        Args:
            rejected_postings:
                List of dictionaries containing company names.

            company_field:
                Dictionary key containing the company name.

        Returns:
            List of validated career-page records.
        """

        # ---------------------------------------------------------
        # Extract distinct company names
        # ---------------------------------------------------------

        companies = []
        seen = set()

        for posting in rejected_postings:

            if not isinstance(posting, dict):
                continue

            company_name = posting.get(
                company_field
            )

            if not company_name:
                continue

            company_name = str(
                company_name
            ).strip()

            if not company_name:
                continue

            # Case-insensitive deduplication
            company_key = company_name.casefold()

            if company_key in seen:
                continue

            seen.add(company_key)
            companies.append(company_name)

        print(
            f"Starting career page discovery for "
            f"{len(companies)} distinct companies "
            f"from {len(rejected_postings)} rejected postings."
        )

        # ---------------------------------------------------------
        # Find one career page per distinct company
        # ---------------------------------------------------------

        for company_name in companies:

            self.find_careers_page(
                company_name
            )

        print(
            f"Career page discovery complete. "
            f"Found {len(self.validated_career_links)} "
            f"career pages."
        )

        return self.validated_career_links

    # =============================================================
    # Find career page for ONE company
    # =============================================================

    def find_careers_page(
        self,
        company_name
    ):

        if not company_name:
            return None

        company_name = str(
            company_name
        ).strip()

        if not company_name:
            return None

        cache_key = company_name.casefold()

        # ---------------------------------------------------------
        # Check career_pages.json first.
        #
        # The JSON file is the persistent source of truth for
        # previously validated career-page URLs.
        #
        # If the company exists in the file, return the stored
        # URL immediately. Do NOT validate it again.
        # ---------------------------------------------------------

        career_pages_data = load_career_pages()

        existing_companies = career_pages_data.get(
            "companies",
            []
        )

        for company in existing_companies:

            if not isinstance(
                company,
                dict
            ):
                continue

            stored_company_name = company.get(
                "companyName"
            )

            stored_url = company.get(
                "careerpageurl"
            )

            if not stored_company_name:
                continue

            if not stored_url:
                continue

            if (
                str(
                    stored_company_name
                ).strip().casefold()
                == cache_key
            ):

                print(
                    f"    Using stored career page: "
                    f"{stored_url}"
                )

                return str(
                    stored_url
                ).strip()

        # ---------------------------------------------------------
        # Company was not found in career_pages.json.
        #
        # Generate candidate URLs and validate them.
        # ---------------------------------------------------------

        career_urls = self.generate_career_urls(
            company_name
        )

        for url in career_urls:

            try:

                validated_url = self.validate_url(
                    url
                )

            except Exception:

                continue

            if not validated_url:
                continue

            print(
                f"    VALID career page: "
                f"{validated_url}"
            )

            result = {
                "companyName": company_name,
                "careerpageurl": validated_url
            }

            # Keep the existing behavior of recording newly
            # discovered results so the existing main.py logic
            # can persist them to career_pages.json.
            self.validated_career_links.append(
                result
            )

            return validated_url

        # ---------------------------------------------------------
        # No valid career page found.
        # ---------------------------------------------------------

        return None


    # def find_careers_page(
    #     self,
    #     company_name
    # ):

    #     if not company_name:
    #         return None

    #     company_name = str(
    #         company_name
    #     ).strip()

    #     if not company_name:
    #         return None

    #     cache_key = company_name.casefold()

    #     if cache_key in self.cache:
    #         return self.cache[cache_key]

    #     career_urls = self.generate_career_urls(
    #         company_name
    #     )

    #     for url in career_urls:

    #         try:

    #             validated_url = self.validate_url(
    #                 url
    #             )

    #         except Exception as error:

    #             # print(
    #             #     f"      URL validation error: "
    #             #     f"{url} - {error}"
    #             # )

    #             continue

    #         if not validated_url:
    #             continue

    #         print(
    #             f"    VALID career page: "
    #             f"{validated_url}"
    #         )

    #         result = {
    #             "companyName": company_name,
    #             "careerpageurl": validated_url
    #         }

    #         self.validated_career_links.append(
    #             result
    #         )

    #         self.cache[
    #             cache_key
    #         ] = validated_url

    #         return self.validated_career_links
    #     #validated_url

    #     # ---------------------------------------------------------
    #     # No valid career page
    #     # ---------------------------------------------------------

    #     self.cache[
    #         cache_key
    #     ] = None

    #     return None

    # =============================================================
    # Generate career URLs
    # =============================================================

    @staticmethod
    def generate_career_urls(
        company_name
    ):

        company = (
            company_name
            .strip()
            .lower()
        )

        company = re.sub(
            r"[^a-z0-9\s-]",
            "",
            company
        )

        domain_name = re.sub(
            r"[^a-z0-9]",
            "",
            company
        )

        domains = [

            f"{domain_name}.com",
            f"www.{domain_name}.com",

            f"careers.{domain_name}.com",

            f"jobs.{domain_name}.com",

            f"{domain_name}.jobs",
            f"www.{domain_name}.jobs",
            f"careers.{domain_name}.jobs",
            f"jobs.{domain_name}.jobs",

            f"{domain_name}hq.com",
            f"www.{domain_name}hq.com",
            f"careers.{domain_name}hq.com",
            f"jobs.{domain_name}hq.com",
        ]

        paths = [

            "/careers",
            "/careers/",

            "/jobs",
            "/jobs/",

            "/all-jobs",
            "/all-jobs/",

            "/en",
            "/en/",

            "/en/careers",
            "/en/careers/",

            "/en/jobs",
            "/en/jobs/",

            "/en/all-jobs",
            "/en/all-jobs/",
        ]

        urls = []

        for domain in domains:

            for path in paths:

                urls.append(
                    f"https://{domain}{path}"
                )

        return list(
            dict.fromkeys(urls)
        )

    # =============================================================
    # Validate URL
    # =============================================================

    def validate_url(
        self,
        url
    ):
        """
        Validate one URL.

        A failed request returns None. It does not raise into
        the career-page discovery process.
        """

        try:

            response = requests.get(
                url,
                headers=dict(
                    self.session.headers
                ),
                timeout=self.timeout,
                allow_redirects=True
            )

            if response.status_code != 200:
                return None

            return response.url

        except requests.RequestException as error:

            # print(
            #     f"      Request failed: "
            #     f"{error}"
            # )

            return None

        except Exception as error:

            print(
                f"      Unexpected URL validation failure: "
                f"{url} - {error}"
            )

            return None

    # =============================================================
    # Get already existing companies where career page is validated
    # =============================================================
    def get_companies_not_in_cache(
        self,
        rejected_company_names,
        career_pages_data
    ):
        """
        Return distinct rejected company names that do not already
        exist in the career-pages JSON data.

        Comparison is case-insensitive while preserving the original
        company name from rejected_company_names.

        Args:
            rejected_company_names:
                List of company names from rejected postings.

            career_pages_data:
                Dictionary loaded from career_pages.json.

        Returns:
            List of company names that still need career-page lookup.
        """

        existing_companies = career_pages_data.get(
            "companies",
            []
        )

        # ---------------------------------------------------------
        # Build a case-insensitive set of companies already stored
        # ---------------------------------------------------------

        existing_company_names = set()

        for company in existing_companies:

            if isinstance(company, dict):

                company_name = company.get(
                    "companyName"
                )

            else:

                company_name = company

            if not company_name:
                continue

            company_name = str(
                company_name
            ).strip()

            if not company_name:
                continue

            existing_company_names.add(
                company_name.casefold()
            )

        # ---------------------------------------------------------
        # Find distinct rejected companies that are not already
        # present in career_pages.json
        # ---------------------------------------------------------

        companies_to_process = []
        seen = set()

        for company_name in rejected_company_names:
            if not company_name:
                continue

            company_name = str(
                company_name
            ).strip()

            if not company_name:
                continue

            company_key = company_name.casefold()

            # -----------------------------------------------------
            # Already encountered in this rejected-company list
            # -----------------------------------------------------

            if company_key in seen:
                continue

            seen.add(company_key)

            # -----------------------------------------------------
            # Already processed in career_pages.json
            # -----------------------------------------------------

            if company_key in existing_company_names:
                continue

            # -----------------------------------------------------
            # New company that needs career-page discovery
            # -----------------------------------------------------

            companies_to_process.append(
                company_name
            )

        print(f"companies_to_process; {companies_to_process}")
        print(f"TYPE BEFORE RETURN: {type(companies_to_process)}")
        print(f"LENGTH BEFORE RETURN: {len(companies_to_process)}")
        return companies_to_process








