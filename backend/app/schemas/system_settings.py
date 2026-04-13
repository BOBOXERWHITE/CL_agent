from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class EditableSystemSettings(BaseModel):
    default_tenant_id: str = Field(min_length=1)
    default_customer_id: str = Field(min_length=1)
    chat_top_k: int = Field(ge=1, le=20)
    chat_confidence_threshold: float = Field(ge=0.0, le=1.0)
    default_eval_dataset: str = Field(min_length=1)


class RuntimeSystemSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    llm_provider: str
    llm_model_name: str
    embedding_provider: str
    embedding_model_name: str
    embedding_dimension: int
    vector_store_provider: str
    auth_enabled: bool


class SystemSettingsResponse(BaseModel):
    editable_settings: EditableSystemSettings
    runtime_settings: RuntimeSystemSettings
