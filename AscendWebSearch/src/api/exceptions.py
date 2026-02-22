class CaptchaRequiredException(Exception):
    """Raised when a manual CAPTCHA solving is required via the VNC UI."""

    def __init__(self, vnc_url: str):
        self.vnc_url = vnc_url
        self.message = f"Manual Captcha resolution required. Please visit: {vnc_url}"
        super().__init__(self.message)
