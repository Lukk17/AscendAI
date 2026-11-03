# Test fixtures

Saved pages the extraction tests run against without touching the network.

| File | Source | Saved |
| :--- | :--- | :--- |
| `books_toscrape_index.html` | `https://books.toscrape.com/`, the listing page defect A59 was measured on | 2026-09-10 |
| `gnu_free_sw_article.html` | `https://www.gnu.org/philosophy/free-sw.en.html`, an article page the precision pass handles alone | 2026-09-10 |
| `embedded_product.html` | Hand-built page carrying the same product in JSON-LD, OpenGraph and microdata | 2026-10-19 |
| `ensemble_readability_wins.html` | Hand-built article with an `aside` block trafilatura drops and readability keeps, so readability wins the D2 ensemble | 2026-10-21 |
| `ensemble_tie.html` | Hand-built short note both extractors return word for word, so the D2 scores tie and trafilatura wins | 2026-10-21 |
