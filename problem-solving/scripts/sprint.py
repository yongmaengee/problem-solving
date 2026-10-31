#!/usr/bin/env python3
"""스프린트와 Blueprint 갱신 관리. 명세(spec.json) 하나를 계속 갱신한다.

  python sprint.py start spec.json --stage 탐색 --lens attn --goal "L² 항을 줄이는 선행연구 탐색"
      새 스프린트를 선언한다. 진행 중인 스프린트가 있으면 먼저 닫으라고 알린다.
      Lens를 해당 블록으로 옮기고(문제 영역 밖이면 거부), 시작 시점의 결정 상태를 스냅숏으로 남긴다.

  python sprint.py end spec.json --summary "..." [--fact "메모리 지수 1.97"]... [--status done|stopped]
      진행 중 스프린트를 닫고 시작 대비 변경량을 기록한다: 결정 상태 변화(quant.py delta) +
      문제 영역·제외 영역·닫힌 길·새 측정·확인된 사실·Blueprint 갱신.
      결정 단계(탐색·경우의 수·결정) 스프린트 두 개가 연속으로 변경량 1 이하이면 절단(보고)을 권고한다.
      정렬·범위·깊이 스프린트는 문제를 정의하는 단계라 절단 판정에 넣지 않는다.

  python sprint.py blueprint spec.json new_nodes.json --code-ref a1b2c3d
      코드가 갱신됐을 때 Blueprint(nodes)를 교체한다. 버전을 올리고, 새로 생기거나 바뀐 블록에
      changed=true를 표시하며, 사라진 블록을 가리키던 Lens·후보·파급을 경고한다.

  python sprint.py propose spec.json --name "채널별 다운샘플링" [--change ...] [--expect ...] [--evidence ...]
      사용자가 보낸 [새 시도 제안]을 명세의 proposals에 등록한다. 다음 스프린트 start가 이를 알려 주고,
      그 스프린트에서 후보로 올려(proposed_by="user") 근거·이식 가능성·경우의 수·가치 비교를 똑같이 거친다.

  python sprint.py status spec.json
      현재 스프린트, 기록, Blueprint 버전을 요약한다.

단계 이름: 정렬 · 범위 · 깊이 · 탐색 · 경우의 수 · 결정 · 종료 · 정리(설명과 정리, 절단 판정 제외)
"""
import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from quant import delta as quant_delta  # noqa: E402

STAGES = ["정렬", "범위", "깊이", "탐색", "경우의 수", "결정", "종료", "정리"]


def load(p):
    return json.load(open(p, encoding="utf-8"))


def save(spec, p):
    open(p, "w", encoding="utf-8").write(json.dumps(spec, ensure_ascii=False, indent=1))


def now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def index(nodes, parent=None, out=None):
    out = {} if out is None else out
    for n in nodes:
        out[n["id"]] = (n, parent)
        index(n.get("children", []), n["id"], out)
    return out


def allowed(spec):
    idx = index(spec["nodes"])
    prob = spec.get("problem") or ([spec["scope"]] if spec.get("scope") else [])
    ok = set()

    def sub(nid):
        ok.add(nid)
        for c in idx[nid][0].get("children", []):
            sub(c["id"])
    for pid in prob:
        if pid not in idx:
            continue
        sub(pid)
        par = idx[pid][1]
        sib = idx[par][0]["children"] if par else spec["nodes"]
        i = [s["id"] for s in sib].index(pid)
        for j in (i - 1, i + 1):
            if 0 <= j < len(sib):
                ok.add(sib[j]["id"])
    ok.update(spec.get("connected", []))
    return ok


def snapshot(spec):
    lens, origin = spec.get("scope"), spec.get("origin", spec.get("scope"))
    if lens == origin:
        cands, table = spec.get("candidates", {}), spec.get("table")
    else:
        p = spec.get("scopes", {}).get(lens, {})
        cands, table = p.get("candidates", {}), p.get("table")
    closed = sorted(c["name"] for v in cands.values() for c in v if isinstance(c, dict) and c.get("closed"))
    return {"scope": lens, "candidates": cands, "table": table, "problem": sorted(spec.get("problem", [])),
            "excluded": sorted(spec.get("excluded", [])), "closed": closed,
            "measured": len((spec.get("knobs") or {}).get("points", [])), "facts": list(spec.get("facts", [])),
            "blueprint": (spec.get("blueprint") or {}).get("version")}


DECIDING = {"탐색", "경우의 수", "결정"}


def sprint_delta(a, b):
    """quant.delta(결정 상태 변화) + 정의·측정 단계의 변화."""
    d = quant_delta(a, b); score, ch = d["delta"], list(d["changes"])
    if a["problem"] != b["problem"]:
        score += 2; ch.append(f"문제 영역 변경: {a['problem']} → {b['problem']}")
    for x in sorted(set(b["excluded"]) ^ set(a["excluded"])):
        score += 1; ch.append(("제외: " if x in b["excluded"] else "다시 포함: ") + x)
    for x in sorted(set(b["closed"]) - set(a["closed"])):
        score += 1; ch.append(f"닫힌 길 추가: {x}")
    if b["measured"] > a["measured"]:
        score += 1; ch.append(f"새 측정 {b['measured'] - a['measured']}점")
    for f in b["facts"][len(a["facts"]):]:
        score += 1; ch.append(f"확인된 사실: {f}")
    if a["blueprint"] != b["blueprint"]:
        score += 1; ch.append(f"Blueprint v{a['blueprint']} → v{b['blueprint']}")
    return {"delta": score, "changes": ch}


def cmd_start(a):
    spec = load(a.spec)
    sp = spec.setdefault("sprints", [])
    if sp and sp[-1].get("status") == "active":
        sys.exit(f"Sprint {sp[-1]['n']}이 진행 중입니다. 먼저 end로 닫으세요.")
    if a.stage not in STAGES:
        sys.exit(f"단계는 {STAGES} 중 하나")
    lens = a.lens or spec.get("scope")
    if lens and lens not in allowed(spec):
        sys.exit(f"'{lens}'는 문제 영역 밖입니다. Lens 이동이 아니라 문제 재정의(2단계)가 필요합니다.")
    spec.setdefault("origin", spec.get("scope"))   # 최상위 candidates/table이 속한 Lens 위치
    spec["scope"] = lens
    s = {"n": len(sp) + 1, "stage": a.stage, "lens": lens, "goal": a.goal, "status": "active",
         "started": now(), "blueprint": spec.get("blueprint", {}).get("version"), "_snap": snapshot(spec)}
    sp.append(s)
    spec["lens_path"] = [{"at": x["lens"], "why": f"Sprint {x['n']} · {x['stage']} — {x['goal']}"} for x in sp]
    save(spec, a.spec)
    out = {k: v for k, v in s.items() if k != "_snap"}
    pend = pending_proposals(spec)
    if pend:
        out["pending_proposals"] = pend
        out["note"] = "이번 스프린트에서 사용자 제안을 후보로 올려 같은 방식으로 따질 것 (proposed_by='user')"
    print(json.dumps(out, ensure_ascii=False))


def cmd_end(a):
    spec = load(a.spec)
    sp = spec.get("sprints", [])
    if not sp or sp[-1].get("status") != "active":
        sys.exit("진행 중인 스프린트가 없습니다.")
    s = sp[-1]
    for f in (a.fact or []):
        spec.setdefault("facts", []).append(f)
    d = sprint_delta(s.pop("_snap"), snapshot(spec))
    s.update({"status": a.status, "ended": now(), "summary": a.summary, "delta": d["delta"], "changes": d["changes"]})
    ds = [x["delta"] for x in sp if "delta" in x and x["stage"] in DECIDING]   # 정의 단계 스프린트로는 절단하지 않음
    trunc = s["stage"] in DECIDING and len(ds) >= 2 and ds[-1] <= 1 and ds[-2] <= 1
    save(spec, a.spec)
    print(json.dumps({"sprint": s["n"], "delta": d["delta"], "changes": d["changes"], "truncate": trunc,
                      "note": "변경량이 두 스프린트 연속 포화 — 루프를 닫고 보고할 것" if trunc else ""}, ensure_ascii=False))


def _sig(n):
    return json.dumps({k: n.get(k) for k in ("label", "note", "code", "hl", "codeNote")}, ensure_ascii=False, sort_keys=True)


def cmd_blueprint(a):
    spec = load(a.spec)
    new = load(a.nodes)
    new = new["nodes"] if isinstance(new, dict) else new
    old = index(spec.get("nodes", []))
    nidx = index(new)
    changed, added = [], []
    for nid, (n, _) in nidx.items():
        n.pop("changed", None)
        if nid not in old:
            n["changed"] = True; added.append(nid)
        elif _sig(n) != _sig(old[nid][0]):
            n["changed"] = True; changed.append(nid)
    removed = [i for i in old if i not in nidx]
    spec["nodes"] = new
    bp = spec.setdefault("blueprint", {"version": 0})
    bp.update({"version": bp.get("version", 0) + 1, "code_ref": a.code_ref, "updated": now(),
               "changed": changed, "added": added, "removed": removed})
    warn = []
    refs = [("Lens", spec.get("scope"))] + [("문제 영역", p) for p in spec.get("problem", [])] + \
           [("파급 대상", r["to"]) for r in spec.get("ripples", [])] + [("후보 위치", k) for k in spec.get("candidates", {})]
    for what, rid in refs:
        if rid in removed:
            warn.append(f"{what} '{rid}'가 새 Blueprint에서 사라짐")
    save(spec, a.spec)
    print(json.dumps({"version": bp["version"], "changed": changed, "added": added, "removed": removed, "warnings": warn},
                     ensure_ascii=False))


def cmd_propose(a):
    spec = load(a.spec)
    ps = spec.setdefault("proposals", [])
    p = {"id": f"p{len(ps) + 1}", "name": a.name, "change": a.change, "expect": a.expect, "evidence": a.evidence,
         "lens": spec.get("scope"), "status": "pending", "at": now()}
    ps.append(p)
    save(spec, a.spec)
    print(json.dumps(p, ensure_ascii=False))


def pending_proposals(spec):
    names = {(c if isinstance(c, dict) else {"name": c})["name"] for v in spec.get("candidates", {}).values() for c in v}
    for sc in spec.get("scopes", {}).values():
        names |= {(c if isinstance(c, dict) else {"name": c})["name"] for v in sc.get("candidates", {}).values() for c in v}
    return [p for p in spec.get("proposals", []) if p.get("status") == "pending" and p["name"] not in names]


def cmd_status(a):
    spec = load(a.spec)
    sp = spec.get("sprints", [])
    print(json.dumps({"blueprint": spec.get("blueprint"),
                      "current": next((x["n"] for x in reversed(sp) if x["status"] == "active"), None),
                      "sprints": [{k: x.get(k) for k in ("n", "stage", "lens", "goal", "status", "delta", "summary")} for x in sp]},
                     ensure_ascii=False, indent=1))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("start"); s.add_argument("spec"); s.add_argument("--stage", required=True)
    s.add_argument("--lens"); s.add_argument("--goal", required=True)
    e = sub.add_parser("end"); e.add_argument("spec"); e.add_argument("--summary", required=True)
    e.add_argument("--status", default="done", choices=["done", "stopped"])
    e.add_argument("--fact", action="append", help="이 스프린트에서 확인된 사실 (여러 번 가능)")
    b = sub.add_parser("blueprint"); b.add_argument("spec"); b.add_argument("nodes"); b.add_argument("--code-ref", required=True)
    t = sub.add_parser("status"); t.add_argument("spec")
    pr = sub.add_parser("propose"); pr.add_argument("spec"); pr.add_argument("--name", required=True)
    pr.add_argument("--change"); pr.add_argument("--expect"); pr.add_argument("--evidence")
    a = ap.parse_args()
    {"start": cmd_start, "end": cmd_end, "blueprint": cmd_blueprint, "status": cmd_status, "propose": cmd_propose}[a.cmd](a)


if __name__ == "__main__":
    main()
