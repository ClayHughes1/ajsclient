import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).parent.parent


def load_config():

    config_path = (
        PROJECT_ROOT
        / "config"
        / "search_config.json"
    )

    with open(
        config_path,
        "r",
        encoding="utf-8"
    ) as file:

        return json.load(file)


def load_companies():

    companies_path = (
        PROJECT_ROOT
        / "config"
        / "companies.json"
    )

    with open(
        companies_path,
        "r",
        encoding="utf-8"
    ) as file:

        return json.load(file)