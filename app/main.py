from datetime import datetime

from app.config import load_config, load_companies
from app.validation.job_validator import JobValidator
from app.etl.transform import jobs_to_dataframe
from app.etl.export import export_to_excel
from app.sources.greenhouse_source import GreenhouseSource

def main():

    print("Starting ajsclient...")

    config = load_config()
    companies = load_companies()

    jobs = []

    for company in companies.get("greenhouse", []):

        source = GreenhouseSource(
            company_name=company["name"],
            board_token=company["board_token"],
            posting_age_days=config["posting_age_days"]
        )

        # source = GreenhouseSource(
        #     company_name=company["name"],
        #     board_token=company["board_token"]
        # )

        jobs.extend(source.search())

    validator = JobValidator(config)

    accepted_jobs = []
    rejected_jobs = []

    for job in jobs:

        valid, reason = validator.validate(job)

        if valid:
            accepted_jobs.append(job)
        else:
            rejected_jobs.append((job, reason))

    print(f"Jobs found: {len(jobs)}")
    print(f"Jobs accepted: {len(accepted_jobs)}")
    print(f"Jobs rejected: {len(rejected_jobs)}")

    for job, reason in rejected_jobs:
        print(
            f"REJECTED: {job.company} - "
            f"{job.title} - {reason}"
        )

    dataframe = jobs_to_dataframe(accepted_jobs)

    output_file = export_to_excel(dataframe)

    print(f"Excel report created: {output_file}")
    print("ajsclient complete.")


if __name__ == "__main__":
    main()