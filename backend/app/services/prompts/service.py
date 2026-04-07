from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.prompt_template import PromptTemplate


DEFAULT_POLICY_PROMPT = """你是企业差旅政策助手。请只基于给定证据回答问题。
如果证据不足，请明确说明证据不足。
回答时优先给出结论，再说明依据。"""


@dataclass(frozen=True)
class PromptSelection:
    id: str | None
    name: str
    task_type: str
    template: str
    version: int


def list_prompt_templates(session: Session) -> list[PromptTemplate]:
    rows = session.execute(
        select(PromptTemplate).order_by(PromptTemplate.task_type.asc(), PromptTemplate.version.desc())
    ).scalars()
    return list(rows)


def create_prompt_template(
    session: Session,
    *,
    name: str,
    task_type: str,
    template: str,
) -> PromptTemplate:
    next_version = (
        session.execute(
            select(func.coalesce(func.max(PromptTemplate.version), 0)).where(PromptTemplate.task_type == task_type)
        ).scalar_one()
        + 1
    )

    prompt_template = PromptTemplate(
        id=str(uuid4()),
        name=name,
        task_type=task_type,
        template=template,
        version=next_version,
        status="draft",
    )
    session.add(prompt_template)
    session.commit()
    session.refresh(prompt_template)
    return prompt_template


def activate_prompt_template(session: Session, prompt_template_id: str) -> PromptTemplate:
    prompt_template = session.get(PromptTemplate, prompt_template_id)
    if prompt_template is None:
        raise LookupError(prompt_template_id)

    session.execute(
        PromptTemplate.__table__.update()
        .where(PromptTemplate.task_type == prompt_template.task_type)
        .values(status="draft")
    )
    prompt_template.status = "active"
    session.add(prompt_template)
    session.commit()
    session.refresh(prompt_template)
    return prompt_template


def get_prompt_selection(session: Session, task_type: str) -> PromptSelection:
    prompt_template = session.execute(
        select(PromptTemplate)
        .where(PromptTemplate.task_type == task_type)
        .where(PromptTemplate.status == "active")
        .order_by(PromptTemplate.version.desc())
        .limit(1)
    ).scalar_one_or_none()

    if prompt_template is not None:
        return PromptSelection(
            id=prompt_template.id,
            name=prompt_template.name,
            task_type=prompt_template.task_type,
            template=prompt_template.template,
            version=prompt_template.version,
        )

    if task_type == "policy_answer":
        return PromptSelection(
            id=None,
            name="系统默认政策问答 Prompt",
            task_type=task_type,
            template=DEFAULT_POLICY_PROMPT,
            version=0,
        )

    return PromptSelection(
        id=None,
        name=f"系统默认 {task_type} Prompt",
        task_type=task_type,
        template="请根据上下文完成当前任务。",
        version=0,
    )
