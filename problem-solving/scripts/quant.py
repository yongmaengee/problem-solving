#!/usr/bin/env python3
"""problem-solving 정량 도구. 표준 라이브러리만 쓴다.

  python quant.py table   spec.json [--n 2000] [--jitter 0.3] [--write]
      가치 테이블 종합 점수, 순위, 가중치 민감도(가중치를 흔들었을 때 각 후보가 1위일 확률),
      1·2위 점수 차. --write면 spec의 table.analysis에 결과를 넣는다.

  python quant.py delta   prev.json cur.json [--history h.json]
      두 루프의 명세를 비교해 변경량을 계산하고 절단 여부를 판정한다 (references/value-table.md 기준).
      --history는 이전 변경량 목록(JSON 배열); 결과를 덧붙여 다시 쓴다.

  python quant.py scaling data.json --x L --y mem [--group B,prec]
      측정값에 log-log 직선을 맞춰 지수를 추정하고 스케일링 형태(상수/선형/제곱/세제곱 이상)를 판별한다.
      data.json은 [{"L": 1024, "mem": 1.2, ...}, ...]. 실패한 측정(ok=false)은 제외하고 경계로 보고한다.

  python quant.py leak    series.json --y mem
      스텝 순서의 측정값에서 증가 추세(누수)를 판별한다.

  python quant.py decide  spec.json [--lens attn] [--write]
      결정을 사용자에게 요청해야 하는지 판정하고(references/autonomous-decision.md의 다섯 사유),
      무응답 시 Claude가 고를 기본값과 이유를 계산한다. --write면 spec의 requests에 넣는다.

  python quant.py sweep   --cmd "python probe.py --L {L} --B {B}" --grid '{"L":[1024,2048],"B":[1,2]}'
                          [--timeout 300] [--out sweep.json] [--knobs spec.json]
      격자의 모든 조합으로 명령을 실행한다. 명령은 stdout 마지막 줄에 JSON 측정값을 출력해야 한다
      (예: {"mem_gb": 3.1, "sec": 0.4}). 실패(예: OOM)는 ok=false와 stderr 끝부분으로 기록한다.
      --knobs면 결과를 spec의 knobs로 넣어 캔버스에서 손잡이로 조절할 수 있게 한다.
      가볍고 되돌릴 수 있는 측정에만 쓴다. 장시간 학습은 sweep 대상이 아니다.
"""
import argparse
import itertools
import json
import math
import random
import shlex
import subprocess
import sys
import time


def load(p):
    return json.load(open(p, encoding="utf-8"))


def dump(obj, p=None):
    s = json.dumps(obj, ensure_ascii=False, indent=1)
    if p:
        open(p, "w", encoding="utf-8").write(s)
    else:
        print(s)


# ---------- table ----------
def totals(table, weights=None):
    w = weights if weights is not None else table.get("weights", {})
    out = {}
    for r in table["rows"]:
        out[r["candidate"]] = sum(r["scores"].get(a, [0])[0] * w.get(a, 1) for a in table["axes"])
    return out


def table_analysis(table, n=2000, jitter=0.3, seed=0):
    rnd = random.Random(seed)
    base = totals(table)
    ranked = sorted(base, key=lambda c: -base[c])
    wins = {c: 0 for c in base}
    w0 = table.get("weights", {})
    for _ in range(n):
        w = {a: w0.get(a, 1) * math.exp(rnd.uniform(-jitter, jitter) * 2) for a in table["axes"]}
        t = totals(table, w)
        wins[max(t, key=t.get)] += 1
    gap = base[ranked[0]] - base[ranked[1]] if len(ranked) > 1 else None
    # 어떤 축이 1·2위를 가르는가
    split = []
    if len(ranked) > 1:
        a, b = [next(r for r in table["rows"] if r["candidate"] == c) for c in ranked[:2]]
        for ax in table["axes"]:
            d = a["scores"].get(ax, [0])[0] - b["scores"].get(ax, [0])[0]
            if d:
                split.append({"axis": ax, "diff": d})
        split.sort(key=lambda x: -abs(x["diff"]))
    p_top = wins[ranked[0]] / n
    return {
        "totals": base, "rank": ranked, "top_gap": gap,
        "p_first": {c: round(wins[c] / n, 3) for c in ranked},
        "robust": p_top >= 0.8,
        "deciding_axes": split[:3],
        "note": ("1위가 가중치 변화에 견고함" if p_top >= 0.8 else
                 "가중치에 따라 1위가 바뀜 — 가중치(무엇을 중시하는가)를 사용자와 먼저 맞출 것"),
    }


# ---------- decide ----------
def _lens_data(spec, lens):
    if not lens or lens == spec.get("scope"):
        return spec.get("candidates", {}), spec.get("table")
    p = spec.get("scopes", {}).get(lens, {})
    return p.get("candidates", {}), p.get("table")


def decide(spec, lens=None):
    lens = lens or spec.get("scope")
    cands, table = _lens_data(spec, lens)
    if not table or not table.get("rows"):
        return {"lens": lens, "need_request": False, "reasons": [], "default": None, "note": "가치 비교 테이블 없음"}
    an = table_analysis(table, n=2000)
    clist = {(c if isinstance(c, dict) else {"name": c})["name"]: (c if isinstance(c, dict) else {"name": c})
             for v in cands.values() for c in v}
    rows = {r["candidate"]: r for r in table["rows"]}
    top = an["rank"][0]; tc = clist.get(top, {}); reasons = []
    if not an["robust"]:
        reasons.append(f"견고하지 않은 1위 — 가중치에 따라 바뀜 (1위 확률 {round(an['p_first'][top]*100)}%)")
    if tc.get("reversible") is False:
        reasons.append("1위 후보가 되돌리기 어려움")
    if tc.get("cost_class") == "heavy":
        reasons.append("1위 후보가 비싼 실행")
    pres = rows[top]["scores"].get("문제 보존도", [5])[0]
    if pres <= 2:
        reasons.append(f"1위 후보가 문제 보존도를 깎음 ({pres}점)")

    def safe(c):
        cc = clist.get(c, {})
        return cc.get("reversible") is not False and cc.get("cost_class") != "heavy" and not cc.get("closed")

    if an["robust"] and safe(top):
        default, why = top, "1위가 견고하고 되돌릴 수 있음"
    else:
        probes = [c for c in an["rank"] if safe(c)]
        if probes:
            default = max(probes, key=lambda c: (rows[c]["scores"].get("판별력", [0])[0], an["totals"][c]))
            why = ("1위가 가중치에 따라 흔들려 걸지 않고, " if not an["robust"] else "1위는 사용자 확인이 필요한 수라 두지 않고, ") + \
                  "되돌릴 수 있는 수 중 판별력이 가장 높은 것으로 다음 판단을 위한 정보를 얻음"
        else:
            default, why = None, "제한조건 안에서 둘 수 있는 수가 없음 — 응답을 기다림"
    req = None
    if reasons:
        req = {"id": f"{lens}-pick", "lens": lens, "question": "다음 수로 무엇을 둘까요?", "why": " / ".join(reasons),
               "options": an["rank"], "default": default, "default_why": why}
    return {"lens": lens, "need_request": bool(reasons), "reasons": reasons, "default": default,
            "default_why": why, "request": req, "p_first": an["p_first"]}


# ---------- delta ----------
def _cands(spec):
    out = set()
    for v in spec.get("candidates", {}).values():
        for c in v:
            c = c if isinstance(c, dict) else {"name": c}
            if not c.get("closed"):
                out.add(c["name"])
    return out


def _cells(spec):
    t = spec.get("table") or {"rows": []}
    return {(r["candidate"], a): s[0] for r in t["rows"] for a, s in r["scores"].items()}


def delta(prev, cur):
    ch, score = [], 0.0
    rp = table_analysis(prev["table"], n=1)["rank"] if prev.get("table") else []
    rc = table_analysis(cur["table"], n=1)["rank"] if cur.get("table") else []
    if rp and rc and rp[0] != rc[0]:
        score += 3; ch.append(f"1순위 변경: {rp[0]} → {rc[0]}")
    if prev.get("scope") != cur.get("scope"):
        score += 2; ch.append(f"Lens 변경: {prev.get('scope')} → {cur.get('scope')}")
    a, b = _cands(prev), _cands(cur)
    for c in sorted(b - a):
        score += 1; ch.append(f"후보 추가: {c}")
    for c in sorted(a - b):
        score += 1; ch.append(f"후보 기각: {c}")
    common = [c for c in rc[1:] if c in rp[1:]]
    moved = [c for c in common if rp.index(c) != rc.index(c)]
    if moved:
        score += 0.5 * len(moved); ch.append(f"순위 변동: {', '.join(moved)}")
    cp, cc = _cells(prev), _cells(cur)
    nchg = sum(1 for k in cc if k in cp and cp[k] != cc[k])
    if nchg:
        score += 0.5 * (nchg // 3); ch.append(f"점수 갱신 {nchg}칸")
    return {"delta": score, "changes": ch}


def truncate_decision(history, threshold=1.0, run=2):
    tail = history[-run:]
    return len(tail) == run and all(d <= threshold for d in tail)


# ---------- scaling / leak ----------
def fit_loglog(xs, ys):
    lx, ly = [math.log(x) for x in xs], [math.log(y) for y in ys]
    n = len(lx); mx, my = sum(lx) / n, sum(ly) / n
    sxx = sum((x - mx) ** 2 for x in lx)
    k = sum((x - mx) * (y - my) for x, y in zip(lx, ly)) / sxx
    res = sum((y - (my + k * (x - mx))) ** 2 for x, y in zip(lx, ly))
    tot = sum((y - my) ** 2 for y in ly) or 1e-12
    return k, 1 - res / tot


def classify(k):
    for lo, hi, name in [(-0.25, 0.25, "상수"), (0.75, 1.3, "선형"), (1.7, 2.3, "제곱"), (2.7, 3.3, "세제곱")]:
        if lo <= k <= hi:
            return name
    return "중간형(혼합 항 가능)" if k < 2.7 else "세제곱 초과"


def fit_offset_power(xs, ys):
    """y = c + a*x^k 를 k 격자 탐색 + (c, a) 최소제곱으로 맞춘다. 상수항(고정 메모리 등)을 분리한다."""
    best = None
    n = len(xs); my = sum(ys) / n
    tot = sum((y - my) ** 2 for y in ys) or 1e-12
    for i in range(0, 401):
        k = i / 100
        zs = [x ** k for x in xs]
        mz = sum(zs) / n
        szz = sum((z - mz) ** 2 for z in zs)
        if szz == 0:
            continue
        a = sum((z - mz) * (y - my) for z, y in zip(zs, ys)) / szz
        c = my - a * mz
        res = sum((y - (c + a * z)) ** 2 for z, y in zip(zs, ys))
        if best is None or res < best[0]:
            best = (res, k, a, c)
    res, k, a, c = best
    return k, a, c, 1 - res / tot


def scaling(rows, x, y, group=None):
    groups = {}
    for r in rows:
        key = ",".join(f"{k}={r.get(k)}" for k in group.split(",")) if group else "_"
        groups.setdefault(key, []).append(r)
    out = []
    for g, rs in groups.items():
        ok = sorted([r for r in rs if r.get("ok", True) and r.get(y) is not None], key=lambda r: r[x])
        fail = [r[x] for r in rs if not r.get("ok", True)]
        if len(ok) < 3:
            out.append({"group": g, "error": "측정점 3개 미만 (상수항 분리에 3점 이상 필요)",
                        "fails_from": min(fail) if fail else None}); continue
        xs, ys = [r[x] for r in ok], [r[y] for r in ok]
        k, a, c, r2 = fit_offset_power(xs, ys)
        naive, _ = fit_loglog(xs, ys) if min(ys) > 0 else (None, None)
        top = ys[-1]
        out.append({"group": g, "exponent": round(k, 2), "shape": classify(k), "baseline": round(c, 4),
                    "baseline_share_at_max": round(c / top, 3) if top else None, "r2": round(r2, 4),
                    "naive_loglog_exponent": round(naive, 2) if naive is not None else None,
                    "fails_from": min(fail) if fail else None,
                    "points": len(ok),
                    "note": ("측정점이 적어 지수가 불안정할 수 있음 — 범위를 넓혀 4점 이상 권장" if len(ok) < 4 else "")
                    + (" 상수항 비중이 커서 단순 log-log는 지수를 과소평가함" if naive is not None and abs(naive - k) > 0.4 else "")})
    return out


def leak(series, y):
    ys = [s[y] if isinstance(s, dict) else s for s in series]
    n = len(ys)
    if n < 4:
        return {"error": "측정점 4개 미만"}
    xs = list(range(n)); mx, my = (n - 1) / 2, sum(ys) / n
    slope = sum((a - mx) * (b - my) for a, b in zip(xs, ys)) / sum((a - mx) ** 2 for a in xs)
    half = n // 2
    rise = (sum(ys[half:]) / (n - half)) - (sum(ys[:half]) / half)
    rel = rise / (abs(my) or 1e-12)
    return {"slope_per_step": slope, "relative_rise": round(rel, 4),
            "leak_suspected": rel > 0.05 and slope > 0,
            "note": "스텝이 지날수록 늘어남 — 누수(텐서 누적, 그래프 보존) 의심" if rel > 0.05 and slope > 0
            else "평탄 — 누수 아님"}


# ---------- sweep ----------
def sweep(cmd, grid, timeout):
    keys = list(grid)
    rows = []
    for combo in itertools.product(*[grid[k] for k in keys]):
        params = dict(zip(keys, combo))
        c = cmd.format(**params)
        t0 = time.time()
        try:
            p = subprocess.run(shlex.split(c), capture_output=True, text=True, timeout=timeout)
            line = next((l for l in reversed(p.stdout.strip().splitlines()) if l.strip().startswith("{")), None)
            if p.returncode == 0 and line:
                rows.append({**params, **json.loads(line), "ok": True, "wall_s": round(time.time() - t0, 2)})
            else:
                rows.append({**params, "ok": False, "err": (p.stderr or p.stdout).strip()[-300:]})
        except subprocess.TimeoutExpired:
            rows.append({**params, "ok": False, "err": f"timeout {timeout}s"})
        print(json.dumps(rows[-1], ensure_ascii=False), file=sys.stderr)
    return rows


def to_knobs(rows, grid):
    metrics = sorted({k for r in rows if r.get("ok") for k in r if k not in grid and k not in ("ok", "wall_s", "err")})
    return {"params": {k: list(v) for k, v in grid.items()}, "metrics": metrics,
            "points": [{"at": {k: r[k] for k in grid}, "ok": r["ok"],
                        "values": {m: r.get(m) for m in metrics}, "err": r.get("err")} for r in rows]}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="tool", required=True)
    t = sub.add_parser("table"); t.add_argument("spec"); t.add_argument("--n", type=int, default=2000)
    t.add_argument("--jitter", type=float, default=0.3); t.add_argument("--write", action="store_true")
    d = sub.add_parser("delta"); d.add_argument("prev"); d.add_argument("cur"); d.add_argument("--history")
    s = sub.add_parser("scaling"); s.add_argument("data"); s.add_argument("--x", required=True)
    s.add_argument("--y", required=True); s.add_argument("--group", help="쉼표로 여러 키: B,prec")
    l = sub.add_parser("leak"); l.add_argument("series"); l.add_argument("--y", default="mem")
    dc = sub.add_parser("decide"); dc.add_argument("spec"); dc.add_argument("--lens"); dc.add_argument("--write", action="store_true")
    w = sub.add_parser("sweep"); w.add_argument("--cmd", dest="command", required=True); w.add_argument("--grid", required=True)
    w.add_argument("--timeout", type=int, default=300); w.add_argument("--out"); w.add_argument("--knobs")
    a = ap.parse_args()

    if a.tool == "table":
        spec = load(a.spec); res = table_analysis(spec["table"], a.n, a.jitter)
        if a.write:
            spec["table"]["analysis"] = res; dump(spec, a.spec)
        dump(res)
    elif a.tool == "decide":
        spec = load(a.spec); res = decide(spec, a.lens)
        if a.write and res["request"]:
            spec["requests"] = [r for r in spec.get("requests", []) if r["id"] != res["request"]["id"]] + [res["request"]]
            dump(spec, a.spec)
        dump(res)
    elif a.tool == "delta":
        res = delta(load(a.prev), load(a.cur))
        if a.history:
            try:
                h = load(a.history)
            except FileNotFoundError:
                h = []
            h.append(res["delta"]); dump(h, a.history)
            res["history"] = h; res["truncate"] = truncate_decision(h)
        dump(res)
    elif a.tool == "scaling":
        dump(scaling(load(a.data), a.x, a.y, a.group))
    elif a.tool == "leak":
        dump(leak(load(a.series), a.y))
    elif a.tool == "sweep":
        grid = json.loads(a.grid)
        rows = sweep(a.command, grid, a.timeout)
        if a.out:
            dump(rows, a.out)
        if a.knobs:
            spec = load(a.knobs); spec["knobs"] = to_knobs(rows, grid); dump(spec, a.knobs)
        dump(rows)


if __name__ == "__main__":
    main()
