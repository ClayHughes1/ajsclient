from datetime import datetime
from pathlib import Path


def export_to_excel(dataframe):

    output_directory = Path("output")
    output_directory.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")

    output_file = (
        output_directory /
        f"ajsclient_{timestamp}.xlsx"
    )

    dataframe.to_excel(
        output_file,
        index=False
    )

    return output_file