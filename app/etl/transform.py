import pandas as pd


def jobs_to_dataframe(jobs):

    rows = []

    for job in jobs:

        rows.append({

            "Company": job.company,

            "Title": job.title,

            "Location": job.location,

            "Posting Date": job.posting_date,

            "Salary": getattr(
                job,
                "salary",
                None
            ),

            "Technology Score": getattr(
                job,
                "score",
                0
            ),

            "Technology Match %": getattr(
                job,
                "technology_percentage",
                0
            ),

            "Matched Technologies": ", ".join(
                getattr(
                    job,
                    "matched_technologies",
                    []
                )
            ),

            "Description": job.description,

            "URL": getattr(
                job,
                "url",
                ""
            )
        })

    return pd.DataFrame(rows)