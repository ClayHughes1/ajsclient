from datetime import datetime, timedelta, timezone

import requests

from app.models.job import Job
from app.sources.job_source import JobSource
from app.utils.html_cleaner import clean_html_description
from app.utils.salary_extractor import extract_salary


class LeverSource(JobSource):

    BASE_URL = "https://api.lever.co/v0/postings"

    def __init__(
        self,
        company_name: str,
        company_token: str,
        posting_age_days: int = 2
    ):
        self.company_name = company_name
        self.company_token = company_token
        self.posting_age_days = posting_age_days

    def search(self, search_term: str = "") -> list[Job]:

        url = (
            f"{self.BASE_URL}/"
            f"{self.company_token}"
        )

        response = requests.get(
            url,
            params={
                "mode": "json"
            },
            timeout=30
        )

        if response.status_code == 404:
            print(
                f"Lever board not found: "
                f"{self.company_name} "
                f"({self.company_token}) - skipping."
            )
            return []

        response.raise_for_status()

        data = response.json()

        jobs = []

        for item in data:

            # -----------------------------------------
            # Lever posting status
            # -----------------------------------------

            if item.get("state") not in (
                None,
                "published"
            ):
                continue

            # -----------------------------------------
            # Job title
            # -----------------------------------------

            title = item.get(
                "text",
                ""
            )

            # -----------------------------------------
            # Job ID
            # -----------------------------------------

            job_id = str(
                item.get(
                    "id",
                    ""
                )
            )

            # -----------------------------------------
            # Posting date
            # -----------------------------------------

            created_at = item.get(
                "createdAt"
            )

            posting_date = None

            if created_at:

                posting_date = datetime.fromtimestamp(
                    created_at / 1000,
                    tz=timezone.utc
                )

                if self.posting_age_days is not None:

                    now = datetime.now(
                        timezone.utc
                    )

                    cutoff_date = (
                        now -
                        timedelta(
                            days=self.posting_age_days
                        )
                    )

                    if posting_date < cutoff_date:
                        continue

            elif self.posting_age_days is not None:

                # We cannot verify posting age.
                continue

            # -----------------------------------------
            # Location
            # -----------------------------------------

            categories = item.get(
                "categories",
                {}
            )

            locations = categories.get(
                "allLocations",
                []
            )

            primary_location = categories.get(
                "location",
                ""
            )

            if not locations and primary_location:
                locations = [
                    primary_location
                ]

            location = "; ".join(
                str(value)
                for value in locations
                if value
            )

            # -----------------------------------------
            # Employment type
            #
            # Lever uses "commitment" for values such
            # as Full-time, Part-time, Contract, etc.
            # -----------------------------------------

            employment_type = categories.get(
                "commitment",
                ""
            )

            # -----------------------------------------
            # Description
            # -----------------------------------------

            content = item.get(
                "content",
                {}
            )

            description = clean_html_description(
                content.get(
                    "description",
                    ""
                )
            )

            # -----------------------------------------
            # Salary
            # -----------------------------------------

            salary = item.get(
                "salaryDescription",
                ""
            )

            if not salary:

                salary_range = item.get(
                    "salaryRange"
                )

                if salary_range:

                    minimum = salary_range.get(
                        "min"
                    )

                    maximum = salary_range.get(
                        "max"
                    )

                    currency = salary_range.get(
                        "currency",
                        ""
                    )

                    if minimum and maximum:

                        salary = (
                            f"{currency} "
                            f"{minimum:,} - "
                            f"{maximum:,}"
                        )

                    elif minimum:

                        salary = (
                            f"{currency} "
                            f"{minimum:,}+"
                        )

            if not salary:
                salary = extract_salary(
                    description
                )

            # -----------------------------------------
            # URLs
            # -----------------------------------------

            urls = item.get(
                "urls",
                {}
            )

            posting_url = urls.get(
                "show",
                ""
            )

            apply_url = urls.get(
                "apply",
                ""
            )

            # If Lever doesn't provide a separate
            # application URL, use the posting URL.
            if not apply_url:
                apply_url = posting_url

            # -----------------------------------------
            # Search term
            # -----------------------------------------

            if search_term:

                searchable_text = (
                    f"{title} "
                    f"{description}"
                ).lower()

                if (
                    search_term.lower()
                    not in searchable_text
                ):
                    continue

            # -----------------------------------------
            # Create common Job object
            # -----------------------------------------

            job = Job(
                company=self.company_name,
                title=title,
                location=location,
                posting_url=posting_url,
                description=description,
                posting_date=posting_date,
                salary=salary,
                source="Lever",
                apply_url=apply_url,
                employment_type=employment_type,
                job_id=job_id
            )

            jobs.append(job)

        return jobs




# from datetime import datetime, timedelta, timezone
# from app.utils.html_cleaner import clean_html_description
# from app.utils.salary_extractor import extract_salary

# import requests

# from app.models.job import Job
# from app.sources.job_source import JobSource


# class LeverSource(JobSource):

#     BASE_URL = "https://api.lever.co/v0/postings"

#     def __init__(
#         self,
#         company_name: str,
#         company_token: str,
#         posting_age_days: int = 2
#     ):
#         self.company_name = company_name
#         self.company_token = company_token
#         self.posting_age_days = posting_age_days

#     def search(self, search_term: str = "") -> list[Job]:

#         url = (
#             f"{self.BASE_URL}/"
#             f"{self.company_token}"
#         )

#         response = requests.get(
#             url,
#             params={
#                 "mode": "json"
#             },
#             timeout=30
#         )

#         if response.status_code == 404:
#             print(
#                 f"Lever board not found: "
#                 f"{self.company_name} "
#                 f"({self.company_token}) - skipping."
#             )
#             return []

#         response.raise_for_status()

#         data = response.json()

#         jobs = []

#         for item in data:

#             # Lever postings should be published jobs.
#             if item.get("state") not in (None, "published"):
#                 continue

#             title = item.get(
#                 "text",
#                 ""
#             )

#             # -----------------------------------------
#             # Posting date
#             # -----------------------------------------

#             created_at = item.get("createdAt")

#             posting_date = None

#             if created_at:

#                 posting_date = datetime.fromtimestamp(
#                     created_at / 1000,
#                     tz=timezone.utc
#                 )

#                 if self.posting_age_days is not None:

#                     now = datetime.now(timezone.utc)

#                     cutoff_date = (
#                         now -
#                         timedelta(
#                             days=self.posting_age_days
#                         )
#                     )

#                     if posting_date < cutoff_date:
#                         continue

#             elif self.posting_age_days is not None:

#                 # We cannot verify posting age.
#                 continue

#             # -----------------------------------------
#             # Location
#             # -----------------------------------------

#             categories = item.get(
#                 "categories",
#                 {}
#             )

#             locations = categories.get(
#                 "allLocations",
#                 []
#             )

#             primary_location = categories.get(
#                 "location",
#                 ""
#             )

#             if not locations and primary_location:
#                 locations = [primary_location]

#             location = "; ".join(
#                 str(value)
#                 for value in locations
#                 if value
#             )

#             # -----------------------------------------
#             # Description
#             # -----------------------------------------

#             content = item.get(
#                 "content",
#                 {}
#             )

#             description = clean_html_description(
#                 content.get("description", "")
#             )

#             # -----------------------------------------
#             # Salary
#             # -----------------------------------------

#             salary = item.get(
#                 "salaryDescription",
#                 ""
#             )

#             if not salary:

#                 salary_range = item.get(
#                     "salaryRange"
#                 )

#                 if salary_range:

#                     minimum = salary_range.get(
#                         "min"
#                     )

#                     maximum = salary_range.get(
#                         "max"
#                     )

#                     currency = salary_range.get(
#                         "currency",
#                         ""
#                     )

#                     if minimum and maximum:

#                         salary = (
#                             f"{currency} "
#                             f"{minimum:,} - "
#                             f"{maximum:,}"
#                         )

#                     elif minimum:

#                         salary = (
#                             f"{currency} "
#                             f"{minimum:,}+"
#                         )

#             if not salary:
#                 salary = extract_salary(description)
                
#             # -----------------------------------------
#             # Posting URL
#             # -----------------------------------------

#             urls = item.get(
#                 "urls",
#                 {}
#             )

#             posting_url = urls.get(
#                 "show",
#                 ""
#             )

#             # -----------------------------------------
#             # Search term
#             # -----------------------------------------

#             if search_term:

#                 searchable_text = (
#                     f"{title} "
#                     f"{description}"
#                 ).lower()

#                 if search_term.lower() not in searchable_text:
#                     continue

#             # -----------------------------------------
#             # Create common Job object
#             # -----------------------------------------

#             job = Job(
#                 company=self.company_name,
#                 title=title,
#                 location=location,
#                 posting_url=posting_url,
#                 description=description,
#                 posting_date=posting_date,
#                 salary=salary,
#                 source="Lever"
#             )

#             jobs.append(job)

#         return jobs