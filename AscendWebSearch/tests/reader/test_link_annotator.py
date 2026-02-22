from src.reader.link_annotator import annotate_links

BASE_URL = "https://example.com"


def test_annotate_links_returns_numbered_map():
    html = """
    <html><body>
        <p>Visit <a href="https://example.com/page1">Page One</a> for details.</p>
        <p>Also see <a href="https://example.com/page2">Page Two</a>.</p>
    </body></html>
    """
    content, links = annotate_links(html, BASE_URL)

    assert len(links) == 2
    assert links[1] == "https://example.com/page1"
    assert links[2] == "https://example.com/page2"
    assert "[1]" in content
    assert "[2]" in content


def test_annotate_links_strips_noise_tags():
    html = """
    <html><body>
        <nav><a href="https://example.com/nav">Nav</a></nav>
        <footer><a href="https://example.com/footer">Footer</a></footer>
        <p><a href="https://example.com/content">Content</a></p>
    </body></html>
    """
    content, links = annotate_links(html, BASE_URL)

    assert len(links) == 1
    assert links[1] == "https://example.com/content"


def test_annotate_links_filter_by_substring():
    html = """
    <html><body>
        <a href="https://example.com/job-offer/senior-dev">Senior Dev</a>
        <a href="https://example.com/about">About Us</a>
        <a href="https://example.com/job-offer/mid-dev">Mid Dev</a>
    </body></html>
    """
    content, links = annotate_links(html, BASE_URL, link_filter="/job-offer/")

    assert len(links) == 2
    assert links[1] == "https://example.com/job-offer/senior-dev"
    assert links[2] == "https://example.com/job-offer/mid-dev"


def test_annotate_links_resolves_relative_urls():
    html = """
    <html><body>
        <a href="/relative/path">Relative</a>
    </body></html>
    """
    content, links = annotate_links(html, "https://example.com")

    assert links[1] == "https://example.com/relative/path"


def test_annotate_links_skips_invalid_hrefs():
    html = """
    <html><body>
        <a href="#">Hash</a>
        <a href="mailto:a@b.com">Mail</a>
        <a href="tel:123">Tel</a>
        <a href="javascript:void(0)">JS</a>
        <a href="https://example.com/valid">Valid</a>
    </body></html>
    """
    content, links = annotate_links(html, BASE_URL)

    assert len(links) == 1
    assert links[1] == "https://example.com/valid"


def test_annotate_links_empty_html_returns_empty():
    content, links = annotate_links("", BASE_URL)

    assert content == ""
    assert links == {}


def test_annotate_links_no_anchors_returns_empty_map():
    html = "<html><body><p>No links here.</p></body></html>"
    content, links = annotate_links(html, BASE_URL)

    assert links == {}
    assert "No links here" in content
