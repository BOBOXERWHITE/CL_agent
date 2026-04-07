from __future__ import annotations

from dataclasses import dataclass

from app.services.rag.text_processing import normalize_text


@dataclass(frozen=True)
class QueryRewriteResult:
    original_query: str
    expanded_query: str
    applied_rules: list[str]


ALIAS_RULES: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    ("住宿别名", ("住宿", "住宿标准", "hotel"), ("酒店", "报销上限", "住宿标准")),
    ("舱位别名", ("business class", "商务舱"), ("economy class", "经济舱", "审批")),
    ("报销别名", ("reimbursement", "报销"), ("报销上限", "费用标准")),
)


def rewrite_query(question: str) -> QueryRewriteResult:
    normalized = normalize_text(question)
    additions: list[str] = []
    applied_rules: list[str] = []

    for rule_name, triggers, expansions in ALIAS_RULES:
        if any(trigger in normalized for trigger in triggers):
            additions.extend(expansions)
            applied_rules.append(rule_name)

    expanded_query = " ".join(part for part in [question, *additions] if part).strip()
    return QueryRewriteResult(
        original_query=question,
        expanded_query=expanded_query,
        applied_rules=applied_rules,
    )
