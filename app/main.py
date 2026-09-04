from time import sleep

from app.sources.lever_source import LeverSource
from app.config import load_config, load_companies
from app.validation.job_validator import JobValidator
from app.etl.transform import jobs_to_dataframe
from app.etl.export import (
    export_to_excel,
    export_rejected_to_excel
)
from app.sources.greenhouse_source import GreenhouseSource
from app.sources.serpapi_source import SerpApiSource
from app.sources.jobspy_source import JobSpySource

from dotenv import load_dotenv

load_dotenv()


def main():

    print("Starting ajsclient...")

    # ---------------------------------------------------------
    # Load configuration
    # ---------------------------------------------------------

    config = load_config()
    companies = load_companies()

    jobs = []

    # ---------------------------------------------------------
    # Search Greenhouse companies
    # ---------------------------------------------------------

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

    for company in companies.get("lever", []):

        source = LeverSource(
            company_name=company["name"],
            company_token=company["company_token"],
            posting_age_days=config["posting_age_days"]
        )

        jobs.extend(source.search())

    # ---------------------------------------------------------
    # Search SerpApi
    # ---------------------------------------------------------

    serpapi = SerpApiSource()

    search_terms = config.get(
        "search_terms",
        []
    )

    for search_term in search_terms:

        serpapi_jobs = serpapi.search(
            query=search_term
        )

        jobs.extend(serpapi_jobs)

    # ---------------------------------------------------------
    # Search JobSpy
    #
    # JobSpy searches multiple job boards.
    #
    # The search is restricted to jobs posted during the
    # previous 24 hours.
    #
    # A pause is used between search terms so LinkedIn does
    # not receive another request immediately.
    # ---------------------------------------------------------

    jobspy = JobSpySource(
        location="United States",
        sites=[
            "indeed",
            "linkedin",
        ],
        posting_age_days=1,
        results_wanted=25,
    )

    # Seconds to wait before starting the next JobSpy search.
    # This is primarily intended to reduce repeated LinkedIn
    # requests.
    jobspy_wait_seconds = 10

    for index, search_term in enumerate(search_terms):

        print(
            f"JobSpy search "
            f"{index + 1}/{len(search_terms)}: "
            f"{search_term}"
        )

        jobspy_jobs = jobspy.search(
            search_term=search_term
        )

        jobs.extend(jobspy_jobs)

        # Do not wait after the final search.
        if index < len(search_terms) - 1:

            print(
                f"Waiting "
                f"{jobspy_wait_seconds} seconds "
                f"before next JobSpy search..."
            )


            sleep(jobspy_wait_seconds)

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
    #
    # rejected_jobs contains:
    #
    #     (job, rejection_reason)
    # ---------------------------------------------------------

    rejected_dataframe = jobs_to_dataframe(
        [job for job, reason in rejected_jobs]
    )

    if not rejected_dataframe.empty:

        rejected_dataframe["rejection_reason"] = [
            reason
            for job, reason in rejected_jobs
        ]

    # rejected_dataframe["job_description"] = [
    #     job.description
    #     for job, reason in rejected_jobs
    # ]

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

    output_file = export_to_excel(
        dataframe
    )

    print(
        f"Excel report created: {output_file}"
    )

    # ---------------------------------------------------------
    # Export rejected jobs
    # ---------------------------------------------------------

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