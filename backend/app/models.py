from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class SessionCreate(BaseModel):
    title: str = "新分析"
    dataset_id: int | None = None


class ChatRequest(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    session_id: str | None = None
    dataset_id: int | None = None


class KnowledgeCreate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=2, max_length=10000)
    category: str = "business_rule"
    dataset_id: int | None = None


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class AdminCreate(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=6, max_length=128)


class ChartSpec(BaseModel):
    type: Literal["bar", "line", "pie", "scatter", "none"] = "none"
    title: str
    x_field: str | None = None
    y_field: str | None = None
    series_name: str | None = None
    series_field: str | None = None
    series_fields: list[str] = Field(default_factory=list)


class AnalysisResponse(BaseModel):
    session_id: str
    message: str
    intent: str
    plan: list[str]
    sql: str
    columns: list[str]
    rows: list[dict[str, Any]]
    chart: ChartSpec
    insights: list[str]
    knowledge_refs: list[dict[str, Any]]
    execution_mode: str
    answer_type: Literal["data_analysis", "knowledge_qa"] = "data_analysis"
    context_applied: bool = False
    effective_question: str = ""
