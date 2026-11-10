from bs4 import BeautifulSoup, Tag

NOISE_TAGS = ("script", "style", "nav", "footer", "iframe")


def remove_noise_tags(soup: BeautifulSoup) -> None:
    for tag in soup(list(NOISE_TAGS)):
        tag.decompose()


def collapsed_text(tag: Tag) -> str:
    return " ".join(tag.get_text().split())
