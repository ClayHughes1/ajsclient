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
from app.sources.built_in_source import BuiltInSource
from app.utils.jobspy_career_validator import (
    JobSpyCareerValidator,
)

import asyncio
import httpx
load_dotenv()


async def main():

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

    search_terms = config.get(
        "search_terms",
        []
    )

    # ---------------------------------------------------------
    # Search Greenhouse companies
    # ---------------------------------------------------------
    print("Starting Greenhouse job posting search.\n")


    # Maximum number of Greenhouse requests allowed to run
    # concurrently.
    #
    # Start with 10. If Greenhouse handles this comfortably,
    # you can experiment with 15 or 20.
    semaphore = asyncio.Semaphore(10)


    async def search_greenhouse_company(company):
        """
        Search one Greenhouse company.

        GreenhouseSource.search() is synchronous because it uses
        requests.get(), so asyncio.to_thread() moves the blocking
        HTTP request and processing onto a worker thread.
        """

        async with semaphore:

            # print(
            #     f"Searching Greenhouse: "
            #     f"{company['name']} "
            #     f"({company['board_token']})"
            # )

            try:

                source = GreenhouseSource(
                    company_name=company["name"],
                    board_token=company["board_token"],
                    posting_age_days=config["posting_age_days"],
                )

                # Run the synchronous search() in a worker thread.
                greenhouse_jobs = await asyncio.to_thread(
                    source.search
                )

                # print(
                #     f"  {company['name']}: "
                #     f"{len(greenhouse_jobs)} jobs found"
                # )

                return greenhouse_jobs

            except Exception as exc:

                print(
                    f"  ERROR searching Greenhouse company "
                    f"{company['name']}: {exc}"
                )

                # Return an empty list so one failed company
                # does not prevent the other searches from running.
                return []

    greenhouse_results = await asyncio.gather(
        *(
            search_greenhouse_company(company)
            for company in companies.get("greenhouse", [])
        )
    )

    for greenhouse_jobs in greenhouse_results:
        jobs.extend(greenhouse_jobs)
    
    
    
    # print("Starting Greenhouse job posting search.\n")

    # for company in companies.get("greenhouse", []):

    #     print(
    #         f"Searching Greenhouse: "
    #         f"{company['name']} "
    #         f"({company['board_token']})"
    #     )

    #     try:

    #         source = GreenhouseSource(
    #             company_name=company["name"],
    #             board_token=company["board_token"],
    #             posting_age_days=config["posting_age_days"],
    #         )

    #         greenhouse_jobs = source.search()

    #         jobs.extend(greenhouse_jobs)

    #         print(
    #             f"  {company['name']}: "
    #             f"{len(greenhouse_jobs)} jobs found"
    #         )

    #     except Exception as exc:

    #         print(
    #             f"  ERROR searching Greenhouse company "
    #             f"{company['name']}: {exc}"
    #         )

    #         # Continue with the next Greenhouse company.
    #         continue

    # ---------------------------------------------------------
    # Search Lever companies
    # ---------------------------------------------------------
    print("Starting Lever job posting search.\n");

    async with httpx.AsyncClient(timeout=30.0) as client:

        async def search_company(company):
            source = LeverSource(
                company_name=company["name"],
                company_token=company["company_token"],
                posting_age_days=config["posting_age_days"],
                client=client,
            )

            return await source.search()

        results = await asyncio.gather(
            *(
                search_company(company)
                for company in companies.get("lever", [])
            )
        )

        for company_jobs in results:
            jobs.extend(company_jobs)


    # for company in companies.get("lever", []):

    #     source = LeverSource(
    #         company_name=company["name"],
    #         company_token=company["company_token"],
    #         posting_age_days=config["posting_age_days"]
    #     )

    #     jobs.extend(await source.search())
        # jobs.extend(source.search())

    # ---------------------------------------------------------
    # Search SerpApi
    # ---------------------------------------------------------
    #ONly get 250 requests per month. 
    # print("Starting SerpApi job posting search.\n");

    # serpapi = SerpApiSource()

    # search_terms = config.get(
    #     "search_terms",
    #     []
    # )
    # tasks = [
    #     serpapi.search(query=search_term)
    #     for search_term in search_terms
    # ]

    # results = await asyncio.gather(*tasks)

    # for serpapi_jobs in results:
    #     jobs.extend(serpapi_jobs)

    # ---------------------------------------------------------
    # Search Workday companies
    # ---------------------------------------------------------
    print("Starting Workday job posting search.\n");

    workday_wait_seconds = 5
    workday_semaphore = asyncio.Semaphore(7)

    async def search_workday_company(company):

        company_name = company["name"]

        try:

            source = WorkdaySource(
                company_name=company_name,
                base_url=company["base_url"],
                posting_age_days=config["posting_age_days"]
            )

        except ValueError as error:

            print(
                f"Skipping Workday company "
                f"{company_name}: {error}"
            )

            return []

        try:

            async with workday_semaphore:

                return await source.search(
                    search_terms=search_terms
                )

        except Exception as error:

            print(
                f"Workday search failed for "
                f"{company_name}: {error}"
            )

            return []


    workday_results = await asyncio.gather(
        *[
            search_workday_company(company)
            for company in companies.get("workday", [])
        ]
    )

    for company_jobs in workday_results:
        jobs.extend(company_jobs)

    # ---------------------------------------------------------
    # Search Ashby companies
    # ---------------------------------------------------------

    print(
        "Starting Ashby job posting search.\n"
    )

    ashby_semaphore = asyncio.Semaphore(7)


    async def search_ashby_company(company):

        company_name = company["name"]

        try:

            source = AshbySource(
                company_name=company_name,
                job_board=company["job_board"],
                posting_age_days=config["posting_age_days"],
                request_delay_seconds=10
            )

        except ValueError as error:

            print(
                f"Skipping Ashby company "
                f"{company_name}: {error}"
            )

            return []

        try:

            async with ashby_semaphore:

                return await source.search()

        except Exception as error:

            print(
                f"Ashby search failed for "
                f"{company_name}: {error}"
            )

            return []

        finally:

            await source.close()


    ashby_results = await asyncio.gather(
        *[
            search_ashby_company(company)
            for company in companies.get("ashby", [])
        ]
    )

    for company_jobs in ashby_results:
        jobs.extend(
            company_jobs
        )


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
    # Search JobSpy
    # ---------------------------------------------------------

    print(
        "Starting JobSpy job posting search.\n"
    )

    jobspy = JobSpySource(
        location="United States",
        sites=[
            "indeed",
            "linkedin",
        ],
        posting_age_days=1,
        results_wanted=50,
    )

    jobspy_jobs = await jobspy.search_all(
        search_terms=search_terms,
        max_concurrency=10,
    )
    jobs.extend(jobspy_jobs)

    print(
        f"JobSpy total jobs found: {len(jobspy_jobs)}"
    )

    # ------------------------------------------------------------
    # Create Built In source ONCE.
    # ------------------------------------------------------------
    print(
        "Starting Built-=n job posting search.\n"
    )

    location = None

    built_in_source = BuiltInSource(
        posting_age_days=2,

        # Global request rate.
        # This applies across all concurrent workers.
        requests_per_second=4.0,

        max_workers=8,

        max_retries=1,
        results_per_page=20,
        max_pages=50,
    )

    # ------------------------------------------------------------
    # Search Built In ONCE.
    #
    # search_terms=None is intentional.
    #
    # Built In is crawled broadly and the application's own
    # filtering happens afterward.
    # ------------------------------------------------------------

    built_in_jobs = await asyncio.to_thread(
        built_in_source.search,
        search_terms=None,
        location=location,
    )

    jobs.extend(built_in_jobs)

    print(
        f"Built In returned "
        f"{len(built_in_jobs)} jobs."
    )


    # ------------------------------------------------------------
    # Apply your 108 filters LOCALLY.
    # ------------------------------------------------------------

    # Your existing filtering logic should go here.
    #
    # filtered_jobs = apply_filters(
    #     built_in_jobs,
    #     filters
    # )

    # filtered_jobs = built_in_jobs

    # print(
    #     f"After local filtering: "
    #     f"{len(filtered_jobs)} jobs"
    # )

    # ---------------------------------------------------------
    # Company Scraper 
    # ---------------------------------------------------------
    print("Starting career page scraping...")
    career_pages = load_career_pages()
    scraper = GenericCareerScraper()


    all_jobs = []

    for career_page in career_pages["companies"]:
        company = career_page["companyName"]
        url = career_page["careerpageurl"]

        try:
            company_jobs = await scraper.scrape(company, url)

            jobs.extend(company_jobs)

            print(
                f"{company}: {len(company_jobs)} jobs found"
            )

        except Exception as exc:
            print(
                f"ERROR scraping {company}: {exc}"
            )

        # for company_job in company_job_results:
        #     jobs.extend(greenhouse_jobs)
        

    # print(
    #     f"Career page scraping complete. "
    #     f"Total jobs: {len(all_jobs)}"
    # )
   
    # print("Starting career page scraping...")

    # career_pages = load_career_pages()
    # scraper = GenericCareerScraper()

    # for career_page in career_pages["companies"]:
    #     company = career_page["companyName"]
    #     url = career_page["careerpageurl"]

    #     try:
            
    #         jobs = scraper.scrape(company, url)
    #         print(f"Jobs found for company {company}:\n {jobs}\n ")
    #         print(
    #             f"{company}: {len(jobs)} jobs found\n"
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
    # Remove duplicate jobs before validation
    # ---------------------------------------------------------
    #
    # A job is considered a duplicate when it has the same
    # source and Job ID. This prevents the same posting from
    # being written to the approved worksheet multiple times.
    #
    # Keep the first occurrence and discard subsequent copies.
    # ---------------------------------------------------------
    unique_jobs = []
    seen_jobs = set()

    for job in jobs:

        source = (job.source or "").strip().lower()
        job_id = (job.job_id or "").strip().lower()

        company = (
            getattr(job, "company", "") or ""
        ).strip().lower()

        title = (
            getattr(job, "title", "") or ""
        ).strip().lower()

        location = (
            getattr(job, "location", "") or ""
        ).strip().lower()

        posting_date = getattr(
            job,
            "posting_date",
            None
        )

        posting_date_key = (
            str(posting_date).strip().lower()
            if posting_date is not None
            else ""
        )

        url = (
            getattr(job, "url", "") or ""
        ).strip().lower()

        # ---------------------------------------------------------
        # Normalize whitespace so insignificant formatting
        # differences do not prevent duplicate detection.
        # ---------------------------------------------------------

        company = " ".join(company.split())
        title = " ".join(title.split())
        location = " ".join(location.split())
        url = " ".join(url.split())

        # ---------------------------------------------------------
        # Prefer the source + Job ID when a Job ID exists.
        #
        # This is the strongest duplicate identifier because the
        # source itself assigns the ID to the posting.
        # ---------------------------------------------------------

        if job_id:

            duplicate_key = (
                "job_id",
                source,
                job_id
            )

        # ---------------------------------------------------------
        # If Job ID is missing, use the job's identifying attributes.
        #
        # Company + title + location + posting date + URL gives us
        # a much stronger fallback than relying on any single field.
        # ---------------------------------------------------------

        else:

            duplicate_key = (
                "job_attributes",
                source,
                company,
                title,
                location,
                posting_date_key,
                url
            )

        if duplicate_key in seen_jobs:
            continue

        seen_jobs.add(duplicate_key)
        unique_jobs.append(job)

    jobs = unique_jobs

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

            # Reject jobs with a score of 0
            if job.score == 0:
                rejected_jobs.append(
                    (job, "Job score is 0")
                )
            else:
                accepted_jobs.append(job)

            # accepted_jobs.append(job)

        else:
            rejected_jobs.append(
                (job, reason)
            )



    # # ---------------------------------------------------------
    # # Validate jobs
    # # ---------------------------------------------------------

    # for job in jobs:

    #     valid, reason = validator.validate(job)

    #     if valid:

    #         (
    #             score,
    #             matched_technologies,
    #             technology_percentage
    #         ) = validator.calculate_score(job)

    #         job.score = score

    #         job.matched_technologies = (
    #             matched_technologies
    #         )

    #         job.technology_percentage = (
    #             technology_percentage
    #         )

    #         accepted_jobs.append(job)

    #     else:

    #         rejected_jobs.append(
    #             (job, reason)
    #         )

    # ---------------------------------------------------------
    # Create rejected posting enricher
    # ---------------------------------------------------------

    print(
        "Starting rejected posting enrichment.\n"
    )

    # ---------------------------------------------------------
    # Build a case-insensitive set of company names that
    # already have a validated career page stored in
    # career_pages.json.
    #
    # IMPORTANT:
    #
    # Only the normalized company names are placed in this set.
    # The URLs remain in career_pages_data.
    # ---------------------------------------------------------

    career_pages_data = load_career_pages()

    existing_company_names = {
        str(company["companyName"]).strip().casefold()
        for company in career_pages_data.get("companies", [])
        if isinstance(company, dict)
        and company.get("companyName")
    }


    # ---------------------------------------------------------
    # Build a unique collection of rejected companies.
    #
    # Multiple rejected jobs may belong to the same company.
    # There is no reason to process the same company more than
    # once when discovering its career page.
    #
    # The dictionary preserves the first (job, reason) pair
    # associated with each company in case that information
    # is needed later.
    # ---------------------------------------------------------

    rejected_companies = {}

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

        # Keep only the first rejected job for each company.
        rejected_companies.setdefault(
            company_key,
            (job, reason)
        )


    # ---------------------------------------------------------
    # Remove companies that already have a validated career
    # page stored in career_pages.json.
    #
    # Set membership is O(1) on average, so this is very fast.
    # ---------------------------------------------------------

    new_company_rejected_jobs = [
        rejected_companies[company_key]
        for company_key in rejected_companies
        if company_key not in existing_company_names
    ]

#Original
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
    # career_pages_data = load_career_pages()

    # existing_companies = career_pages_data.get(
    #     "companies",
    #     []
    # )

    # existing_company_names = set()

    # for company in existing_companies:

    #     if not isinstance(company, dict):
    #         continue

    #     company_name = company.get(
    #         "companyName"
    #     )

    #     if not company_name:
    #         continue

    #     company_name = str(
    #         company_name
    #     ).strip()

    #     if not company_name:
    #         continue

    #     existing_company_names.add(
    #         company_name.casefold()
    #     )

    # # ---------------------------------------------------------
    # # Get rejected jobs that belong to companies that do NOT
    # # already exist in career_pages.json.
    # #
    # # These are the ONLY jobs that need career-page discovery.
    # # ---------------------------------------------------------

    # new_company_rejected_jobs = []

    # seen_new_companies = set()

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

    #     # -----------------------------------------------------
    #     # Company already has a validated career page.
    #     #
    #     # Do NOT send this company through
    #     # CompanyCareersSource.
    #     # -----------------------------------------------------

    #     if company_key in existing_company_names:
    #         continue

    #     # -----------------------------------------------------
    #     # Prevent processing the same NEW company more than
    #     # once during this run.
    #     # -----------------------------------------------------

    #     if company_key in seen_new_companies:
    #         continue

    #     seen_new_companies.add(
    #         company_key
    #     )

    #     new_company_rejected_jobs.append(
    #         (job, reason)
    #     )

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
    # await rejected_enricher.enrich(
    #     new_company_rejected_jobs
    # )

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
    print(f"Converting accepted jobs to data frame: {len(accepted_jobs)}")
    dataframe = jobs_to_dataframe(
        accepted_jobs
    )

    # ---------------------------------------------------------
    # Convert rejected jobs to DataFrame
    # ---------------------------------------------------------
    print(f"Converting rejected jobs to data frame: {len(rejected_jobs)}")

    rejected_dataframe = jobs_to_dataframe(
        [job for job, reason in rejected_jobs]
    )

    # print(f"Rejected dataFrame length:  {len(rejected_dataframe)}\n\n")

    # if not rejected_dataframe.empty:

    #     rejected_dataframe["rejection_reason"] = [
    #         reason
    #         for job, reason in rejected_jobs
    #     ]

    # rejected_dataframe["source"] = [
    #     job.source
    #     for job, reason in rejected_jobs
    # ]

    print(
        f"Jobs rejected: {len(rejected_jobs)}"
    )

    # ---------------------------------------------------------
    # Export to Excel
    # ---------------------------------------------------------
    print(f"Exporting accepted jobs to excel worksheet")
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
    print("Exporting the rejected records to excel work sheet")
    if len(rejected_dataframe) > 0:
        export_rejected_to_excel(
            rejected_dataframe
        )


    # print(
    #     f"Jobs rejected: {len(rejected_jobs)}"
    # )

    print("ajsclient complete.   "
        f"Finish time: {datetime.now().strftime('%Y-%m-%d %I:%M:%S %p')}"
    )

if __name__ == "__main__":
    asyncio.run(main())

