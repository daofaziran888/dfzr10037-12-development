"""推荐引擎领域服务：字段、状态和动作来自业务配置；分来源推荐数据由 reco_source 域承载。"""
from __future__ import annotations

from typing import Any

from app.services.base import BaseModuleService
from app.services.reco_source import reco_source_hub


class RecoEngineService(BaseModuleService):
    MODULE = "reco_engine"
    ENTITY = "推荐规则"
    OPERATION_TERM = "关联"
    LIST_FIELDS = ["规则编号", "推荐场景", "源实体", "推荐算法", "候选数量", "过滤条件", "命中次数", "采纳率"]
    REQUIRED_FIELDS = ["规则编号", "推荐场景", "源实体"]
    STATUS_ORDER = ["草稿", "已生效", "效果差", "已停用"]
    ACTION_RULES = {"启效规则": "已生效", "标记差效": "效果差", "停用规则": "已停用"}
    NEGATIVE_ACTIONS = ["停用规则"]

    def domain_snapshot(self) -> dict[str, Any]:
        base = super().domain_snapshot()
        # 分来源推荐：共享/受限引证分开归属，候选分值按入口权限各自计算。
        base["source_separated"] = reco_source_hub.snapshot_summary()
        return base
