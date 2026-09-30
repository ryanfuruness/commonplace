"""Checks applied to everything written into the commons.

Entries must describe situations at a level of abstraction that travels
("Series B fintech entering KSA"), never the specifics of the session they
came from. Credentials, email addresses and international phone numbers are
unambiguous signs that text was not abstracted, so they are rejected. The
patterns favour precision: a false rejection teaches agents to route around
the check, while abstraction beyond these cases is the contributor's job and
a curator's check. All patterns are bounded so they run in linear time.
"""

from __future__ import annotations

import re

_SECRET_PATTERNS = [
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{20,200}"), "an API key"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "an AWS access key"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,200}"), "a GitHub token"),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,200}"), "a Slack token"),
    (re.compile(r"-----BEGIN [A-Z ]{0,40}PRIVATE KEY-----"), "a private key"),
]
# A credential assignment only when the value looks machine-generated: long,
# with both letters and digits, and no spaces.
_ASSIGNMENT = re.compile(r"(?i)\b(?:api[_-]?key|secret|password|passwd|token)\b\s{0,3}[:=]\s{0,3}(\S{16,200})")
# user@domain.tld, but not scp-style git remotes (git@host:org/repo).
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9\-]{1,63}(?:\.[A-Za-z0-9\-]{1,63}){0,8}\.[A-Za-z]{2,24}\b(?!:\S)")
# International format only (+country code): precise, and the common form in shared material.
_PHONE = re.compile(r"(?<![\w+])\+\d{1,3}[\s.\-]?(?:\(?\d{1,4}\)?[\s.\-]?){2,5}\d{2,4}\b")

RECOMMENDED_SECTIONS = {
    "methodology": ["approach", "traps", "human corrections", "evidence"],
    "source_intel": ["sources", "evidence"],
    "pitfall": ["trap", "avoid", "evidence"],
    "other": [],
}

MIN_BODY, MAX_BODY = 200, 20000


class LintError(ValueError):
    pass


def check_text(*fields: str | None) -> None:
    text = "\n".join(f for f in fields if f)
    for pattern, what in _SECRET_PATTERNS:
        if pattern.search(text):
            raise LintError(
                f"Rejected: the text appears to contain {what}. Nothing session-specific "
                "belongs in the commons; remove it and describe the situation abstractly."
            )
    for m in _ASSIGNMENT.finditer(text):
        value = m.group(1)
        if re.search(r"[A-Za-z]", value) and re.search(r"\d", value):
            raise LintError("Rejected: the text appears to contain a credential. Remove it.")
    if _EMAIL.search(text):
        raise LintError(
            "Rejected: the text contains an email address. Describe people by role "
            "(\"the CFO\", \"a procurement lead\"), not by contact details."
        )
    for m in _PHONE.finditer(text):
        digits = re.sub(r"\D", "", m.group())
        if 8 <= len(digits) <= 15:
            raise LintError("Rejected: the text contains what looks like a phone number.")


def check_entry(kind: str, body: str) -> list[str]:
    if len(body) < MIN_BODY:
        raise LintError(
            f"Body is {len(body)} characters; entries need at least {MIN_BODY}. An entry "
            "should carry enough reasoning that a fresh agent could act on it."
        )
    if len(body) > MAX_BODY:
        raise LintError(f"Body exceeds {MAX_BODY} characters; split it into focused entries.")
    lowered = body.lower()
    missing = [s for s in RECOMMENDED_SECTIONS.get(kind, []) if s not in lowered]
    if not missing:
        return []
    return [
        "Advisory: no section mentions " + ", ".join(missing) + ". Add them where there is something "
        "true to say; leave them out otherwise."
    ]
