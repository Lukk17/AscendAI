class HumanInterventionRequiredException(Exception):
    """Raised when a manual CAPTCHA solving or Login is required via the VNC UI."""

    def __init__(self, vnc_url: str, intervention_type: str = "captcha"):
        self.vnc_url = vnc_url
        self.intervention_type = intervention_type
        action = "Captcha resolution" if intervention_type == "captcha" else "Login authentication"
        self.message = f"Manual {action} required. Please visit: {vnc_url}"
        super().__init__(self.message)


class ChallengeDetectedException(Exception):
    """Raised by underlying strategies when the ChallengeDetector trips a wall heuristic, triggering an immediate abort."""

    def __init__(self, intervention_type: str):
        self.intervention_type = intervention_type
        self.message = f"Challenge detected: {intervention_type}"
        super().__init__(self.message)
