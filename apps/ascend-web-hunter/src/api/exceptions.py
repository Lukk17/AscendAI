from src.reader.cloudflare.challenge_signals import ChallengeVerdict


class HumanInterventionRequiredException(Exception):
    """Raised when a manual CAPTCHA solving or Login is required via the VNC UI."""

    def __init__(
        self,
        vnc_url: str,
        intervention_type: str = "captcha",
        flow_id: str | None = None,
        joined: bool = False,
        window: dict[str, int] | None = None,
    ):
        self.vnc_url = vnc_url
        self.intervention_type = intervention_type
        self.flow_id = flow_id
        self.joined = joined
        self.window = window
        action = "Captcha resolution" if intervention_type == "captcha" else "Login authentication"
        self.message = f"Manual {action} required. Please visit: {vnc_url}"
        super().__init__(self.message)


class ChallengeDetectedException(Exception):
    """
    Raised by underlying strategies when the scored challenge verdict trips a wall,
    triggering an immediate abort. Carries the verdict: the message names the
    vendor and the score, and the intervention type is the verdict's.
    """

    def __init__(self, verdict: ChallengeVerdict):
        self.verdict = verdict
        self.intervention_type = verdict.intervention_type
        self.message = (
            f"Challenge detected: vendor={verdict.vendor} "
            f"score={verdict.score}/{verdict.threshold} type={verdict.intervention_type}"
        )
        super().__init__(self.message)


class NoVNCFlowBusyException(Exception):
    """
    Raised when a NoVNC intervention is requested while every local window
    slot is taken. Only one flow per slot -- manual `session/establish` or
    an automatic escalation from a read -- can run at a time.
    """

    def __init__(
        self,
        holder_url: str,
        holder_profile: str,
        active_flows: int = 0,
        max_concurrent_flows: int = 0,
        flows: list[dict[str, object]] | None = None,
    ):
        self.holder_url = holder_url
        self.holder_profile = holder_profile
        self.active_flows = active_flows
        self.max_concurrent_flows = max_concurrent_flows
        self.flows = flows if flows is not None else []
        self.message = (
            f"All {max_concurrent_flows} NoVNC intervention windows are in use; "
            f"the oldest is {holder_url} (profile={holder_profile}). Try again shortly."
            if max_concurrent_flows
            else (
                f"A NoVNC intervention is already in progress for {holder_url} "
                f"(profile={holder_profile}). Only one intervention can run at a time; try again shortly."
            )
        )
        super().__init__(self.message)
