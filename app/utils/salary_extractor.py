import re


SALARY_PATTERN = re.compile(
    r"\$?\s*([\d,]+)"
    r"\s*(?:-|–|—|to)"
    r"\s*\$?\s*([\d,]+)"
    r"\s*(USD|US\$)?",
    re.IGNORECASE
)


def extract_salary(description: str) -> str:
    """
    Extract a salary range from a job description.

    Examples:
        $150,000—$175,000 USD
        $150,000 - $175,000 USD
        $150,000 to $175,000 USD
    """

    if not description:
        return ""

    match = SALARY_PATTERN.search(description)

    if not match:
        return ""

    minimum = match.group(1)
    maximum = match.group(2)
    currency = match.group(3) or "USD"

    return (
        f"${minimum} - "
        f"${maximum} "
        f"{currency.upper()}"
    )