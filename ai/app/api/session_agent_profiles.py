from __future__ import annotations

from typing import Any


def agent_profile_prompt_payload(profile: dict[str, Any], *, skill_registry: Any | None = None) -> dict[str, Any]:
    payload = {
        "profileId": profile.get("profile_id"),
        "profileKey": profile.get("profile_key"),
        "agentType": profile.get("agent_type"),
        "templateKey": profile.get("template_key"),
        "configSnapshot": profile.get("config_snapshot") or {},
    }
    skill_descriptions = _profile_skill_descriptions(payload, skill_registry=skill_registry)
    if skill_descriptions:
        payload["skillDescriptions"] = skill_descriptions
    return payload


def instruction_bundle_prompt_payload(bundle: dict[str, Any]) -> dict[str, Any]:
    return {
        "bundleId": bundle.get("bundle_id"),
        "entryDocumentKey": bundle.get("entry_document_key") or "AGENTS.md",
        "documents": [
            {
                "documentKey": document.get("document_key") or document.get("documentKey"),
                "displayName": document.get("display_name") or document.get("displayName"),
                "content": document.get("content") or "",
            }
            for document in list(bundle.get("documents") or [])
            if isinstance(document, dict)
        ],
    }


def profile_model(profile: dict[str, Any] | None) -> str | None:
    if profile is None:
        return None
    config = profile.get("config_snapshot") if isinstance(profile.get("config_snapshot"), dict) else {}
    value = config.get("model") or profile.get("model_name")
    text = str(value or "").strip()
    return text or None


def profile_provider_name(profile: dict[str, Any] | None) -> str | None:
    if profile is None:
        return None
    config = profile.get("config_snapshot") if isinstance(profile.get("config_snapshot"), dict) else {}
    model = str(config.get("model") or profile.get("model_name") or "").strip()
    if model.lower().startswith("gemini-"):
        return "gemini_api_key"
    value = config.get("providerName") or config.get("provider_name") or config.get("adapterType") or profile.get("provider_name")
    text = str(value or "").strip()
    if text == "openai":
        return "openai_api_key"
    if text == "gemini":
        return "gemini_api_key"
    return text or None


def _profile_skill_descriptions(profile_payload: dict[str, Any], *, skill_registry: Any | None) -> list[dict[str, str]]:
    skills = getattr(skill_registry, "_skills", {}) if skill_registry is not None else {}
    if not isinstance(skills, dict):
        return []
    config = profile_payload.get("configSnapshot")
    if not isinstance(config, dict):
        return []
    descriptions: list[dict[str, str]] = []
    for skill_name in [str(skill).strip() for skill in list(config.get("skills") or []) if str(skill).strip()]:
        skill = skills.get(skill_name)
        if not isinstance(skill, dict):
            continue
        descriptions.append(
            {
                "name": skill_name,
                "description": str(skill.get("description") or "").strip(),
            }
        )
    return descriptions
