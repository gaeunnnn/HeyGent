from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


SUPPORTED_PREVIEW_PACKAGES = frozenset(
    {
        "@dnd-kit/core",
        "@dnd-kit/utilities",
        "@radix-ui/react-accordion",
        "@radix-ui/react-alert-dialog",
        "@radix-ui/react-aspect-ratio",
        "@radix-ui/react-avatar",
        "@radix-ui/react-checkbox",
        "@radix-ui/react-collapsible",
        "@radix-ui/react-context-menu",
        "@radix-ui/react-dialog",
        "@radix-ui/react-dropdown-menu",
        "@radix-ui/react-hover-card",
        "@radix-ui/react-label",
        "@radix-ui/react-menubar",
        "@radix-ui/react-navigation-menu",
        "@radix-ui/react-popover",
        "@radix-ui/react-progress",
        "@radix-ui/react-radio-group",
        "@radix-ui/react-scroll-area",
        "@radix-ui/react-select",
        "@radix-ui/react-separator",
        "@radix-ui/react-slider",
        "@radix-ui/react-slot",
        "@radix-ui/react-switch",
        "@radix-ui/react-tabs",
        "@radix-ui/react-toggle",
        "@radix-ui/react-toggle-group",
        "@radix-ui/react-tooltip",
        "@react-three/drei",
        "@react-three/fiber",
        "@xyflow/react",
        "animejs",
        "axios",
        "bootstrap",
        "class-variance-authority",
        "clsx",
        "cmdk",
        "d3",
        "date-fns",
        "embla-carousel-react",
        "framer-motion",
        "gsap",
        "input-otp",
        "lottie-react",
        "lucide-react",
        "mapbox-gl",
        "motion",
        "next-themes",
        "react",
        "react-day-picker",
        "react-dom",
        "react-hook-form",
        "react-icons",
        "react-is",
        "react-markdown",
        "react-resizable-panels",
        "react-router",
        "recharts",
        "remark-gfm",
        "sonner",
        "tailwind-merge",
        "three",
        "vaul",
        "zustand",
    }
)

LUCIDE_REACT_UNSUPPORTED_BRAND_IMPORTS = {
    "Discord": "react-icons/fa: FaDiscord",
    "Facebook": "react-icons/fa: FaFacebook",
    "FacebookIcon": "react-icons/fa: FaFacebook",
    "Github": "react-icons/fa: FaGithub",
    "GithubIcon": "react-icons/fa: FaGithub",
    "GitHub": "react-icons/fa: FaGithub",
    "GitHubIcon": "react-icons/fa: FaGithub",
    "Gitlab": "react-icons/fa: FaGitlab",
    "GitlabIcon": "react-icons/fa: FaGitlab",
    "Instagram": "react-icons/fa: FaInstagram",
    "InstagramIcon": "react-icons/fa: FaInstagram",
    "LinkedIn": "react-icons/fa: FaLinkedinIn",
    "LinkedInIcon": "react-icons/fa: FaLinkedinIn",
    "Linkedin": "react-icons/fa: FaLinkedinIn",
    "LinkedinIcon": "react-icons/fa: FaLinkedinIn",
    "Twitter": "react-icons/fa: FaXTwitter or FaTwitter",
    "TwitterIcon": "react-icons/fa: FaXTwitter or FaTwitter",
    "XTwitter": "react-icons/fa: FaXTwitter",
    "XTwitterIcon": "react-icons/fa: FaXTwitter",
    "Youtube": "react-icons/fa: FaYoutube",
    "YoutubeIcon": "react-icons/fa: FaYoutube",
}

_IMPORT_FROM_PATTERN = re.compile(
    r"(?P<prefix>\bimport\s+(?:type\s+)?|\bexport\s+(?:type\s+)?)(?P<imports>[\s\S]*?)\s+from\s+['\"](?P<specifier>[^'\"]+)['\"]",
    re.MULTILINE,
)


@dataclass(frozen=True, slots=True)
class PrototypeValidationIssue:
    code: str
    message: str
    file_path: str
    package_name: str | None = None
    import_name: str | None = None
    suggestion: str | None = None


def validate_prototype_preview_files(
    files: dict[str, dict[str, str]],
    *,
    entry_file: str,
    framework: str,
) -> list[PrototypeValidationIssue]:
    if framework.strip().lower() != "react":
        return []

    issues: list[PrototypeValidationIssue] = []
    for file_path, payload in files.items():
        code = str(payload.get("code") or "")
        for specifier, import_names in _iter_imports(code):
            package_name = _package_name(specifier)
            if not package_name:
                continue
            if package_name not in SUPPORTED_PREVIEW_PACKAGES:
                issues.append(
                    PrototypeValidationIssue(
                        code="unsupported_preview_dependency",
                        message=(
                            f"Preview runtime does not include '{package_name}'. "
                            "Use a supported dependency or implement a React/CSS fallback."
                        ),
                        file_path=file_path,
                        package_name=package_name,
                    )
                )
                continue
            if package_name == "lucide-react":
                for import_name in import_names:
                    suggestion = LUCIDE_REACT_UNSUPPORTED_BRAND_IMPORTS.get(import_name)
                    if suggestion:
                        issues.append(
                            PrototypeValidationIssue(
                                code="unsupported_lucide_brand_icon",
                                message=(
                                    f"lucide-react in the preview runtime does not export '{import_name}'. "
                                    f"Use {suggestion} for brand icons, or replace it with a generic lucide icon."
                                ),
                                file_path=file_path,
                                package_name=package_name,
                                import_name=import_name,
                                suggestion=suggestion,
                            )
                        )

    normalized_entry = _normalize_path(entry_file)
    entry_payload = files.get(normalized_entry)
    if entry_payload is not None and normalized_entry.endswith((".tsx", ".jsx")):
        entry_code = str(entry_payload.get("code") or "")
        if "export default" not in entry_code:
            issues.append(
                PrototypeValidationIssue(
                    code="missing_default_export",
                    message=f"{normalized_entry} should export a default React component for the preview panel.",
                    file_path=normalized_entry,
                )
            )

    return issues


def validation_issues_payload(issues: list[PrototypeValidationIssue]) -> list[dict[str, Any]]:
    return [
        {
            "code": issue.code,
            "message": issue.message,
            "filePath": issue.file_path,
            "packageName": issue.package_name,
            "importName": issue.import_name,
            "suggestion": issue.suggestion,
        }
        for issue in issues
    ]


def _iter_imports(code: str) -> list[tuple[str, list[str]]]:
    imports: list[tuple[str, list[str]]] = []
    for match in _IMPORT_FROM_PATTERN.finditer(code):
        imports.append((match.group("specifier"), _named_imports(match.group("imports"))))
    return imports


def _named_imports(import_clause: str) -> list[str]:
    open_index = import_clause.find("{")
    close_index = import_clause.find("}", open_index + 1)
    if open_index < 0 or close_index < 0:
        return []
    names: list[str] = []
    body = import_clause[open_index + 1 : close_index]
    for raw_part in body.split(","):
        part = raw_part.strip()
        if not part:
            continue
        if part.startswith("type "):
            part = part[5:].strip()
        name = part.split(" as ", 1)[0].strip()
        if name:
            names.append(name)
    return names


def _package_name(specifier: str) -> str:
    normalized = specifier.strip()
    if not normalized or normalized.startswith(".") or normalized.startswith("/"):
        return ""
    parts = normalized.split("/")
    if normalized.startswith("@"):
        return "/".join(parts[:2]) if len(parts) >= 2 else normalized
    return parts[0]


def _normalize_path(value: str) -> str:
    text = str(value or "").replace("\\", "/").strip()
    if not text:
        return ""
    return text if text.startswith("/") else f"/{text}"
