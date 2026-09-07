import re


class RejectedPostingEnricher:
    """
    Enriches rejected job postings with company and careers-page
    information.

    Company careers searching is delegated to CompanyCareersSource.
    """

    def __init__(self, careers_source):

        self.careers_source = careers_source

    # ---------------------------------------------------------
    # Main enrichment method
    # ---------------------------------------------------------

    def enrich(self, rejected_jobs):
        """
        rejected_jobs is expected to contain:

            [
                (job, rejection_reason),
                ...
            ]

        The job objects are updated in place and the same list
        is returned.
        """

        for job, rejection_reason in rejected_jobs:

            # print(
            #     f"Enriching rejected posting: "
            #     f"{job.company} - {job.title}"
            # )

            # -------------------------------------------------
            # Preserve rejection reason
            # -------------------------------------------------

            job.rejection_reason = (
                rejection_reason
            )

            # -------------------------------------------------
            # Extract company name
            # -------------------------------------------------

            company_name = (
                self.extract_company_name(job)
            )

            job.extracted_company_name = (
                company_name
            )

            # -------------------------------------------------
            # No company name
            # -------------------------------------------------

            if not company_name:

                job.company_careers_url = None

                job.company_careers_url_valid = (
                    False
                )

                # print(
                #     "  Company name could not be extracted"
                # )

                continue

            # -------------------------------------------------
            # Find company's careers page
            #
            # CompanyCareersSource performs the actual search.
            # -------------------------------------------------

            careers_url = (
                self.careers_source.find_careers_page(
                    company_name
                )
            )

            job.company_careers_url = (
                careers_url
            )

            # -------------------------------------------------
            # Record whether a valid URL was found
            # -------------------------------------------------

            job.company_careers_url_valid = (
                careers_url is not None
            )

            # -------------------------------------------------
            # Debug output
            # -------------------------------------------------

            # print(
            #     f"  Company: "
            #     f"{company_name}"
            # )

            # print(
            #     f"  Careers URL: "
            #     f"{job.company_careers_url}"
            # )

            # print(
            #     f"  Careers URL valid: "
            #     f"{job.company_careers_url_valid}"
            # )

        return rejected_jobs

    # ---------------------------------------------------------
    # Extract company name
    # ---------------------------------------------------------

    def extract_company_name(self, job):
        """
        Extract the company name from the job object.

        Prefer the job's company field. Fall back to company_name
        if the source uses that attribute.

        The company name is cleaned of common corporate suffixes.
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
        # Remove common corporate suffixes
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


# class RejectedPostingEnricher:

#     def __init__(self, careers_source):

#         self.careers_source = careers_source

#     # ---------------------------------------------------------
#     # Main enrichment method
#     # ---------------------------------------------------------

#     def enrich(self, rejected_jobs):

#         for job, rejection_reason in rejected_jobs:

#             print(
#                 f"Enriching rejected posting: "
#                 f"{job.company} - {job.title}"
#             )

#             # -------------------------------------------------
#             # Preserve original rejection reason.
#             # -------------------------------------------------

#             job.rejection_reason = (
#                 rejection_reason
#             )

#             # -------------------------------------------------
#             # Extract company name.
#             # -------------------------------------------------

#             company_name = (
#                 self.extract_company_name(job)
#             )

#             job.extracted_company_name = (
#                 company_name
#             )

#             # -------------------------------------------------
#             # No company name.
#             # -------------------------------------------------

#             if not company_name:

#                 job.company_careers_search_url = (
#                     None
#                 )

#                 job.company_careers_url = (
#                     None
#                 )

#                 job.company_careers_url_valid = (
#                     False
#                 )

#                 print(
#                     "  Company: None"
#                 )

#                 print(
#                     "  Careers URL: None"
#                 )

#                 print(
#                     "  Careers URL valid: False"
#                 )

#                 continue

#             # -------------------------------------------------
#             # Build search URL for reporting.
#             # -------------------------------------------------

#             search_url = (
#                 self.build_careers_search_url(
#                     company_name
#                 )
#             )

#             job.company_careers_search_url = (
#                 search_url
#             )

#             # -------------------------------------------------
#             # Ask CompanyCareersSource to find the page.
#             #
#             # CompanyCareersSource handles caching, so multiple
#             # rejected jobs for the same company only cause one
#             # actual web search.
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
#             # Validate URL.
#             # -------------------------------------------------

#             if careers_url:

#                 job.company_careers_url_valid = (
#                     self.careers_source.validate_url(
#                         careers_url
#                     )
#                 )

#             else:

#                 job.company_careers_url_valid = (
#                     False
#                 )

#             # -------------------------------------------------
#             # Debug output.
#             # -------------------------------------------------

#             print(
#                 f"  Company: "
#                 f"{company_name}"
#             )

#             print(
#                 f"  Careers URL: "
#                 f"{job.company_careers_url}"
#             )

#             print(
#                 f"  Careers URL valid: "
#                 f"{job.company_careers_url_valid}"
#             )

#         return rejected_jobs

#     # ---------------------------------------------------------
#     # Extract company name
#     # ---------------------------------------------------------

#     def extract_company_name(self, job):

#         company = getattr(
#             job,
#             "company",
#             None
#         )

#         if company:

#             return self.clean_company_name(
#                 company
#             )

#         company = getattr(
#             job,
#             "company_name",
#             None
#         )

#         if company:

#             return self.clean_company_name(
#                 company
#             )

#         # -----------------------------------------------------
#         # Last-resort extraction from title.
#         # -----------------------------------------------------

#         title = getattr(
#             job,
#             "title",
#             ""
#         )

#         for separator in (
#             " – ",
#             " — ",
#             " - "
#         ):

#             if separator in title:

#                 company = (
#                     title
#                     .split(
#                         separator,
#                         1
#                     )[0]
#                     .strip()
#                 )

#                 return self.clean_company_name(
#                     company
#                 )

#         return None

#     # ---------------------------------------------------------
#     # Clean company name
#     # ---------------------------------------------------------

#     def clean_company_name(self, company_name):

#         if not company_name:

#             return None

#         company_name = str(
#             company_name
#         ).strip()

#         # Remove common corporate suffixes.
#         company_name = re.sub(
#             r"\s*,?\s*"
#             r"(Inc\.?|LLC|Ltd\.?|"
#             r"Corporation|Corp\.?|"
#             r"Company|Co\.?)$",
#             "",
#             company_name,
#             flags=re.IGNORECASE
#         )

#         return company_name.strip()

#     # ---------------------------------------------------------
#     # Build search URL
#     # ---------------------------------------------------------

#     def build_careers_search_url(
#         self,
#         company_name
#     ):

#         from urllib.parse import quote

#         query = quote(
#             f"{company_name} careers"
#         )

#         return (
#             "https://html.duckduckgo.com/html/?q="
#             + query
#         )
