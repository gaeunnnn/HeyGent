from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AgentInstructionDocumentResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    document_id: str | None = Field(default=None, alias="documentId")
    document_key: str = Field(alias="documentKey")
    display_name: str = Field(alias="displayName")
    content_format: str = Field(default="markdown", alias="contentFormat")
    content: str = ""
    version: int = 1


class AgentInstructionBundleResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    bundle_id: str = Field(alias="bundleId")
    profile_id: str = Field(alias="profileId")
    mode: str = "managed"
    entry_document_key: str = Field(alias="entryDocumentKey")
    documents: list[AgentInstructionDocumentResponse] = Field(default_factory=list)


class AgentTemplateResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    template_id: str = Field(alias="templateId")
    template_key: str = Field(alias="templateKey")
    template_version: int = Field(alias="templateVersion")
    display_name: str = Field(alias="displayName")
    name: str
    role: str
    title: str
    description: str
    adapter_type: str = Field(alias="adapterType")
    model: str | None = None
    profile_image: str | None = Field(default=None, alias="profileImage")
    visual_key: str | None = Field(default=None, alias="visualKey")
    skills: list[str] = Field(default_factory=list)
    entry_document_key: str = Field(alias="entryDocumentKey")
    documents: list[AgentInstructionDocumentResponse] = Field(default_factory=list)


class AgentProfileResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    profile_id: str = Field(alias="profileId")
    session_id: str | None = Field(default=None, alias="sessionId")
    profile_key: str = Field(alias="profileKey")
    profile_version: int = Field(alias="profileVersion")
    agent_type: str = Field(alias="agentType")
    template_key: str | None = Field(default=None, alias="templateKey")
    name: str
    role: str
    title: str | None = None
    description: str | None = None
    adapter_type: str | None = Field(default=None, alias="adapterType")
    model: str | None = None
    profile_image: str | None = Field(default=None, alias="profileImage")
    visual_key: str | None = Field(default=None, alias="visualKey")
    skills: list[str] = Field(default_factory=list)
    instruction_bundle_id: str | None = Field(default=None, alias="instructionBundleId")
    entry_document_key: str | None = Field(default=None, alias="entryDocumentKey")
    config_snapshot: dict[str, Any] = Field(default_factory=dict, alias="configSnapshot")


class AgentTemplateListResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    items: list[AgentTemplateResponse] = Field(default_factory=list)


class AgentProfileListResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    items: list[AgentProfileResponse] = Field(default_factory=list)


class SkillCatalogItemResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    skill_id: str = Field(alias="skillId")
    name: str
    display_name: str = Field(alias="displayName")
    description: str = ""
    source_type: str = Field(default="builtin", alias="sourceType")
    source_path: str | None = Field(default=None, alias="sourcePath")
    version: int = 1
    enabled: bool = True
    default_enabled: bool = Field(default=True, alias="defaultEnabled")


class SkillCatalogDocumentResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    document_key: str = Field(alias="documentKey")
    title: str
    content: str = ""
    content_format: str = Field(default="markdown", alias="contentFormat")


class SkillCatalogDetailResponse(SkillCatalogItemResponse):
    body: str = ""
    files: list[str] = Field(default_factory=list)
    documents: list[SkillCatalogDocumentResponse] = Field(default_factory=list)


class SkillCatalogListResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    items: list[SkillCatalogItemResponse] = Field(default_factory=list)


class CustomSkillDocumentRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    document_key: str = Field(alias="documentKey")
    title: str | None = None
    content: str
    content_format: str = Field(default="markdown", alias="contentFormat")


class CreateCustomSkillRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    name: str
    display_name: str | None = Field(default=None, alias="displayName")
    description: str = ""
    body: str
    documents: list[CustomSkillDocumentRequest] = Field(default_factory=list)
    source_url: str | None = Field(default=None, alias="sourceUrl")


class GenerateCustomSkillDraftRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    goal: str


class ImportCustomSkillUrlRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    url: str


class CustomSkillDraftResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str
    display_name: str = Field(alias="displayName")
    description: str = ""
    body: str
    documents: list[SkillCatalogDocumentResponse] = Field(default_factory=list)
    source_url: str | None = Field(default=None, alias="sourceUrl")


class UpdateUserSkillSettingRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    enabled: bool


class CreateSessionAgentFromTemplateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    template_key: str = Field(alias="templateKey")


class CreateSessionAgentRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    name: str
    role: str = "general"
    title: str | None = None
    description: str | None = None
    adapter_type: str | None = Field(default=None, alias="adapterType")
    model: str | None = None
    profile_image: str | None = Field(default=None, alias="profileImage")
    skills: list[str] = Field(default_factory=list)
    entry_document_key: str = Field(default="AGENTS.md", alias="entryDocumentKey")
    instructions_files: dict[str, str] = Field(default_factory=dict, alias="instructionsFiles")


class UpdateSessionAgentRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    name: str | None = None
    role: str | None = None
    title: str | None = None
    description: str | None = None
    adapter_type: str | None = Field(default=None, alias="adapterType")
    model: str | None = None
    profile_image: str | None = Field(default=None, alias="profileImage")
    skills: list[str] | None = None
    entry_document_key: str | None = Field(default=None, alias="entryDocumentKey")
    instructions_files: dict[str, str] | None = Field(default=None, alias="instructionsFiles")


class SaveInstructionDocumentRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    document_key: str = Field(alias="documentKey")
    display_name: str = Field(alias="displayName")
    content: str
