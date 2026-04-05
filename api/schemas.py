"""Pydantic request/response models for the Learning Agent API."""

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    type: str
    message: str
    pending_action: dict | None = None


class ConfirmRequest(BaseModel):
    action_data: dict


# ---------------------------------------------------------------------------
# Concepts
# ---------------------------------------------------------------------------


class CreateConceptRequest(BaseModel):
    title: str = Field(..., max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    topic_ids: list[int] | None = None
    topic_titles: list[str] | None = None


class UpdateConceptRequest(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class RemarkRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=2000)


# ---------------------------------------------------------------------------
# Topics
# ---------------------------------------------------------------------------


class CreateTopicRequest(BaseModel):
    title: str = Field(..., max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    parent_ids: list[int] | None = None


class UpdateTopicRequest(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class TopicLinkRequest(BaseModel):
    parent_id: int
    child_id: int


# ---------------------------------------------------------------------------
# Relations
# ---------------------------------------------------------------------------


class CreateRelationRequest(BaseModel):
    concept_id_a: int
    concept_id_b: int
    relation_type: str = "builds_on"


class RemoveRelationRequest(BaseModel):
    concept_id_a: int
    concept_id_b: int


# ---------------------------------------------------------------------------
# Persona
# ---------------------------------------------------------------------------


class PersonaRequest(BaseModel):
    name: str
