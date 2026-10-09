"""Specialist writing instructions and transparent, limited editorial checks."""
import re

PROFILES = {
    "press_release": {"agent": "Envoy", "role": "Press release writer", "instructions":
        "Write a factual headline, a concise announcement lead, then supporting paragraphs. "
        "Use an inverted pyramid. Do not add a dateline, quote, boilerplate or media contact unless supplied. "
        "Avoid promotional claims and invented significance. Aim for 150–250 words, but use fewer when facts are sparse."},
    "social": {"agent": "Ripple", "role": "Social editor", "instructions":
        "Write one concise social post, 40–90 words. Start with the actual news. Use short paragraphs. "
        "Include a call to action only if supplied facts support it. No invented hashtags, emoji, links or hype."},
    "email": {"agent": "Liaison", "role": "Outreach writer", "instructions":
        "Use title as the email subject. Write a complete email body, 80–160 words: direct opening, relevant detail, "
        "and a clear next step only when supported. No invented recipient names, signatures, promises or placeholders."},
    "podcast": {"agent": "Orator", "role": "Podcast producer", "instructions":
        "Create a solo-host spoken script with sections Cold open, Introduction, Main story, and Closing. "
        "Use short, speakable sentences, natural transitions and no invented guests or quotations. "
        "Aim for 350–600 words only when supported by sufficient material. Put show notes and source references in summary. "
        "Never claim audio has been generated."},
}


def inspect_copy(output: dict, source: str, forbidden: str = "") -> dict:
    """Flags mechanical problems; this does not establish factual support."""
    copy = "\n".join(output.get(k, "") for k in ("title", "body", "summary"))
    issues = []
    number_pattern = r"\b\d+(?:[,.]\d+)*%?"
    for value in sorted(set(re.findall(number_pattern, copy))):
        if value not in set(re.findall(number_pattern, source)):
            issues.append({"kind": "unsupported_number", "text": value, "message": "Number is absent from the supplied source material."})
    for value in sorted(set(re.findall(r"https?://[^\s<>]+", copy))):
        if value.rstrip('.,;)') not in source:
            issues.append({"kind": "unsupported_link", "text": value, "message": "Link is absent from the supplied source material."})
    for value in re.findall(r"\[(?:insert\b|your\b|link\b|name\b|date\b|company\b)[^\]]*\]|\b(?:TBD|TODO|lorem ipsum)\b", copy, re.I):
        issues.append({"kind": "placeholder", "text": value, "message": "Unfinished placeholder remains in the copy."})
    for value in (x.strip() for x in forbidden.splitlines()):
        if value and value.casefold() in copy.casefold():
            issues.append({"kind": "brand_language", "text": value, "message": "Phrase is excluded by the brand profile."})
    return {"issues": issues[:50], "word_count": len(output.get("body", "").split()),
            "reading_minutes": max(1, round(len(output.get("body", "").split()) / 150)),
            "scope": "Checks numbers, links, placeholders and excluded phrases. Factual accuracy still requires source review."}
