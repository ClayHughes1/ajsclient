import pandas as pd


def jobs_to_dataframe(jobs):

    rows = []

    for job in jobs:

        posting_date = getattr(
            job,
            "posting_date",
            None
        )

        # ---------------------------------------------------------
        # Preserve missing posting dates as the literal string
        # "None" so Excel does not convert them into blank cells.
        # ---------------------------------------------------------

        if posting_date is None:
            posting_date = "None"

        rows.append({

            "Company": job.company,

            "Title": job.title,

            "Location": job.location,

            "Posting Date": posting_date,

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
                getattr(
                    job,
                    "posting_url",
                    ""
                )
            )
        })

    return pd.DataFrame(rows)
