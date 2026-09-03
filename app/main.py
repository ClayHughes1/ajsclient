from app.sources.lever_source import LeverSource
from app.config import load_config, load_companies
from app.validation.job_validator import JobValidator
from app.etl.transform import jobs_to_dataframe
from app.etl.export import export_to_excel
from app.sources.greenhouse_source import GreenhouseSource
# fe97661776c1158ec6fb1f492661ebe9b563f72c68b7c33777004699b6a56e8a

from dotenv import load_dotenv
load_dotenv()

# import os
# api_key = os.getenv("SERPAPI_API_KEY")

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

            # -------------------------------------------------
            # Calculate technology score
            # -------------------------------------------------

            (
                score,
                matched_technologies,
                technology_percentage
            ) = validator.calculate_score(job)

            # -------------------------------------------------
            # Attach calculated values to job
            # -------------------------------------------------

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

    print(f"Jobs found: {len(jobs)}")

    print(
        f"Jobs accepted: "
        f"{len(accepted_jobs)}"
    )

    print(
        f"Jobs rejected: "
        f"{len(rejected_jobs)}"
    )

    # ---------------------------------------------------------
    # Display rejected jobs
    # ---------------------------------------------------------

    for job, reason in rejected_jobs:

        print(
            f"REJECTED: {job.company} - "
            f"{job.title} - {reason}"
        )

    # ---------------------------------------------------------
    # Convert accepted jobs to DataFrame
    # ---------------------------------------------------------

    dataframe = jobs_to_dataframe(
        accepted_jobs
    )

    # ---------------------------------------------------------
    # Export to Excel
    # ---------------------------------------------------------

    output_file = export_to_excel(
        dataframe
    )

    print(
        f"Excel report created: "
        f"{output_file}"
    )

    print("ajsclient complete.")


if __name__ == "__main__":
    main()