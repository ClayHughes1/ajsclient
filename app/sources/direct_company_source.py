import re

from app.utils.career_pages_storage import load_career_pages


class RejectedPostingEnricher:
    """
    Enriches rejected job postings with company and careers-page
    information.

    Existing career pages are loaded from career_pages.json once
    at the beginning of the enrichment process.

    A company already present in career_pages.json will NOT cause
    another web request.

    CompanyCareersSource.find_careers_page() is called only when
    the company does not already exist in career_pages.json.
    """

    def __init__(
        self,
        careers_source
    ):

        self.careers_source = careers_source

    # =========================================================
    # MAIN ENRICHMENT
    # =========================================================

    def enrich(
        self,
        rejected_jobs
    ):
        """
        rejected_jobs is expected to contain:

            [
                (job, rejection_reason),
                ...
            ]

        Job objects are updated in place.
        """

        # -----------------------------------------------------
        # Load career_pages.json ONCE.
        #
        # This is the persistent source of truth.
        # -----------------------------------------------------

        career_pages_data = load_career_pages()

        existing_companies = (
            career_pages_data.get(
                "companies",
                []
            )
        )

        # -----------------------------------------------------
        # Build a fast company-name lookup.
        #
        # The URL is stored as the VALUE because we need to
        # assign it to the job.
        #
        # Example:
        #
        # {
        #     "nvidia":
        #         "https://www.nvidia.com/en-us/about-nvidia/careers/",
        #
        #     "humana":
        #         "https://careers.humana.com/us/en"
        # }
        # -----------------------------------------------------

        career_page_lookup = {}

        for company in existing_companies:

            if not isinstance(
                company,
                dict
            ):
                continue

            company_name = company.get(
                "companyName"
            )

            career_page_url = company.get(
                "careerpageurl"
            )

            if not company_name:
                continue

            if not career_page_url:
                continue

            company_key = str(
                company_name
            ).strip().casefold()

            if not company_key:
                continue

            career_page_lookup[
                company_key
            ] = str(
                career_page_url
            ).strip()

        # -----------------------------------------------------
        # Process rejected jobs.
        # -----------------------------------------------------

        for job, rejection_reason in rejected_jobs:

            # -------------------------------------------------
            # Preserve rejection reason.
            # -------------------------------------------------

            job.rejection_reason = (
                rejection_reason
            )

            # -------------------------------------------------
            # Extract company name.
            # -------------------------------------------------

            company_name = (
                self.extract_company_name(
                    job
                )
            )

            job.extracted_company_name = (
                company_name
            )

            # -------------------------------------------------
            # No company name.
            # -------------------------------------------------

            if not company_name:

                job.company_careers_url = None

                job.company_careers_url_valid = (
                    False
                )

                continue

            # -------------------------------------------------
            # Normalize company name for lookup.
            # -------------------------------------------------

            company_key = (
                company_name.casefold()
            )

            # =================================================
            # CHECK career_pages.json LOOKUP
            # =================================================

            stored_career_url = (
                career_page_lookup.get(
                    company_key
                )
            )

            if stored_career_url:

                # -------------------------------------------------
                # The URL was already validated during a previous
                # run and stored in career_pages.json.
                #
                # DO NOT call find_careers_page().
                # DO NOT make an HTTP request.
                # -------------------------------------------------

                print(
                    f"    Using stored career page: "
                    f"{stored_career_url}"
                )

                job.company_careers_url = (
                    stored_career_url
                )

                job.company_careers_url_valid = (
                    True
                )

                continue

            # =================================================
            # COMPANY NOT IN career_pages.json
            # =================================================

            print(
                f"    Searching for career page: "
                f"{company_name}"
            )

            careers_url = (
                self.careers_source.find_careers_page(
                    company_name
                )
            )

            job.company_careers_url = (
                careers_url
            )

            job.company_careers_url_valid = (
                careers_url is not None
            )

            # -------------------------------------------------
            # If a new URL was discovered, add it to the
            # in-memory lookup.
            #
            # This DOES NOT write to disk.
            #
            # main.py remains responsible for saving the
            # newly discovered career page to career_pages.json.
            #
            # The purpose here is simply to prevent another
            # web search for the same company during this
            # enrichment run.
            # -------------------------------------------------

            if careers_url:

                career_page_lookup[
                    company_key
                ] = careers_url

        return rejected_jobs

    # =========================================================
    # EXTRACT COMPANY NAME
    # =========================================================

    def extract_company_name(
        self,
        job
    ):
        """
        Extract the company name from the job object.

        Prefer the job's company field.

        Fall back to company_name if the source uses that
        attribute.

        Common corporate suffixes are removed.
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

        company = str(
            company
        ).strip()

        if not company:

            return None

        # -----------------------------------------------------
        # Remove common corporate suffixes.
        # -----------------------------------------------------

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
            flags=re.IGNORECASE
        )

        return company.strip()



# import re

# # ---------------------------------------------------------
# # Use the actual import path for your project.
# # ---------------------------------------------------------

# from app.utils.career_pages_storage import load_career_pages


# class RejectedPostingEnricher:
#     """
#     Enriches rejected job postings with company and careers-page
#     information.

#     Company careers searching is delegated to CompanyCareersSource.

#     Existing career-page URLs are read from career_pages.json
#     before CompanyCareersSource is called.
#     """

#     def __init__(self, careers_source):

#         self.careers_source = careers_source

#     # ---------------------------------------------------------
#     # Main enrichment method
#     # ---------------------------------------------------------

#     def enrich(self, rejected_jobs):
#         """
#         rejected_jobs is expected to contain:

#             [
#                 (job, rejection_reason),
#                 ...
#             ]

#         The job objects are updated in place and the same list
#         is returned.
#         """

#         # -----------------------------------------------------
#         # Load career_pages.json ONCE.
#         #
#         # This is the persistent source of truth for companies
#         # whose career pages have already been validated.
#         # -----------------------------------------------------

#         career_pages_data = load_career_pages()

#         existing_companies = (
#             career_pages_data.get(
#                 "companies",
#                 []
#             )
#         )

#         # -----------------------------------------------------
#         # Build a lookup of existing companies.
#         #
#         # This is NOT a URL cache.
#         #
#         # It is simply an in-memory lookup of the JSON data
#         # that we already had to load for this enrichment run.
#         # -----------------------------------------------------

#         career_page_lookup = {}

#         for company in existing_companies:

#             if not isinstance(
#                 company,
#                 dict
#             ):
#                 continue

#             stored_company_name = company.get(
#                 "companyName"
#             )

#             stored_career_url = company.get(
#                 "careerpageurl"
#             )

#             if not stored_company_name:
#                 continue

#             if not stored_career_url:
#                 continue

#             company_key = str(
#                 stored_company_name
#             ).strip().casefold()

#             if not company_key:
#                 continue

#             career_page_lookup[
#                 company_key
#             ] = str(
#                 stored_career_url
#             ).strip()

#         # -----------------------------------------------------
#         # Process rejected jobs.
#         # -----------------------------------------------------

#         for job, rejection_reason in rejected_jobs:

#             # -------------------------------------------------
#             # Preserve rejection reason
#             # -------------------------------------------------

#             job.rejection_reason = (
#                 rejection_reason
#             )

#             # -------------------------------------------------
#             # Extract company name
#             # -------------------------------------------------

#             company_name = (
#                 self.extract_company_name(job)
#             )

#             job.extracted_company_name = (
#                 company_name
#             )

#             # -------------------------------------------------
#             # No company name
#             # -------------------------------------------------

#             if not company_name:

#                 job.company_careers_url = None

#                 job.company_careers_url_valid = (
#                     False
#                 )

#                 continue

#             # -------------------------------------------------
#             # Normalize company name for JSON lookup.
#             # -------------------------------------------------

#             company_key = (
#                 company_name.casefold()
#             )

#             # -------------------------------------------------
#             # FIRST check career_pages.json.
#             #
#             # If the company already exists, DO NOT call
#             # find_careers_page().
#             #
#             # This prevents:
#             #
#             #   - career URL generation
#             #   - web searching
#             #   - URL validation
#             #   - HTTP requests
#             # -------------------------------------------------

#             stored_career_url = (
#                 career_page_lookup.get(
#                     company_key
#                 )
#             )

#             if stored_career_url:

#                 job.company_careers_url = (
#                     stored_career_url
#                 )

#                 job.company_careers_url_valid = (
#                     True
#                 )

#                 continue

#             # -------------------------------------------------
#             # Company does NOT exist in career_pages.json.
#             #
#             # ONLY NOW ask CompanyCareersSource to find and
#             # validate a career page.
#             # -------------------------------------------------

#             careers_url = (
#                 self.careers_source.find_careers_page(
#                     company_name
#                 )
#             )

#             job.company_careers_url = (
#                 careers_url
#             )

#             # -------------------------------------------------
#             # Record whether a URL was found.
#             # -------------------------------------------------

#             job.company_careers_url_valid = (
#                 careers_url is not None
#             )

#             # -------------------------------------------------
#             # If a new career page was discovered, add it to
#             # our lookup for the remainder of THIS enrichment
#             # run.
#             #
#             # This prevents multiple rejected jobs for the
#             # same NEW company from triggering repeated
#             # searches during this run.
#             # -------------------------------------------------

#             if careers_url:

#                 career_page_lookup[
#                     company_key
#                 ] = careers_url

#         return rejected_jobs

#     # ---------------------------------------------------------
#     # Extract company name
#     # ---------------------------------------------------------

#     def extract_company_name(self, job):
#         """
#         Extract the company name from the job object.

#         Prefer the job's company field. Fall back to company_name
#         if the source uses that attribute.

#         The company name is cleaned of common corporate suffixes.
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
#         # Remove common corporate suffixes
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




# # import re


# # class RejectedPostingEnricher:
# #     """
# #     Enriches rejected job postings with company and careers-page
# #     information.

# #     Company careers searching is delegated to CompanyCareersSource.
# #     """

# #     def __init__(self, careers_source):

# #         self.careers_source = careers_source

# #     # ---------------------------------------------------------
# #     # Main enrichment method
# #     # ---------------------------------------------------------

# #     def enrich(self, rejected_jobs):
# #         """
# #         rejected_jobs is expected to contain:

# #             [
# #                 (job, rejection_reason),
# #                 ...
# #             ]

# #         The job objects are updated in place and the same list
# #         is returned.
# #         """

# #         for job, rejection_reason in rejected_jobs:
# #             # -------------------------------------------------
# #             # Preserve rejection reason
# #             # -------------------------------------------------

# #             job.rejection_reason = (
# #                 rejection_reason
# #             )

# #             # -------------------------------------------------
# #             # Extract company name
# #             # -------------------------------------------------

# #             company_name = (
# #                 self.extract_company_name(job)
# #             )

# #             job.extracted_company_name = (
# #                 company_name
# #             )

# #             # -------------------------------------------------
# #             # No company name
# #             # -------------------------------------------------

# #             if not company_name:

# #                 job.company_careers_url = None

# #                 job.company_careers_url_valid = (
# #                     False
# #                 )

# #                 # print(
# #                 #     "  Company name could not be extracted"
# #                 # )

# #                 continue

# #             # -------------------------------------------------
# #             # Find company's careers page
# #             #
# #             # CompanyCareersSource performs the actual search.
# #             # -------------------------------------------------

# #             careers_url = (
# #                 self.careers_source.find_careers_page(
# #                     company_name
# #                 )
# #             )

# #             job.company_careers_url = (
# #                 careers_url
# #             )

# #             # -------------------------------------------------
# #             # Record whether a valid URL was found
# #             # -------------------------------------------------

# #             job.company_careers_url_valid = (
# #                 careers_url is not None
# #             )

# #             # -------------------------------------------------
# #             # Debug output
# #             # -------------------------------------------------

# #             # print(
# #             #     f"  Company: "
# #             #     f"{company_name}"
# #             # )

# #             # print(
# #             #     f"  Careers URL: "
# #             #     f"{job.company_careers_url}"
# #             # )

# #             # print(
# #             #     f"  Careers URL: "
# #             #     f"{job.company_careers_url}"
# #             # )



# #         return rejected_jobs

# #     # ---------------------------------------------------------
# #     # Extract company name
# #     # ---------------------------------------------------------

# #     def extract_company_name(self, job):
# #         """
# #         Extract the company name from the job object.

# #         Prefer the job's company field. Fall back to company_name
# #         if the source uses that attribute.

# #         The company name is cleaned of common corporate suffixes.
# #         """

# #         company = getattr(
# #             job,
# #             "company",
# #             None
# #         )

# #         if not company:

# #             company = getattr(
# #                 job,
# #                 "company_name",
# #                 None
# #             )

# #         if not company:

# #             return None

# #         company = str(
# #             company
# #         ).strip()

# #         if not company:

# #             return None

# #         # -----------------------------------------------------
# #         # Remove common corporate suffixes
# #         # -----------------------------------------------------

# #         company = re.sub(
# #             r"\s*,?\s*"
# #             r"(Inc\.?|"
# #             r"LLC|"
# #             r"Ltd\.?|"
# #             r"Limited|"
# #             r"Corporation|"
# #             r"Corp\.?|"
# #             r"Company|"
# #             r"Co\.?)$",
# #             "",
# #             company,
# #             flags=re.IGNORECASE
# #         )

# #         return company.strip()

