from __future__ import annotations

from dataclasses import dataclass

from app.services.agents.policy_profiles import match_policy_profile, match_policy_profiles


@dataclass(frozen=True)
class PolicyDomainDecision:
    domain: str
    specialist: str
    confidence: float
    fallback_reason: str | None = None


def choose_policy_specialist_plan(question: str) -> list[PolicyDomainDecision]:
    profiles = match_policy_profiles(question)
    if profiles:
        return [
            PolicyDomainDecision(
                domain=profile.domain,
                specialist=profile.specialist,
                confidence=profile.confidence,
            )
            for profile in profiles
        ]
    return [
        PolicyDomainDecision(
            domain="generic",
            specialist="generic_policy_agent",
            confidence=0.55,
            fallback_reason="no policy specialist signal detected; fallback to generic policy path",
        )
    ]


def choose_policy_specialist(question: str) -> PolicyDomainDecision:
    profile = match_policy_profile(question)
    if profile is not None:
        return PolicyDomainDecision(
            domain=profile.domain,
            specialist=profile.specialist,
            confidence=profile.confidence,
        )
    return PolicyDomainDecision(
        domain="generic",
        specialist="generic_policy_agent",
        confidence=0.55,
        fallback_reason="no policy specialist signal detected; fallback to generic policy path",
    )


__all__ = ["PolicyDomainDecision", "choose_policy_specialist", "choose_policy_specialist_plan"]
