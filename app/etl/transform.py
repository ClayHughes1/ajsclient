import pandas as pd


def jobs_to_dataframe(jobs) -> pd.DataFrame:

    records = []

    for job in jobs:
        records.append({
            "Company": job.company,
            "Title": job.title,
            "Location": job.location,
            "Posting Date": job.posting_date,
            "Salary": job.salary,
            "Source": job.source,
            "Posting URL": job.posting_url,
            "Description": job.description
        })

    return pd.DataFrame(records)