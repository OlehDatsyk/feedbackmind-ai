"""Pydantic schemas for structured AI output. Every AI response is validated against one of these."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

SentimentLabel = Literal["positive", "negative", "neutral", "mixed", "uncertain"]
EmotionName = Literal["frustration", "satisfaction", "confusion", "disappointment", "appreciation", "urgency", "concern", "excitement"]


class AITopic(BaseModel):
    name: str = Field(max_length=80, description="Short topic name. Prefer one of the existing topic names when it fits.")
    sentiment: SentimentLabel
    evidence: str = Field(default="", max_length=400, description="Exact quote from the feedback text.")


class AIEmotion(BaseModel):
    emotion: EmotionName
    confidence: float = Field(ge=0, le=1)
    evidence: str = Field(default="", max_length=300, description="Exact quote from the feedback text.")


class AIRecordAnalysis(BaseModel):
    id: str = Field(description="The record id exactly as given.")
    sentiment: SentimentLabel
    score: float = Field(ge=-1, le=1, description="-1 very negative .. +1 very positive")
    confidence: float = Field(ge=0, le=1)
    explanation: str = Field(max_length=500)
    evidence: list[str] = Field(default_factory=list, max_length=3, description="Exact short quotes from the text.")
    language: str = Field(default="", max_length=16, description="ISO 639-1 code")
    topics: list[AITopic] = Field(default_factory=list, max_length=6)
    emotions: list[AIEmotion] = Field(default_factory=list, max_length=4)


class AIBatchAnalysis(BaseModel):
    results: list[AIRecordAnalysis]


class AIInsightNarrative(BaseModel):
    key: str = Field(description="The insight key exactly as given.")
    summary: str = Field(max_length=800)
    suggested_action: str = Field(max_length=600)


class AIInsightNarratives(BaseModel):
    insights: list[AIInsightNarrative]


class AIAnalystAnswer(BaseModel):
    answer: str = Field(max_length=6000, description="Markdown answer. Cite records inline as [#<record id>].")
    cited_record_ids: list[str] = Field(default_factory=list, max_length=30)
    data_sufficient: bool
    limitations: str = Field(default="", max_length=1000)
