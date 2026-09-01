from dataclasses import dataclass
from datetime import datetime


@dataclass
class Job:
    company: str
    title: str
    location: str
    posting_url: str
    description: str = ""
    posting_date: datetime | None = None
    salary: str = ""
    source: str = ""