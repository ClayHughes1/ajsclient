from datetime import datetime

from app.models.job import Job
from app.validation.job_validator import JobValidator


def test_rejects_security_clearance():

    config = {
        "excluded_terms": [
            "TS/SCI",
            "Top Secret",
            "Secret clearance"
        ],
        "search_terms": [
            ".NET",
            "C#",
            "Software Engineer"
        ]
    }

    validator = JobValidator(config)

    job = Job(
        company="Test Company",
        title="Software Engineer",
        location="Melbourne, FL",
        posting_url="https://example.com/job",
        description="C# .NET developer. TS/SCI required.",
        posting_date=datetime.now()
    )

    valid, reason = validator.validate(job)

    assert valid is False
    assert "TS/SCI" in reason