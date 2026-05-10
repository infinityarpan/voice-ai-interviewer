INITIAL_SHORTLIST_CONTEXT = (
    "This is an initial recruiter shortlist screen for a recruitment firm serving multiple clients. "
    "The goal is to collect broad first-round suitability signals, not make a final technical hiring decision. "
    "Ask broad role-relevant questions and avoid deep implementation drills unless needed to clarify a clear risk. "
    "A plausible candidate can be recommended for the first round even if they are not yet proven strong."
)


def shortlist_context_lines() -> list[str]:
    return [
        INITIAL_SHORTLIST_CONTEXT,
        "Optimize for broad coverage, communication clarity, practical exposure, and obvious red flags.",
        "Do not reject candidates for missing low-level details during this initial screen.",
    ]
