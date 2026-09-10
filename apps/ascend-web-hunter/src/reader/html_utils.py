from bs4 import BeautifulSoup

NOISE_TAGS = ("script", "style", "nav", "footer", "iframe")


def remove_noise_tags(soup: BeautifulSoup) -> None:
    for tag in soup(list(NOISE_TAGS)):
        tag.decompose()
