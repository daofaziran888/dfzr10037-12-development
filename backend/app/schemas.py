"""通用接口契约；模块字段由领域服务持有，不再为每个模块复制一份模型类。"""
from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PageResult(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int = 1
    size: int = 20


class ActionResult(BaseModel):
    ok: bool
    message: str
    entry: dict[str, Any] | None = None


class EntryPayload(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)
    remark: str | None = None


class ActionPayload(BaseModel):
    action: str
    remark: str | None = None


class RecomputePayload(BaseModel):
    """分来源推荐重算请求：entry 为入口（公共入口/融合入口）。"""
    entry: str


class ExpandPayload(BaseModel):
    """种子扩边请求：relations 缺省时携带该入口有权限的全部关系。"""
    seed: str
    entry: str
    relations: list[str] | None = None
    operator: str | None = None
