import pytest

from app.sources.ashby_source import AshbySource


def test_ashby_search():

    ashby = AshbySource(
        company_name="Acme",
        job_board="acme",
        posting_age_days=2,
        request_delay_seconds=0
    )

    jobs = ashby.search()

    assert isinstance(
        jobs,
        list
    )

    print(
        f"\nAshby test returned "
        f"{len(jobs)} jobs:\n"
    )

    for job in jobs:

        print(
            "-" * 60
        )

        print(
            f"Company: "
            f"{job.company}"
        )

        print(
            f"Title: "
            f"{job.title}"
        )

        print(
            f"Location: "
            f"{job.location}"
        )

        print(
            f"Posting Date: "
            f"{job.posting_date}"
        )

        print(
            f"Salary: "
            f"{job.salary}"
        )

        print(
            f"Posting URL: "
            f"{job.posting_url}"
        )

        print(
            f"Source: "
            f"{job.source}"
        )
