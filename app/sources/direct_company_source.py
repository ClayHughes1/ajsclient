# import re

# from app.utils.career_pages_storage import load_career_pages


# class RejectedPostingEnricher:
#     """
#     Enriches rejected job postings with company and careers-page
#     information.

#     Existing career pages are loaded from career_pages.json once
#     at the beginning of the enrichment process.

#     A company already present in career_pages.json will NOT cause
#     another web request.

#     CompanyCareersSource.find_careers_page() is called only when
#     the company does not already exist in career_pages.json.
#     """

#     def __init__(
#         self,
#         careers_source
#     ):

#         self.careers_source = careers_source

#     # =========================================================
#     # MAIN ENRICHMENT
#     # =========================================================

#     def enrich(
#         self,
#         rejected_jobs
#     ):
#         """
#         rejected_jobs is expected to contain:

#             [
#                 (job, rejection_reason),
#                 ...
#             ]

#         Job objects are updated in place.
#         """

#         # -----------------------------------------------------
#         # Load career_pages.json ONCE.
#         #
#         # This is the persistent source of truth.
#         # -----------------------------------------------------

#         career_pages_data = load_career_pages()

#         existing_companies = (
#             career_pages_data.get(
#                 "companies",
#                 []
#             )
#         )

#         # -----------------------------------------------------
#         # Build a fast company-name lookup.
#         #
#         # The URL is stored as the VALUE because we need to
#         # assign it to the job.
#         #
#         # Example:
#         #
#         # {
#         #     "nvidia":
#         #         "https://www.nvidia.com/en-us/about-nvidia/careers/",
#         #
#         #     "humana":
#         #         "https://careers.humana.com/us/en"
#         # }
#         # -----------------------------------------------------

#         career_page_lookup = {}

#         for company in existing_companies:

#             if not isinstance(
#                 company,
#                 dict
#             ):
#                 continue

#             company_name = company.get(
#                 "companyName"
#             )

#             career_page_url = company.get(
#                 "careerpageurl"
#             )

#             if not company_name:
#                 continue

#             if not career_page_url:
#                 continue

#             company_key = str(
#                 company_name
#             ).strip().casefold()

#             if not company_key:
#                 continue

#             career_page_lookup[
#                 company_key
#             ] = str(
#                 career_page_url
#             ).strip()

#         # -----------------------------------------------------
#         # Process rejected jobs.
#         # -----------------------------------------------------

#         for job, rejection_reason in rejected_jobs:

#             # -------------------------------------------------
#             # Preserve rejection reason.
#             # -------------------------------------------------

#             job.rejection_reason = (
#                 rejection_reason
#             )

#             # -------------------------------------------------
#             # Extract company name.
#             # -------------------------------------------------

#             company_name = (
#                 self.extract_company_name(
#                     job
#                 )
#             )

#             job.extracted_company_name = (
#                 company_name
#             )

#             # -------------------------------------------------
#             # No company name.
#             # -------------------------------------------------

#             if not company_name:

#                 job.company_careers_url = None

#                 job.company_careers_url_valid = (
#                     False
#                 )

#                 continue

#             # -------------------------------------------------
#             # Normalize company name for lookup.
#             # -------------------------------------------------

#             company_key = (
#                 company_name.casefold()
#             )

#             # =================================================
#             # CHECK career_pages.json LOOKUP
#             # =================================================

#             stored_career_url = (
#                 career_page_lookup.get(
#                     company_key
#                 )
#             )

#             if stored_career_url:

#                 # -------------------------------------------------
#                 # The URL was already validated during a previous
#                 # run and stored in career_pages.json.
#                 #
#                 # DO NOT call find_careers_page().
#                 # DO NOT make an HTTP request.
#                 # -------------------------------------------------

#                 print(
#                     f"    Using stored career page: "
#                     f"{stored_career_url}"
#                 )

#                 job.company_careers_url = (
#                     stored_career_url
#                 )

#                 job.company_careers_url_valid = (
#                     True
#                 )

#                 continue

#             # =================================================
#             # COMPANY NOT IN career_pages.json
#             # =================================================

#             print(
#                 f"    Searching for career page: "
#                 f"{company_name}"
#             )

#             careers_url = (
#                 self.careers_source.find_careers_page(
#                     company_name
#                 )
#             )

#             job.company_careers_url = (
#                 careers_url
#             )

#             job.company_careers_url_valid = (
#                 careers_url is not None
#             )

#             # -------------------------------------------------
#             # If a new URL was discovered, add it to the
#             # in-memory lookup.
#             #
#             # This DOES NOT write to disk.
#             #
#             # main.py remains responsible for saving the
#             # newly discovered career page to career_pages.json.
#             #
#             # The purpose here is simply to prevent another
#             # web search for the same company during this
#             # enrichment run.
#             # -------------------------------------------------

#             if careers_url:

#                 career_page_lookup[
#                     company_key
#                 ] = careers_url

#         return rejected_jobs

#     # =========================================================
#     # EXTRACT COMPANY NAME
#     # =========================================================

#     def extract_company_name(
#         self,
#         job
#     ):
#         """
#         Extract the company name from the job object.

#         Prefer the job's company field.

#         Fall back to company_name if the source uses that
#         attribute.

#         Common corporate suffixes are removed.
#         """

#         company = getattr(
#             job,
#             "company",
#             None
#         )

#         if not company:

#             company = getattr(
#                 job,
#                 "company_name",
#                 None
#             )

#         if not company:

#             return None

#         company = str(
#             company
#         ).strip()

#         if not company:

#             return None

#         # -----------------------------------------------------
#         # Remove common corporate suffixes.
#         # -----------------------------------------------------

#         company = re.sub(
#             r"\s*,?\s*"
#             r"(Inc\.?|"
#             r"LLC|"
#             r"Ltd\.?|"
#             r"Limited|"
#             r"Corporation|"
#             r"Corp\.?|"
#             r"Company|"
#             r"Co\.?)$",
#             "",
#             company,
#             flags=re.IGNORECASE
#         )

#         return company.strip()


import asyncio
import re

from app.utils.career_pages_storage import load_career_pages


class RejectedPostingEnricher:
    """
    Enrich rejected jobs with company career-page information.

    Existing career pages are loaded once.

    Companies not already present in career_pages.json are
    resolved concurrently.
    """

    def __init__(
        self,
        careers_source,
        max_concurrency=20,
    ):
        self.careers_source = careers_source
        self.max_concurrency = max_concurrency

    async def enrich(self, rejected_jobs):
        """
        Enrich rejected jobs.

        Companies already present in career_pages.json do not
        generate web requests.

        New companies are resolved concurrently.
        """

        # -----------------------------------------------------
        # Load existing career pages once.
        # -----------------------------------------------------

        career_pages_data = load_career_pages()

        existing_companies = career_pages_data.get(
            "companies",
            []
        )

        career_page_lookup = self._build_career_lookup(
            existing_companies
        )

        # -----------------------------------------------------
        # Phase 1:
        # Extract company names and prepare jobs.
        # -----------------------------------------------------

        jobs_by_company = {}

        for job, rejection_reason in rejected_jobs:

            job.rejection_reason = rejection_reason

            company_name = self.extract_company_name(job)

            job.extracted_company_name = company_name

            if not company_name:
                job.company_careers_url = None
                job.company_careers_url_valid = False
                continue

            company_key = company_name.casefold().strip()

            jobs_by_company.setdefault(
                company_key,
                []
            ).append(job)

        # -----------------------------------------------------
        # Phase 2:
        # Determine which companies require web requests.
        # -----------------------------------------------------

        companies_to_search = {}

        for company_key, jobs in jobs_by_company.items():

            # Already known.
            if company_key in career_page_lookup:
                continue

            # Use the first job's company name for searching.
            company_name = jobs[0].extracted_company_name

            companies_to_search[company_key] = company_name

        # -----------------------------------------------------
        # Phase 3:
        # Search for unknown companies concurrently.
        # -----------------------------------------------------

        if companies_to_search:

            results = await self._find_career_pages(
                companies_to_search
            )

            # Add newly discovered pages to lookup.
            career_page_lookup.update(results)

        # -----------------------------------------------------
        # Phase 4:
        # Assign results to jobs.
        # -----------------------------------------------------

        for company_key, jobs in jobs_by_company.items():

            career_url = career_page_lookup.get(
                company_key
            )

            is_valid = career_url is not None

            for job in jobs:
                job.company_careers_url = career_url
                job.company_careers_url_valid = is_valid

        return rejected_jobs

    async def _find_career_pages(self, companies):
        """
        Resolve multiple companies concurrently.

        companies:
            {
                "nvidia": "NVIDIA",
                "humana": "Humana",
                ...
            }

        Returns:
            {
                "nvidia": "https://...",
                "humana": "https://..."
            }
        """

        semaphore = asyncio.Semaphore(
            self.max_concurrency
        )

        async def find_one(company_key, company_name):

            async with semaphore:

                try:
                    # print(
                    #     f"Searching for career page: "
                    #     f"{company_name}"
                    # )

                    url = await asyncio.to_thread(
                        self.careers_source.find_careers_page,
                        company_name
                    )

                    if url:
                        return company_key, url

                    # Store None as well so the company is not
                    # searched repeatedly during this run.
                    return company_key, None

                except Exception as exc:

                    print(
                        f"Failed to find career page for "
                        f"{company_name}: {exc}"
                    )

                    return company_key, None

        tasks = [
            find_one(company_key, company_name)
            for company_key, company_name in companies.items()
        ]

        results = await asyncio.gather(
            *tasks
        )

        return {
            company_key: url
            for company_key, url in results
            if url
        }

    @staticmethod
    def _build_career_lookup(existing_companies):
        """
        Build:

            company_name -> career page URL
        """

        lookup = {}

        for company in existing_companies:

            if not isinstance(company, dict):
                continue

            company_name = company.get("companyName")
            career_page_url = company.get("careerpageurl")

            if not company_name or not career_page_url:
                continue

            company_key = str(
                company_name
            ).strip().casefold()

            if not company_key:
                continue

            lookup[company_key] = str(
                career_page_url
            ).strip()

        return lookup

    @staticmethod
    def extract_company_name(job):
        """
        Extract and normalize company name.
        """

        company = getattr(
            job,
            "company",
            None
        )

        if not company:
            company = getattr(
                job,
                "company_name",
                None
            )

        if not company:
            return None

        company = str(company).strip()

        if not company:
            return None

        company = re.sub(
            r"\s*,?\s*"
            r"(Inc\.?|"
            r"LLC|"
            r"Ltd\.?|"
            r"Limited|"
            r"Corporation|"
            r"Corp\.?|"
            r"Company|"
            r"Co\.?)$",
            "",
            company,
            flags=re.IGNORECASE,
        )

        return company.strip()




