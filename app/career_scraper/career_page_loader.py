import json
from pathlib import Path


class CareerPageLoader:
    """
    Loads validated company career pages from career_pages.json.
    """

    # def __init__(self, file_path="career_pages.json"):
    #     self.file_path = Path(file_path)

    def __init__(self):
        self.file_path = (
            Path(__file__).resolve().parent.parent / "career_pages.json"
        )

    def load(self):
        """
        Load and validate career page records.

        Returns:
            list: A list of dictionaries containing company and URL.
        """
        if not self.file_path.exists():
            raise FileNotFoundError(
                f"Career pages file not found: {self.file_path}"
            )

        try:
            with self.file_path.open("r", encoding="utf-8") as file:
                career_pages = json.load(file)

        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Invalid JSON in {self.file_path}: {exc}"
            ) from exc

        if not isinstance(career_pages, list):
            raise ValueError(
                "career_pages.json must contain a list of career pages."
            )

        validated_pages = []

        for page in career_pages:
            if not isinstance(page, dict):
                continue

            company = page.get("company")
            url = page.get("url")

            if not company or not url:
                continue

            validated_pages.append({
                "company": company.strip(),
                "url": url.strip()
            })

        return validated_pages
