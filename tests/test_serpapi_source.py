from app.sources.serpapi_source import SerpApiSource

serpapi = SerpApiSource()


test_jobs = serpapi.search(
    query=".NET Developer"
)

print(f"\nSerpApi test returned {len(test_jobs)} jobs:\n")

for job in test_jobs:
    print(job.company)
    print(job.title)
    print(job.location)
    print(job.posting_date)
    print(job.posting_url)
    print("-" * 60)
