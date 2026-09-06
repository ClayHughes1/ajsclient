import os
import time
import requests

from datetime import date

from dotenv import load_dotenv

from app.models.job import Job


load_dotenv()


class USAJobsSource:

    BASE_URL = (
        "https://data.usajobs.gov/api/Search"
    )

    def __init__(
        self,
        posting_age_days: int = 2
    ):

        self.api_key = os.getenv(
            "USAJOBS_API_KEY"
        )

        self.user_agent = os.getenv(
            "USAJOBS_USER_AGENT"
        )

        if not self.api_key:

            raise ValueError(
                "USAJOBS_API_KEY was not found "
                "in the .env file."
            )

        if not self.user_agent:

            raise ValueError(
                "USAJOBS_USER_AGENT was not found "
                "in the .env file."
            )

        self.posting_age_days = posting_age_days

        self.headers = {
            "Host": "data.usajobs.gov",
            "User-Agent": self.user_agent,
            "Authorization-Key": self.api_key
        }

    def search(
        self,
        search_terms: list[str] | None = None,
        location: str | None = None,
        radius_miles: int | None = None
    ) -> list[Job]:

        jobs = []

        search_terms = (
            search_terms or []
        )

        # ---------------------------------------------------------
        # Build USAJOBS query.
        #
        # 2210 = Information Technology Management
        # ---------------------------------------------------------

        params = {
            "JobCategoryCode": "2210",
            "DatePosted": self.posting_age_days,
            "ResultsPerPage": 500,
            "Fields": "Full"
        }

        if location:

            params["LocationName"] = location

        if radius_miles:

            params["Radius"] = radius_miles

        # ---------------------------------------------------------
        # Perform broad IT search.
        #
        # Application-specific filtering is performed locally.
        # ---------------------------------------------------------

        page = 1

        while True:

            params["Page"] = page

            try:

                response = requests.get(
                    self.BASE_URL,
                    headers=self.headers,
                    params=params,
                    timeout=30
                )

                response.raise_for_status()

                data = response.json()

            except requests.RequestException as error:

                print(
                    f"USAJOBS request failed: "
                    f"{error}"
                )

                break

            except ValueError as error:

                print(
                    f"USAJOBS returned invalid JSON: "
                    f"{error}"
                )

                break

            search_result = data.get(
                "SearchResult",
                {}
            )

            items = search_result.get(
                "SearchResultItems",
                []
            )

            if not items:

                break

            # -----------------------------------------------------
            # Normalize USAJOBS records.
            # -----------------------------------------------------

            for item in items:

                job = self._normalize_job(
                    item
                )

                if not job:

                    continue

                # -------------------------------------------------
                # Apply title filtering locally.
                # -------------------------------------------------

                if search_terms:

                    if not self._title_matches(
                        job.title,
                        search_terms
                    ):

                        continue

                jobs.append(
                    job
                )

            # -----------------------------------------------------
            # Determine whether more pages exist.
            # -----------------------------------------------------

            total = search_result.get(
                "SearchResultCountAll",
                0
            )

            if page * 500 >= total:

                break

            page += 1

            # -----------------------------------------------------
            # Be polite to the API.
            # -----------------------------------------------------

            time.sleep(1)

        print(
            f"USAJOBS returned "
            f"{len(jobs)} matching jobs."
        )

        return jobs

    def _normalize_job(
        self,
        item: dict
    ) -> Job | None:

        descriptor = item.get(
            "MatchedObjectDescriptor",
            {}
        )

        # ---------------------------------------------------------
        # Basic job information
        # ---------------------------------------------------------

        title = (
            descriptor.get(
                "PositionTitle",
                ""
            )
            or ""
        ).strip()

        company = (
            descriptor.get(
                "OrganizationName",
                ""
            )
            or ""
        ).strip()

        # ---------------------------------------------------------
        # Posting URL
        # ---------------------------------------------------------

        posting_url = (
            descriptor.get(
                "PositionURI",
                ""
            )
            or ""
        ).strip()

        # ---------------------------------------------------------
        # Apply URL
        #
        # USAJOBS can return ApplyURI as a list.
        # ---------------------------------------------------------

        apply_url = self._get_apply_url(
            descriptor
        )

        # ---------------------------------------------------------
        # Location
        # ---------------------------------------------------------

        locations = descriptor.get(
            "PositionLocation",
            []
        )

        location = ""

        if locations:

            first_location = locations[0]

            location = (
                first_location.get(
                    "LocationName",
                    ""
                )
                or ""
            ).strip()

        # ---------------------------------------------------------
        # Description
        # ---------------------------------------------------------

        description = (
            descriptor.get(
                "QualificationSummary",
                ""
            )
            or ""
        ).strip()

        # ---------------------------------------------------------
        # Job announcement number
        # ---------------------------------------------------------

        job_id = str(
            descriptor.get(
                "PositionID",
                ""
            )
        ).strip()

        if not title or not company:

            return None

        return Job(
            company=company,
            title=title,
            location=location,
            posting_url=posting_url,
            description=description,
            posting_date=self._get_posting_date(
                descriptor
            ),
            salary=self._get_salary(
                descriptor
            ),
            source="USAJOBS",
            apply_url=apply_url,
            employment_type="",
            job_id=job_id
        )

    def _get_apply_url(
        self,
        descriptor: dict
    ) -> str:

        apply_uri = descriptor.get(
            "ApplyURI",
            []
        )

        # ---------------------------------------------------------
        # USAJOBS normally returns ApplyURI as a list.
        # ---------------------------------------------------------

        if isinstance(
            apply_uri,
            list
        ):

            for url in apply_uri:

                if url:

                    return str(
                        url
                    ).strip()

        # ---------------------------------------------------------
        # Handle string response defensively.
        # ---------------------------------------------------------

        if isinstance(
            apply_uri,
            str
        ):

            return apply_uri.strip()

        return ""

    def _get_posting_date(
        self,
        descriptor: dict
    ):

        # ---------------------------------------------------------
        # IMPORTANT:
        #
        # PublicationStartDate is the USAJOBS publication date.
        #
        # Do NOT use PositionStartDate here.
        #
        # PositionStartDate represents the position's start-date
        # information, not when the announcement was published.
        # ---------------------------------------------------------

        date_string = descriptor.get(
            "PublicationStartDate"
        )

        if not date_string:

            return None

        try:

            return date.fromisoformat(
                str(
                    date_string
                )[:10]
            )

        except ValueError:

            return None

    def _get_salary(
        self,
        descriptor: dict
    ) -> str:

        remuneration = descriptor.get(
            "PositionRemuneration",
            []
        )

        if not remuneration:

            return ""

        values = []

        for item in remuneration:

            minimum = item.get(
                "MinimumRange",
                ""
            )

            maximum = item.get(
                "MaximumRange",
                ""
            )

            if minimum:

                values.append(
                    str(minimum)
                )

            if maximum:

                values.append(
                    str(maximum)
                )

        return " - ".join(
            values
        )

    def _title_matches(
        self,
        title: str,
        search_terms: list[str]
    ) -> bool:

        title_lower = title.lower()

        for term in search_terms:

            if term.lower() in title_lower:

                return True

        return False


# import os
# import time
# import requests

# from datetime import date, timedelta

# from dotenv import load_dotenv

# from app.models.job import Job


# load_dotenv()


# class USAJobsSource:

#     BASE_URL = (
#         "https://data.usajobs.gov/api/Search"
#     )

#     def __init__(
#         self,
#         posting_age_days: int = 2
#     ):

#         self.api_key = os.getenv(
#             "USAJOBS_API_KEY"
#         )

#         self.user_agent = os.getenv(
#             "USAJOBS_USER_AGENT"
#         )

#         if not self.api_key:

#             raise ValueError(
#                 "USAJOBS_API_KEY was not found "
#                 "in the .env file."
#             )

#         if not self.user_agent:

#             raise ValueError(
#                 "USAJOBS_USER_AGENT was not found "
#                 "in the .env file."
#             )

#         self.posting_age_days = posting_age_days

#         self.headers = {
#             "Host": "data.usajobs.gov",
#             "User-Agent": self.user_agent,
#             "Authorization-Key": self.api_key
#         }

#     def search(
#         self,
#         search_terms: list[str] | None = None,
#         location: str | None = None,
#         radius_miles: int | None = None
#     ) -> list[Job]:

#         jobs = []

#         search_terms = (
#             search_terms or []
#         )

#         # ---------------------------------------------------------
#         # Build USAJOBS query.
#         #
#         # 2210 = Information Technology Management
#         # ---------------------------------------------------------

#         params = {
#             "JobCategoryCode": "2210",
#             "DatePosted": self.posting_age_days,
#             "ResultsPerPage": 500,
#             "Fields": "Full"
#         }

#         if location:

#             params["LocationName"] = location

#         if radius_miles:

#             params["Radius"] = radius_miles

#         # ---------------------------------------------------------
#         # We can perform one broad IT search and perform your
#         # application-specific title/technology filtering locally.
#         # ---------------------------------------------------------

#         page = 1

#         while True:

#             params["Page"] = page

#             try:

#                 response = requests.get(
#                     self.BASE_URL,
#                     headers=self.headers,
#                     params=params,
#                     timeout=30
#                 )

#                 response.raise_for_status()

#                 data = response.json()

#             except requests.RequestException as error:

#                 print(
#                     f"USAJOBS request failed: "
#                     f"{error}"
#                 )

#                 break

#             search_result = data.get(
#                 "SearchResult",
#                 {}
#             )

#             items = search_result.get(
#                 "SearchResultItems",
#                 []
#             )

#             if not items:
#                 break

#             # -----------------------------------------------------
#             # Normalize USAJOBS records.
#             # -----------------------------------------------------

#             for item in items:

#                 job = self._normalize_job(
#                     item
#                 )

#                 if not job:
#                     continue

#                 # -------------------------------------------------
#                 # Apply your existing search-term logic locally.
#                 # -------------------------------------------------

#                 if search_terms:

#                     if not self._title_matches(
#                         job.title,
#                         search_terms
#                     ):

#                         continue

#                 jobs.append(
#                     job
#                 )

#             # -----------------------------------------------------
#             # Determine whether more pages exist.
#             # -----------------------------------------------------

#             total = search_result.get(
#                 "SearchResultCountAll",
#                 0
#             )

#             if page * 500 >= total:

#                 break

#             page += 1

#             # -----------------------------------------------------
#             # Be polite to the API.
#             # -----------------------------------------------------

#             time.sleep(1)

#         print(
#             f"USAJOBS returned "
#             f"{len(jobs)} matching jobs."
#         )

#         return jobs

#     def _normalize_job(
#         self,
#         item: dict
#     ) -> Job | None:

#         descriptor = item.get(
#             "MatchedObjectDescriptor",
#             {}
#         )

#         title = (
#             descriptor.get(
#                 "PositionTitle",
#                 ""
#             )
#             .strip()
#         )

#         company = (
#             descriptor.get(
#                 "OrganizationName",
#                 ""
#             )
#             .strip()
#         )

#         posting_url = (
#             descriptor.get(
#                 "PositionURI",
#                 ""
#             )
#             .strip()
#         )

#         apply_url = (
#             descriptor.get(
#                 "ApplyURI",
#                 ""
#             )
#             .strip()
#         )

#         # ---------------------------------------------------------
#         # Location
#         # ---------------------------------------------------------

#         locations = descriptor.get(
#             "PositionLocation",
#             []
#         )

#         location = ""

#         if locations:

#             first_location = locations[0]

#             location = (
#                 first_location.get(
#                     "LocationName",
#                     ""
#                 )
#             )

#         # ---------------------------------------------------------
#         # Description
#         # ---------------------------------------------------------

#         description = (
#             descriptor.get(
#                 "QualificationSummary",
#                 ""
#             )
#             or ""
#         )

#         # ---------------------------------------------------------
#         # Job announcement number
#         # ---------------------------------------------------------

#         job_id = str(
#             descriptor.get(
#                 "PositionID",
#                 ""
#             )
#         ).strip()

#         if not title or not company:

#             return None

#         return Job(
#             company=company,
#             title=title,
#             location=location,
#             posting_url=posting_url,
#             description=description,
#             posting_date=self._get_posting_date(
#                 descriptor
#             ),
#             salary=self._get_salary(
#                 descriptor
#             ),
#             source="USAJOBS",
#             apply_url=apply_url,
#             employment_type="",
#             job_id=job_id
#         )

#     def _get_posting_date(
#         self,
#         descriptor: dict
#     ):

#         date_string = (
#             descriptor.get(
#                 "PositionStartDate"
#             )
#         )

#         if not date_string:

#             return None

#         try:

#             return date.fromisoformat(
#                 date_string[:10]
#             )

#         except ValueError:

#             return None

#     def _get_salary(
#         self,
#         descriptor: dict
#     ) -> str:

#         remuneration = descriptor.get(
#             "PositionRemuneration",
#             []
#         )

#         if not remuneration:

#             return ""

#         values = []

#         for item in remuneration:

#             minimum = item.get(
#                 "MinimumRange",
#                 ""
#             )

#             maximum = item.get(
#                 "MaximumRange",
#                 ""
#             )

#             if minimum:

#                 values.append(
#                     str(minimum)
#                 )

#             if maximum:

#                 values.append(
#                     str(maximum)
#                 )

#         return " - ".join(
#             values
#         )

#     def _title_matches(
#         self,
#         title: str,
#         search_terms: list[str]
#     ) -> bool:

#         title_lower = title.lower()

#         for term in search_terms:

#             if term.lower() in title_lower:

#                 return True

#         return False
