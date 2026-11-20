"""Deterministic, non-AI baseline analysis.

* Sentiment: VADER lexicon (English only). Results are labelled ``method="lexicon"`` everywhere in the UI and API so
  they are never mistaken for AI output. No confidence score is produced, because a lexicon score is not a
  probability.
* Topics: keyword rules per topic (each topic has an editable keyword list).
* Emotions: keyword cues. This is a text signal only - never a psychological assessment.

This lets the application provide statistics without an AI provider. When an AI provider is configured, users can
re-analyse records with AI; the AI result becomes the current classification and the lexicon result stays in history.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

from langdetect import DetectorFactory, LangDetectException, detect_langs
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

DetectorFactory.seed = 0  # deterministic language detection

LEXICON_VERSION = "vader-3.3.2+rules-v1"

DEFAULT_TOPICS: list[tuple[str, str, list[str]]] = [
    (
        "Product quality",
        "Build quality, defects, durability and how well the product is made.",
        ["quality", "defect", "broken", "broke", "flimsy", "durable", "sturdy", "cheaply made", "well made", "faulty", "damaged", "material"],
    ),
    (
        "Pricing",
        "Price, value for money, fees and billing amounts.",
        ["price", "pricing", "expensive", "cheap", "cost", "overpriced", "value for money", "affordable", "fee", "subscription", "billing", "charged"],
    ),
    (
        "Customer service",
        "Interactions with support or service staff.",
        [
            "customer service",
            "support",
            "agent",
            "staff",
            "representative",
            "helpdesk",
            "help desk",
            "service team",
            "rude",
            "helpful",
            "response time",
            "responded",
        ],
    ),
    (
        "Delivery",
        "Shipping speed, couriers, packaging and arrival condition.",
        ["deliver*", "ship", "shipping", "shipment", "courier", "arrived", "arrival", "package", "packaging", "dispatch", "late", "tracking", "parcel"],
    ),
    (
        "Website usability",
        "Navigating the website, checkout and account pages.",
        ["website", "site", "checkout", "navigation", "navigate", "login", "log in", "sign up", "web page", "webpage"],
    ),
    (
        "Performance",
        "Speed, lag, loading times and responsiveness.",
        ["slow", "speed", "lag", "laggy", "loading", "load time", "performance", "freeze", "freezes", "responsive"],
    ),
    (
        "Reliability",
        "Crashes, outages, bugs and consistency.",
        ["crash*", "bug", "buggy", "outage", "is down", "went down", "error", "unreliable", "reliable", "glitch", "stopped working"],
    ),
    (
        "Documentation",
        "Manuals, guides, help articles and instructions.",
        ["documentation", "docs", "manual", "instructions", "guide", "tutorial", "help article", "faq"],
    ),
    (
        "Communication",
        "Updates, notifications, emails and transparency.",
        ["communication", "email", "emails", "notification", "update", "informed", "no response", "never heard", "kept me posted", "newsletter"],
    ),
    (
        "Refunds",
        "Refunds, returns, cancellations and money back.",
        ["refund*", "return", "returned", "money back", "cancel", "cancellation", "chargeback", "exchange"],
    ),
    (
        "Features",
        "Functionality, missing features and feature requests.",
        ["feature", "features", "functionality", "integration", "option", "wish it had", "would be nice", "missing", "add support", "request"],
    ),
    (
        "User experience",
        "Ease of use, design, onboarding and overall experience.",
        [
            "easy to use",
            "intuitive",
            "confusing",
            "user friendly",
            "user-friendly",
            "design",
            "interface",
            "ui",
            "ux",
            "onboarding",
            "experience",
            "complicated",
        ],
    ),
]

EMOTION_CUES: dict[str, list[str]] = {
    "frustration": ["frustrat*", "annoy*", "fed up", "ridiculous", "unacceptable", "infuriat*", "sick of", "waste of time", "useless"],
    "satisfaction": ["satisfied", "happy with", "pleased", "works well", "worked well", "does the job", "exactly what i needed", "very good"],
    "confusion": ["confus*", "unclear", "don't understand", "do not understand", "not sure how", "how do i", "makes no sense", "lost"],
    "disappointment": ["disappoint*", "let down", "expected better", "expected more", "not worth", "regret", "underwhelm*"],
    "appreciation": ["thank*", "appreciat*", "grateful", "kudos", "shout out", "great job", "well done"],
    "urgency": ["urgent", "asap", "immediately", "right now", "critical", "emergency", "as soon as possible"],
    "concern*": ["worried", "concern", "afraid", "unsafe", "risk", "privacy", "security issue", "scared"],
    "excitement": ["excit*", "can't wait", "cannot wait", "amazing", "awesome", "love it", "loving", "fantastic", "incredible"],
}

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?;])\s+|\n+")
_WORD = re.compile(r"[A-Za-z']+")


@lru_cache(maxsize=1)
def _analyzer() -> SentimentIntensityAnalyzer:
    return SentimentIntensityAnalyzer()


@lru_cache(maxsize=4096)
def _kw_pattern(keyword: str) -> re.Pattern[str]:
    kw = keyword.lower().strip()
    if kw.endswith("*"):  # explicit prefix match: "deliver*" -> delivery, delivered, ...
        return re.compile(r"(?<![a-z0-9])" + re.escape(kw[:-1]))
    # Whole word/phrase, allowing simple inflections ("crash" -> "crashes", "crashed").
    return re.compile(r"(?<![a-z0-9])" + re.escape(kw) + r"(?:s|es|ed|d|ing)?(?![a-z0-9])")


def keyword_hits(text_lower: str, keywords: list[str]) -> list[str]:
    return [kw for kw in keywords if kw and kw.strip() and _kw_pattern(kw).search(text_lower)]


def detect_language(text: str) -> str | None:
    """Return an ISO 639-1 code, or None when the text is too short for a reliable guess."""
    letters = sum(ch.isalpha() for ch in text)
    if letters < 20:
        return None
    try:
        langs = detect_langs(text)
    except LangDetectException:
        return None
    if not langs or langs[0].prob < 0.80:
        return None
    return langs[0].lang


@dataclass
class SentimentResult:
    label: str
    score: float | None
    explanation: str
    evidence: list[str] = field(default_factory=list)
    language: str | None = None


def label_from_compound(compound: float, pos: float, neg: float) -> str:
    if pos >= 0.12 and neg >= 0.12 and abs(compound) < 0.6:
        return "mixed"
    if compound >= 0.05:
        return "positive"
    if compound <= -0.05:
        return "negative"
    return "neutral"


def lexicon_sentiment(text: str) -> SentimentResult:
    language = detect_language(text)
    if language is not None and language != "en":
        return SentimentResult(
            label="uncertain",
            score=None,
            explanation=f"Detected language '{language}'. The rule-based analyser supports English only; use AI analysis for other languages.",
            language=language,
        )
    analyzer = _analyzer()
    scores = analyzer.polarity_scores(text)
    words = [w.lower() for w in _WORD.findall(text)]
    hits = sorted({w for w in words if w in analyzer.lexicon}, key=lambda w: -abs(analyzer.lexicon[w]))
    if len(words) < 3:
        return SentimentResult(
            label="uncertain",
            score=None,
            explanation="Too short to classify reliably with the rule-based analyser.",
            language=language,
        )
    label = label_from_compound(scores["compound"], scores["pos"], scores["neg"])
    explanation = (
        f"Rule-based lexicon score {scores['compound']:+.2f} (positive share {scores['pos']:.2f}, negative share {scores['neg']:.2f}). "
        "Not an AI classification; sarcasm and domain-specific language may be misread."
    )
    return SentimentResult(label=label, score=round(scores["compound"], 4), explanation=explanation, evidence=hits[:5], language=language or "en")


def aspect_sentiment(text: str, keywords: list[str]) -> tuple[str | None, str | None]:
    """Sentiment of the sentences that mention a topic, plus the first matching sentence as evidence."""
    sentences = [s.strip() for s in _SENTENCE_SPLIT.split(text) if s.strip()]
    relevant = [s for s in sentences if keyword_hits(s.lower(), keywords)]
    if not relevant:
        return None, None
    scores = _analyzer().polarity_scores(" ".join(relevant))
    return label_from_compound(scores["compound"], scores["pos"], scores["neg"]), relevant[0][:400]


def keyword_emotions(text: str) -> list[dict]:
    lower = text.lower()
    found = []
    for emotion, cues in EMOTION_CUES.items():
        hits = keyword_hits(lower, cues)
        if hits:
            found.append({"emotion": emotion, "confidence": None, "evidence": hits[:3]})
    return found
