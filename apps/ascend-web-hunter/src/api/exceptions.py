class HumanInterventionRequiredException(Exception):
    """Raised when a manual CAPTCHA solving or Login is required via the VNC UI."""

    def __init__(self, vnc_url: str, intervention_type: str = "captcha"):
        self.vnc_url = vnc_url
        self.intervention_type = intervention_type
        action = "Captcha resolution" if intervention_type == "captcha" else "Login authentication"
        self.message = f"Manual {action} required. Please visit: {vnc_url}"
        super().__init__(self.message)


class ChallengeDetectedException(Exception):
    """
    Raised by underlying strategies when the ChallengeDetector trips a wall heuristic,
    triggering an immediate abort.
    """

    def __init__(self, intervention_type: str):
        self.intervention_type = intervention_type
        self.message = f"Challenge detected: {intervention_type}"
        super().__init__(self.message)


class NoVNCFlowBusyException(Exception):
    """
    Raised when a NoVNC intervention is requested while another one already
    holds the single shared browser, VNC display and CDP port. Only one
    flow -- manual `session/establish` or an automatic escalation from a
    read -- can run at a time.
    """

    def __init__(self, holder_url: str, holder_profile: str):
        self.holder_url = holder_url
        self.holder_profile = holder_profile
        self.message = (
            f"A NoVNC intervention is already in progress for {holder_url} "
            f"(profile={holder_profile}). Only one intervention can run at a time; try again shortly."
        )
        super().__init__(self.message)
