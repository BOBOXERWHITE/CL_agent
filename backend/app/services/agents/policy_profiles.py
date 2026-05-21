from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

QuestionFacts = dict[str, Any]
Subquestion = dict[str, str]


@dataclass(frozen=True)
class PolicyDomainProfile:
    domain: str
    specialist: str
    label: str
    confidence: float
    keywords: tuple[str, ...]
    dimension_labels: dict[str, str] = field(default_factory=dict)
    interrupt_reason: str = "policy answer does not cover all required dimensions"
    extract_facts_fn: Callable[[str], QuestionFacts] | None = None
    required_dimensions_fn: Callable[[str, QuestionFacts], list[str]] | None = None
    subquestion_builder_fn: Callable[[str, QuestionFacts, list[str]], list[Subquestion]] | None = (
        None
    )

    def extract_facts(self, question: str) -> QuestionFacts:
        if self.extract_facts_fn is None:
            return {}
        return self.extract_facts_fn(question)

    def required_dimensions(self, question: str, facts: QuestionFacts) -> list[str]:
        if self.required_dimensions_fn is None:
            return []
        return self.required_dimensions_fn(question, facts)

    def build_subquestions(
        self,
        question: str,
        facts: QuestionFacts,
        required_dimensions: list[str],
    ) -> list[Subquestion]:
        if self.subquestion_builder_fn is None:
            return [{"dimension": "primary", "question": question}]
        return self.subquestion_builder_fn(question, facts, required_dimensions)


_CITY_PATTERN = re.compile(
    r"(北京|上海|广州|深圳|成都|杭州|南京|苏州|重庆|天津|武汉|西安|纽约|东京)",
)
_LEVEL_PATTERN = re.compile(r"\bL([1-9])\b", re.IGNORECASE)
_RATE_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:元/晚|元|cny/晚|cny|rmb/晚|rmb)",
    re.IGNORECASE,
)
_INVOICE_ITEM_PATTERN = re.compile(r"(住宿费|餐饮费|商务服务费|代订住宿费)")

_HOTEL_KEYWORDS: tuple[str, ...] = (
    "酒店",
    "住宿",
    "房费",
    "含早",
    "早餐",
    "folio",
    "入住",
    "离店",
    "walk",
)
_FLIGHT_KEYWORDS: tuple[str, ...] = (
    "机票",
    "航班",
    "舱位",
    "商务舱",
    "经济舱",
    "头等舱",
    "business class",
    "economy class",
    "first class",
    "改签",
    "退票",
)
_REIMBURSEMENT_KEYWORDS: tuple[str, ...] = (
    "报销",
    "发票",
    "税号",
    "抬头",
    "进项税",
    "补贴",
    "审批",
    "行程单",
    "付款凭证",
    "住宿单",
)


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    normalized = text.lower()
    return any(keyword.lower() in normalized for keyword in keywords)


def _detect_booking_channel(question: str) -> str | None:
    upper = question.upper()
    if "OBT" in upper:
        return "OBT"
    if "TMC" in upper:
        return "TMC"
    if "OTA" in upper:
        return "OTA"
    return None


def _extract_common_city_and_level(question: str) -> QuestionFacts:
    facts: QuestionFacts = {}
    city_match = _CITY_PATTERN.search(question)
    if city_match:
        facts["city"] = city_match.group(1)
    level_match = _LEVEL_PATTERN.search(question)
    if level_match:
        facts["employee_level"] = f"L{level_match.group(1)}"
    return facts


def _with_primary(question: str, items: list[Subquestion]) -> list[Subquestion]:
    return [{"dimension": "primary", "question": question}, *items]


def _extract_hotel_facts(question: str) -> QuestionFacts:
    facts = _extract_common_city_and_level(question)
    rate_match = _RATE_PATTERN.search(question)
    if rate_match:
        facts["nightly_rate"] = float(rate_match.group(1))
    if "含早" in question or "早餐" in question:
        facts["contains_breakfast"] = True
    if "周五" in question and "周一" in question:
        facts["weekend_stay_pattern"] = "friday_to_monday"
    if "发票" in question:
        facts["invoice_present"] = True
    if "抬头" in question:
        facts["invoice_title_present"] = True
    if "税号" in question:
        facts["tax_id_present"] = True
    invoice_items = _INVOICE_ITEM_PATTERN.findall(question)
    if invoice_items:
        facts["invoice_items"] = sorted(set(invoice_items))
    booking_channel = _detect_booking_channel(question)
    if booking_channel:
        facts["booking_channel"] = booking_channel
    return facts


def _hotel_required_dimensions(question: str, facts: QuestionFacts) -> list[str]:
    dimensions: list[str] = ["room_rate_standard"]
    if facts.get("contains_breakfast") or "早餐" in question:
        dimensions.append("breakfast_allowance")
    if facts.get("invoice_present") or "进项税" in question or "发票" in question:
        dimensions.append("invoice_tax")
    if facts.get("weekend_stay_pattern"):
        dimensions.append("weekend_stay_justification")
    if facts.get("booking_channel") or "协议价" in question or "预订" in question:
        dimensions.append("booking_channel_compliance")
    return dimensions


def _hotel_subquestions(
    question: str,
    facts: QuestionFacts,
    required_dimensions: list[str],
) -> list[Subquestion]:
    city = str(facts.get("city", "该出差城市"))
    level = str(facts.get("employee_level", "该员工级别"))
    items: list[Subquestion] = []
    for dimension in required_dimensions:
        if dimension == "room_rate_standard":
            items.append(
                {
                    "dimension": dimension,
                    "question": (
                        f"根据酒店差旅政策，{level}在{city}的每晚住宿标准、超标阈值和审批要求是什么？"
                    ),
                }
            )
        elif dimension == "breakfast_allowance":
            items.append(
                {
                    "dimension": dimension,
                    "question": "根据酒店差旅政策，酒店含早时早餐补贴或餐补应该如何处理？",
                }
            )
        elif dimension == "invoice_tax":
            items.append(
                {
                    "dimension": dimension,
                    "question": (
                        "根据酒店开票与税务政策，发票抬头、税号、住宿费与餐饮费分开开票时，"
                        "哪些可以报销，哪些可以抵扣？"
                    ),
                }
            )
        elif dimension == "weekend_stay_justification":
            items.append(
                {
                    "dimension": dimension,
                    "question": "根据酒店差旅政策，周五入住周一离店是否需要周末停留说明或公务证明？",
                }
            )
        elif dimension == "booking_channel_compliance":
            items.append(
                {
                    "dimension": dimension,
                    "question": "根据酒店差旅政策，通过 OBT、TMC、OTA 等渠道预订时，有哪些合规要求和例外审批规则？",
                }
            )
    return _with_primary(question, items)


def _extract_flight_facts(question: str) -> QuestionFacts:
    facts = _extract_common_city_and_level(question)
    lowered = question.lower()
    if "国内" in question or "境内" in question:
        facts["trip_scope"] = "domestic"
    elif "国际" in question or "海外" in question or "出境" in question:
        facts["trip_scope"] = "international"

    if "商务舱" in question or "business class" in lowered:
        facts["cabin_requested"] = "business"
    elif "头等舱" in question or "first class" in lowered:
        facts["cabin_requested"] = "first"
    elif "高端经济舱" in question or "premium economy" in lowered:
        facts["cabin_requested"] = "premium_economy"
    elif "经济舱" in question or "economy class" in lowered:
        facts["cabin_requested"] = "economy"

    if any(keyword in question for keyword in ("改签", "退票", "取消", "no-show")):
        facts["change_or_refund"] = True

    booking_channel = _detect_booking_channel(question)
    if booking_channel:
        facts["booking_channel"] = booking_channel
    if "审批" in question:
        facts["approval_context"] = True
    return facts


def _flight_required_dimensions(question: str, facts: QuestionFacts) -> list[str]:
    dimensions: list[str] = ["cabin_policy"]
    if facts.get("cabin_requested") in {"business", "first", "premium_economy"} or facts.get(
        "approval_context"
    ):
        dimensions.append("approval_requirement")
    if facts.get("change_or_refund"):
        dimensions.append("change_refund_policy")
    if facts.get("booking_channel") or "预订" in question or "下单" in question:
        dimensions.append("booking_channel_compliance")
    return dimensions


def _flight_subquestions(
    question: str,
    facts: QuestionFacts,
    required_dimensions: list[str],
) -> list[Subquestion]:
    trip_scope = (
        "国内"
        if facts.get("trip_scope") == "domestic"
        else "国际"
        if facts.get("trip_scope") == "international"
        else "该次"
    )
    cabin = str(facts.get("cabin_requested", "目标舱位"))
    items: list[Subquestion] = []
    for dimension in required_dimensions:
        if dimension == "cabin_policy":
            items.append(
                {
                    "dimension": dimension,
                    "question": f"根据机票差旅政策，{trip_scope}出差默认可预订哪些舱位，{cabin}是否符合默认规则？",
                }
            )
        elif dimension == "approval_requirement":
            items.append(
                {
                    "dimension": dimension,
                    "question": f"根据机票差旅政策，预订 {cabin} 或其他例外舱位时，需要哪些审批条件和前置要求？",
                }
            )
        elif dimension == "change_refund_policy":
            items.append(
                {
                    "dimension": dimension,
                    "question": "根据机票差旅政策，改签、退票或取消时，费用承担、审批和操作规则是什么？",
                }
            )
        elif dimension == "booking_channel_compliance":
            items.append(
                {
                    "dimension": dimension,
                    "question": "根据机票差旅政策，通过 OBT、TMC 或其他渠道预订机票时，有哪些合规要求和例外审批规则？",
                }
            )
    return _with_primary(question, items)


def _extract_reimbursement_facts(question: str) -> QuestionFacts:
    facts = _extract_common_city_and_level(question)
    if "发票" in question:
        facts["invoice_present"] = True
    if "抬头" in question:
        facts["invoice_title_present"] = True
    if "税号" in question:
        facts["tax_id_present"] = True
    invoice_items = _INVOICE_ITEM_PATTERN.findall(question)
    if invoice_items:
        facts["invoice_items"] = sorted(set(invoice_items))
    if any(keyword in question for keyword in ("补贴", "餐补", "津贴", "定额", "含早")):
        facts["allowance_context"] = True
    if any(keyword in question for keyword in ("审批", "超标", "例外")):
        facts["approval_context"] = True

    document_hits = [
        keyword
        for keyword in (
            "行程单",
            "入住单",
            "folio",
            "审批单",
            "付款凭证",
            "登机牌",
            "合同",
            "对账单",
        )
        if keyword.lower() in question.lower()
    ]
    if document_hits:
        facts["supporting_documents"] = document_hits
    return facts


def _reimbursement_required_dimensions(question: str, facts: QuestionFacts) -> list[str]:
    dimensions: list[str] = ["invoice_tax"]
    if facts.get("approval_context") or "报销" in question:
        dimensions.append("approval_requirement")
    if facts.get("allowance_context"):
        dimensions.append("allowance_policy")
    if facts.get("supporting_documents") or "报销" in question or "材料" in question:
        dimensions.append("supporting_documents")
    return dimensions


def _reimbursement_subquestions(
    question: str,
    facts: QuestionFacts,
    required_dimensions: list[str],
) -> list[Subquestion]:
    items: list[Subquestion] = []
    for dimension in required_dimensions:
        if dimension == "invoice_tax":
            items.append(
                {
                    "dimension": dimension,
                    "question": (
                        "根据报销合规政策，发票抬头、税号、发票项目、专票或普票，以及进项税分别如何处理？"
                    ),
                }
            )
        elif dimension == "approval_requirement":
            items.append(
                {
                    "dimension": dimension,
                    "question": "根据报销合规政策，超标、例外或补录报销时，需要哪些审批与补充说明材料？",
                }
            )
        elif dimension == "allowance_policy":
            items.append(
                {
                    "dimension": dimension,
                    "question": "根据报销合规政策，餐补、住宿补贴、含早和定额补贴之间如何抵扣或互斥？",
                }
            )
        elif dimension == "supporting_documents":
            items.append(
                {
                    "dimension": dimension,
                    "question": "根据报销合规政策，提交报销时需要哪些行程单、入住单、付款凭证、审批单或其他支持材料？",
                }
            )
    return _with_primary(question, items)


HOTEL_PROFILE = PolicyDomainProfile(
    domain="hotel",
    specialist="hotel_policy_agent",
    label="酒店",
    confidence=0.92,
    keywords=_HOTEL_KEYWORDS,
    dimension_labels={
        "room_rate_standard": "房费标准与超标审批",
        "breakfast_allowance": "含早与餐补处理",
        "invoice_tax": "发票项目与进项税处理",
        "weekend_stay_justification": "周末停留说明",
        "booking_channel_compliance": "预订渠道合规",
    },
    interrupt_reason="酒店政策答案未覆盖全部必答维度",
    extract_facts_fn=_extract_hotel_facts,
    required_dimensions_fn=_hotel_required_dimensions,
    subquestion_builder_fn=_hotel_subquestions,
)

FLIGHT_PROFILE = PolicyDomainProfile(
    domain="flight",
    specialist="flight_policy_agent",
    label="机票",
    confidence=0.87,
    keywords=_FLIGHT_KEYWORDS,
    dimension_labels={
        "cabin_policy": "舱位规则",
        "approval_requirement": "审批要求",
        "change_refund_policy": "改签退票规则",
        "booking_channel_compliance": "预订渠道合规",
    },
    interrupt_reason="机票政策答案未覆盖全部必答维度",
    extract_facts_fn=_extract_flight_facts,
    required_dimensions_fn=_flight_required_dimensions,
    subquestion_builder_fn=_flight_subquestions,
)

REIMBURSEMENT_PROFILE = PolicyDomainProfile(
    domain="reimbursement",
    specialist="reimbursement_policy_agent",
    label="报销",
    confidence=0.85,
    keywords=_REIMBURSEMENT_KEYWORDS,
    dimension_labels={
        "invoice_tax": "发票与税务处理",
        "approval_requirement": "审批与例外流程",
        "allowance_policy": "补贴与定额政策",
        "supporting_documents": "报销材料完整性",
    },
    interrupt_reason="报销政策答案未覆盖全部必答维度",
    extract_facts_fn=_extract_reimbursement_facts,
    required_dimensions_fn=_reimbursement_required_dimensions,
    subquestion_builder_fn=_reimbursement_subquestions,
)

POLICY_PROFILES: tuple[PolicyDomainProfile, ...] = (
    HOTEL_PROFILE,
    FLIGHT_PROFILE,
    REIMBURSEMENT_PROFILE,
)

_PROFILE_BY_DOMAIN = {profile.domain: profile for profile in POLICY_PROFILES}
_PROFILE_BY_SPECIALIST = {profile.specialist: profile for profile in POLICY_PROFILES}


def match_policy_profile(question: str) -> PolicyDomainProfile | None:
    for profile in POLICY_PROFILES:
        if _contains_any(question, profile.keywords):
            return profile
    return None


def match_policy_profiles(question: str) -> list[PolicyDomainProfile]:
    return [profile for profile in POLICY_PROFILES if _contains_any(question, profile.keywords)]


def get_policy_profile(domain: str) -> PolicyDomainProfile | None:
    return _PROFILE_BY_DOMAIN.get(domain)


def get_policy_profile_by_specialist(specialist: str) -> PolicyDomainProfile | None:
    return _PROFILE_BY_SPECIALIST.get(specialist)


__all__ = [
    "FLIGHT_PROFILE",
    "HOTEL_PROFILE",
    "POLICY_PROFILES",
    "REIMBURSEMENT_PROFILE",
    "PolicyDomainProfile",
    "get_policy_profile",
    "get_policy_profile_by_specialist",
    "match_policy_profile",
    "match_policy_profiles",
]
