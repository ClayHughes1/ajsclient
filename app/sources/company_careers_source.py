import re
import requests


class CompanyCareersSource:
    """
    Finds a company's careers page by testing combinations of
    known company-domain and careers-path patterns.

    The first URL that returns HTTP 200 is considered a valid
    careers page.

    Validated results are stored in:

        self.validated_career_links

    Example:

        {
            "companyName": "Datadog",
            "careerpageurl": "https://careers.datadoghq.com/all-jobs/"
        }
    """

    def __init__(
        self,
        timeout=10
    ):

        self.timeout = timeout

        # ---------------------------------------------------------
        # HTTP session
        # ---------------------------------------------------------

        self.session = requests.Session()

        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/140.0 Safari/537.36"
            ),
            "Accept": (
                "text/html,application/xhtml+xml,"
                "application/xml;q=0.9,image/avif,"
                "image/webp,*/*;q=0.8"
            ),
            "Accept-Language": "en-US,en;q=0.9"
        })

        # ---------------------------------------------------------
        # Validated career links
        #
        # Example:
        #
        # [
        #     {
        #         "companyName": "Datadog",
        #         "careerpageurl":
        #             "https://careers.datadoghq.com/all-jobs/"
        #     }
        # ]
        # ---------------------------------------------------------

        self.validated_career_links = []

        # ---------------------------------------------------------
        # Cache
        #
        # company name -> career URL or None
        # ---------------------------------------------------------

        self.cache = {}

    # =============================================================
    # Find careers page
    # =============================================================

    def find_careers_page(
        self,
        company_name
    ):
        """
        Find and validate a company's careers page.

        Returns:
            Validated careers URL
            or None
        """

        if not company_name:
            return None

        company_name = str(
            company_name
        ).strip()

        if not company_name:
            return None

        # ---------------------------------------------------------
        # Cache
        # ---------------------------------------------------------

        cache_key = company_name.lower()

        if cache_key in self.cache:

            return self.cache[
                cache_key
            ]

        # print(
        #     f"    Searching career URL patterns for: "
        #     f"{company_name}"
        # )

        # ---------------------------------------------------------
        # Generate URL candidates
        # ---------------------------------------------------------

        career_urls = (
            self.generate_career_urls(
                company_name
            )
        )

        # print(
        #     f"    Generated "
        #     f"{career_urls} "
        #     f"career URL candidates.\n\n"
        # )

        # ---------------------------------------------------------
        # Test every candidate
        #
        # First HTTP 200 wins.
        # ---------------------------------------------------------

        for url in career_urls:

            # print(
            #     f"    Testing: "
            #     f"{url}"
            # )

            if self.validate_url(url):

                print(
                    f"    VALID career page: "
                    f"{url}"
                )

                # -------------------------------------------------
                # Store validated result
                # -------------------------------------------------

                result = {
                    "companyName": company_name,
                    "careerpageurl": url
                }

                self.validated_career_links.append(
                    result
                )

                # -------------------------------------------------
                # Cache
                # -------------------------------------------------

                self.cache[
                    cache_key
                ] = url

                return url

        # ---------------------------------------------------------
        # Nothing found
        # ---------------------------------------------------------

        # print(
        #     f"    No valid career page found for: "
        #     f"{company_name}"
        # )

        self.cache[
            cache_key
        ] = None

        return None

    # =============================================================
    # Generate career URLs
    # =============================================================

    @staticmethod
    def generate_career_urls(
        company_name
    ):
        """
        Generate every URL variation represented by the known
        career-page examples.

        Examples represented by this algorithm:

            https://careers.datadoghq.com/all-jobs/
            https://www.spacex.com/careers
            https://stripe.com/careers
            https://www.anthropic.com/careers
            https://www.cloudflare.com/careers/
            https://www.dropbox.jobs/en/
            https://www.lyft.com/careers
        """

        # ---------------------------------------------------------
        # Normalize company name
        # ---------------------------------------------------------

        company = (
            company_name
            .strip()
            .lower()
        )

        # Remove common punctuation
        company = re.sub(
            r"[^a-z0-9\s-]",
            "",
            company
        )

        # ---------------------------------------------------------
        # Domain-safe company name
        #
        # "The Home Depot"
        #     -> thehomedepot
        #
        # "Block, Inc."
        #     -> blockinc
        # ---------------------------------------------------------

        domain_name = re.sub(
            r"[^a-z0-9]",
            "",
            company
        )

        # ---------------------------------------------------------
        # Generate possible domains
        #
        # These represent the domain structures observed in the
        # manually collected examples.
        # ---------------------------------------------------------

        domains = [

            # ---------------------------------------------
            # Normal .com
            # ---------------------------------------------

            f"{domain_name}.com",

            f"www.{domain_name}.com",

            # ---------------------------------------------
            # Careers subdomain
            # ---------------------------------------------

            f"careers.{domain_name}.com",

            # ---------------------------------------------
            # Jobs subdomain
            # ---------------------------------------------

            f"jobs.{domain_name}.com",

            # ---------------------------------------------
            # .jobs domain
            #
            # Dropbox:
            #
            # www.dropbox.jobs/en/
            # ---------------------------------------------

            f"{domain_name}.jobs",

            f"www.{domain_name}.jobs",

            f"careers.{domain_name}.jobs",

            f"jobs.{domain_name}.jobs",

            # ---------------------------------------------
            # HQ variation
            #
            # Datadog:
            #
            # datadoghq.com
            # ---------------------------------------------

            f"{domain_name}hq.com",

            f"www.{domain_name}hq.com",

            f"careers.{domain_name}hq.com",

            f"jobs.{domain_name}hq.com",
        ]

        # ---------------------------------------------------------
        # Career paths
        #
        # Ordered so the most common/simple patterns are tested
        # first.
        # ---------------------------------------------------------

        paths = [

            # ---------------------------------------------
            # Standard careers
            # ---------------------------------------------

            "/careers",
            "/careers/",

            # ---------------------------------------------
            # Standard jobs
            # ---------------------------------------------

            "/jobs",
            "/jobs/",

            # ---------------------------------------------
            # All jobs
            # ---------------------------------------------

            "/all-jobs",
            "/all-jobs/",

            # ---------------------------------------------
            # International / language paths
            #
            # Dropbox:
            #
            # /en/
            # ---------------------------------------------

            "/en",
            "/en/",

            "/en/careers",
            "/en/careers/",

            "/en/jobs",
            "/en/jobs/",

            "/en/all-jobs",
            "/en/all-jobs/",
        ]

        # ---------------------------------------------------------
        # Build combinations
        # ---------------------------------------------------------

        urls = []

        for domain in domains:

            for path in paths:

                url = (
                    f"https://{domain}{path}"
                )

                urls.append(
                    url
                )
        # ---------------------------------------------------------
        # Remove duplicates while preserving order
        # ---------------------------------------------------------

        return list(
            dict.fromkeys(urls)
        )

    # =============================================================
    # Validate URL
    # =============================================================

    def validate_url(
        self,
        url
    ):

        try:

            response = self.session.get(
                url,
                timeout=self.timeout,
                allow_redirects=True
            )

            # print(
            #     f"      HTTP "
            #     f"{response.status_code}"
            # )

            # print(
            #     f"      Final URL: "
            #     f"{response.url}"
            # )

            if response.status_code != 200:
                return None

            return response.url

        except requests.RequestException as error:

            print(
                f"      Request failed: "
                f"{error}"
            )

            return None
