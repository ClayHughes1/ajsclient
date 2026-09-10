from time import sleep

from app.sources.lever_source import LeverSource
from app.config import load_config, load_companies
from app.validation.job_validator import JobValidator
from app.etl.transform import jobs_to_dataframe
from app.etl.export import (
    export_to_excel,
    export_rejected_to_excel
)
# from utils.career_pages_storage import (
#     load_career_pages,
#     get_distinct_company_names,
#     filter_rejected_jobs_by_company
# )

from app.sources.greenhouse_source import GreenhouseSource
from app.sources.serpapi_source import SerpApiSource
from app.sources.jobspy_source import JobSpySource
from app.sources.ashby_source import AshbySource
from app.sources.usajobs_source import USAJobsSource

from dotenv import load_dotenv
from app.sources.workday_source import WorkdaySource
from app.sources.company_careers_source import CompanyCareersSource
from app.sources.direct_company_source import RejectedPostingEnricher
from datetime import datetime
import json
import os
from app.utils.career_pages_storage import (
    load_career_pages,
    save_career_pages
)
from app.career_scraper.generic_scraper import GenericCareerScraper


load_dotenv()


def main():

    print(
        f"Starting ajsclient... "
        f"Start time: {datetime.now().strftime('%Y-%m-%d %I:%M:%S %p')}"
    )

    # ---------------------------------------------------------
    # Load configuration
    # ---------------------------------------------------------

    config = load_config()
    companies = load_companies()

    jobs = []

    # ---------------------------------------------------------
    # Search Greenhouse companies
    # ---------------------------------------------------------
    print("Starting Greenhouse job posting search.\n");
    for company in companies.get("greenhouse", []):

        source = GreenhouseSource(
            company_name=company["name"],
            board_token=company["board_token"],
            posting_age_days=config["posting_age_days"]
        )

        jobs.extend(source.search())

    # ---------------------------------------------------------
    # Search Lever companies
    # ---------------------------------------------------------
    # print("Starting Lever job posting search.\n");

    # for company in companies.get("lever", []):

    #     source = LeverSource(
    #         company_name=company["name"],
    #         company_token=company["company_token"],
    #         posting_age_days=config["posting_age_days"]
    #     )

    #     jobs.extend(source.search())

    # ---------------------------------------------------------
    # Search SerpApi
    # ---------------------------------------------------------
    #ONly get 250 requests per month. 
    #print("Starting SerpApi job posting search.\n");

    # serpapi = SerpApiSource()

    # search_terms = config.get(
    #     "search_terms",
    #     []
    # )

    # for search_term in search_terms:

    #     serpapi_jobs = serpapi.search(
    #         query=search_term
    #     )

    #     jobs.extend(serpapi_jobs)

    # ---------------------------------------------------------
    # Search JobSpy
    
    # JobSpy searches multiple job boards.
    
    # The search is restricted to jobs posted during the
    # previous 24 hours.
    
    # A pause is used between search terms so LinkedIn does
    # not receive another request immediately.
    # ---------------------------------------------------------
    # print("Starting JObSpy job posting search.\n");

    # search_terms = config.get(
    #     "search_terms",
    #     []
    # )

    # jobspy = JobSpySource(
    #     location="United States",
    #     sites=[
    #         "indeed",
    #         "linkedin",
    #     ],
    #     posting_age_days=1,
    #     results_wanted=25,
    # )

    # jobspy_wait_seconds = 10

    # for index, search_term in enumerate(search_terms):

    #     print(
    #         f"JobSpy search "
    #         f"{index + 1}/{len(search_terms)}: "
    #         f"{search_term}"
    #     )

    #     jobspy_jobs = jobspy.search(
    #         search_term=search_term
    #     )

    #     jobs.extend(jobspy_jobs)

    # # Do not wait after the final search.
    # if index < len(search_terms) - 1:

    #     print(
    #         f"Waiting "
    #         f"{jobspy_wait_seconds} seconds "
    #         f"before next JobSpy search..."
    #     )

    #     sleep(jobspy_wait_seconds)

    # ---------------------------------------------------------
    # Search Workday companies
    # ---------------------------------------------------------
    # print("Starting Workday job posting search.\n");

    # search_terms = config.get(
    #     "search_terms",
    #     []
    # )

    # workday_wait_seconds = 5

    # for company in companies.get("workday", []):

    #     company_name = company["name"]

    #     try:

    #         source = WorkdaySource(
    #             company_name=company_name,
    #             base_url=company["base_url"],
    #             posting_age_days=config["posting_age_days"]
    #         )

    #     except ValueError as error:

    #         print(
    #             f"Skipping Workday company "
    #             f"{company_name}: {error}"
    #         )

    #         continue

    #     try:

    #         # jobs.extend(
    #         #     source.search()
    #         # )

    #         jobs.extend(
    #             source.search(
    #                 search_terms=search_terms
    #             )
    #         )


    #     except Exception as error:

    #         print(
    #             f"Workday search failed for "
    #             f"{company_name}: {error}"
    #         )

    #         continue

    # ---------------------------------------------------------
    # Search Ashby companies
    # ---------------------------------------------------------
    # print("Starting Ashby job posting search.\n");

    # for company in companies.get("ashby", []):

    #     company_name = company["name"]

    #     try:

    #         source = AshbySource(
    #             company_name=company_name,
    #             job_board=company["job_board"],
    #             posting_age_days=config["posting_age_days"],
    #             request_delay_seconds=10
    #         )

    #     except ValueError as error:

    #         print(
    #             f"Skipping Ashby company "
    #             f"{company_name}: {error}"
    #         )

    #         continue

    #     try:

    #         jobs.extend(
    #             source.search()
    #         )

    #     except Exception as error:

    #         print(
    #             f"Ashby search failed for "
    #             f"{company_name}: {error}"
    #         )

    #         continue

    # ---------------------------------------------------------
    # Search USAJOBS
    # ---------------------------------------------------------
    print("Starting USAJOBS job posting search.\n");

    try:

        source = USAJobsSource(
            posting_age_days=config[
                "posting_age_days"
            ]
        )

        jobs.extend(
            source.search(
                search_terms=config.get(
                    "search_terms",
                    []
                ),
                location=config[
                    "location"
                ][
                    "accepted_locations"
                ],
                radius_miles=config[
                    "location"
                ][
                    "radius_miles"
                ]
            )
        )
    
    except Exception as error:

        print(
            f"USAJOBS search failed: {error}"
        )

    # ---------------------------------------------------------
    # Company Scraper 
    # ---------------------------------------------------------
    # print("Starting career page scraping...")

    # loader = load_career_pages()
    # career_pages = loader.load()

    # scraper = CareerScraper()

    # for career_page in career_pages:
    #     company = career_page["company"]
    #     url = career_page["url"]

    #     try:
    #         jobs = scraper.scrape(company, url)

    #         print(
    #             f"{company}: {len(jobs)} jobs found"
    #         )

    #     except Exception as exc:
    #         print(
    #             f"ERROR scraping {company}: {exc}"
    #         )

    # print("Career page scraping complete.")

    # ---------------------------------------------------------
    # Create validator
    # ---------------------------------------------------------

    validator = JobValidator(config)

    accepted_jobs = []
    rejected_jobs = []

    # ---------------------------------------------------------
    # Validate jobs
    # ---------------------------------------------------------

    for job in jobs:

        valid, reason = validator.validate(job)

        if valid:

            (
                score,
                matched_technologies,
                technology_percentage
            ) = validator.calculate_score(job)

            job.score = score

            job.matched_technologies = (
                matched_technologies
            )

            job.technology_percentage = (
                technology_percentage
            )

            accepted_jobs.append(job)

        else:

            rejected_jobs.append(
                (job, reason)
            )

    # ---------------------------------------------------------
    # Create rejected posting enricher
    # ---------------------------------------------------------

    print(
        "Starting rejected posting enrichment.\n"
    )

    # ---------------------------------------------------------
    # Load existing career-page results.
    #
    # This creates career_pages.json if it does not exist.
    # ---------------------------------------------------------

    career_pages_data = load_career_pages()

    # ---------------------------------------------------------
    # Build a case-insensitive set of company names that
    # already have a validated career page stored in
    # career_pages.json.
    #
    # IMPORTANT:
    #
    # Only the company names are placed in this set.
    # The URLs remain in career_pages_data.
    # ---------------------------------------------------------

    existing_companies = career_pages_data.get(
        "companies",
        []
    )

    existing_company_names = set()

    for company in existing_companies:

        if not isinstance(company, dict):
            continue

        company_name = company.get(
            "companyName"
        )

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
    # Get rejected jobs that belong to companies that do NOT
    # already exist in career_pages.json.
    #
    # These are the ONLY jobs that need career-page discovery.
    # ---------------------------------------------------------

    new_company_rejected_jobs = []

    seen_new_companies = set()

    for job, reason in rejected_jobs:

        company_name = getattr(
            job,
            "company",
            None
        )

        if not company_name:
            continue

        company_name = str(
            company_name
        ).strip()

        if not company_name:
            continue

        company_key = company_name.casefold()

        # -----------------------------------------------------
        # Company already has a validated career page.
        #
        # Do NOT send this company through
        # CompanyCareersSource.
        # -----------------------------------------------------

        if company_key in existing_company_names:
            continue

        # -----------------------------------------------------
        # Prevent processing the same NEW company more than
        # once during this run.
        # -----------------------------------------------------

        if company_key in seen_new_companies:
            continue

        seen_new_companies.add(
            company_key
        )

        new_company_rejected_jobs.append(
            (job, reason)
        )

    # ---------------------------------------------------------
    # Debug information.
    # ---------------------------------------------------------

    print(
        f"    Rejected postings: "
        f"{len(rejected_jobs)}"
    )

    print(
        f"    Companies already in "
        f"career_pages.json: "
        f"{len(existing_company_names)}"
    )

    print(
        f"    New companies requiring "
        f"career-page discovery: "
        f"{len(new_company_rejected_jobs)}"
    )

    # ---------------------------------------------------------
    # Create career source.
    # ---------------------------------------------------------

    careers_source = CompanyCareersSource()

    rejected_enricher = RejectedPostingEnricher(
        careers_source=careers_source
    )

    # ---------------------------------------------------------
    # ONLY enrich jobs belonging to companies that do not
    # already exist in career_pages.json.
    # ---------------------------------------------------------

    rejected_enricher.enrich(
        new_company_rejected_jobs
    )

    # ---------------------------------------------------------
    # Add newly discovered career pages to career_pages.json.
    # ---------------------------------------------------------

    # ---------------------------------------------------------
    # Track career pages discovered during this run.
    # ---------------------------------------------------------

    new_career_pages = []

    for job, rejection_reason in new_company_rejected_jobs:

        company_name = getattr(
            job,
            "extracted_company_name",
            None
        )

        career_pages = getattr(
            job,
            "company_careers_url",
            None
        )

        if not company_name:
            continue

        if not career_pages:
            continue

        # -------------------------------------------------
        # company_careers_url is the validated career URL
        # returned by RejectedPostingEnricher.
        # -------------------------------------------------

        discovered_company_name = str(
            company_name
        ).strip()

        career_page_url = str(
            career_pages
        ).strip()

        if not discovered_company_name:
            continue

        if not career_page_url:
            continue

        company_key = (
            discovered_company_name
            .casefold()
        )

        # -------------------------------------------------
        # Company already exists in career_pages.json.
        # -------------------------------------------------

        if company_key in existing_company_names:
            print(
                f"Already exists: "
                f"{discovered_company_name}"
            )
            continue

        # -------------------------------------------------
        # New company.
        # -------------------------------------------------

        new_career_page = {
            "companyName": discovered_company_name,
            "careerpageurl": career_page_url
        }

        # -------------------------------------------------
        # Add directly to the data that will be saved.
        # -------------------------------------------------

        career_pages_data.setdefault(
            "companies",
            []
        ).append(
            new_career_page
        )

        # -------------------------------------------------
        # Track new records discovered during this run.
        # -------------------------------------------------

        new_career_pages.append(
            new_career_page
        )

        # -------------------------------------------------
        # Prevent duplicate additions during this run.
        # -------------------------------------------------

        existing_company_names.add(
            company_key
        )

    # ---------------------------------------------------------
    # Save updated career-page data.
    # ---------------------------------------------------------

    print(f"Saving new career pages - new career page length; {len(new_career_pages)}")

    if new_career_pages:

        print(
            f"New career pages discovered: "
            f"{len(new_career_pages)}"
        )

        for company in new_career_pages:

            print(
                f"Company: {company['companyName']} | "
                f"URL: {company['careerpageurl']}"
            )

    else:

        print("No new career pages discovered.")


    save_career_pages(
        career_pages_data
    )


    #         new_career_page = {
    #             "companyName": discovered_company_name,
    #             "careerpageurl": career_page_url
    #         }

    #         new_career_pages.append(
    #             new_career_page
    #         )

    #         # -------------------------------------------------
    #         # Prevent this same company from being added again
    #         # during the current run.
    #         # -------------------------------------------------

    #         existing_company_names.add(
    #             company_key
    #         )


    # # ---------------------------------------------------------
    # # Add only the newly discovered career pages to the
    # # existing career-page data.
    # # ---------------------------------------------------------

    # if new_career_pages:

    #     career_pages_data.setdefault(
    #         "companies",
    #         []
    #     ).extend(
    #         new_career_pages
    #     )


    # # ---------------------------------------------------------
    # # Save updated career-page data.
    # # ---------------------------------------------------------

    # print("Saving new career pages")

    # if new_career_pages:

    #     print(
    #         f"New career pages discovered: "
    #         f"{len(new_career_pages)}"
    #     )

    #     for company in new_career_pages:
    #         print(
    #             f"Company: {company['companyName']} | "
    #             f"URL: {company['careerpageurl']}"
    #         )

    # else:

    #     print("No new career pages discovered.")


    # save_career_pages(
    #     career_pages_data
    # )


#     for job, rejection_reason in new_company_rejected_jobs:

#         company_name = getattr(
#             job,
#             "extracted_company_name",
#             None
#         )

#         career_pages = getattr(
#             job,
#             "company_careers_url",
#             None
#         )

#         print(f"Company name: {company_name} - URL: {career_pages}")

#         if not company_name:
#             continue

#         if not career_pages:
#             continue

#         # company_careers_url contains a list of:
#         #
#         # {
#         #     "companyName": "...",
#         #     "careerpageurl": "..."
#         # }
#         #
#         if not isinstance(career_pages, list):
#             continue

#         for career_page in career_pages:

#             if not isinstance(career_page, dict):
#                 continue

#             discovered_company_name = career_page.get(
#                 "companyName"
#             )

#             career_page_url = career_page.get(
#                 "careerpageurl"
#             )

#             if not discovered_company_name:
#                 continue

#             if not career_page_url:
#                 continue

#             company_key = str(
#                 discovered_company_name
#             ).strip().casefold()

#             # -------------------------------------------------
#             # Company already exists in career_pages.json.
#             # -------------------------------------------------

#             if company_key in existing_company_names:
#                 continue

#             # -------------------------------------------------
#             # New company -- add it to the JSON data.
#             # -------------------------------------------------

#             career_pages_data.setdefault(
#                 "companies",
#                 []
#             ).append(
#                 {
#                     "companyName": str(
#                         discovered_company_name
#                     ).strip(),
#                     "careerpageurl": str(
#                         career_page_url
#                     ).strip()
#                 }
#             )

#             # -------------------------------------------------
#             # Prevent duplicate additions during this run.
#             # -------------------------------------------------

#             existing_company_names.add(
#                 company_key
#             )

#     # ---------------------------------------------------------
#     # Save updated career-page data.
#     # ---------------------------------------------------------
#     print("Saving new carrer pages")

#     for company in new_company_rejected_jobs:
#         print(f"{company}\n\n\n\n");

#         # print(f"COmpany:   {company}\n\n\n\n");
#         # print(
#         #     f"Company: {company.get('companyName')} | "
#         #     f"URL: {company.get('careerpageurl')}"
#         # )
# # .get("companies", [])
#     save_career_pages(
#         career_pages_data
#     )


    # # ---------------------------------------------------------
    # # Create rejected posting enricher
    # # ---------------------------------------------------------

    # print(
    #     "Starting rejected posting enrichment.\n"
    # )

    # # ---------------------------------------------------------
    # # Load existing career-page results
    # #
    # # This creates career_pages.json if it does not exist.
    # # ---------------------------------------------------------

    # career_pages_data = load_career_pages()

    # # ---------------------------------------------------------
    # # Get distinct company names from rejected postings
    # #
    # # rejected_jobs contains:
    # #
    # #     (job, rejection_reason)
    # #
    # # so the actual job is the first item in each tuple.
    # # ---------------------------------------------------------

    # rejected_company_names = []

    # seen_companies = set()

    # for job, reason in rejected_jobs:
    #     company_name = getattr(
    #         job,
    #         "company",
    #         None
    #     )

    #     if not company_name:
    #         continue

    #     company_name = str(
    #         company_name
    #     ).strip()

    #     if not company_name:
    #         continue

    #     company_key = company_name.casefold()

    #     if company_key in seen_companies:
    #         continue

    #     seen_companies.add(
    #         company_key
    #     )

    #     rejected_company_names.append(
    #         company_name
    #     )

    # # ---------------------------------------------------------
    # # Create career source
    # # ---------------------------------------------------------

    # careers_source = CompanyCareersSource()
    # existing_company_names = set()

    # rejected_enricher = RejectedPostingEnricher(
    #     careers_source=careers_source
    # )

    # rejected_enricher.enrich(
    #     rejected_jobs
    # )

    # # ---------------------------------------------------------
    # # Add newly discovered career pages to career_pages.json
    # # ---------------------------------------------------------

    # existing_companies = career_pages_data.get(
    #     "companies",
    #     []
    # )

    # # Build a case-insensitive set of company names
    # # already stored in career_pages.json.
    # existing_company_names = set()

    # for company in existing_companies:

    #     if not isinstance(company, dict):
    #         continue

    #     company_name = company.get(
    #         "companyName"
    #     )

    #     if not company_name:
    #         continue

    #     existing_company_names.add(
    #         str(company_name).strip().casefold()
    #     )


    # # ---------------------------------------------------------
    # # Process career pages discovered during enrichment
    # # ---------------------------------------------------------

    # for job, rejection_reason in rejected_jobs:

    #     company_name = getattr(
    #         job,
    #         "extracted_company_name",
    #         None
    #     )

    #     career_pages = getattr(
    #         job,
    #         "company_careers_url",
    #         None
    #     )

    #     if not company_name:
    #         continue

    #     if not career_pages:
    #         continue

    #     # company_careers_url appears to contain a list
    #     # of {companyName, careerpageurl} dictionaries.
    #     if not isinstance(career_pages, list):
    #         continue

    #     for career_page in career_pages:

    #         if not isinstance(career_page, dict):
    #             continue

    #         discovered_company_name = career_page.get(
    #             "companyName"
    #         )

    #         career_page_url = career_page.get(
    #             "careerpageurl"
    #         )

    #         if not discovered_company_name:
    #             continue

    #         if not career_page_url:
    #             continue

    #         company_key = str(
    #             discovered_company_name
    #         ).strip().casefold()

    #         # -------------------------------------------------
    #         # Company already exists in career_pages.json
    #         # -------------------------------------------------

    #         if company_key in existing_company_names:
    #             continue

    #         # -------------------------------------------------
    #         # New company -- add it to the JSON data
    #         # -------------------------------------------------

    #         career_pages_data.setdefault(
    #             "companies",
    #             []
    #         ).append(
    #             {
    #                 "companyName": str(
    #                     discovered_company_name
    #                 ).strip(),
    #                 "careerpageurl": str(
    #                     career_page_url
    #                 ).strip()
    #             }
    #         )

    #         # Prevent duplicate additions during this run.
    #         existing_company_names.add(
    #             company_key
    #         )


    # # ---------------------------------------------------------
    # # Save updated career-pages data
    # # ---------------------------------------------------------

    # save_career_pages(
    #     career_pages_data
    # )


    # ---------------------------------------------------------
    # Console summary
    # ---------------------------------------------------------

    print(
        f"Jobs found: {len(jobs)}"
    )

    print(
        f"Jobs accepted: {len(accepted_jobs)}"
    )

    # ---------------------------------------------------------
    # Convert accepted jobs to DataFrame
    # ---------------------------------------------------------

    dataframe = jobs_to_dataframe(
        accepted_jobs
    )

    # ---------------------------------------------------------
    # Convert rejected jobs to DataFrame
    # ---------------------------------------------------------

    rejected_dataframe = jobs_to_dataframe(
        [job for job, reason in rejected_jobs]
    )

    if not rejected_dataframe.empty:

        rejected_dataframe["rejection_reason"] = [
            reason
            for job, reason in rejected_jobs
        ]

    rejected_dataframe["source"] = [
        job.source
        for job, reason in rejected_jobs
    ]

    print(
        f"Jobs rejected: {len(rejected_jobs)}"
    )

    # ---------------------------------------------------------
    # Export to Excel
    # ---------------------------------------------------------
    if len(dataframe) > 0:
        output_file = export_to_excel(
            dataframe
        )
        print(
            f"Excel report created: {output_file}"
        )



    # ---------------------------------------------------------
    # Export rejected jobs
    # ---------------------------------------------------------
    if len(rejected_dataframe) > 0:
        rejected_output_file = export_rejected_to_excel(
            rejected_dataframe
        )

    print(
        f"Jobs rejected: {len(rejected_jobs)}"
    )

    print(
        f"Rejected jobs report created: "
        f"{rejected_output_file}"
    )

    print("ajsclient complete.")


if __name__ == "__main__":
    main()