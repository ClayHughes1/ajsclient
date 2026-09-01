from datetime import datetime

from app.models.job import Job
from app.validation.job_validator import JobValidator
from app.etl.transform import jobs_to_dataframe
from app.etl.export import export_to_excel


def main():

    print("Starting ajsclient...")

    config = {
        "excluded_terms": [
            "TS/SCI",
            "Top Secret",
            "Secret clearance",
            "sponsorship required",
            "visa sponsorship"
        ]
    }

    jobs = [
        Job(
            company="Example Company",
            title="Senior .NET Developer",
            location="Melbourne, FL",
            posting_url="https://example.com/job/1",
            description="C# .NET SQL Server REST API",
            posting_date=datetime.now(),
            salary="$135,000 - $145,000",
            source="Test"
        ),
        Job(
            company="Example Defense Company",
            title="Software Engineer",
            location="Melbourne, FL",
            posting_url="https://example.com/job/2",
            description="C# .NET Active TS/SCI clearance required",
            posting_date=datetime.now(),
            salary="$140,000",
            source="Test"
        )
    ]

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