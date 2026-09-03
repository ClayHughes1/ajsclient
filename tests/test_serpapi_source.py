
import os

import pytest
from dotenv import load_dotenv

from app.sources.serpapi_source import SerpApiSource


load_dotenv()

SERPAPI_API_KEY = os.getenv("SERPAPI_API_KEY")


@pytest.mark.skipif(
    not SERPAPI_API_KEY,
    reason="SERPAPI_API_KEY not configured"
)
def test_serpapi_search():

    serpapi = SerpApiSource()

    jobs = serpapi.search(
        query=".NET Developer"
    )

    assert isinstance(jobs, list)




# from app.sources.serpapi_source import SerpApiSource

# serpapi = SerpApiSource()


# test_jobs = serpapi.search(
#     query=".NET Developer"
# )

# print(f"\nSerpApi test returned {len(test_jobs)} jobs:\n")

# for job in test_jobs:
#     print(job.company)
#     print(job.title)
#     print(job.location)
#     print(job.posting_date)
#     print(job.posting_url)
#     print("-" * 60)
