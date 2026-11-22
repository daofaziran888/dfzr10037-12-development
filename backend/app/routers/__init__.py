"""业务路由汇总：分来源推荐是固定路径，必须排在通用资源路由之前注册。"""
from __future__ import annotations

from app.routers import reco_source, resource

ROUTERS = [reco_source, resource]
