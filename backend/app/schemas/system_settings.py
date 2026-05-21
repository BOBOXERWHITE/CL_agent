from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# The intelligent-agent router supports a 3-strategy chain (LLM → embedding
# → keyword) — see ``app/services/agents/router.py``. The literal type is
# what the router code feeds into ``_build_chain`` so the page can never
# save a value the router can't honour.
AgentRouterProvider = Literal["llm", "embedding", "keyword"]


class EditableSystemSettings(BaseModel):
    default_tenant_id: str = Field(min_length=1)
    default_customer_id: str = Field(min_length=1)
    chat_top_k: int = Field(ge=1, le=20)
    chat_confidence_threshold: float = Field(ge=0.0, le=1.0)
    default_eval_dataset: str = Field(min_length=1)
    agent_router_provider: AgentRouterProvider = "keyword"
    # P11: how many prior turns to inject into the LLM messages array.
    # 0 disables multi-turn context (the legacy single-shot behaviour).
    chat_history_max_turns: int = Field(ge=0, le=20, default=5)


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
