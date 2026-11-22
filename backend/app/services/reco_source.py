"""分来源推荐域服务：探查邻边与实体融合的候选引证按可用归属关联，按入口产出分来源推荐数据。

推荐规则此前不区分共享依据与受限依据：候选 M7 同时由探索小组公开的邻边和仅限
融合人员核实的对应关系推得，两类证据混在一个候选里争用同一名次。本模块把引证
（证据边）按「归属」分开登记，候选分值只在入口有权使用的引证范围内计算：

- 公共入口：只能使用「共享」引证（探索小组公开的邻边）；
- 融合入口：可使用「共享」与「受限」引证（含仅限融合人员核实的对应关系）。

重复提交同一条引证只计一次；撤销公开边后按重算记录复算候选；子图探查的待办
接到分来源推荐数据后同步准备扩边，提交给探查的种子只携带该入口有权限的关系，
越权使用证据直接拒绝。
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from app.store import store

# 入口 → 该入口有权使用的引证归属。
ENTRY_SCOPES: dict[str, frozenset[str]] = {
    "公共入口": frozenset({"共享"}),
    "融合入口": frozenset({"共享", "受限"}),
}
SOURCE_KINDS = ("探查邻边", "实体融合")
ATTRIBUTIONS = ("共享", "受限")


class RecoSourceHub:
    """分来源推荐数据中心：引证登记去重、按入口计分、重算复算、扩边待办同步。"""

    # ---------- 数据表 ----------
    def evidence_rows(self) -> list[dict[str, Any]]:
        return store.rows("reco_evidence")

    def recompute_rows(self) -> list[dict[str, Any]]:
        return store.rows("reco_recompute_log")

    def expansion_rows(self) -> list[dict[str, Any]]:
        return store.rows("subgraph_expansion")

    # ---------- 基础工具 ----------
    @staticmethod
    def _scope(entry: str) -> frozenset[str]:
        scope = ENTRY_SCOPES.get(entry)
        if scope is None:
            raise ValueError(f"未知入口「{entry}」，可选：{'、'.join(ENTRY_SCOPES)}")
        return scope

    @staticmethod
    def _next_code(rows: list[dict[str, Any]], field: str, prefix: str) -> str:
        best = 0
        for row in rows:
            code = str(row.get(field, ""))
            if code.startswith(prefix) and code[len(prefix):].isdigit():
                best = max(best, int(code[len(prefix):]))
        return f"{prefix}{best + 1:04d}"

    @staticmethod
    def _next_id(rows: list[dict[str, Any]]) -> int:
        return max((int(row.get("id", 0)) for row in rows), default=0) + 1

    @staticmethod
    def _active(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [row for row in rows if row.get("状态") == "有效"]

    @staticmethod
    def _score(rows: list[dict[str, Any]]) -> float:
        return round(sum(float(row.get("支持度", 0) or 0) for row in rows), 6)

    def _permitted(self, candidate: str, scope: frozenset[str]) -> list[dict[str, Any]]:
        return [
            row for row in self._active(self.evidence_rows())
            if row.get("候选实体") == candidate and row.get("归属") in scope
        ]

    # ---------- 引证登记：重复提交同一条引证只计一次 ----------
    def register_evidence(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str, bool]:
        candidate = str(values.get("候选实体", "")).strip()
        relation = str(values.get("关系", "")).strip()
        kind = str(values.get("来源类型", "")).strip()
        attribution = str(values.get("归属", "")).strip()
        if not candidate or not relation:
            return None, "缺少必填字段：候选实体、关系", False
        if kind not in SOURCE_KINDS:
            return None, f"来源类型须为：{'、'.join(SOURCE_KINDS)}", False
        if attribution not in ATTRIBUTIONS:
            return None, f"归属须为：{'、'.join(ATTRIBUTIONS)}", False
        try:
            support = round(float(values.get("支持度", 0) or 0), 6)
        except (TypeError, ValueError):
            return None, "支持度须为数值", False
        submitter = str(values.get("提交人", "")).strip() or "未署名"

        rows = self.evidence_rows()
        for row in rows:
            same = (
                row.get("候选实体") == candidate
                and row.get("关系") == relation
                and row.get("来源类型") == kind
            )
            if same and row.get("状态") == "有效":
                row["提交次数"] = int(row.get("提交次数", 1)) + 1
                return row, f"重复提交同一条引证只计一次：{row['引证编号']}（累计提交 {row['提交次数']} 次）", True

        entry = {
            "id": self._next_id(rows),
            "引证编号": self._next_code(rows, "引证编号", "EV-"),
            "候选实体": candidate,
            "关系": relation,
            "来源类型": kind,
            "归属": attribution,
            "支持度": support,
            "提交人": submitter,
            "状态": "有效",
            "提交次数": 1,
        }
        rows.append(entry)
        synced = self._sync_expansion_todos()
        return entry, f"引证 {entry['引证编号']} 已登记（{attribution}/{kind}），同步扩边待办 {synced} 条", False

    # ---------- 撤销公开边：候选按重算记录复算，扩边待办同步 ----------
    def revoke_evidence(self, code: str) -> tuple[dict[str, Any] | None, str]:
        row = next((r for r in self.evidence_rows() if r.get("引证编号") == code), None)
        if row is None:
            return None, f"引证 {code} 不存在"
        if row.get("状态") == "已撤销":
            return row, f"引证 {code} 已撤销，无需重复操作"
        row["状态"] = "已撤销"
        logs = [self.recompute(entry) for entry in ENTRY_SCOPES]
        synced = self._sync_expansion_todos()
        brief = "；".join(f"{log['入口']}指纹 {log['依据指纹'][:8]}" for log in logs)
        return row, f"引证 {code}（{row['归属']}）已撤销，候选已重算（{brief}），同步扩边待办 {synced} 条"

    # ---------- 分来源推荐数据：分值只在入口有权使用的引证内计算 ----------
    def board(self, entry: str) -> dict[str, Any]:
        scope = self._scope(entry)
        usable = [
            row for row in self._active(self.evidence_rows())
            if row.get("归属") in scope
        ]
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in usable:
            grouped.setdefault(str(row.get("候选实体")), []).append(row)
        items: list[dict[str, Any]] = []
        for candidate, evs in grouped.items():
            items.append({
                "候选实体": candidate,
                "分值": self._score(evs),
                "参与引证": sorted(str(e.get("引证编号")) for e in evs),
                "可用关系": sorted({str(e.get("关系")) for e in evs}),
                "证据构成": {
                    kind: sorted(str(e.get("引证编号")) for e in evs if e.get("来源类型") == kind)
                    for kind in SOURCE_KINDS
                },
            })
        items.sort(key=lambda item: (-item["分值"], item["候选实体"]))
        for rank, item in enumerate(items, 1):
            item["名次"] = rank
        return {"入口": entry, "可用归属": sorted(scope), "候选数": len(items), "候选": items}

    # ---------- 重算：同一引证状态复算结果一致，撤销后指纹随之变化 ----------
    def recompute(self, entry: str) -> dict[str, Any]:
        result = self.board(entry)
        scope = self._scope(entry)
        usable = [
            row for row in self._active(self.evidence_rows())
            if row.get("归属") in scope
        ]
        payload = sorted(
            [str(r.get("引证编号")), str(r.get("归属")), str(r.get("来源类型")), str(r.get("支持度"))]
            for r in usable
        )
        fingerprint = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        rows = self.recompute_rows()
        log = {
            "id": self._next_id(rows),
            "重算编号": self._next_code(rows, "重算编号", "RC-"),
            "入口": entry,
            "依据指纹": fingerprint,
            "引证数": len(usable),
            "候选名次": result["候选"],
        }
        rows.append(log)
        return log

    # ---------- 提交种子扩边：只携带入口有权限的关系，越权使用证据应拒绝 ----------
    def submit_seed(
        self,
        seed: str,
        entry: str,
        relations: list[str] | None = None,
        operator: str = "",
    ) -> tuple[dict[str, Any] | None, str]:
        seed = seed.strip()
        if not seed:
            return None, "缺少必填字段：种子"
        try:
            scope = self._scope(entry)
        except ValueError as exc:
            return None, str(exc)
        candidate_rows = [r for r in self.evidence_rows() if r.get("候选实体") == seed]
        active = [r for r in candidate_rows if r.get("状态") == "有效"]
        permitted = [r for r in active if r.get("归属") in scope]
        permitted_relations = sorted({str(r.get("关系")) for r in permitted})

        requested = [str(rel).strip() for rel in (relations or []) if str(rel).strip()]
        requested = list(dict.fromkeys(requested))
        if requested:
            for rel in requested:
                if rel in permitted_relations:
                    continue
                origin_active = next((r for r in active if r.get("关系") == rel), None)
                if origin_active is not None:
                    return None, (
                        f"越权使用证据被拒绝：关系「{rel}」来自{origin_active['归属']}引证 "
                        f"{origin_active['引证编号']}（{origin_active['来源类型']}），{entry}无权使用"
                    )
                origin_any = next((r for r in candidate_rows if r.get("关系") == rel), None)
                if origin_any is not None:
                    return None, f"关系「{rel}」所在引证 {origin_any['引证编号']} 已撤销，需重新登记后再扩边"
                return None, f"关系「{rel}」在候选 {seed} 的引证中不存在"
            used = [r for r in permitted if str(r.get("关系")) in requested]
            carried = [rel for rel in requested if any(str(r.get("关系")) == rel for r in used)]
        else:
            used = permitted
            carried = permitted_relations

        rows = self.expansion_rows()
        todo = {
            "id": self._next_id(rows),
            "待办编号": self._next_code(rows, "待办编号", "EXP-"),
            "种子": seed,
            "入口": entry,
            "请求关系": requested,
            "可用关系": carried,
            "参与引证": sorted(str(r.get("引证编号")) for r in used),
            "候选分值": self._score(used),
            "关联探查配置": self._pending_explorations(),
            "状态": "待扩边",
            "同步次数": 0,
            "提交人": operator.strip() or "未署名",
        }
        rows.append(todo)
        if not used:
            return todo, f"种子 {seed} 已受理（{entry}），但该入口下无可用引证，扩边关系为空"
        return todo, f"种子 {seed} 已受理（{entry}），参与引证 {len(used)} 条，分值 {todo['候选分值']}"

    # ---------- 子图探查待办：接到分来源推荐数据后同步准备扩边 ----------
    def _pending_explorations(self) -> list[str]:
        return [
            str(row.get("配置编号"))
            for row in store.rows("subgraph_exp")
            if row.get("pending")
        ]

    def _sync_expansion_todos(self) -> int:
        synced = 0
        for todo in self.expansion_rows():
            if todo.get("状态") != "待扩边":
                continue
            scope = ENTRY_SCOPES.get(str(todo.get("入口")), frozenset())
            permitted = self._permitted(str(todo.get("种子", "")), scope)
            requested = [str(rel) for rel in (todo.get("请求关系") or [])]
            if requested:
                used = [r for r in permitted if str(r.get("关系")) in requested]
                todo["可用关系"] = [
                    rel for rel in requested if any(str(r.get("关系")) == rel for r in used)
                ]
            else:
                used = permitted
                todo["可用关系"] = sorted({str(r.get("关系")) for r in used})
            todo["参与引证"] = sorted(str(r.get("引证编号")) for r in used)
            todo["候选分值"] = self._score(used)
            todo["关联探查配置"] = self._pending_explorations()
            todo["同步次数"] = int(todo.get("同步次数", 0)) + 1
            synced += 1
        return synced

    # ---------- 查询与快照 ----------
    def expansion_todos(self) -> list[dict[str, Any]]:
        return list(self.expansion_rows())

    def snapshot_summary(self) -> dict[str, Any]:
        rows = self.evidence_rows()
        active = self._active(rows)
        return {
            "引证总数": len(rows),
            "有效引证": len(active),
            "共享引证": sum(1 for r in active if r.get("归属") == "共享"),
            "受限引证": sum(1 for r in active if r.get("归属") == "受限"),
            "各入口候选数": {entry: len(self.board(entry)["候选"]) for entry in ENTRY_SCOPES},
            "扩边待办": len(self.expansion_rows()),
        }


reco_source_hub = RecoSourceHub()
