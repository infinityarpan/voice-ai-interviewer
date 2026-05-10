from app.schemas.interview import InterviewQuestion

MAX_QUESTION_WORDS = 45
TWO_MINUTE_INSTRUCTION = "Answer in about 2 minutes."


def constrain_question_for_two_minutes(question: InterviewQuestion) -> InterviewQuestion:
    text = _single_prompt(_strip_time_phrasing(question.question_text))
    text = _limit_words(text, MAX_QUESTION_WORDS)
    if TWO_MINUTE_INSTRUCTION.lower() not in text.lower():
        text = f"{text} {TWO_MINUTE_INSTRUCTION}"
    return question.model_copy(update={"question_text": text})


def _strip_time_phrasing(text: str) -> str:
    replacements = [
        "In about 2 minutes, ",
        "In about 2 minutes,",
        "Follow-up (about 2 minutes): ",
        "Follow-up (about 2 minutes):",
        "about 2 minutes",
    ]
    cleaned = text.strip()
    for value in replacements:
        cleaned = cleaned.replace(value, "")
    return cleaned.strip()


def _single_prompt(text: str) -> str:
    parts = [part.strip() for part in text.replace("?", ".").split(".") if part.strip()]
    if not parts:
        return "Walk me through your approach."
    first = parts[0]
    if len(parts) > 1 and len(first.split()) < 18:
        first = f"{first}; {parts[1]}"
    return first.rstrip(".?") + "."


def _limit_words(text: str, max_words: int) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text
    shortened = " ".join(words[:max_words]).rstrip(".,;:")
    return f"{shortened}."
