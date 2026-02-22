import re


class CloudflareDetector:
    CLOUDFLARE_KEYWORDS = [
        "Just a moment...",
        "Attention Required!",
        "Cloudflare",
        "Please wait while your request is being verified",
        "Enable JavaScript and cookies to continue",
        "Additional Verification Required"
    ]

    @staticmethod
    def is_blocked(status_code: int, html_content: str) -> bool:
        """
        Checks if the response indicates a WAF/Cloudflare block.
        """
        if not html_content:
            if status_code in (403, 429, 503):
                return True
            return False

        if len(html_content) > 50000:
            return False

        for keyword in CloudflareDetector.CLOUDFLARE_KEYWORDS:
            if keyword in html_content:
                return True

        if re.search(r'Ray ID: \w+', html_content, re.IGNORECASE):
            return True

        if 'cf-turnstile' in html_content:
            return True

        if 'cf_clearance' in html_content:
            return True

        return False
