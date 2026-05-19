from __future__ import annotations

from dataclasses import dataclass
import re


SECRETS_DOCUMENT_KEY = "SECRETS.md"
MASKED_SECRET_VALUE = "<stored>"
ENCRYPTED_SECTION_SUFFIX = " (암호화 저장 완료)"
REQUIRED_SECRET_KEYS_BY_SECTION = {
    "srt-booking": frozenset(("KSKILL_SRT_ID", "KSKILL_SRT_PASSWORD")),
}

_SECTION_PATTERN = re.compile(r"^##\s+(?P<section>.+?)\s*$")
_ASSIGNMENT_PATTERN = re.compile(r"^(?P<key>[A-Za-z_][A-Za-z0-9_]*)=(?P<value>.*)$")


@dataclass(frozen=True, slots=True)
class SecretAssignment:
    section: str
    key: str
    value: str


def is_secrets_document(document_key: str) -> bool:
    return document_key.strip().lower() == SECRETS_DOCUMENT_KEY.lower()


def sanitize_secret_document(content: str) -> tuple[str, list[SecretAssignment]]:
    current_section = "default"
    assignments: list[SecretAssignment] = []
    sanitized_lines: list[str] = []
    section_line_indexes: dict[str, int] = {}
    stored_keys_by_section: dict[str, set[str]] = {}

    for line in content.splitlines(keepends=True):
        line_body = line.rstrip("\r\n")
        newline = line[len(line_body) :]
        section_match = _SECTION_PATTERN.match(line_body.strip())
        if section_match:
            current_section = _normalize_section_name(section_match.group("section").strip())
            section_line_indexes[current_section] = len(sanitized_lines)
            sanitized_lines.append(f"## {current_section}{newline}")
            continue

        assignment_match = _ASSIGNMENT_PATTERN.match(line_body)
        if assignment_match is None:
            sanitized_lines.append(line)
            continue

        key = assignment_match.group("key")
        value = assignment_match.group("value").strip()
        if value == MASKED_SECRET_VALUE:
            stored_keys_by_section.setdefault(current_section, set()).add(key)
            sanitized_lines.append(line)
            continue
        if not value:
            sanitized_lines.append(line)
            continue

        assignments.append(SecretAssignment(section=current_section, key=key, value=value))
        stored_keys_by_section.setdefault(current_section, set()).add(key)
        sanitized_lines.append(f"{key}={MASKED_SECRET_VALUE}{newline}")

    for section, required_keys in REQUIRED_SECRET_KEYS_BY_SECTION.items():
        line_index = section_line_indexes.get(section)
        if line_index is None:
            continue
        line = sanitized_lines[line_index]
        line_body = line.rstrip("\r\n")
        newline = line[len(line_body) :]
        complete = required_keys.issubset(stored_keys_by_section.get(section, set()))
        suffix = ENCRYPTED_SECTION_SUFFIX if complete else ""
        sanitized_lines[line_index] = f"## {section}{suffix}{newline}"

    return "".join(sanitized_lines), assignments


def _normalize_section_name(section: str) -> str:
    if section.endswith(ENCRYPTED_SECTION_SUFFIX):
        return section[: -len(ENCRYPTED_SECTION_SUFFIX)].strip()
    return section
