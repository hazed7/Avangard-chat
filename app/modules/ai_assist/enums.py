from enum import StrEnum


class RewriteStyle(StrEnum):
    FORMAL = "formal"
    CASUAL = "casual"
    SHORTER = "shorter"
    CLEARER = "clearer"
    FRIENDLY = "friendly"
    ASSERTIVE = "assertive"


STYLE_PROMPTS: dict[RewriteStyle, str] = {
    RewriteStyle.FORMAL: (
        "Rewrite the message in a formal, professional tone. "
        "Remove slang and casual expressions. Keep the original meaning."
    ),
    RewriteStyle.CASUAL: (
        "Rewrite the message in a casual, conversational tone. "
        "Make it sound natural and relaxed. Keep the original meaning."
    ),
    RewriteStyle.SHORTER: (
        "Rewrite the message making it significantly shorter. "
        "Remove filler words and redundancy. Keep all key information."
    ),
    RewriteStyle.CLEARER: (
        "Rewrite the message to be clearer and more precise. "
        "Remove ambiguity. Keep the original meaning and tone."
    ),
    RewriteStyle.FRIENDLY: (
        "Rewrite the message in a warm, friendly tone. "
        "Make it feel approachable and positive. Keep the original meaning."
    ),
    RewriteStyle.ASSERTIVE: (
        "Rewrite the message in a confident, assertive tone. "
        "Remove hedging phrases like 'maybe', 'I think', 'sort of'. "
        "Keep the original meaning."
    ),
}
