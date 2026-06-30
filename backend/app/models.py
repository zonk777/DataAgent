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


class KnowledgeUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=2, max_length=10000)
    category: str = "business_rule"
    dataset_id: int | None = None


class DatasetUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = ""


class DatasetColumnUpdate(BaseModel):
    description: str = Field(max_length=1000)


class MySQLImportRequest(BaseModel):
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(default=3306, ge=1, le=65535)
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(default="", max_length=256)
    database: str = Field(min_length=1, max_length=128)
    table: str = Field(min_length=1, max_length=128)
    name: str | None = Field(default=None, max_length=120)
    description: str = Field(default="", max_length=1000)
    limit: int = Field(default=100000, ge=1, le=1000000)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class AdminCreate(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=6, max_length=128)
    role: Literal["admin", "data_analyst", "business_user"] = "admin"
    dataset_ids: list[int] = Field(default_factory=list)


class AdminUpdate(BaseModel):
    role: Literal["admin", "data_analyst", "business_user"] = "admin"
    dataset_ids: list[int] = Field(default_factory=list)


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
