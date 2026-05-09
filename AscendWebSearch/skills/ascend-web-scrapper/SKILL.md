---
name: ascend-web-scrapper
description: Self-hosted web scraping service for job sites and other pages. Use when scraping job listings or any web pages.
---

# Ascend Web Scrapper

Self-hosted web scraping service at `http://host.docker.internal:7021`.

## Endpoint

**URL:** `http://host.docker.internal:7021/api/v2/web/read`

**Method:** `POST`

**Header:** `Content-Type: application/json`

**Body:**
```json
{"url":"https://<actual_job_page_url>/","include_links":true,"heavy_mode":true}
```

Replace `<actual_job_page_url>` with the actual URL you want to scrape.

## Example

```bash
curl -s --max-time 60 http://host.docker.internal:7021/api/v2/web/read \
  -X POST \
  -H "Content-Type: application/json" \
  -d '{"url":"https://www.linkedin.com/jobs/view/123","include_links":true,"heavy_mode":true}'
```

## Response

Returns JSON with:
- `content` - page content
- `links` - dictionary of found links
- `status` - "success" or error status

## Usage

Use this skill whenever you need to scrape job listings or any web pages for the job-seeker project or other purposes.

**For job scraping**, the typical flow is:
1. Use this endpoint to fetch job listing pages
2. Parse the content with appropriate parser functions
3. Save results to Excel using `file_handler.py`
