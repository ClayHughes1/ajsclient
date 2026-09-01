from datetime import datetime, timedelta, timezone


class JobValidator:

    def __init__(self, config: dict):
        self.config = config

    def validate(self, job) -> tuple[bool, str]:

        title = job.title.lower()

        text = (
            f"{job.title} "
            f"{job.description} "
            f"{job.location}"
        ).lower()

        # Positive role match
        search_terms = self.config.get(
            "search_terms",
            []
        )

        if not any(
            search_term.lower() in title
            or search_term.lower() in job.description.lower()
            for search_term in search_terms
        ):
            return False, "No matching job title or description"

        # Posting age
        posting_age_days = self.config.get(
            "posting_age_days"
        )

        if posting_age_days is not None:

            if not job.posting_date:
                return False, "Missing posting date"

            now = datetime.now(timezone.utc)

            posting_date = job.posting_date

            if posting_date.tzinfo is None:
                posting_date = posting_date.replace(
                    tzinfo=timezone.utc
                )

            cutoff_date = (
                now - timedelta(days=posting_age_days)
            )

            if posting_date < cutoff_date:
                return False, (
                    f"Posting older than "
                    f"{posting_age_days} days"
                )

        # Negative/exclusion match
        for excluded_term in self.config["excluded_terms"]:

            if excluded_term.lower() in text:
                return False, (
                    f"Excluded term: {excluded_term}"
                )

        # Location
        location_config = self.config.get(
            "location",
            {}
        )

        job_location = job.location.lower().strip()

        # Remote jobs are accepted when remote searching is enabled
        if self.config.get("remote", False):

            remote_terms = [
                "remote",
                "work from home",
                "remote - united states",
                "remote, united states"
            ]

            if any(
                term in job_location
                for term in remote_terms
            ):
                return True, ""

        # Explicitly excluded locations
        excluded_locations = location_config.get(
            "excluded_locations",
            []
        )

        for excluded_location in excluded_locations:

            if excluded_location.lower() in job_location:
                return False, (
                    f"Excluded location: "
                    f"{excluded_location}"
                )

        # Accepted local locations
        accepted_locations = location_config.get(
            "accepted_locations",
            []
        )

        if any(
            accepted_location.lower() in job_location
            for accepted_location in accepted_locations
        ):
            return True, ""

        return False, "Location outside accepted area"

    def calculate_score(self, job) -> tuple[int, list[str]]:

        technology_weights = self.config.get(
            "technology_weights",
            {}
        )

        text = (
            f"{job.title} "
            f"{job.description}"
        ).lower()

        score = 0
        matched_technologies = []

        for technology, weight in technology_weights.items():

            if technology.lower() in text:

                score += weight
                matched_technologies.append(
                    technology
                )

        return score, matched_technologies

# from datetime import datetime, timedelta, timezone


# class JobValidator:

#     def __init__(self, config: dict):
#         self.config = config

#     def validate(self, job) -> tuple[bool, str]:

#         title = job.title.lower()

#         text = (
#             f"{job.title} "
#             f"{job.description} "
#             f"{job.location}"
#         ).lower()

#         # Positive role match
#         search_terms = self.config.get(
#             "search_terms",
#             []
#         )

#         if not any(
#             search_term.lower() in title
#             or search_term.lower() in job.description.lower()
#             for search_term in search_terms
#         ):
#             return False, "No matching job title or description"

#         # Posting age
#         posting_age_days = self.config.get(
#             "posting_age_days"
#         )

#         if posting_age_days is not None:

#             if not job.posting_date:
#                 return False, "Missing posting date"

#             now = datetime.now(timezone.utc)

#             posting_date = job.posting_date

#             if posting_date.tzinfo is None:
#                 posting_date = posting_date.replace(
#                     tzinfo=timezone.utc
#                 )

#             cutoff_date = (
#                 now - timedelta(days=posting_age_days)
#             )

#             if posting_date < cutoff_date:
#                 return False, (
#                     f"Posting older than "
#                     f"{posting_age_days} days"
#                 )

#         # Negative/exclusion match
#         for excluded_term in self.config["excluded_terms"]:

#             if excluded_term.lower() in text:
#                 return False, (
#                     f"Excluded term: {excluded_term}"
#                 )

#         # Location
#         location_config = self.config.get(
#             "location",
#             {}
#         )

#         job_location = job.location.lower().strip()

#         # Remote jobs are accepted when remote searching is enabled
#         if self.config.get("remote", False):

#             remote_terms = [
#                 "remote",
#                 "work from home",
#                 "remote - united states",
#                 "remote, united states"
#             ]

#             if any(
#                 term in job_location
#                 for term in remote_terms
#             ):
#                 return True, ""

#         # Explicitly excluded locations
#         excluded_locations = location_config.get(
#             "excluded_locations",
#             []
#         )

#         for excluded_location in excluded_locations:

#             if excluded_location.lower() in job_location:
#                 return False, (
#                     f"Excluded location: "
#                     f"{excluded_location}"
#                 )

#         # Accepted local locations
#         accepted_locations = location_config.get(
#             "accepted_locations",
#             []
#         )

#         if any(
#             accepted_location.lower() in job_location
#             for accepted_location in accepted_locations
#         ):
#             return True, ""

#         return False, "Location outside accepted area"


