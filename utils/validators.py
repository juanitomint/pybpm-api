import re


def sanitize_xss(value: str) -> str:
    """Strip HTML tags to prevent XSS in user-controlled fields (folder names, etc.)."""
    if not isinstance(value, str):
        return value
    return re.sub(r"<[^>]*>", "", value)
