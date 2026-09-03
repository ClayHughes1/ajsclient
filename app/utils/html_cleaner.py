from html import unescape
from bs4 import BeautifulSoup


def clean_html_description(html_content: str) -> str:
    """
    Convert HTML job descriptions into readable plain text.

    - Decodes HTML entities such as &lt;, &gt;, &#39;, &amp;, etc.
    - Removes HTML tags.
    - Preserves useful paragraph/list structure.
    - Normalizes whitespace.
    """

    if not html_content:
        return ""

    # Decode HTML entities first.
    decoded_html = unescape(html_content)

    # Parse the HTML.
    soup = BeautifulSoup(decoded_html, "html.parser")

    # Add readable spacing for block elements.
    for tag in soup.find_all(
        ["h1", "h2", "h3", "h4", "h5", "h6", "p", "div"]
    ):
        tag.insert_before("\n\n")
        tag.insert_after("\n\n")

    # Turn list items into readable bullets.
    for tag in soup.find_all("li"):
        tag.insert_before("\n• ")
        tag.insert_after("\n")

    # Extract plain text.
    text = soup.get_text()

    # Decode any entities that remain after parsing.
    text = unescape(text)

    # Normalize whitespace while preserving paragraphs.
    lines = []

    for line in text.splitlines():

        line = " ".join(line.split())

        if line:
            lines.append(line)

    # Remove excessive blank lines.
    result = "\n".join(lines)

    while "\n\n\n" in result:
        result = result.replace(
            "\n\n\n",
            "\n\n"
        )

    return result.strip()