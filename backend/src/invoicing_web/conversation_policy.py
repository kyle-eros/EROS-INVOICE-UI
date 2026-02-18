from __future__ import annotations

from dataclasses import dataclass

from .models import ConversationAction, ConversationThreadStatus

_RISKY_KEYWORDS = {
    "chargeback",
    "lawsuit",
    "lawyer",
    "attorney",
    "fraud",
    "scam",
    "harass",
    "threat",
    "report you",
    "police",
    "legal",
    "dispute",
}


@dataclass(frozen=True)
class ConversationPolicyDecision:
    action: ConversationAction
    reason: str



def _contains_risky_content(body_text: str) -> bool:
    normalized = body_text.lower()
    return any(keyword in normalized for keyword in _RISKY_KEYWORDS)



def evaluate_conversation_policy(
    *,
    thread_status: ConversationThreadStatus,
    inbound_text: str,
    suggested_confidence: float,
    auto_reply_count: int,
    confidence_threshold: float,
    max_auto_replies: int,
) -> ConversationPolicyDecision:
    if thread_status in {"human_handoff", "agent_paused"}:
        return ConversationPolicyDecision(action="no_reply", reason="thread_not_automated")

    if _contains_risky_content(inbound_text):
        return ConversationPolicyDecision(action="handoff", reason="risky_content")

    if auto_reply_count >= max_auto_replies:
        return ConversationPolicyDecision(action="handoff", reason="max_auto_replies_reached")

    if suggested_confidence < confidence_threshold:
        return ConversationPolicyDecision(action="handoff", reason="confidence_below_threshold")

    return ConversationPolicyDecision(action="respond", reason="policy_ok")



def default_eros_reply(inbound_text: str) -> str:
    body = inbound_text.strip()
    if "?" in body:
        return (
            "Thanks for checking in. We reviewed your account and are on it now. "
            "If you want, I can share the latest invoice status and next payment steps in one message."
        )

    return (
        "Thanks for the update. We have this in progress and will keep you posted with the next step shortly."
    )
