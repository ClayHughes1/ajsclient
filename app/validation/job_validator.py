from datetime import datetime, timedelta, timezone, date
import re


class JobValidator:

    def __init__(self, config: dict):
        self.config = config

    def validate(self, job) -> tuple[bool, str]:

        title = (job.title or "").lower()

        description = job.description or ""
        location = job.location or ""

        text = (
            f"{job.title or ''} "
            f"{description} "
            f"{location}"
        ).lower()

        # ---------------------------------------------------------
        # 1. Positive role match
        # ---------------------------------------------------------

        search_terms = self.config.get(
            "search_terms",
            []
        )

        if not any(
            search_term.lower() in title
            or search_term.lower() in description.lower()
            for search_term in search_terms
        ):
            return False, "No matching job title or description"

        # ---------------------------------------------------------
        # 2. Posting age
        # ---------------------------------------------------------
        #
        # IMPORTANT:
        #
        # A missing posting date is allowed.
        #
        # If SerpApi returns posting_date=None, the job is allowed
        # to continue through validation. We do NOT reject it merely
        # because the posting date is unavailable.
        #
        # If a posting date IS available, however, it must satisfy
        # the configured posting_age_days requirement.
        # ---------------------------------------------------------

        posting_age_days = self.config.get(
            "posting_age_days"
        )

        if posting_age_days is not None:

            posting_date = job.posting_date

            # -----------------------------------------------------
            # Missing posting date:
            #
            # Let the job slide.
            #
            # The absence of a posting date is NOT considered a
            # validation failure.
            # -----------------------------------------------------

            if posting_date is None:
                pass

            # -----------------------------------------------------
            # Handle datetime values.
            # -----------------------------------------------------

            elif isinstance(posting_date, datetime):

                if posting_date.tzinfo is None:

                    posting_date = posting_date.replace(
                        tzinfo=timezone.utc
                    )

                now = datetime.now(timezone.utc)

                cutoff_date = (
                    now
                    - timedelta(days=posting_age_days)
                )

                if posting_date < cutoff_date:

                    return False, (
                        f"Posting older than "
                        f"{posting_age_days} days"
                    )

            # -----------------------------------------------------
            # Handle date values.
            #
            # SerpApiSource converts values such as:
            #
            # "today"
            # "1 day ago"
            # "2 days ago"
            #
            # into datetime.date objects.
            # -----------------------------------------------------

            elif isinstance(posting_date, date):

                cutoff_date = (
                    date.today()
                    - timedelta(days=posting_age_days)
                )

                if posting_date < cutoff_date:

                    return False, (
                        f"Posting older than "
                        f"{posting_age_days} days"
                    )

            # -----------------------------------------------------
            # Unknown / invalid posting date type.
            # -----------------------------------------------------

            else:

                return False, "Invalid posting date"

        # ---------------------------------------------------------
        # 3. Negative / exclusion match
        # ---------------------------------------------------------

        for excluded_term in self.config.get(
            "excluded_terms",
            []
        ):

            if excluded_term.lower() in text:

                return False, (
                    f"Excluded term: {excluded_term}"
                )

        # ---------------------------------------------------------
        # 4. Required technology compatibility
        # ---------------------------------------------------------

        incompatible_technology = (
            self.detect_incompatible_technology(job)
        )

        if incompatible_technology:

            return False, (
                "Required incompatible technology: "
                f"{incompatible_technology}"
            )

        # ---------------------------------------------------------
        # 5. Location
        # ---------------------------------------------------------

        location_config = self.config.get(
            "location",
            {}
        )

        job_location = location.lower().strip()

        # ---------------------------------------------------------
        # Remote U.S. positions
        # ---------------------------------------------------------

        if self.config.get("remote", False):

            remote_us_terms = [
                "remote - usa",
                "remote - united states",
                "remote, usa",
                "remote, united states",
                "remote, us",
                "remote, u.s.",
                "us-remote",
                "usa-remote",
                "united states-remote",
                "remote united states"
            ]

            if any(
                term in job_location
                for term in remote_us_terms
            ):
                return True, ""

        # ---------------------------------------------------------
        # Explicitly excluded locations
        # ---------------------------------------------------------

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

        # ---------------------------------------------------------
        # Accepted local locations
        # ---------------------------------------------------------

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

    # =============================================================
    # TECHNOLOGY SCORING
    # =============================================================

    def calculate_score(
        self,
        job
    ) -> tuple[int, list[str], float]:

        technology_weights = self.config.get(
            "technology_weights",
            {}
        )

        preferred_technologies = self.config.get(
            "preferred_technologies",
            []
        )

        text = (
            f"{job.title or ''} "
            f"{job.description or ''}"
        ).lower()

        matched_technologies = []

        score = 0

        # ---------------------------------------------------------
        # Detect preferred technologies.
        #
        # Each technology can only count once, regardless of how
        # many times it appears in the job description.
        # ---------------------------------------------------------

        for technology in preferred_technologies:

            pattern = (
                rf"(?<!\w)"
                rf"{re.escape(technology.lower())}"
                rf"(?!\w)"
            )

            if re.search(pattern, text):

                matched_technologies.append(
                    technology
                )

                weight = technology_weights.get(
                    technology,
                    0
                )

                try:
                    score += int(weight)
                except (
                    TypeError,
                    ValueError
                ):
                    pass

        # ---------------------------------------------------------
        # Technology Match Percentage
        #
        # Formula:
        #
        # Unique preferred technologies found
        # ----------------------------------- × 100
        # Total configured preferred technologies
        # ---------------------------------------------------------

        technology_percentage = 0.0

        total_preferred = len(
            preferred_technologies
        )

        if total_preferred > 0:

            technology_percentage = round(
                (
                    len(matched_technologies)
                    / total_preferred
                ) * 100,
                2
            )

        return (
            score,
            matched_technologies,
            technology_percentage
        )

    # =============================================================
    # REQUIRED TECHNOLOGY VALIDATION
    # =============================================================

    def detect_incompatible_technology(
        self,
        job
    ) -> str | None:

        description = job.description or ""

        # ---------------------------------------------------------
        # Technologies explicitly allowed by the candidate profile.
        #
        # These come from search_criteria.json.
        # ---------------------------------------------------------

        allowed_technologies = {
            technology.lower()
            for technology in self.config.get(
                "preferred_technologies",
                []
            )
        }

        # ---------------------------------------------------------
        # Incompatible technology definitions come directly
        # from search_criteria.json.
        # ---------------------------------------------------------

        incompatible_technologies = self.config.get(
            "incompatible_technologies",
            {}
        )

        # ---------------------------------------------------------
        # Preferred / optional indicators
        # ---------------------------------------------------------

        preferred_terms = [
            "preferred",
            "prefer",
            "preferred qualification",
            "preferred qualifications",
            "nice to have",
            "nice-to-have",
            "bonus",
            "helpful",
            "plus",
            "a plus",
            "preferred skill",
            "preferred skills",
            "desired",
            "desired qualification",
            "desired qualifications",
            "would be nice",
            "would be a plus"
        ]

        # ---------------------------------------------------------
        # Required indicators
        # ---------------------------------------------------------

        required_terms = [
            "required",
            "requirement",
            "requirements",
            "minimum requirement",
            "minimum requirements",
            "minimum qualification",
            "minimum qualifications",
            "required qualification",
            "required qualifications",
            "required skill",
            "required skills",
            "must have",
            "must-have",
            "must be",
            "proficiency in",
            "experience in",
            "experience with",
            "expertise in",
            "expertise with",
            "strong experience",
            "strong background",
            "professional experience",
            "programming experience",
            "backend experience",
            "backend programming",
            "software development experience",
            "development experience"
        ]

        # ---------------------------------------------------------
        # Technical context indicators
        # ---------------------------------------------------------

        technical_requirement_patterns = [
            "programming language",
            "programming languages",
            "backend",
            "backend language",
            "backend languages",
            "software engineer",
            "software development",
            "developing software",
            "write code",
            "coding experience",
            "development experience",
            "engineering experience"
        ]

        # ---------------------------------------------------------
        # Break description into lines.
        # ---------------------------------------------------------

        lines = [
            line.strip()
            for line in description.splitlines()
            if line.strip()
        ]

        in_required_section = False
        in_preferred_section = False

        # ---------------------------------------------------------
        # Scan description
        # ---------------------------------------------------------

        for line in lines:

            line_lower = line.lower()

            # -----------------------------------------------------
            # Detect section context
            # -----------------------------------------------------

            if any(
                term in line_lower
                for term in preferred_terms
            ):

                in_preferred_section = True
                in_required_section = False

            elif any(
                term in line_lower
                for term in required_terms
            ):

                in_required_section = True
                in_preferred_section = False

            # -----------------------------------------------------
            # Find technologies using ONLY the configured
            # incompatible_technologies dictionary.
            # -----------------------------------------------------

            found_technologies = []

            for technology, aliases in (
                incompatible_technologies.items()
            ):

                patterns_to_check = [
                    technology
                ]

                if isinstance(aliases, list):
                    patterns_to_check.extend(
                        aliases
                    )

                for alias in patterns_to_check:

                    if not alias:
                        continue

                    pattern = (
                        rf"(?<!\w)"
                        rf"{re.escape(alias.lower())}"
                        rf"(?!\w)"
                    )

                    if re.search(
                        pattern,
                        line_lower
                    ):

                        found_technologies.append(
                            technology
                        )

                        break

            # -----------------------------------------------------
            # Nothing incompatible found.
            # -----------------------------------------------------

            if not found_technologies:
                continue

            # -----------------------------------------------------
            # Preferred technologies do not cause rejection.
            # -----------------------------------------------------

            if (
                in_preferred_section
                or any(
                    term in line_lower
                    for term in preferred_terms
                )
            ):
                continue

            # -----------------------------------------------------
            # Determine whether this line represents a technical
            # requirement.
            # -----------------------------------------------------

            is_required = (

                in_required_section

                or any(
                    term in line_lower
                    for term in required_terms
                )

                or any(
                    term in line_lower
                    for term in technical_requirement_patterns
                )
            )

            if not is_required:
                continue

            # -----------------------------------------------------
            # Reject if a required incompatible technology is not
            # part of the preferred technology list.
            # -----------------------------------------------------

            for technology in found_technologies:

                if (
                    technology.lower()
                    not in allowed_technologies
                ):

                    return technology

        return None
