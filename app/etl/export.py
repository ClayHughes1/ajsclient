from datetime import datetime
from pathlib import Path

import pandas as pd


def _prepare_dataframe(dataframe):

    export_dataframe = dataframe.copy()

    for column in export_dataframe.columns:

        if export_dataframe[column].map(
            lambda value: isinstance(value, datetime)
        ).any():

            export_dataframe[column] = (
                export_dataframe[column]
                .map(
                    lambda value:
                    value.date()
                    if isinstance(value, datetime)
                    else value
                )
            )

    return export_dataframe


def export_to_excel(dataframe):

    output_directory = Path("output")
    output_directory.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime(
        "%Y-%m-%d_%H%M%S"
    )

    output_file = (
        output_directory /
        f"ajsclient_{timestamp}.xlsx"
    )

    export_dataframe = _prepare_dataframe(
        dataframe
    )

    export_dataframe.to_excel(
        output_file,
        index=False
    )

    return output_file


def export_rejected_to_excel(dataframe):

    output_directory = Path("output")
    output_directory.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime(
        "%Y-%m-%d_%H%M%S"
    )

    output_file = (
        output_directory /
        f"ajsclient_rejected_{timestamp}.xlsx"
    )

    export_dataframe = _prepare_dataframe(
        dataframe
    )

    export_dataframe.to_excel(
        output_file,
        index=False
    )

    return output_file

