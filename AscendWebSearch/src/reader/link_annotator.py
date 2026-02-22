from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

NOISE_TAGS = ['script', 'style', 'nav', 'footer', 'iframe']
LINK_MARKER_TEMPLATE = "[{index}]"
VALID_SCHEMES = ('http', 'https')
SKIPPED_HREF_PREFIXES = ('#', 'mailto:', 'tel:', 'javascript:')


def annotate_links(
        html: str,
        base_url: str,
        link_filter: str | None = None,
) -> tuple[str, dict[int, str]]:
    soup = BeautifulSoup(html, 'html.parser')
    _remove_noise_tags(soup)
    link_map: dict[int, str] = {}
    link_index = 1

    for anchor in soup.find_all('a', href=True):
        absolute_url = _resolve_absolute_url(anchor['href'], base_url)
        if not absolute_url:
            continue
        if link_filter and link_filter not in absolute_url:
            continue
        marker = LINK_MARKER_TEMPLATE.format(index=link_index)
        anchor.string = f"{anchor.get_text(strip=True)} {marker}"
        link_map[link_index] = absolute_url
        link_index += 1

    return soup.get_text(separator=' ', strip=True), link_map


def _remove_noise_tags(soup: BeautifulSoup) -> None:
    for tag in soup(NOISE_TAGS):
        tag.decompose()


def _resolve_absolute_url(href: str, base_url: str) -> str:
    if not href or href.startswith(SKIPPED_HREF_PREFIXES):
        return ""
    absolute = urljoin(base_url, href)
    parsed = urlparse(absolute)
    return absolute if parsed.scheme in VALID_SCHEMES else ""
