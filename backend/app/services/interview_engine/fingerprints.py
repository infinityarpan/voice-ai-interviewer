import re


def question_fingerprint(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text.lower()).strip()
    normalized = re.sub(r"[^a-z0-9 ]", "", normalized)
    return normalized
