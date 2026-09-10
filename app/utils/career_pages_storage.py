import json
import os


CAREER_PAGES_FILE = "career_pages.json"


def ensure_career_pages_file(
    file_path=CAREER_PAGES_FILE
):
    """
    Ensure the career-pages JSON file exists.

    Creates an empty file with the expected structure if
    the file does not already exist.
    """

    if not os.path.exists(file_path):

        with open(
            file_path,
            "w",
            encoding="utf-8"
        ) as file:

            json.dump(
                {
                    "companies": []
                },
                file,
                indent=4
            )

        print(
            f"Created career pages file: "
            f"{file_path}"
        )


def load_career_pages(
    file_path=CAREER_PAGES_FILE
):
    """
    Load existing career-page data from JSON.

    Returns:
        Dictionary containing career-page data.
    """

    ensure_career_pages_file(
        file_path
    )

    try:

        with open(
            file_path,
            "r",
            encoding="utf-8"
        ) as file:

            data = json.load(file)

        if not isinstance(data, dict):

            return {
                "companies": []
            }

        if not isinstance(
            data.get("companies"),
            list
        ):

            data["companies"] = []

        return data

    except (
        json.JSONDecodeError,
        OSError
    ) as error:

        print(
            f"Unable to read career pages file: "
            f"{error}"
        )

        return {
            "companies": []
        }

def get_distinct_company_names(
    rejected_jobs
):
    """
    Extract distinct company names from rejected jobs.

    Comparison is case-insensitive, while the original
    company name formatting is preserved.
    """

    company_names = []
    seen = set()

    for job in rejected_jobs:

        company_name = job.get(
            "companyName"
        )

        if not company_name:
            continue

        company_name = str(
            company_name
        ).strip()

        if not company_name:
            continue

        company_key = company_name.lower()

        if company_key in seen:
            continue

        seen.add(company_key)

        company_names.append(
            company_name
        )

    return company_names

def filter_rejected_jobs_by_company(
    rejected_jobs,
    company_names
):
    """
    Return only rejected jobs belonging to the supplied
    company names.
    """

    company_set = {
        str(company_name).strip().lower()
        for company_name in company_names
        if company_name
    }

    return [
        job
        for job in rejected_jobs
        if (
            job.get("companyName")
            and str(
                job.get("companyName")
            ).strip().lower()
            in company_set
        )
    ]

def save_career_pages(
    career_pages_data,
    file_path=CAREER_PAGES_FILE
):
    """
    Save career-page data to the JSON file.
    """

    try:

        with open(
            file_path,
            "w",
            encoding="utf-8"
        ) as file:

            json.dump(
                career_pages_data,
                file,
                indent=4,
                ensure_ascii=False
            )

    except OSError as error:

        print(
            f"Unable to save career pages file: "
            f"{error}"
        )
