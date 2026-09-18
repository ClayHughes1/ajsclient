import asyncio
import re
from dataclasses import dataclass


@dataclass
class CompanyCareerPage:
    """
    Represents a resolved company career page.

    Example:

        CompanyCareerPage(
            companyName="NVIDIA",
            careerpageurl="https://www.nvidia.com/en-us/about-nvidia/careers/"
        )
    """

    companyName: str
    careerpageurl: str


class JobSpyCareerValidator:
    """
    Validates JobSpy postings against the company's actual
    career-site postings.

    JobSpy is treated strictly as a candidate source.

    The actual company career site is the source of truth.

    A JobSpy posting is retained only when:

        1. The company career page can be discovered.
        2. The career page can be scraped.
        3. Actual jobs are extracted from that career page.
        4. The JobSpy title sufficiently matches an actual
           career-site job.

    If the career page cannot be discovered or scraped, the
    JobSpy posting is NOT allowed through.

    This is intentional because the purpose of this validator
    is to prevent stale/zombie Indeed/LinkedIn postings from
    entering the worksheet.
    """

    def __init__(
        self,
        career_page_finder,
        generic_scraper,
        max_concurrency=5,
        title_match_threshold=0.92,
    ):
        self.career_page_finder = career_page_finder

        self.generic_scraper = generic_scraper

        self.max_concurrency = max_concurrency

        self.title_match_threshold = (
            title_match_threshold
        )

    # =============================================================
    # PUBLIC METHOD
    # =============================================================

    async def validate(
        self,
        jobspy_jobs,
    ):
        """
        Validate JobSpy jobs against actual company career pages.

        Returns only JobSpy jobs that are confirmed to exist on
        the company's actual career site.
        """

        if not jobspy_jobs:
            return []

        #print()
        #print("=" * 80)
        #print("VALIDATING JOBSPY JOBS AGAINST COMPANY CAREER PAGES")
        #print("=" * 80)

        # ---------------------------------------------------------
        # Phase 1:
        #
        # Group JobSpy jobs by company.
        # ---------------------------------------------------------

        jobs_by_company = (
            self._group_jobs_by_company(
                jobspy_jobs
            )
        )

        #print()
        #print(
        #     f"Unique companies found: "
        #     f"{len(jobs_by_company)}"
        # )

        # ---------------------------------------------------------
        # Phase 2:
        #
        # Find the actual career page for each company.
        #
        # IMPORTANT:
        #
        # We do NOT use CompanyCareersSource here.
        #
        # JobSpy companies have not necessarily been discovered
        # previously, so the career-page finder must dynamically
        # locate the company's career page.
        # ---------------------------------------------------------

        career_pages = await self._resolve_career_pages(
            jobs_by_company
        )

        #print()
        #print(
        #     f"Career pages resolved: "
        #     f"{len(career_pages)}"
        # )

        # ---------------------------------------------------------
        # Phase 3:
        #
        # Scrape each company's career page.
        # ---------------------------------------------------------

        career_jobs_by_company = (
            await self._scrape_career_pages(
                career_pages
            )
        )

        # ---------------------------------------------------------
        # Phase 4:
        #
        # Compare every JobSpy posting against ALL jobs found
        # on that company's actual career site.
        # ---------------------------------------------------------

        validated_jobs = []

        zombie_count = 0

        unable_to_verify_count = 0

        for company_key, jobs in jobs_by_company.items():

            company_career_jobs = (
                career_jobs_by_company.get(
                    company_key,
                    []
                )
            )

            company_name = (
                getattr(
                    jobs[0],
                    "company",
                    None,
                )
                or getattr(
                    jobs[0],
                    "company_name",
                    None,
                )
                or company_key
            )

            #print()
            #print(
            #     f"Validating company: "
            #     f"{company_name}"
            # )

            #print(
            #     f"  JobSpy jobs: "
            #     f"{len(jobs)}"
            # )

            #print(
            #     f"  Career-page jobs: "
            #     f"{len(company_career_jobs)}"
            # )

            # -----------------------------------------------------
            # IMPORTANT:
            #
            # If there is no career-page evidence, do NOT pass the
            # JobSpy jobs through.
            #
            # Otherwise a failure to verify would allow exactly
            # the zombie postings we are trying to eliminate.
            # -----------------------------------------------------

            if not company_career_jobs:

                #print(
                #     f"  REJECTING: Unable to verify "
                #     f"career-page jobs for {company_name}"
                # )

                unable_to_verify_count += len(jobs)

                continue

            # -----------------------------------------------------
            # Build normalized title index.
            # -----------------------------------------------------

            career_title_index = (
                self._build_title_index(
                    company_career_jobs
                )
            )

            # -----------------------------------------------------
            # Compare every JobSpy job against the company's
            # actual career-site jobs.
            # -----------------------------------------------------

            for job in jobs:

                job_title = getattr(
                    job,
                    "title",
                    ""
                )

                match = self._find_title_match(
                    job_title,
                    career_title_index,
                )

                if match:

                    #print(
                    #     f"  KEEP: "
                    #     f"{job_title}"
                    # )

                    #print(
                    #     f"    Career job: "
                    #     f"{match.title}"
                    # )

                    # -------------------------------------------------
                    # Optional metadata for downstream auditing.
                    # -------------------------------------------------

                    job.career_page_verified = True

                    job.career_page_verified_title = (
                        match.title
                    )

                    job.career_page_verified_url = (
                        getattr(
                            match,
                            "posting_url",
                            None,
                        )
                    )

                    validated_jobs.append(
                        job
                    )

                else:

                    #print(
                    #     f"  REMOVE / ZOMBIE: "
                    #     f"{job_title}"
                    # )

                    job.career_page_verified = False

                    zombie_count += 1

        # ---------------------------------------------------------
        # Final summary.
        # ---------------------------------------------------------

        #print()
        #print("=" * 80)

        #print(
        #     f"JobSpy jobs before validation: "
        #     f"{len(jobspy_jobs)}"
        # )

        #print(
        #     f"JobSpy jobs after validation: "
        #     f"{len(validated_jobs)}"
        # )

        #print(
        #     f"Potential zombie postings removed: "
        #     f"{zombie_count}"
        # )

        #print(
        #     f"Unable to verify postings removed: "
        #     f"{unable_to_verify_count}"
        # )

        #print("=" * 80)

        return validated_jobs

    # =============================================================
    # GROUP BY COMPANY
    # =============================================================

    @staticmethod
    def _group_jobs_by_company(
        jobs,
    ):
        """
        Group JobSpy jobs by normalized company name.
        """

        result = {}

        for job in jobs:

            company = (
                getattr(
                    job,
                    "company",
                    None,
                )
                or getattr(
                    job,
                    "company_name",
                    None,
                )
            )

            if not company:
                continue

            company = str(
                company
            ).strip()

            if not company:
                continue

            company_key = (
                JobSpyCareerValidator
                ._normalize_company_name(
                    company
                )
            )

            result.setdefault(
                company_key,
                []
            ).append(
                job
            )

        return result

    # =============================================================
    # RESOLVE CAREER PAGES
    # =============================================================

    async def _resolve_career_pages(
        self,
        jobs_by_company,
    ):
        """
        Dynamically find a career page for each unique company.

        The career_page_finder is responsible for searching for
        and validating the company's career page.

        Returns:

            {
                "nvidia": CompanyCareerPage(...),
                "humana": CompanyCareerPage(...),
            }
        """

        semaphore = asyncio.Semaphore(
            self.max_concurrency
        )

        async def resolve_one(
            company_key,
            jobs,
        ):

            async with semaphore:

                company_name = (
                    getattr(
                        jobs[0],
                        "company",
                        None,
                    )
                    or getattr(
                        jobs[0],
                        "company_name",
                        None,
                    )
                )

                if not company_name:

                    return (
                        company_key,
                        None,
                    )

                #print()
                #print(
                #     f"Finding career page: "
                #     f"{company_name}"
                # )

                try:

                    career_url = await asyncio.to_thread(
                        self.career_page_finder.find_careers_page,
                        company_name,
                    )

                except Exception as exc:

                    #print(
                    #     f"  Failed to find career page "
                    #     f"for {company_name}: {exc}"
                    # )

                    return (
                        company_key,
                        None,
                    )

                if not career_url:

                    #print(
                    #     f"  No valid career page found "
                    #     f"for {company_name}"
                    # )

                    return (
                        company_key,
                        None,
                    )

                #print(
                #     f"  Career page: "
                #     f"{career_url}"
                # )

                return (
                    company_key,
                    CompanyCareerPage(
                        companyName=company_name,
                        careerpageurl=career_url,
                    ),
                )

        tasks = [
            resolve_one(
                company_key,
                jobs,
            )
            for company_key, jobs
            in jobs_by_company.items()
        ]

        results = await asyncio.gather(
            *tasks
        )

        return {
            company_key: career_page
            for company_key, career_page
            in results
            if career_page is not None
        }

    # =============================================================
    # SCRAPE CAREER PAGES
    # =============================================================

    async def _scrape_career_pages(
        self,
        career_pages,
    ):
        """
        Scrape each resolved company career page.

        GenericCareerScraper is responsible for retrieving the
        actual career-site HTML/JSON/API data and extracting jobs.

        Returns:

            {
                "nvidia": [Job, Job, Job],
                "humana": [Job, Job],
            }
        """

        semaphore = asyncio.Semaphore(
            self.max_concurrency
        )

        async def scrape_one(
            company_key,
            career_page,
        ):

            async with semaphore:

                company_name = (
                    career_page.companyName
                )

                career_url = (
                    career_page.careerpageurl
                )

                #print()
                #print(
                #     f"Scraping actual career jobs: "
                #     f"{company_name}"
                # )

                #print(
                #     f"  URL: "
                #     f"{career_url}"
                # )

                try:

                    jobs = await asyncio.to_thread(
                        self.generic_scraper.scrape,
                        company_name,
                        career_url,
                    )

                    jobs = jobs or []

                    #print(
                    #     f"  Actual jobs discovered: "
                    #     f"{len(jobs)}"
                    # )

                    return (
                        company_key,
                        jobs,
                    )

                except Exception as exc:

                    #print(
                    #     f"  Failed scraping "
                    #     f"{company_name}: {exc}"
                    # )

                    return (
                        company_key,
                        [],
                    )

        tasks = [
            scrape_one(
                company_key,
                career_page,
            )
            for company_key, career_page
            in career_pages.items()
        ]

        results = await asyncio.gather(
            *tasks
        )

        return dict(
            results
        )

    # =============================================================
    # TITLE INDEX
    # =============================================================

    def _build_title_index(
        self,
        career_jobs,
    ):
        """
        Build:

            normalized title -> Job

        Multiple jobs with the same normalized title are retained
        as a list.
        """

        index = {}

        for job in career_jobs:

            title = getattr(
                job,
                "title",
                None,
            )

            if not title:
                continue

            normalized = (
                self._normalize_title(
                    title
                )
            )

            if not normalized:
                continue

            index.setdefault(
                normalized,
                []
            ).append(
                job
            )

        return index

    # =============================================================
    # TITLE MATCH
    # =============================================================

    def _find_title_match(
        self,
        jobspy_title,
        career_title_index,
    ):
        """
        Find a matching career-page job.

        Matching strategy:

            1. Exact normalized title.
            2. Token similarity.

        The similarity threshold prevents unrelated jobs from
        being accepted.
        """

        normalized_jobspy_title = (
            self._normalize_title(
                jobspy_title
            )
        )

        if not normalized_jobspy_title:
            return None

        # ---------------------------------------------------------
        # Exact normalized match.
        # ---------------------------------------------------------

        exact = career_title_index.get(
            normalized_jobspy_title
        )

        if exact:
            return exact[0]

        # ---------------------------------------------------------
        # Fuzzy token matching.
        # ---------------------------------------------------------

        best_job = None

        best_score = 0.0

        for normalized_career_title, jobs in (
            career_title_index.items()
        ):

            score = (
                self._title_similarity(
                    normalized_jobspy_title,
                    normalized_career_title,
                )
            )

            if score > best_score:

                best_score = score

                best_job = jobs[0]

        if (
            best_job
            and best_score
            >= self.title_match_threshold
        ):

            return best_job

        return None

    # =============================================================
    # TITLE NORMALIZATION
    # =============================================================

    @staticmethod
    def _normalize_title(
        title,
    ):
        """
        Normalize titles while preserving meaningful words.

        Example:

            "Senior Software Engineer"
            "Senior Software Engineer - Remote"

        are NOT automatically made identical.
        """

        if not title:
            return ""

        value = str(
            title
        ).casefold()

        value = value.replace(
            "&",
            " and ",
        )

        value = re.sub(
            r"[^a-z0-9]+",
            " ",
            value,
        )

        value = re.sub(
            r"\s+",
            " ",
            value,
        ).strip()

        return value

    # =============================================================
    # TITLE SIMILARITY
    # =============================================================

    @staticmethod
    def _title_similarity(
        title1,
        title2,
    ):
        """
        Token-based Jaccard similarity.
        """

        tokens1 = set(
            title1.split()
        )

        tokens2 = set(
            title2.split()
        )

        if not tokens1 or not tokens2:
            return 0.0

        intersection = (
            tokens1
            & tokens2
        )

        union = (
            tokens1
            | tokens2
        )

        if not union:
            return 0.0

        return (
            len(intersection)
            / len(union)
        )

    # =============================================================
    # COMPANY NORMALIZATION
    # =============================================================

    @staticmethod
    def _normalize_company_name(
        company,
    ):
        """
        Normalize company names for grouping JobSpy results.
        """

        if not company:
            return ""

        value = str(
            company
        ).strip()

        value = re.sub(
            r"\s*,?\s*"
            r"(Inc\.?|"
            r"LLC|"
            r"Ltd\.?|"
            r"Limited|"
            r"Corporation|"
            r"Corp\.?|"
            r"Company|"
            r"Co\.?)$",
            "",
            value,
            flags=re.IGNORECASE,
        )

        value = re.sub(
            r"\s+",
            " ",
            value,
        )

        return value.casefold().strip()

