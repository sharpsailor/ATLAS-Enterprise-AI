"""Deterministic regex guardrails. A demo layer, not a security boundary: English only, easy to rephrase around."""
import re

_I = re.IGNORECASE
INPUT_RULES = {
    "ignore_instructions": re.compile(r"\b(ignore|disregard|forget)\b.{0,30}\b(previous|prior|above|earlier)\b.{0,20}\b(instructions?|rules|system prompt)", _I),
    "reveal_prompt": re.compile(r"\b(reveal|print|dump|disclose|show|leak)\b.{0,30}\b(system|developer|hidden)\s+(prompt|message|instructions?)", _I),
    "secret_exfiltration": re.compile(r"\b(reveal|dump|expose|send|give|print|show|leak)\b.{0,40}\b(api[\s_-]?keys?|passwords?|credentials?|secrets?|secret[\s_-]?keys?|tokens?)\b", _I),
    "disable_guardrails": re.compile(r"\b(bypass|disable|turn\s+off|ignore)\b.{0,30}\b(guardrails?|safety|filters?|checks?)\b", _I),
    "impersonation": re.compile(r"\b(pretend|act)\b.{0,20}\b(as|to be)\b.{0,20}\b(the\s+)?(system|developer|administrator|admin)\b", _I),
}
OUTPUT_RULES = {
    "private_key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "aws_key_id": re.compile(r"\b(AKIA|ASIA)[A-Z0-9]{16}\b"),
    "named_secret": re.compile(r"\b(aws_secret_access_key|pinecone_api_key|database_url)\s*[:=]", _I),
    "credential_assignment": re.compile(r"\b(password|api[\s_-]?key|secret[\s_-]?key)\s*[:=]\s*\S{12,}", _I),
}


def _first_match(rules: dict, text: str) -> str | None:
    return next((name for name, rx in rules.items() if rx.search(text)), None)


def classify_input(text: str) -> str | None:
    """Name of the first rule the input trips, or None if it is clean."""
    return _first_match(INPUT_RULES, text)


def check_output(text: str) -> str | None:
    return _first_match(OUTPUT_RULES, text)
