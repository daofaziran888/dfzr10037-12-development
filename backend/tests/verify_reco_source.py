#!/usr/bin/env python3
"""分来源推荐验收脚本：共享/受限引证按入口归属，M7 场景全流程核对。

场景对应：
1. 候选 M7 同时由共享邻边（EV-0001，支持度 0.6）和受限对应关系（EV-0002，支持度 0.9）推得；
2. 公共入口与融合入口各自看到不同的分来源推荐数据，M7 在两个入口争用不同名次；
3. 重复提交同一条引证只计一次；
4. 公共入口越权使用受限证据被拒绝；
5. 可查看融合关系的人与仅能查看探索片段的人分别提交 M7 作为种子；
6. 撤销公开边 EV-0001 后重算候选，再提交 M7，比较实际参与扩边的证据数据。

用法：先启动后端，再执行  .venv/bin/python tests/verify_reco_source.py [base_url]
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")
FAILURES: list[str] = []


def call(method: str, path: str, body: dict | None = None, query: dict | None = None) -> tuple[int, dict]:
    url = BASE + path
    if query:
        url += "?" + urllib.parse.urlencode(query)
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" —— {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


def candidate(board: dict, name: str) -> dict | None:
    return next((c for c in board["候选"] if c["候选实体"] == name), None)


def main() -> int:
    status, health = call("GET", "/api/health")
    check("后端健康检查", status == 200 and health.get("ok"), str(health))

    # ---- 1. 分来源推荐数据：同一候选在不同入口名次/分值不同 ----
    _, pub = call("GET", "/api/reco_source/board", query={"entry": "公共入口"})
    _, fus = call("GET", "/api/reco_source/board", query={"entry": "融合入口"})
    m7_pub, m7_fus = candidate(pub, "M7"), candidate(fus, "M7")
    check("公共入口 M7 仅含共享引证 EV-0001，分值 0.6",
          m7_pub is not None and m7_pub["参与引证"] == ["EV-0001"] and m7_pub["分值"] == 0.6,
          json.dumps(m7_pub, ensure_ascii=False))
    check("融合入口 M7 含共享+受限引证，分值 1.5",
          m7_fus is not None and m7_fus["参与引证"] == ["EV-0001", "EV-0002"] and m7_fus["分值"] == 1.5,
          json.dumps(m7_fus, ensure_ascii=False))
    check("M7 在两个入口争用不同名次（公共第2、融合第1）",
          m7_pub is not None and m7_fus is not None
          and m7_pub["名次"] == 2 and m7_fus["名次"] == 1,
          f"公共={m7_pub and m7_pub['名次']} 融合={m7_fus and m7_fus['名次']}")
    check("公共入口分值只在有权使用的共享边内计算（看不到 EV-0002）",
          all("EV-0002" not in c["参与引证"] for c in pub["候选"]))

    # ---- 2. 重算可复算：同一引证状态指纹一致 ----
    _, rc1 = call("POST", "/api/reco_source/recompute", {"entry": "公共入口"})
    _, rc2 = call("POST", "/api/reco_source/recompute", {"entry": "公共入口"})
    check("同一引证状态重算指纹一致（可复算）",
          rc1.get("依据指纹") == rc2.get("依据指纹"),
          f"{rc1.get('依据指纹')} vs {rc2.get('依据指纹')}")
    fp_before = rc1.get("依据指纹")

    # ---- 3. 重复提交同一条引证只计一次 ----
    dup_body = {"values": {"候选实体": "M7", "关系": "共同作者", "来源类型": "探查邻边",
                           "归属": "共享", "支持度": 0.6, "提交人": "探索小组"}}
    _, dup = call("POST", "/api/reco_source/evidence", dup_body)
    _, pub2 = call("GET", "/api/reco_source/board", query={"entry": "公共入口"})
    m7_pub2 = candidate(pub2, "M7")
    check("重复提交同一条引证只计一次", dup.get("ok") and "只计一次" in dup.get("message", ""),
          dup.get("message", ""))
    check("重复提交后 M7 公共分值仍为 0.6",
          m7_pub2 is not None and m7_pub2["分值"] == 0.6 and m7_pub2["参与引证"] == ["EV-0001"],
          json.dumps(m7_pub2, ensure_ascii=False))

    # ---- 4. 越权使用证据应拒绝 ----
    _, deny = call("POST", "/api/reco_source/expand",
                   {"seed": "M7", "entry": "公共入口",
                    "relations": ["共同作者", "同一实体对应"], "operator": "仅看探索片段的人"})
    check("公共入口请求受限关系被拒绝（越权）",
          not deny.get("ok") and "越权" in deny.get("message", "") and "EV-0002" in deny.get("message", ""),
          deny.get("message", ""))

    # ---- 5. 两类人分别提交 M7 作为种子 ----
    _, exp_pub = call("POST", "/api/reco_source/expand",
                      {"seed": "M7", "entry": "公共入口", "operator": "仅看探索片段的人"})
    t_pub = exp_pub.get("entry") or {}
    check("公共入口提交 M7：只携带共享关系，参与引证 [EV-0001]，分值 0.6",
          exp_pub.get("ok") and t_pub.get("参与引证") == ["EV-0001"]
          and t_pub.get("可用关系") == ["共同作者"] and t_pub.get("候选分值") == 0.6,
          json.dumps(t_pub, ensure_ascii=False))
    check("扩边待办已同步到子图探查待办配置",
          "SUBG-0001" in t_pub.get("关联探查配置", []), json.dumps(t_pub, ensure_ascii=False))

    _, exp_fus = call("POST", "/api/reco_source/expand",
                      {"seed": "M7", "entry": "融合入口", "operator": "可查看融合关系的人"})
    t_fus = exp_fus.get("entry") or {}
    check("融合入口提交 M7：携带共享+受限关系，参与引证 [EV-0001, EV-0002]，分值 1.5",
          exp_fus.get("ok") and t_fus.get("参与引证") == ["EV-0001", "EV-0002"]
          and t_fus.get("候选分值") == 1.5,
          json.dumps(t_fus, ensure_ascii=False))

    # ---- 6. 撤销公开边 EV-0001：重算候选，待办同步 ----
    _, revoke = call("POST", "/api/reco_source/evidence/EV-0001/revoke")
    check("撤销公开边 EV-0001 并触发重算", revoke.get("ok") and "已重算" in revoke.get("message", ""),
          revoke.get("message", ""))

    _, pub3 = call("GET", "/api/reco_source/board", query={"entry": "公共入口"})
    _, fus3 = call("GET", "/api/reco_source/board", query={"entry": "融合入口"})
    m7_fus3 = candidate(fus3, "M7")
    check("撤销后公共入口 M7 无可用引证（退出候选）", candidate(pub3, "M7") is None,
          json.dumps(pub3["候选"], ensure_ascii=False))
    check("撤销后融合入口 M7 仅靠受限引证 EV-0002，分值 0.9",
          m7_fus3 is not None and m7_fus3["参与引证"] == ["EV-0002"] and m7_fus3["分值"] == 0.9,
          json.dumps(m7_fus3, ensure_ascii=False))

    _, rc3 = call("POST", "/api/reco_source/recompute", {"entry": "公共入口"})
    check("撤销后重算指纹变化（候选已按新引证状态复算）",
          rc3.get("依据指纹") != fp_before and rc3.get("引证数") == 1,
          json.dumps(rc3, ensure_ascii=False))

    # ---- 7. 撤掉公开边再试：比较实际参与扩边的证据数据 ----
    _, exp_pub2 = call("POST", "/api/reco_source/expand",
                       {"seed": "M7", "entry": "公共入口", "operator": "仅看探索片段的人"})
    t_pub2 = exp_pub2.get("entry") or {}
    check("撤销后公共入口再提交 M7：无引证参与扩边，分值 0",
          exp_pub2.get("ok") and t_pub2.get("参与引证") == [] and t_pub2.get("候选分值") == 0,
          json.dumps(t_pub2, ensure_ascii=False))
    _, exp_fus2 = call("POST", "/api/reco_source/expand",
                       {"seed": "M7", "entry": "融合入口", "operator": "可查看融合关系的人"})
    t_fus2 = exp_fus2.get("entry") or {}
    check("撤销后融合入口再提交 M7：仅受限引证 EV-0002 参与，分值 0.9",
          exp_fus2.get("ok") and t_fus2.get("参与引证") == ["EV-0002"] and t_fus2.get("候选分值") == 0.9,
          json.dumps(t_fus2, ensure_ascii=False))

    _, expansions = call("GET", "/api/reco_source/expansions")
    todos = expansions.get("items", [])
    pre_pub = next((t for t in todos if t["待办编号"] == t_pub.get("待办编号")), None)
    check("撤销前建立的公共待办已随引证变更同步（参与引证清空）",
          pre_pub is not None and pre_pub["参与引证"] == [] and pre_pub["同步次数"] >= 1,
          json.dumps(pre_pub, ensure_ascii=False))

    print("\n=== 实际参与扩边的证据数据对比（M7） ===")
    print(f"{'待办':<9}{'入口':<7}{'提交人':<12}{'参与引证':<22}{'可用关系':<18}{'分值':<6}同步")
    for t in todos:
        if t.get("种子") != "M7":
            continue
        print(f"{t['待办编号']:<9}{t['入口']:<7}{t['提交人']:<12}"
              f"{json.dumps(t['参与引证'], ensure_ascii=False):<22}"
              f"{json.dumps(t['可用关系'], ensure_ascii=False):<18}"
              f"{t['候选分值']:<6}{t['同步次数']}")

    # ---- 8. 撤销后重新登记同一边：作为新引证参与，候选重算回来 ----
    _, reg = call("POST", "/api/reco_source/evidence", dup_body)
    new_code = (reg.get("entry") or {}).get("引证编号", "")
    _, pub4 = call("GET", "/api/reco_source/board", query={"entry": "公共入口"})
    m7_pub4 = candidate(pub4, "M7")
    check("撤销后重新登记公开边生成新引证，公共入口 M7 重算为 0.6",
          reg.get("ok") and new_code != "EV-0001"
          and m7_pub4 is not None and m7_pub4["参与引证"] == [new_code] and m7_pub4["分值"] == 0.6,
          json.dumps(m7_pub4, ensure_ascii=False))

    # ---- 9. 回归：既有模块与跨模块链路不受影响 ----
    _, reco_list = call("GET", "/api/reco_engine")
    check("推荐引擎列表接口正常", reco_list.get("total", 0) >= 3)
    _, action = call("POST", "/api/subgraph_exp/1/actions", {"action": "启动探查"})
    check("子图探查动作与跨模块推送正常",
          action.get("ok") and "搜索模板" in action.get("message", "")
          and "推荐引擎" in action.get("message", ""),
          action.get("message", ""))

    print()
    if FAILURES:
        print(f"共 {len(FAILURES)} 项未通过：")
        for name in FAILURES:
            print(f"  - {name}")
        return 1
    print("全部验收项通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
