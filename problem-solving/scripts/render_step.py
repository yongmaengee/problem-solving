#!/usr/bin/env python3
"""Blueprint + Lens 렌더러 (중간 개입용).

사용법: python render_step.py spec.json out.html

Blueprint  = 캔버스 전체. 코드의 정보 흐름을 블록 트리로 펼친 설계도.
Lens       = Blueprint 위를 움직이는 초점. Lens 안은 선명하고 바깥은 흐려진다.
             진행 중인 스프린트의 Lens는 바깥 테두리가 천천히 돈다.
             Lens 옆에는 카드가 순서대로 이어 붙는다: 지금 보는 곳 → 둘 수 있는 수 →
             두면 생길 일 → 견주어 보기 → 바꿔 볼 수 있는 값 → 정해 주실 것.
             선 모양은 확실성(실선 확인 · 점선 예측 · 흐린 선 약함), 색은 관계의 종류.
Lens 이동  = Claude가 lens_path로 코드의 처리 흐름을 따라 경로를 정한다.
             이동은 문제 영역(problem) 아래이거나 문제 영역과 직결된 블록 안으로만 허용된다.

spec (전체 예시: examples/oom_spec.json):
{
  "title": "...",
  "nodes": [{"id","label","note","children":[...],"code","hl":[줄],"codeNote"}],
  "problem": ["model","train"],          # 문제로 정의한 블록(들). Lens 허용 범위의 기준
  "connected": ["data"],                 # 선택: 흐름상 인접하지 않지만 문제 영역과 직결된 블록
  "scope": "train",                      # Lens 시작 위치
  "lens_path": [{"at":"train","why":"..."},{"at":"attn","why":"..."}],   # Claude가 정한 Lens 경로
  "candidates": {"train":[{"name","source","check","diff","port_code","port_condition",
                            "outcomes":[{"case","p","text","learn"}],"closed":false}]},
  "ripples": [{"from","to","effect","kind":"direct|own"}],
  "table": {"axes":[...],"weights":{},"rows":[...],"analysis":{...}},
  "scopes": {"attn":{"candidates":{...},"ripples":[...],"table":{...}}},   # 미리 계산한 다른 Lens 위치
  "knobs": {...},                        # quant.py sweep --knobs
  "excluded": ["pre"],                   # 논의에서 제외한 블록
  "ask": "검토형 결정 질문",
  "theme": "light"                       # light(기본) · dark · auto(시스템 설정 따름)
}
"""
import json
import sys


def upgrade(spec):
    if "nodes" not in spec:
        notes = spec.get("notes", {})
        spec["nodes"] = [{"id": b, "label": b, **({"note": notes[b]} if b in notes else {})} for b in spec["blocks"]]
    sc = spec.get("scope")
    if isinstance(sc, list):
        spec["scope"] = sc[0] if sc else None
    if isinstance(spec.get("problem"), str):
        spec["problem"] = [spec["problem"]]
    return spec


CSS = r"""
:root{--bg:#f7f6f2;--card:#fff;--fg:#1f1e1c;--mut:#6b6a65;--bd:#d3d1c7;--acc:#534ab7;--accbg:#eeedfe;--accfg:#3c3489;--rip:#f1efe8;--hi:#faeeda;--hifg:#633806;--code:#f1efe8;--line:#7f77dd;--own:#d85a30;--ok:#1d9e75;--bad:#e24b4a;--mid:#ba7517;--prob:#fbfaf6;--sh:0 1px 2px rgba(0,0,0,.06),0 8px 24px rgba(0,0,0,.06)}
[data-theme="dark"]{--bg:#161615;--card:#22221f;--fg:#ecebe6;--mut:#a3a29c;--bd:#3d3d3a;--acc:#afa9ec;--accbg:#2a2650;--accfg:#e4e2fb;--rip:#2a2a27;--hi:#4a3208;--hifg:#fac775;--code:#1b1b19;--own:#f0997b;--prob:#1d1d1b;--sh:0 1px 2px rgba(0,0,0,.4),0 8px 24px rgba(0,0,0,.35)}
*{box-sizing:border-box}html,body{height:100%;margin:0;overflow:hidden;background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,-apple-system,"Apple SD Gothic Neo","Noto Sans KR",sans-serif}
#vp{position:fixed;inset:0;overflow:hidden;cursor:grab}#vp.grab{cursor:grabbing}
#world{position:absolute;left:0;top:0;transform-origin:0 0;transition:transform .9s cubic-bezier(.65,0,.35,1)}#world.free{transition:none}
#links{position:absolute;left:0;top:0;overflow:visible;pointer-events:none}
.trow{display:flex;align-items:flex-start;gap:28px;width:max-content}
#bp{display:flex;align-items:flex-start;gap:70px;padding:110px 120px;width:max-content}
.trow.column{flex-direction:column;align-items:flex-start;gap:18px}.trow.column>.flow{margin:0 0 0 140px}
.trow.grid{display:grid;grid-template-columns:repeat(var(--gc),300px);gap:46px 40px;align-items:start}
.krow.column{flex-direction:column;gap:14px}.krow.column>.flow{margin:0 0 0 120px}
.ord{position:absolute;top:-11px;right:14px;font-size:11px;font-weight:600;width:20px;height:20px;border-radius:50%;background:var(--card);border:1px solid var(--bd);display:flex;align-items:center;justify-content:center;color:var(--mut)}
#ov{width:360px;flex:none;background:var(--card);border:1px solid var(--bd);border-left:4px solid var(--acc);border-radius:16px;box-shadow:var(--sh);padding:16px 18px;font-size:13px}
#ov h3{margin:0 0 2px;font-size:16px}#ov .ovs{font-size:11.5px;color:var(--mut);margin-bottom:10px}
#ov .r{margin-top:10px}#ov .r b{display:block;font-size:11.5px;color:var(--acc);margin-bottom:2px;font-weight:600}#ov ul{margin:2px 0 0;padding-left:16px}#ov li{margin:1px 0}
#ov .now{background:var(--accbg);color:var(--accfg);border-radius:8px;padding:7px 9px}
.flow{color:var(--mut);font-size:22px;margin-top:22px;flex:none;user-select:none}
.node{width:300px;flex:none;border:1px solid var(--bd);border-radius:16px;background:var(--card);padding:16px;box-shadow:var(--sh);cursor:zoom-in;position:relative;
  transition:opacity .6s,filter .6s,box-shadow .3s,border-color .3s,border-radius .6s}
.node:hover{border-color:var(--acc)}.node.focus{box-shadow:0 0 0 3px var(--accbg),var(--sh)}
.node.prob{background:linear-gradient(var(--card),var(--card)) padding-box,repeating-linear-gradient(135deg,var(--bd) 0 6px,transparent 6px 12px) border-box;border:1.5px solid transparent}
.tag{position:absolute;top:-11px;left:14px;font-size:11px;padding:1px 8px;border-radius:999px;background:var(--bd);color:var(--fg);letter-spacing:.02em}
.tag.p{background:var(--hi);color:var(--hifg)}
.lab{font-weight:600;font-size:17px;letter-spacing:-.01em}.note{font-size:12.5px;color:var(--mut);margin-top:4px}
.kids{position:relative;margin-top:14px;border-top:1px solid var(--bd);padding-top:14px}
.krow{position:absolute;left:0;top:14px;display:flex;align-items:flex-start;gap:28px;width:max-content;transform-origin:0 0}
.stack{display:flex;flex-direction:column;gap:8px;margin-top:14px}
.cand{border:1px solid var(--acc);border-radius:10px;padding:9px 11px;background:var(--accbg);color:var(--accfg);font-weight:500;cursor:pointer}
.cand.picked{outline:3px solid var(--acc);outline-offset:2px}
.cand .m,.rip .m{font-size:11.5px;font-weight:400;opacity:.8;margin-top:2px}
.cand.closed{background:transparent;border-style:dashed;color:var(--mut);text-decoration:line-through;cursor:default}
.rip{border:1px dashed var(--bd);border-radius:10px;padding:8px 11px;background:var(--rip);font-size:13px}.rip.own{border-color:var(--own)}
pre.code{font:11.5px/1.55 ui-monospace,SFMono-Regular,Menlo,monospace;background:var(--code);border-radius:10px;padding:10px 0;margin:12px 0 0;overflow:hidden;white-space:pre-wrap;word-break:break-all}
pre.code span{display:block;padding:0 10px}pre.code span.h{background:var(--hi);color:var(--hifg)}
.cn{font-size:11.5px;color:var(--hifg);background:var(--hi);border-radius:6px;padding:4px 8px;margin-top:6px}
.node.ex{width:auto;min-width:150px;padding:10px 20px;border-radius:999px;border-style:dashed;box-shadow:none}
.node.ex .note{margin:0;font-size:11px}.node.exin{animation:exin .6s cubic-bezier(.65,0,.35,1)}
@keyframes exin{from{border-radius:16px;transform:scale(1.04)}to{border-radius:999px;transform:none}}
#world.fanning .node:not(.path){opacity:.16!important;filter:blur(3px)!important}
/* Lens */
#lens{position:absolute;pointer-events:none;z-index:2;
  transition:left .9s cubic-bezier(.65,0,.35,1),top .9s cubic-bezier(.65,0,.35,1),width .9s cubic-bezier(.65,0,.35,1),height .9s cubic-bezier(.65,0,.35,1)}
#lens svg.lo{position:absolute;inset:0;width:100%;height:100%;overflow:visible}#lens svg.lo rect{fill:none;stroke:var(--acc)}
#lens .lt{white-space:nowrap;position:absolute;bottom:-12px;left:18px;background:var(--acc);color:var(--card);font-size:11px;padding:1px 9px;border-radius:999px;transform-origin:0 100%}
.wg{display:grid;grid-template-columns:auto 1fr 34px;gap:4px 8px;align-items:center;font-size:11.5px;margin:8px 0}.wg input{width:100%;accent-color:var(--acc)}
.w{font-size:11px;color:var(--mut)}.kres{padding:8px 10px;border-radius:8px;background:var(--rip);font-size:12.5px;margin-top:6px}.kres.ok{border-left:3px solid var(--ok)}.kres.bad{border-left:3px solid var(--bad)}
.warn{padding:9px;border-radius:8px;background:var(--hi);color:var(--hifg);font-size:12px}
textarea{width:100%;min-height:56px;border:1px solid var(--bd);border-radius:8px;background:var(--card);color:var(--fg);font:inherit;font-size:12.5px;padding:7px}
#msg{white-space:pre-wrap;font:11px/1.5 ui-monospace,monospace;background:var(--code);padding:8px;border-radius:8px;margin:8px 0}
button.pri{background:var(--acc);color:var(--card);border:0;border-radius:8px;padding:6px 11px;font:inherit;font-size:12.5px;cursor:pointer}
.ask{padding:9px 10px;border-left:3px solid var(--acc);background:var(--accbg);color:var(--accfg);border-radius:0 8px 8px 0;font-size:12.5px;margin-bottom:10px}
.rq{border:1px solid var(--bd);border-radius:10px;padding:10px;margin-bottom:10px}.rqq{font-weight:600;font-size:13px;margin-bottom:3px}
.ops{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0}.op{border:1px solid var(--bd);background:var(--card);color:var(--fg);border-radius:8px;padding:5px 9px;font:inherit;font-size:12px;cursor:pointer}
.op.on{border-color:var(--acc);background:var(--accbg);color:var(--accfg)}.op i{font-style:normal;font-size:10px;color:var(--mut);margin-left:3px}
.dflt{font-size:11.5px;color:var(--mut);background:var(--rip);border-radius:6px;padding:6px 8px}
details summary{cursor:pointer;margin-top:8px}
#sprints{bottom:74px;left:50%;transform:translateX(-50%);display:flex;align-items:center;gap:6px;padding:6px 8px;max-width:92vw;overflow-x:auto;white-space:nowrap}
#sprints .sc{border:1px solid var(--bd);background:var(--card);color:var(--fg);border-radius:999px;padding:3px 10px;font:inherit;font-size:12px;cursor:pointer}
#sprints .sc.on{border-color:var(--acc);background:var(--accbg);color:var(--accfg)}#sprints .sc.act b::before{content:"● ";color:var(--ok)}
#sprints .sc i{font-style:normal;color:var(--mut);font-size:11px}#sprints .sa{color:var(--mut)}
.tag.c{background:var(--accbg);color:var(--accfg)}.node.chg{box-shadow:0 0 0 2px var(--accbg),var(--sh)}
#stack.two{width:760px;flex-direction:row;align-items:flex-start;gap:40px}#stack .col{display:flex;flex-direction:column;gap:22px;width:360px;flex:none}
#stack{position:absolute;z-index:3;width:360px;transform-origin:0 0;display:flex;flex-direction:column;gap:22px;transition:left .9s cubic-bezier(.65,0,.35,1),top .9s cubic-bezier(.65,0,.35,1)}
#stack svg.sl{position:absolute;left:0;top:0;width:1px;height:1px;overflow:visible;pointer-events:none}
.sec{position:relative;background:var(--card);border:1px solid var(--bd);border-radius:14px;box-shadow:var(--sh);padding:12px 14px;opacity:0;transform:translateY(-10px) scale(.98);transition:opacity .45s,transform .45s}
.sec.in{opacity:1;transform:none}.sec .st{font-size:12px;font-weight:600;color:var(--acc);margin-bottom:6px;letter-spacing:.01em}
.sec .big{font-weight:600;font-size:15px}.sec .kv{margin-top:8px;font-size:12.5px}.note2{margin-top:8px;padding:8px 10px;border-left:3px solid var(--acc);background:var(--accbg);color:var(--accfg);border-radius:0 8px 8px 0;font-size:12.5px}
.mv,.cs{border:1px solid var(--bd);border-radius:10px;padding:8px 10px;margin-top:6px;font-size:12.5px;cursor:pointer}.mv:hover,.cs:hover{border-color:var(--acc)}
.mv.on{border-color:var(--acc);background:var(--accbg)}.mv.closed{cursor:default;opacity:.6}.mv.closed b{text-decoration:line-through}
.bar{display:flex;height:6px;border-radius:3px;overflow:hidden;margin:6px 0 3px;gap:2px}.bar i{display:block}.bar i.ok{background:var(--ok)}.bar i.mid{background:var(--mid)}.bar i.bad{background:var(--bad)}
.hint{margin-top:6px}
.sec table{border-collapse:collapse;font-size:11.5px;width:100%}.sec th,.sec td{border-bottom:1px solid var(--bd);padding:4px 3px;text-align:center}
.sec th{font-weight:500;font-size:10.5px;color:var(--mut)}.sec td.n{text-align:left;font-weight:600}.sec tr.top td{background:var(--hi)}.sec tr.sel td{outline:1px solid var(--acc)}
.ln{fill:none;stroke:var(--line)}.ln.solid{}.ln.faint{opacity:.35}.ln.dash{stroke-dasharray:6 5}
#legend{bottom:18px;left:16px;padding:8px 10px;font-size:11px;color:var(--mut);display:grid;grid-template-columns:28px auto;gap:3px 8px;align-items:center}
#legend svg{width:28px;height:8px;overflow:visible}#legend .x{grid-column:1/3;text-align:right;cursor:pointer;color:var(--acc)}
@keyframes ring{to{stroke-dashoffset:-22}}
#lens svg.lo rect{stroke-dasharray:7 4}#lens.live svg.lo rect{animation:ring 2.4s linear infinite}#lens.live.moving svg.lo rect{animation-duration:.5s}
#plinks{position:absolute;left:0;top:0;width:1px;height:1px;overflow:visible;pointer-events:none;z-index:2}
#proxy{position:absolute;z-index:3;transform-origin:0 0;transition:left .9s cubic-bezier(.65,0,.35,1),top .9s cubic-bezier(.65,0,.35,1)}
.pxrow{display:flex;gap:22px;align-items:flex-end;width:max-content}.pxrow.vcol{flex-direction:column;align-items:flex-end;gap:16px}
.px{width:230px;background:var(--card);border:1px solid var(--bd);border-top:3px solid var(--line);border-radius:12px;box-shadow:var(--sh);padding:9px 11px;font-size:12px;cursor:zoom-in;
  opacity:0;transform:translateY(12px) scale(.96);transition:opacity .45s,transform .45s,box-shadow .3s,border-color .3s}
.px.in{opacity:1;transform:none}.px.dim{opacity:.35}.px.hit{border-color:var(--acc);box-shadow:0 0 0 3px var(--accbg),var(--sh)}
.px .pp{font-size:10.5px;color:var(--mut)}.px .pl{font-weight:600;font-size:14px;margin:1px 0 4px}
.px .pe{border-left:2px solid var(--line);padding-left:6px;margin-top:4px}.px .pe.own{border-color:var(--own)}.px .pe i{font-style:normal;color:var(--own);font-size:10.5px}
.px .pw{color:var(--mut);margin-top:4px}
#plinks path{fill:none}#plinks path.po{stroke:var(--mut);opacity:.55;stroke-dasharray:1.2 1.4;animation:flow 1.6s linear infinite}#plinks path.po.on{stroke:var(--acc);opacity:.9}
#plinks path.pf{opacity:.28;stroke-dasharray:2.4 1.8}#plinks path.pf.conf{stroke-dasharray:none}#plinks path.pf.weak{opacity:.15}
#plinks path.pf.on{opacity:1;animation:flow .9s linear infinite}#plinks path.pf.on.conf{stroke-dasharray:5 1.2}#plinks path.pf.on.weak{opacity:.5}
@keyframes flow{to{stroke-dashoffset:-8.4}}
#plinks circle.pin{fill:var(--mut);opacity:.6}#plinks circle.pin.on{opacity:1}
.vb{display:inline-block;font-size:10.5px;font-weight:600;padding:0 6px;border-radius:999px;margin-left:2px;vertical-align:1px}
.vb.v3{background:#e1f5ee;color:#085041}.vb.v2{background:#faeeda;color:#633806}.vb.v1{background:#fcebeb;color:#791f1f}.vb.v0{background:var(--rip);color:var(--mut)}
[data-theme="dark"] .vb.v3{background:#085041;color:#9fe1cb}[data-theme="dark"] .vb.v2{background:#633806;color:#fac775}[data-theme="dark"] .vb.v1{background:#791f1f;color:#f7c1c1}
.ev{margin-top:5px;display:flex;flex-wrap:wrap;gap:4px 10px;font-size:11.5px}.evl{color:var(--acc);text-decoration:none;cursor:pointer}.evl:hover{text-decoration:underline}
.evc{width:100%}.evc summary{cursor:pointer;color:var(--acc);font-size:11.5px}pre.code.sm{font-size:10.5px;margin-top:4px}
.ub{display:inline-block;font-size:10px;font-weight:600;padding:0 6px;border-radius:999px;background:var(--hi);color:var(--hifg)}
.cand.user{border-style:dashed}.mv.user{border-style:dashed}.mv.pend{opacity:.75;cursor:default}
.newp{margin:8px 0;border:1px dashed var(--acc);border-radius:10px;padding:8px 10px}.newp summary{cursor:pointer;color:var(--acc);font-weight:600;font-size:12.5px}
.fl2{display:block;font-size:11.5px;color:var(--mut);margin-top:6px}.fl2 input{display:block;width:100%;margin-top:2px;border:1px solid var(--bd);border-radius:7px;background:var(--card);color:var(--fg);font:inherit;font-size:12.5px;padding:5px 7px}
.rq.fill{border-color:var(--acc)}
/* fan */
#fan{position:absolute;left:0;top:0;z-index:3}
#fan svg.fl{position:absolute;left:0;top:0;overflow:visible;width:1px;height:1px;pointer-events:none}
#fan svg.fl path{fill:none;stroke:var(--line);stroke-dasharray:100;stroke-dashoffset:100;transition:stroke-dashoffset .7s ease,opacity .7s}#fan svg.fl path.in{stroke-dashoffset:0}#fan svg.fl path.faint.in{opacity:.4}#fan svg.fl path.dash.in{stroke-dasharray:3 2.5}
.fwrap{position:absolute;display:flex;flex-direction:column;gap:16px;width:240px;transform-origin:0 0}
.fcard{padding:10px 12px;border-radius:12px;background:var(--card);border:1px solid var(--bd);box-shadow:var(--sh);font-size:12.5px;opacity:0;transform:translateX(-14px) scale(.97);transition:opacity .45s,transform .45s}
.fcard.in{opacity:1;transform:none}.fcard .ft{font-weight:600;font-size:12px;margin-bottom:3px}.fcard .fs{font-size:11.5px;color:var(--mut);margin-top:4px}
.fcard.k-ok{border-left:4px solid var(--ok)}.fcard.k-bad{border-left:4px solid var(--bad)}.fcard.k-mid{border-left:4px solid var(--mid)}.fcard.k-src{border-left:4px solid var(--acc)}.fcard.k-port{border-left:4px solid #888780}.fcard.k-rip{border-left:4px solid var(--own)}
/* chrome */
.ui{position:fixed;z-index:5;background:var(--card);border:1px solid var(--bd);border-radius:12px;box-shadow:var(--sh)}
#theme{top:16px;right:16px;padding:6px 11px;cursor:pointer;font:inherit;color:var(--fg)}
#crumb{top:16px;left:16px;padding:8px 12px;font-size:13px;max-width:72vw}#crumb a{color:var(--acc);cursor:pointer;text-decoration:none}#crumb .t{font-weight:600;margin-right:10px}
#crumb .h{font-size:11px;color:var(--mut);margin-top:2px}
#crumb button{margin-left:8px;border:1px solid var(--acc);background:var(--accbg);color:var(--accfg);border-radius:8px;padding:3px 8px;font:inherit;font-size:12px;cursor:pointer}
#crumb button.ghost{background:transparent;border-color:var(--bd);color:var(--mut)}#crumb button[disabled]{opacity:.5;cursor:not-allowed}
#bar{bottom:18px;left:50%;transform:translateX(-50%);display:flex;align-items:center;gap:12px;padding:8px 10px;max-width:min(880px,92vw)}
#bar button{border:1px solid var(--bd);background:var(--card);color:var(--fg);border-radius:8px;padding:6px 10px;cursor:pointer;font:inherit}
#cap{flex:1;font-size:13.5px;min-width:200px}#dots{display:flex;gap:5px}#dots i{width:7px;height:7px;border-radius:50%;background:var(--bd);cursor:pointer}#dots i.on{background:var(--acc)}
"""

JS = r"""
const S=__SPEC__;
const $=id=>document.getElementById(id);
const vp=$('vp'),world=$('world'),topRow=$('top'),bpEl=$('bp'),ovEl=$('ov'),lensEl=$('lens'),stackEl=$('stack'),fanEl=$('fan'),pxEl=$('proxy'),plSvg=$('plinks');let PX=[];
const E=(t,c,h)=>{const e=document.createElement(t);if(c)e.className=c;if(h!=null)e.innerHTML=h;return e};
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const vb=c=>c?'<span class="vb v'+({'강':3,'중':2,'약':1}[c]||0)+'">검증: '+esc(c)+'</span>':'';
const safeUrl=u=>/^https?:\/\//.test(u||'')?u:null;
function evs(c){const L=[];(c.evidence||[]).forEach(e=>L.push(e));if(c.url)L.push({type:'url',label:c.source||c.url,url:c.url});if(c.code)L.push({type:'code',...c.code});return L}
function evHTML(c,full){const L=evs(c);if(!L.length)return'';let h='<div class="ev">';
  L.forEach(e=>{if(e.type==='code'){h+='<details class="evc"'+(full?' open':'')+'><summary>코드 '+esc(e.path||'')+(e.lines?':'+esc(e.lines):'')+'</summary>'+(e.snippet?'<pre class="code sm">'+esc(e.snippet)+'</pre>':'')+(e.note?'<div class="w">'+esc(e.note)+'</div>':'')+'</details>'}
    else{const u=safeUrl(e.url);h+=u?'<a class="evl" href="'+esc(u)+'" target="_blank" rel="noopener">'+esc(e.label||u)+' ↗</a>':'<span class="evl">'+esc(e.label||'')+'</span>'}});
  return h+'</div>'}
const ORIG={candidates:S.candidates||{},ripples:S.ripples||[],table:S.table||null},PRE=S.scopes||{};
const st={lens:S.scope,origin:S.origin||S.scope,pick:null,weights:{},knob:{},note:'',ex:new Set(S.excluded||[]),moves:[],ans:{},newp:{},fill:{}};
const SP=S.sprints||[];let spi=SP.length?SP.length-1:-1;
const spFor=id=>{for(let i=SP.length-1;i>=0;i--)if(SP[i].lens===id&&i<=Math.max(spi,0))return SP[i];return null};
const REQ=()=>(S.requests||[]).filter(r=>!r.lens||r.lens===st.lens);
let byId={},cam={x:0,y:0,s:1},BOX=new Map(),cur=null,F=[],fi=0,moved=false,drag=null,V=null,fanOpen=null;
function view(){const id=st.lens;if(id===st.origin)return{...ORIG,pull:S.pull||[],pre:true};const p=PRE[id];
  return p?{candidates:p.candidates||{},ripples:p.ripples||[],table:p.table||null,pull:p.pull||[],pre:true}:{candidates:{},ripples:[],table:null,pull:[],pre:false}}
function idx(list,parent){list.forEach(n=>{n.id=n.id||n.label;n.parent=parent;byId[n.id]=n;idx(n.children||[],n)})}
idx(S.nodes,null);
/* ---- Lens 허용 범위: 문제 영역의 하위 + 문제 영역과 직결된 블록 ---- */
const PROB=new Set(S.problem||(S.scope?[S.scope]:[])),ALLOW=new Set();
function sub(n,set){set.add(n.id);(n.children||[]).forEach(c=>sub(c,set))}
PROB.forEach(id=>{const n=byId[id];if(!n)return;sub(n,ALLOW);const sib=n.parent?n.parent.children:S.nodes,i=sib.indexOf(n);
  [sib[i-1],sib[i+1]].forEach(m=>{if(m)ALLOW.add(m.id)})});
(S.connected||[]).forEach(id=>ALLOW.add(id));if(S.scope)ALLOW.add(S.scope);
const inRange=id=>ALLOW.has(id);
/* ---- Blueprint 배치 ---- */
function decideLayout(){const L=S.layout;if(L==='row'||L==='column'||L==='grid')return L;const n=S.nodes.length;
  return n<=6?'row':(S.branching?'grid':(n<=12?'column':'grid'))}
const LAYOUT=decideLayout();
/* ---- Blueprint ---- */
function build(n){
  if(st.ex.has(n.id)){const el=E('div','node ex');n.el=el;el.dataset.id=n.id;el.append(E('div','lab',esc(n.label)),E('div','note','논의에서 제외'));n.row=null;
    el.addEventListener('click',e=>{e.stopPropagation();if(!moved)focus(n)});return el}
  const el=E('div','node'+(PROB.has(n.id)?' prob':''));n.el=el;el.dataset.id=n.id;
  if(n.changed)el.classList.add('chg');
  if(PROB.has(n.id))el.append(E('div','tag p','문제 정의'+(n.changed?' · 갱신':'')));else if(n.changed)el.append(E('div','tag c','갱신'));else if(!n.changed&&n.id!==st.lens&&(PRE[n.id]||n.id===st.origin))el.append(E('div','tag','미리 계산됨'));
  el.append(E('div','lab',esc(n.label)));if(n.note)el.append(E('div','note',esc(n.note)));
  if(n.code){const pre=E('pre','code'),hl=new Set(n.hl||[]);n.code.split('\n').forEach((l,i)=>pre.append(E('span',hl.has(i+1)?'h':'',esc(l)||' ')));el.append(pre);
    if(n.codeNote)el.append(E('div','cn',esc(n.codeNote)))}
  n.row=null;if(n.children&&n.children.length){const col=n.layout==='column',k=E('div','kids'),r=E('div','krow'+(col?' column':''));n.children.forEach((c,i)=>{if(i)r.append(E('div','flow',col?'↓':'→'));r.append(build(c))});k.append(r);el.append(k);n.row=r;n.kids=k}
  const cs=V.candidates[n.id];if(n.id===st.lens&&cs&&cs.length){const sk=E('div','stack');cs.forEach(c=>{c=typeof c==='string'?{name:c}:c;
    const d=E('div','cand'+(c.closed?' closed':'')+(c.proposed_by==='user'?' user':'')+(st.pick===c.name?' picked':''),esc(c.name)+'<div class="m">'+(c.proposed_by==='user'?'<span class="ub">사용자 제안</span> ':'')+esc(c.source||'')+' '+vb(c.check)+'</div>');d.dataset.cand=c.name;
    if(!c.closed){d.addEventListener('mouseenter',()=>{st.hover=c.name;plDraw()});d.addEventListener('mouseleave',()=>{st.hover=null;plDraw()})}
    if(!c.closed)d.addEventListener('click',e=>{e.stopPropagation();if(moved)return;st.pick=st.pick===c.name?null:c.name;markPick();
      if(st.pick){openFan(c,d,n)}else{closeFan();showStack();frameLens()}});sk.append(d)});el.append(sk)}
  const rs=V.ripples.filter(r=>r.to===n.id);if(rs.length){const sk=E('div','stack');rs.forEach(r=>{
    const d=E('div','rip'+(r.kind==='own'?' own':''),'<div class="m">'+esc(r.from)+' →'+(r.kind==='own'?' 자체 반응':'')+'</div>'+esc(r.effect));d.dataset.from=r.from;sk.append(d)});el.append(sk)}
  el.addEventListener('click',e=>{e.stopPropagation();if(!moved)focus(n)});return el}
function fit(n){(n.children||[]).forEach(fit);if(n.row){const inner=n.el.clientWidth-34,k=Math.min(.62,inner/n.row.offsetWidth);
  n.row.style.transform=`scale(${k})`;n.kids.style.height=(n.row.offsetHeight*k+14)+'px'}}
function fade(){const on=new Set(),sc=byId[st.lens];if(!sc)return;sub(sc,on);for(let p=sc.parent;p;p=p.parent)on.add(p.id);
  Object.values(byId).forEach(n=>{if(n.el){n.el.classList.toggle('path',on.has(n.id));delete n.el.dataset.o;n.el.style.opacity='';n.el.style.filter=''}});
  const f=list=>{const j=list.findIndex(n=>on.has(n.id));if(j<0)return;list.forEach((n,i)=>{if(!n.el)return;const d=Math.abs(i-j);
    if(!on.has(n.id)){const ex=st.ex.has(n.id);n.el.dataset.o=ex?.32:Math.max(.42,1-.18*d);n.el.dataset.b=ex?3:Math.min(2.4,.7*d);
      n.el.style.opacity=n.el.dataset.o;n.el.style.filter='blur('+n.el.dataset.b+'px)'}else f(n.children||[])})};f(S.nodes)}
function wpos(el){if(BOX.has(el))return BOX.get(el);const r=el.getBoundingClientRect(),w=world.getBoundingClientRect();const b={x:r.left-w.left,y:r.top-w.top,w:r.width,h:r.height};BOX.set(el,b);return b}
function links(){const svg=$('links');svg.setAttribute('width',bpEl.offsetWidth);svg.setAttribute('height',bpEl.offsetHeight);
  let h='<defs><marker id="ah" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M2 1L8 5L2 9" fill="none" stroke="context-stroke" stroke-width="1.6"/></marker></defs>';
  const cs=[...topRow.querySelectorAll('.cand')];const find=nm=>cs.find(c=>c.dataset.cand===nm)||cs.find(c=>c.dataset.cand.includes(nm)||nm.includes(c.dataset.cand));
  const style=c=>c==='confirmed'?'':c==='weak'?' opacity="__F__"':' stroke-dasharray="6 5"';
  const pulled=new Set(PX.map(x=>x.id));topRow.querySelectorAll('.rip').forEach(rp=>{if(pulled.has(rp.closest('.node').dataset.id))return;const src=find(rp.dataset.from);if(!src)return;const r=V.ripples.find(x=>x.from===rp.dataset.from&&x.to===rp.closest('.node').dataset.id)||{};
    const a=wpos(src),b=wpos(rp),R=b.x>a.x,x1=R?a.x+a.w:a.x,y1=a.y+a.h/2,x2=R?b.x:b.x+b.w,y2=b.y+b.h/2,dx=Math.max(60,Math.abs(x2-x1)*.45)*(R?1:-1);
    let op=1;for(let n=byId[rp.closest('.node').dataset.id];n;n=n.parent)op=Math.min(op,parseFloat(n.el.dataset.o||1));const hot=st.pick&&src.dataset.cand===st.pick;
    const f=(st.pick&&!hot?op*.25:op)*(r.certainty==='weak'?.35:1);
    h+=`<path d="M${x1} ${y1} C${x1+dx} ${y1},${x2-dx} ${y2},${x2} ${y2}" fill="none" stroke="var(${r.kind==='own'?'--own':'--line'})" stroke-width="${hot?2.6:1.6}"${r.certainty==='confirmed'?'':r.certainty==='weak'?'':' stroke-dasharray="6 5"'} vector-effect="non-scaling-stroke" opacity="${f}" marker-end="url(#ah)"/>`});
  (S.relations||[]).forEach(rl=>{const A=find(rl.a),B=find(rl.b);if(!A||!B)return;const a=wpos(A),b=wpos(B),x=Math.min(a.x,b.x),ya=a.y+a.h/2,yb=b.y+b.h/2,bend=Math.max(18,Math.abs(yb-ya)*.35)*(a.w/260);
    const col=rl.type==='conflict'?'--bad':rl.type==='combine'?'--ok':'--line';
    h+=`<path d="M${x} ${ya} C${x-bend} ${ya},${x-bend} ${yb},${x} ${yb}" fill="none" stroke="var(${col})" stroke-width="2"${rl.certainty==='confirmed'?'':rl.certainty==='weak'?' opacity=".35"':' stroke-dasharray="6 5"'} vector-effect="non-scaling-stroke"/>`});
  svg.innerHTML=h}
function markPick(){topRow.querySelectorAll('.cand').forEach(c=>c.classList.toggle('picked',c.dataset.cand===st.pick));links();plDraw()}
/* ---- Lens 오브젝트 ---- */
const SECS=[{k:'here',t:'지금 보는 곳'},{k:'moves',t:'둘 수 있는 수'},{k:'cases',t:'두면 생길 일'},{k:'weigh',t:'견주어 보기'},{k:'try',t:'바꿔 볼 수 있는 값'},{k:'ask',t:'정해 주실 것'}];
const UPTO={'정렬':1,'범위':1,'깊이':1,'탐색':2,'경우의 수':3,'결정':6,'종료':6,'정리':6};
const shown={};
function lensRect(){const n=byId[st.lens];if(!n||!n.el)return null;const b=wpos(n.el),k=b.w/300,p=12*k;return{x:b.x-p,y:b.y-p,w:b.w+2*p,h:b.h+2*p,k}}
function placeLens(){const r=lensRect();if(!r){lensEl.style.display=stackEl.style.display='none';return}
  lensEl.style.display='';Object.assign(lensEl.style,{left:r.x+'px',top:r.y+'px',width:r.w+'px',height:r.h+'px'});lensK=r.k;lensStroke();
  const sp=spFor(st.lens),lt=lensEl.querySelector('.lt');lt.style.transform=`scale(${r.k})`;lt.style.bottom=(-12*r.k)+'px';
  lt.textContent=(sp?'Sprint '+sp.n+' · '+sp.stage+(sp.status==='active'?'':' ✓'):'Lens')+(V.pre?'':' · 아직 계산 전');
  lensEl.classList.toggle('live',!SP.length||(sp&&sp.status==='active'));
  Object.assign(stackEl.style,{left:(r.x+r.w+70*r.k)+'px',top:r.y+'px',transform:`scale(${r.k})`})}
function spinFast(){lensEl.classList.add('moving');clearTimeout(lensEl._t);lensEl._t=setTimeout(()=>lensEl.classList.remove('moving'),1400)}
function visibleSecs(){const sp=spFor(st.lens);let n=sp?(UPTO[sp.stage]||6):6;let ks=SECS.slice(0,n).map(x=>x.k);
  if(!S.knobs)ks=ks.filter(k=>k!=='try');if(!V.table)ks=ks.filter(k=>k!=='weigh');
  if(!V.pre)ks=['here','ask'];else if((REQ().length||st.moves.length)&&!ks.includes('ask'))ks.push('ask');return ks}
function totals(t){return t.rows.map(r=>({r,tot:t.axes.reduce((a,x)=>a+((r.scores[x]||[0])[0])*(st.weights[x]??1),0)})).sort((a,b)=>b.tot-a.tot)}
function knobPoint(){const K=S.knobs;if(!K)return null;return K.points.find(p=>Object.keys(K.params).every(k=>String(p.at[k])===String(st.knob[k])))}
function secHTML(k){const n=byId[st.lens],t=V.table,cs=(V.candidates[st.lens]||[]).map(c=>typeof c==='string'?{name:c}:c);let h='';
  if(k==='here'){const sp=spFor(st.lens);
    h+='<div class="big">'+esc(n?n.label:'')+'</div>'+(n&&n.note?'<div class="w">'+esc(n.note)+'</div>':'');
    if(sp)h+='<div class="kv"><b>Sprint '+sp.n+' · '+esc(sp.stage)+'</b> '+esc(sp.goal)+(sp.summary?'<div class="w">→ '+esc(sp.summary)+'</div>':'')+'</div>';
    if(!V.pre)h+='<div class="warn">이 자리는 아직 셈하지 않았습니다. 셈해 달라고 하시면 이어서 봅니다.</div>';
    else if(st.lens===st.origin&&S.ask&&!REQ().length)h+='<div class="note2">'+esc(S.ask)+'</div>'}
  if(k==='moves'){h+=cs.map(c=>'<div class="mv'+(c.closed?' closed':'')+(c.proposed_by==='user'?' user':'')+(st.pick===c.name?' on':'')+'" data-c="'+esc(c.name)+'"><b>'+esc(c.name)+'</b> '+(c.proposed_by==='user'?'<span class="ub">사용자 제안</span>':'')+
      (c.closed?'<div class="w">이미 해 본 길</div>':'<div class="w">'+esc(c.source||'')+' '+vb(c.check)+'</div>'+(c.diff?'<div class="w">차이점: '+esc(c.diff)+'</div>':'')+evHTML(c,false))+'</div>').join('');
    const names=new Set(cs.map(c=>c.name)),pend=(S.proposals||[]).filter(p=>!names.has(p.name)&&(!p.lens||p.lens===st.lens));
    if(pend.length)h+='<div class="w" style="margin-top:8px">다음 스프린트에서 검토할 제안</div>'+pend.map(p=>'<div class="mv user pend"><b>'+esc(p.name)+'</b> <span class="ub">사용자 제안 · 검토 대기</span><div class="w">'+esc(p.change||'')+'</div></div>').join('')}
  if(k==='cases')h+=cs.filter(c=>!c.closed).map(c=>{const o=c.outcomes||[];return '<div class="cs" data-c="'+esc(c.name)+'"><b>'+esc(c.name)+'</b>'+
      (o.length?'<div class="bar">'+o.map(x=>'<i class="'+(/실패/.test(x.case)?'bad':/부분/.test(x.case)?'mid':'ok')+'" style="flex:'+(x.p||1/o.length)+'" title="'+esc(x.case)+'"></i>').join('')+'</div><div class="w">'+o.map(x=>esc(x.case.split(' — ')[0])+(x.p!=null?' '+Math.round(x.p*100)+'%':'')).join(' · ')+'</div>':'<div class="w">아직 그려보지 않음</div>')+'</div>'}).join('')+'<div class="w hint">Lens 안의 수를 누르면 갈래가 펼쳐집니다</div>';
  if(k==='weigh'){const rows=totals(t);
    h+='<table><tr><th></th><th>수</th><th>합</th>'+t.axes.map(a=>'<th>'+esc(a).replace(' ','<br>')+'</th>').join('')+'</tr>'+
      rows.map((x,i)=>'<tr class="'+(i?'':'top')+(st.pick===x.r.candidate?' sel':'')+'"><td><input type="radio" name="pk" value="'+esc(x.r.candidate)+'"'+(st.pick===x.r.candidate?' checked':'')+'></td><td class="n">'+esc(x.r.candidate)+'</td><td><b>'+(+x.tot.toFixed(1))+'</b></td>'+
      t.axes.map(a=>{const s=x.r.scores[a];return '<td title="'+esc(s&&s[1]||'')+'">'+(s?s[0]:'–')+'</td>'}).join('')+'</tr>').join('')+'</table>';
    if(t.analysis)h+='<div class="w" style="margin-top:6px">무게를 흔들어도 1위일 가능성: '+Object.entries(t.analysis.p_first).map(([c,p])=>esc(c)+' '+Math.round(p*100)+'%').join(' · ')+'</div>';
    h+='<details><summary class="w">무엇을 더 중요하게 볼지 조정</summary><div class="wg">'+t.axes.map(a=>'<label>'+esc(a)+'</label><input type="range" min="0" max="3" step="0.5" value="'+(st.weights[a]??1)+'" data-a="'+esc(a)+'"><span>×'+(st.weights[a]??1)+'</span>').join('')+'</div></details>'}
  if(k==='try'){const K=S.knobs;h+='<div class="wg">';Object.entries(K.params).forEach(([kk,vals])=>{if(!(kk in st.knob))st.knob[kk]=vals[0];const i=vals.findIndex(v=>String(v)===String(st.knob[kk]));
      h+='<label>'+esc(kk)+'</label><input type="range" min="0" max="'+(vals.length-1)+'" step="1" value="'+i+'" data-k="'+esc(kk)+'"><span>'+esc(st.knob[kk])+'</span>'});
    const kp=knobPoint();h+='</div>'+(kp?(kp.ok?'<div class="kres ok">'+Object.entries(kp.values).map(([m,v])=>'<b>'+esc(m)+'</b> '+esc(v)).join(' · ')+'</div>':'<div class="kres bad">이 조합은 실패했습니다 — '+esc(kp.err||'')+'</div>'):'<div class="kres">재 보지 않은 조합</div>')+'<div class="w">미리 재 둔 값입니다</div>'}
  if(k==='ask'){const R=REQ();
    if(!V.pre)h+='<div class="rq"><div class="rqq">이 자리를 셈해 볼까요?</div><div class="w">직접 Lens를 옮긴 곳이라 아직 후보와 갈래가 없습니다.</div></div>';
    R.filter(r=>r.type==='fill').forEach(r=>{const a=st.fill[r.id]||{};h+='<div class="rq fill"><div class="rqq">'+esc(r.question)+'</div><div class="w">'+esc(r.why||'')+'</div>'+
      (r.fields||[]).map(f=>'<label class="fl2">'+esc(f.label)+'<input data-fr="'+esc(r.id)+'" data-fk="'+esc(f.key)+'" placeholder="'+esc(f.placeholder||'')+'" value="'+esc(a[f.key]||'')+'"></label>').join('')+'<div class="dflt">채우지 않으면 이 요청은 다음 스프린트로 넘어갑니다</div></div>'});
    R.filter(r=>r.type!=='fill').forEach(r=>{h+='<div class="rq"><div class="rqq">'+esc(r.question)+'</div><div class="w">'+esc(r.why)+'</div><div class="ops">'+r.options.map(o=>'<button class="op'+(st.ans[r.id]===o?' on':'')+'" data-r="'+esc(r.id)+'" data-o="'+esc(o)+'">'+esc(o)+'</button>').join('')+'</div>'+
      '<div class="dflt">답이 없으면 <b>'+esc(r.default||'기다립니다')+'</b>로 갑니다 — '+esc(r.default_why||'')+'</div></div>'});
    if(!R.length&&V.pre&&!st.moves.length)h+='<div class="w">지금은 여쭐 것이 없습니다. 이어서 진행합니다.</div>';
    const np=st.newp;h+='<details class="newp"'+(np.open?' open':'')+'><summary>+ 완전히 새로운 시도 제안하기</summary><div class="w">채워 주시면 다음 스프린트에서 후보로 올려 근거·이식 가능성·경우의 수를 같은 방식으로 따져 봅니다.</div>'+
      [['name','시도 이름','예) 채널별 다운샘플링 후 attention'],['change','무엇을 바꾸나','어느 블록의 무엇을 어떻게'],['expect','기대하는 결과','무엇이 좋아질 것 같은지'],['evidence','근거 (선택)','URL이나 코드 위치']].map(([k2,l,ph])=>'<label class="fl2">'+l+'<input data-np="'+k2+'" placeholder="'+esc(ph)+'" value="'+esc(np[k2]||'')+'"></label>').join('')+'</details>';
    h+='<textarea id="nt" placeholder="덧붙일 말이 있다면">'+esc(st.note)+'</textarea>';
    const any=Object.keys(st.ans).length||st.note.trim()||st.moves.length||st.ex.size!==(S.excluded||[]).length||(st.newp.name||'').trim()||Object.values(st.fill).some(o=>Object.values(o).some(v=>v.trim()));
    if(any)h+='<pre id="msg">'+esc(message())+'</pre><button id="send" class="pri">'+(typeof sendPrompt==='function'?'Claude에게 전하기':'복사해서 전하기')+'</button> <span id="sent" class="w"></span>'}
  return h}
function showStack(){const r=lensRect();if(!r||fanOpen){stackEl.style.display='none';return}stackEl.style.display='';
  const ks=visibleSecs(),seen=shown[st.lens]||(shown[st.lens]=new Set());stackEl.innerHTML='<svg class="sl"></svg>';
  const two=ks.length>3,cols=two?[E('div','col'),E('div','col')]:[stackEl],cut=Math.ceil(ks.length/2);if(two)cols.forEach(c=>stackEl.append(c));stackEl.classList.toggle('two',two);
  ks.forEach((k,i)=>{const sec=SECS.find(x=>x.k===k),d=E('div','sec s-'+k+(seen.has(k)?' in':''),'<div class="st">'+sec.t+'</div>'+secHTML(k));d.dataset.k=k;
    if(!seen.has(k))d.style.transitionDelay=(120+i*110)+'ms';(two?cols[i<cut?0:1]:stackEl).append(d)});
  wireStack();requestAnimationFrame(()=>requestAnimationFrame(()=>{stackEl.querySelectorAll('.sec').forEach(d=>{d.classList.add('in');seen.add(d.dataset.k)});stackLines()}))}
function stackLines(){const svg=stackEl.querySelector('svg.sl');if(!svg||!lensRect())return;const secs=[...stackEl.querySelectorAll('.sec')];let h='';
  const r=lensRect(),k=r.k,x0=-70,y0=(lensRect().h/2)/k;
  if(secs[0]){const y=secs[0].offsetTop+22;h+=`<path class="ln solid" d="M${x0} ${Math.min(y0,y)} C${x0+40} ${Math.min(y0,y)},${-30} ${y},0 ${y}"/>`}
  for(let i=1;i<secs.length;i++){const a=secs[i-1],b=secs[i],xa=a.offsetLeft+24,ya=a.offsetTop+a.offsetHeight,xb=b.offsetLeft+24,yb=b.offsetTop;
    h+=xa===xb?`<path class="ln solid" d="M${xa} ${ya} L${xb} ${yb}"/>`:`<path class="ln solid" d="M${xa} ${ya} C${xa} ${ya+40},${xb-80} ${yb-30},${xb-30} ${yb-14} S${xb} ${yb-6},${xb} ${yb}"/>`}
  svg.innerHTML=h;svg.querySelectorAll('path').forEach(p=>p.setAttribute('stroke-width',(1.4/(cam.s*k)).toFixed(4)))}
function wireStack(){const fl=stackEl;const re=()=>{const k=document.activeElement&&document.activeElement.id;showStack();if(k==='nt'){const t=stackEl.querySelector('#nt');t.focus();t.setSelectionRange(t.value.length,t.value.length)}};
  fl.querySelectorAll('.mv[data-c],.cs[data-c]').forEach(m=>m.onclick=e=>{e.stopPropagation();if(m.classList.contains('closed'))return;const card=[...topRow.querySelectorAll('.cand')].find(c=>c.dataset.cand===m.dataset.c);if(card)card.click()});
  fl.querySelectorAll('input[name=pk]').forEach(r=>r.onchange=()=>{st.pick=r.value;markPick();re()});
  fl.querySelectorAll('input[data-a]').forEach(r=>r.oninput=()=>{st.weights[r.dataset.a]=parseFloat(r.value);const open=r.closest('details').open;showStack();const d=stackEl.querySelector('details');if(d)d.open=open});
  fl.querySelectorAll('input[data-k]').forEach(r=>r.oninput=()=>{st.knob[r.dataset.k]=S.knobs.params[r.dataset.k][+r.value];st.knobTouched=true;showStack()});
  fl.querySelectorAll('button.op').forEach(b=>b.onclick=()=>{const id=b.dataset.r;if(st.ans[id]===b.dataset.o)delete st.ans[id];else st.ans[id]=b.dataset.o;showStack()});
  const refreshMsg=()=>{const m=fl.querySelector('#msg');if(m)m.textContent=message();else{const id=document.activeElement&&document.activeElement.dataset,key=id&&(id.np||id.fk);showStack();if(key){const el=stackEl.querySelector(id.np?'[data-np="'+id.np+'"]':'[data-fk="'+id.fk+'"]');if(el){el.focus();el.setSelectionRange(el.value.length,el.value.length)}}}};
  fl.querySelectorAll('input[data-np]').forEach(i=>i.oninput=()=>{st.newp[i.dataset.np]=i.value;st.newp.open=true;refreshMsg()});
  fl.querySelectorAll('input[data-fr]').forEach(i=>i.oninput=()=>{(st.fill[i.dataset.fr]||(st.fill[i.dataset.fr]={}))[i.dataset.fk]=i.value;refreshMsg()});
  const nd=fl.querySelector('details.newp');if(nd)nd.addEventListener('toggle',()=>{st.newp.open=nd.open});
  const nt=fl.querySelector('#nt');if(nt)nt.oninput=()=>{const had=!!st.note.trim();st.note=nt.value;const m=fl.querySelector('#msg');if(m)m.textContent=message();else if(!had&&st.note.trim())re()};
  const sb=fl.querySelector('#send');if(sb)sb.onclick=()=>{const m=message();if(typeof sendPrompt==='function'){sendPrompt(m);fl.querySelector('#sent').textContent='전했습니다'}
    else (navigator.clipboard?navigator.clipboard.writeText(m):Promise.reject()).then(()=>fl.querySelector('#sent').textContent='복사됨 — 대화창에 붙여넣어 주세요',
      ()=>{const r=document.createRange();r.selectNodeContents(fl.querySelector('#msg'));getSelection().removeAllRanges();getSelection().addRange(r);fl.querySelector('#sent').textContent='선택됨 — 복사해 주세요'})};
  fl.querySelectorAll('input,textarea,button,details,summary').forEach(x=>x.addEventListener('mousedown',e=>e.stopPropagation()))}
function message(){const L=['[problem-solving 결정 응답]'],ln=byId[st.lens];
  REQ().filter(r=>r.type!=='fill').forEach(r=>L.push('요청 「'+r.question+'」 → '+(st.ans[r.id]?st.ans[r.id]:'응답 없음 (기본값 '+(r.default||'대기')+' 적용)')));
  const path=(S.lens_path||[]).map(p=>byId[p.at]?byId[p.at].label:p.at).filter((x,i,a)=>!i||a[i-1]!==x);if(path.length)L.push('Claude의 Lens 경로: '+path.join(' → '));
  L.push('Lens: '+(ln?ln.label:st.lens)+' ('+st.lens+')'+(st.moves.length?' — 사용자가 이동 ('+st.moves.join(' → ')+')'+(V.pre?'':', 새 위치 계산 요청'):''));
  if(st.pick)L.push('살펴본 수: '+st.pick);
  const w0=(V.table&&V.table.weights)||{};const dw=V.table?V.table.axes.filter(a=>(st.weights[a]??1)!==(w0[a]??1)).map(a=>a+' '+(w0[a]??1)+'→'+st.weights[a]):[];if(dw.length)L.push('가중치 조정: '+dw.join(', '));
  const kp=knobPoint();if(kp&&st.knobTouched)L.push('손잡이: '+Object.entries(st.knob).map(([k,v])=>k+'='+v).join(', ')+' → '+(kp.ok?Object.entries(kp.values).map(([k,v])=>k+' '+v).join(', '):'실패'));
  if(st.ex.size){L.push('논의에서 제외: '+[...st.ex].map(i=>byId[i]?byId[i].label:i).join(', '));const ig=V.ripples.filter(r=>st.ex.has(r.to));if(ig.length)L.push('제외 영역으로 가는 파급 무시: '+ig.map(r=>r.from+'→'+(byId[r.to]?byId[r.to].label:r.to)).join(', '))}
  REQ().filter(r=>r.type==='fill').forEach(r=>{const a=st.fill[r.id]||{};const v=(r.fields||[]).filter(f=>(a[f.key]||'').trim()).map(f=>f.label+': '+a[f.key].trim());if(v.length)L.push('요청 「'+r.question+'」 채움 → '+v.join(' / '))});
  const np=st.newp;if((np.name||'').trim())L.push('[새 시도 제안] '+np.name.trim()+(np.change?' / 바꿀 것: '+np.change.trim():'')+(np.expect?' / 기대: '+np.expect.trim():'')+(np.evidence?' / 근거: '+np.evidence.trim():'')+' — 다음 스프린트에서 후보로 검토');
  if(st.note.trim())L.push('메모: '+st.note.trim());return L.join('\n')}
/* ---- 경우의 수 펼치기 ---- */
function closeFan(){if(!fanOpen)return;fanOpen=null;fanEl.innerHTML='';world.classList.remove('fanning');stackEl.style.display=''}
function openFan(c,card,node){closeFan();fanOpen=c.name;world.classList.add('fanning');stackEl.style.display='none';const nb=wpos(node.el),cb=wpos(card);
  const items=[];if(c.source||c.diff||evs(c).length)items.push({k:'src',t:'출처 및 근거',b:(c.proposed_by==='user'?'사용자 제안':'')+(c.source?(c.proposed_by==='user'?' · ':'')+c.source:'')||'출처 없음',s:c.diff?'차이점: '+c.diff:'',x:vb(c.check)+evHTML(c,true)});
  if(c.port_code||c.port_condition)items.push({k:'port',t:'이식 가능성',b:c.port_condition?'조건: '+c.port_condition:'',s:c.port_code?'코드: '+c.port_code:''});
  (c.outcomes||[]).forEach(o=>items.push({k:/성공|해결/.test(o.case)&&!/부분/.test(o.case)?'ok':/실패/.test(o.case)?'bad':'mid',t:o.case+(o.p!=null?' · '+Math.round(o.p*100)+'%':''),b:o.text||'',s:o.learn?'얻는 정보: '+o.learn:''}));
  const rs=V.ripples.filter(r=>c.name.includes(r.from)||r.from.includes(c.name));if(rs.length)items.push({k:'rip',t:'파급 영향 '+rs.length+'곳',b:rs.map(r=>(byId[r.to]?byId[r.to].label:r.to)+': '+r.effect).join(' / '),s:''});
  if(!items.length)items.push({k:'mid',t:'경우의 수 미작성',b:'다음 스프린트에서 그려 달라고 요청할 수 있습니다',s:''});
  const k=nb.w/300,X=nb.x+nb.w+90*k,wrap=E('div','fwrap');fanEl.append(wrap);
  const cards=items.map((it,i)=>{const d=E('div','fcard k-'+it.k,'<div class="ft">'+esc(it.t)+'</div>'+(it.b?'<div>'+esc(it.b)+'</div>':'')+(it.s?'<div class="fs">'+esc(it.s)+'</div>':'')+(it.x||''));d.querySelectorAll('a,summary').forEach(a=>{a.addEventListener('mousedown',e=>e.stopPropagation());a.addEventListener('click',e=>e.stopPropagation())});d.style.transitionDelay=(80+i*70)+'ms';wrap.append(d);return d});
  const tot=wrap.offsetHeight*k,x1=nb.x+nb.w,y1=cb.y+cb.h/2,yt=y1-tot/2;Object.assign(wrap.style,{left:X+'px',top:yt+'px',transform:'scale('+k+')'});
  const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('class','fl');fanEl.prepend(svg);let ph='';
  cards.forEach((d,i)=>{const y2=yt+(d.offsetTop+d.offsetHeight/2)*k;const it=items[i],cl=it.k==='src'?'':it.k==='port'?' faint':' dash',co=it.k==='rip'?'var(--own)':it.k==='ok'?'var(--ok)':it.k==='bad'?'var(--bad)':it.k==='mid'?'var(--mid)':'var(--line)';ph+=`<path class="fp${cl}" d="M${x1} ${y1} C${x1+60*k} ${y1},${X-60*k} ${y2},${X} ${y2}" pathLength="100" style="stroke:${co};transition-delay:${40+i*70}ms"/>`});
  svg.innerHTML=ph;requestAnimationFrame(()=>requestAnimationFrame(()=>fanEl.querySelectorAll('.fcard,.fl path').forEach(e=>e.classList.add('in'))));
  frameRect({x:nb.x,y:Math.min(nb.y-100*k,yt),w:X+250*k-nb.x,h:Math.max(nb.y+nb.h,yt+tot)-Math.min(nb.y-100*k,yt)});
  svg.querySelectorAll('path').forEach(p=>p.setAttribute('stroke-width',(1.8/cam.s).toFixed(4)));$('cap').innerHTML='<b>'+esc(c.name)+'</b> — 이 수를 두면'}
/* ---- 카메라 ---- */
let lensK=1;function lensStroke(){const rc=lensEl.querySelector('rect'),s=cam.s;
  rc.setAttribute('width','100%');rc.setAttribute('height','100%');rc.setAttribute('rx',24*lensK);
  rc.setAttribute('stroke-width',2/s)}
function apply(){world.style.transform=`translate(${cam.x}px,${cam.y}px) scale(${cam.s})`;lensStroke();plWidth();if(stackEl&&stackEl.style.display!=='none')stackLines()}
function frameRect(r,pad){const W=innerWidth,H=innerHeight-150,s=Math.min(W*(pad||.9)/r.w,H*.86/r.h,80);cam={s,x:W/2-(r.x+r.w/2)*s,y:70+H/2-(r.y+r.h/2)*s};apply()}
function frameTo(el,pad){const p=wpos(el);frameRect(p,pad||.62)}
function frameLens(){const r=lensRect();if(!r)return;const on=stackEl.style.display!=='none',rs=[{x:r.x,y:r.y,w:r.w,h:r.h}];
  if(on)rs.push({x:r.x+r.w+70*r.k,y:r.y,w:stackEl.offsetWidth*r.k,h:stackEl.offsetHeight*r.k});PX.forEach(x=>rs.push(x.box));
  const x0=Math.min(...rs.map(q=>q.x)),y0=Math.min(...rs.map(q=>q.y)),x1=Math.max(...rs.map(q=>q.x+q.w)),y1=Math.max(...rs.map(q=>q.y+q.h));
  frameRect({x:x0-10*r.k,y:y0-20*r.k,w:x1-x0+20*r.k,h:y1-y0+50*r.k})}
function crumb(){const c=$('crumb'),chain=[];for(let n=cur;n;n=n.parent)chain.unshift(n);
  const bp=S.blueprint;let h='<span class="t">'+esc(S.title||'')+'</span><a data-i="">Blueprint'+(bp?' v'+bp.version:'')+'</a>'+(bp&&bp.code_ref?'<span class="w"> @'+esc(bp.code_ref)+'</span>':'')+chain.map(n=>' › <a data-i="'+esc(n.id)+'">'+esc(n.label)+'</a>').join('');
  if(cur&&cur.id!==st.lens&&!st.ex.has(cur.id)){const pre=PRE[cur.id]||cur.id===st.origin;
    h+=inRange(cur.id)?' <button id="ss">Lens를 여기로'+(pre?'':' (아직 셈 전)')+'</button>':' <button disabled title="문제 영역의 하위이거나 직결된 블록만 Lens 대상">Lens 범위 밖</button>'}
  if(cur&&cur.id!==st.lens){let anc=false;for(let p=byId[st.lens];p;p=p.parent)if(p===cur)anc=true;if(!anc&&!PROB.has(cur.id))h+=' <button id="ex" class="ghost">'+(st.ex.has(cur.id)?'논의에 다시 포함':'논의에서 제외')+'</button>'}
  h+='<div class="h">끌어서 이동 · 휠로 확대 · 눌러서 들어가기 · 빈 곳을 누르면 한 단계 위 · ←/→ 다음 장면 · Esc 처음으로</div>';c.innerHTML=h;
  c.querySelectorAll('a').forEach(a=>a.onclick=()=>focus(a.dataset.i?byId[a.dataset.i]:null));
  const b=c.querySelector('#ss');if(b)b.onclick=()=>{st.moves.push(byId[cur.id].label);moveLens(cur.id)};const x=c.querySelector('#ex');if(x)x.onclick=()=>toggleEx(cur.id)}
function focus(n,caption){topRow.querySelectorAll('.node.focus').forEach(e=>e.classList.remove('focus'));
  topRow.querySelectorAll('.node[data-o]').forEach(e=>{e.style.opacity=e.dataset.o;e.style.filter='blur('+(e.dataset.b||0)+'px)'});cur=n||null;closeFan();
  if(n&&n.id===st.lens){showStack();frameLens();setTimeout(()=>{frameLens();stackLines()},60)}
  else if(n){stackEl.style.display='none';n.el.classList.add('focus');for(let p=n;p;p=p.parent)if(p.el.dataset.o){p.el.style.opacity=1;p.el.style.filter='none'}frameTo(n.el)}
  else{stackEl.style.display='none';frameTo(bpEl,.94)}
  $('cap').innerHTML=caption!=null?caption:(n?'<b>'+esc(n.label)+'</b>'+(n.note?' — '+esc(n.note):''):'Blueprint — 정보가 흐르는 순서대로 본 시스템');crumb()}
/* ---- 지금 상황 (Blueprint 바깥 오버뷰) ---- */
function overview(){const O=S.overview||{},sp=SP.length?SP[SP.length-1]:null,li=a=>a&&a.length?'<ul>'+a.map(x=>'<li>'+esc(x)+'</li>').join('')+'</ul>':'';
  const facts=[...(O.facts||[]),...(S.facts||[])];const curLens=sp?sp.lens:S.scope;
  const tb=curLens===st.origin?S.table:(PRE[curLens]||{}).table;let lead='';
  if(tb&&tb.rows&&tb.rows.length){const w=tb.weights||{},tot=r=>tb.axes.reduce((a,x)=>a+((r.scores[x]||[0])[0])*(w[x]||1),0),top=[...tb.rows].sort((a,b)=>tot(b)-tot(a))[0];
    lead=esc(top.candidate)+(tb.analysis&&tb.analysis.p_first?' — 무게를 흔들어도 1위일 가능성 '+Math.round((tb.analysis.p_first[top.candidate]||0)*100)+'%':'')}
  const nreq=(S.requests||[]).length,names=new Set();[S.candidates||{},...Object.values(PRE).map(p=>p.candidates||{})].forEach(cs=>Object.values(cs).forEach(v=>v.forEach(c=>names.add(c.name||c))));
  const npro=(S.proposals||[]).filter(p=>p.status==='pending'&&!names.has(p.name)).length,bp=S.blueprint;
  let h='<h3>지금 상황</h3><div class="ovs">'+esc(S.title||'')+(bp?' · Blueprint v'+bp.version+(bp.code_ref?' @'+esc(bp.code_ref):''):'')+'</div>';
  if(O.problem)h+='<div class="r"><b>문제</b>'+esc(O.problem)+'</div>';
  if(O.observed||O.interpretation)h+='<div class="r"><b>본 것과 해석</b>'+(O.observed?esc(O.observed):'')+(O.interpretation?'<div class="w">해석: '+esc(O.interpretation)+'</div>':'')+'</div>';
  if(O.closed&&O.closed.length)h+='<div class="r"><b>이미 해 본 것</b>'+li(O.closed)+'</div>';
  if(O.constraints&&O.constraints.length)h+='<div class="r"><b>지켜야 할 것</b>'+li(O.constraints)+'</div>';
  if(facts.length)h+='<div class="r"><b>확인된 사실</b>'+li(facts)+'</div>';
  if(sp)h+='<div class="r now"><b>지금</b>Sprint '+sp.n+' · '+esc(sp.stage)+' — '+esc(sp.goal)+'</div>';
  if(lead)h+='<div class="r"><b>가장 앞선 수</b>'+lead+'</div>';
  if(nreq||npro)h+='<div class="r"><b>기다리는 것</b>'+(nreq?'정해 주실 것 '+nreq+'건':'')+(nreq&&npro?' · ':'')+(npro?'검토 대기 제안 '+npro+'건':'')+'</div>';
  if(O.next)h+='<div class="r"><b>다음</b>'+esc(O.next)+'</div>';
  h+='<div class="r w">배치: '+({row:'가로',column:'세로',grid:'격자'}[LAYOUT])+(S.layout_why?' — '+esc(S.layout_why):'')+'</div>';
  ovEl.innerHTML=h}
/* ---- 꺼내 놓은 블록과 영향선 ---- */
const nameHit=(cand,from)=>cand===from||cand.includes(from)||from.includes(cand);
function proxies(){pxEl.innerHTML='';PX=[];const r=lensRect();if(!r)return;
  const ids=[];V.ripples.forEach(x=>{if(!ids.includes(x.to))ids.push(x.to)});(V.pull||[]).forEach(x=>{if(!ids.includes(x.id))ids.push(x.id)});
  const list=ids.filter(id=>byId[id]&&byId[id].el&&id!==st.lens&&!st.ex.has(id));if(!list.length)return;
  const row=E('div','pxrow');pxEl.append(row);
  list.forEach(id=>{const n=byId[id],chain=[];for(let p=n.parent;p;p=p.parent)chain.unshift(p.label);const eff=V.ripples.filter(x=>x.to===id),why=(V.pull||[]).find(x=>x.id===id);
    const d=E('div','px','<div class="pp">'+esc(chain.concat(n.label).join(' › '))+'</div><div class="pl">'+esc(n.label)+'</div>'+
      eff.map(x=>'<div class="pe'+(x.kind==='own'?' own':'')+'" data-f="'+esc(x.from)+'"><b>'+esc(x.from)+'</b> → '+esc(x.effect)+(x.kind==='own'?' <i>스스로 반응</i>':'')+'</div>').join('')+(why?'<div class="pw">'+esc(why.why)+'</div>':''));
    d.dataset.id=id;d.addEventListener('click',e=>{e.stopPropagation();if(!moved)focus(n)});d.addEventListener('mouseenter',()=>{st.pxh=id;plDraw()});d.addEventListener('mouseleave',()=>{st.pxh=null;plDraw()});row.append(d);PX.push({id,el:d,eff})});
  const V2=LAYOUT==='column';if(V2)row.classList.add('vcol');const h=row.offsetHeight,w=row.offsetWidth,ox=V2?r.x-(w+86)*r.k:r.x,oy=V2?r.y:r.y-(h+86)*r.k;
  Object.assign(pxEl.style,{left:ox+'px',top:oy+'px',transform:`scale(${r.k})`});
  PX.forEach(x=>{x.box={x:ox+x.el.offsetLeft*r.k,y:oy+x.el.offsetTop*r.k,w:x.el.offsetWidth*r.k,h:x.el.offsetHeight*r.k}});
  requestAnimationFrame(()=>pxEl.querySelectorAll('.px').forEach((d,i)=>{d.style.transitionDelay=(i*90)+'ms';d.classList.add('in')}));plDraw()}
function plDraw(){if(!plSvg)return;const r=lensRect();let h='';const act=st.pick||st.hover;if(!r||!PX.length){plSvg.innerHTML='';return}
  const cs=[...topRow.querySelectorAll('.cand')];
  const V2=LAYOUT==='column';PX.forEach(x=>{const b=x.box,o=wpos(byId[x.id].el),ox=V2?o.x:o.x+o.w/2,oy=V2?o.y+Math.min(40,o.h/2):o.y,cx=V2?b.x:b.x+b.w/2,cy=V2?b.y+b.h/2:b.y;
    const hit=act&&x.eff.some(e=>nameHit(act,e.from));x.el.classList.toggle('hit',!!hit);x.el.classList.toggle('dim',!!act&&!hit);
    if(hit||st.pxh===x.id)h+=`<path class="po${st.pxh===x.id?' on':''}" d="M${cx} ${cy} C${V2?cx-80*r.k:cx} ${V2?cy:cy-80*r.k},${V2?ox-80*r.k:ox} ${V2?oy:oy-80*r.k},${ox} ${oy}" pathLength="100"/><circle class="pin on" cx="${ox}" cy="${oy}" r="${3.5*r.k}"/>`;
    x.eff.forEach(e=>{const src=cs.find(c=>nameHit(c.dataset.cand,e.from));if(!src)return;const a=wpos(src),sx=a.x,sy=a.y+a.h/2,tx=V2?b.x+b.w:b.x+b.w/2,ty=V2?b.y+b.h/2:b.y+b.h;
      const on=act&&nameHit(act,e.from),col=e.kind==='own'?'var(--own)':'var(--line)',cl=(on?'pf on':'pf')+(e.certainty==='confirmed'?' conf':e.certainty==='weak'?' weak':'');
      h+=`<path class="${cl}" style="stroke:${col}" d="M${sx} ${sy} C${sx-90*r.k} ${sy},${V2?tx+90*r.k:tx} ${V2?ty:ty+90*r.k},${tx} ${ty}" pathLength="100"/>`;
      if(on)h+=`<circle class="pin on" style="fill:${col}" cx="${sx}" cy="${sy}" r="${3.5*r.k}"/><circle class="pin on" style="fill:${col}" cx="${tx}" cy="${ty}" r="${3.5*r.k}"/>`})});
  plSvg.innerHTML=h;plWidth()}
function plWidth(){if(!plSvg)return;const w=1.6/cam.s;plSvg.querySelectorAll('path').forEach(p=>p.style.strokeWidth=(p.classList.contains('on')?2.4/cam.s:w)+'px')}
/* ---- 렌더 ---- */
function renderAll(){closeFan();V=view();world.classList.add('free');const keep=cam;world.style.transform='none';BOX.clear();
  topRow.innerHTML='';topRow.className='trow '+LAYOUT;if(LAYOUT==='grid')topRow.style.setProperty('--gc',Math.ceil(Math.sqrt(S.nodes.length)));
  S.nodes.forEach((n,i)=>{if(i&&LAYOUT!=='grid')topRow.append(E('div','flow',LAYOUT==='column'?'↓':'→'));const el=build(n);if(LAYOUT==='grid')el.append(E('div','ord',String(i+1)));topRow.append(el)});overview();
  S.nodes.forEach(fit);fade();topRow.querySelectorAll('.node,.cand,.rip').forEach(wpos);wpos(topRow);wpos(bpEl);links();
  st.weights=Object.assign({},(V.table&&V.table.weights)||{});cam=keep;apply();world.offsetWidth;world.classList.remove('free');placeLens();proxies()}
function moveLens(id){spinFast();st.lens=id;st.pick=null;renderAll();focus(byId[id])}
function toggleEx(id){if(st.ex.has(id))st.ex.delete(id);else st.ex.add(id);renderAll();const n=byId[id];
  if(n&&st.ex.has(id)){n.el.classList.add('exin');setTimeout(()=>focus(n.parent||null),650)}else if(n)focus(n)}
function frames(){if(S.frames)return S.frames;const f=[{focus:null,caption:'Blueprint — 코드에서 정보가 흐르는 순서. 빗금 테두리가 문제로 정한 곳'}];
  if(SP.length){SP.forEach((x,i)=>f.push({sprint:i,lens:x.lens,focus:x.lens,caption:'<b>Sprint '+x.n+' · '+esc(x.stage)+(x.status==='active'?' (진행 중)':'')+'</b> — '+esc(x.goal)+(x.summary?' → '+esc(x.summary):'')+(inRange(x.lens)?'':' <span style="color:var(--bad)">⚠ 문제 영역 밖</span>')}))}
  const path=SP.length?SP.map(x=>({at:x.lens})):(S.lens_path&&S.lens_path.length?S.lens_path:(S.scope?[{at:S.scope}]:[]));
  if(!SP.length)path.forEach((p,i)=>f.push({lens:p.at,focus:p.at,caption:'<b>Lens '+(i?'이동':'')+' → '+esc(byId[p.at]?byId[p.at].label:p.at)+'</b>'+(p.why?' — '+esc(p.why):'')+(inRange(p.at)?'':' <span style="color:var(--bad)">⚠ 문제 영역 밖 — 문제를 다시 정의해야 하는 이동</span>')}));
  const last=path.length?path[path.length-1].at:S.scope;
  if(last){const save=st.lens;st.lens=last;const vv=view();st.lens=save;const seen=new Set();
    vv.ripples.forEach(r=>{if(seen.has(r.to)||!byId[r.to]||st.ex.has(r.to))return;seen.add(r.to);f.push({lens:last,focus:r.to,caption:'<b>파급 → '+esc(byId[r.to].label)+'</b> — '+esc(r.from)+': '+esc(r.effect)})});
    const cur=SP.length?SP[SP.length-1]:null,late=!cur||['경우의 수','결정','종료'].includes(cur.stage);
    const pend=(S.requests||[]).filter(r=>!r.lens||r.lens===last);if(!late&&!pend.length)return f;
    f.push(pend.length?{lens:last,focus:last,caption:'<b>정해 주실 것</b> — '+esc(pend[0].question)+(pend[0].type==='fill'?' (채우지 않으면 다음 스프린트로 넘어갑니다)':' (답이 없으면 정해진 범위 안에서 Claude가 고릅니다)')}
      :{lens:last,focus:last,caption:'<b>다음 수</b> — 여쭐 것이 없어 가장 나은 수로 이어 갑니다. 근거는 Lens 옆에 있습니다'})}
  return f}
function go(i){fi=Math.max(0,Math.min(F.length-1,i));const f=F[fi];if(f.sprint!=null){spi=f.sprint}else if(f.lens)spi=SP.length-1;if(f.lens&&f.lens!==st.lens){spinFast();st.lens=f.lens;st.pick=null;renderAll()}
  focus(f.focus?byId[f.focus]:null,f.caption);[...$('dots').children].forEach((d,j)=>d.classList.toggle('on',j===fi));placeLens();strip()}
function strip(){const el=$('sprints');if(!SP.length){el.style.display='none';return}
  el.innerHTML='<span class="w">Sprints</span>'+SP.map((x,i)=>'<button class="sc'+(i===spi?' on':'')+(x.status==='active'?' act':'')+'" data-i="'+i+'" title="'+esc(x.goal)+(x.summary?' → '+esc(x.summary):'')+'"><b>S'+x.n+'</b> '+esc(x.stage)+' · '+esc(byId[x.lens]?byId[x.lens].label:x.lens)+(x.delta!=null?' <i>Δ'+x.delta+'</i>':'')+'</button>').join('<span class="sa">›</span>');
  el.querySelectorAll('.sc').forEach(b=>b.onclick=()=>{const j=F.findIndex(f=>f.sprint===+b.dataset.i);if(j>=0)go(j)})}
/* ---- 입력 ---- */
$('prev').onclick=()=>go(fi-1);$('next').onclick=()=>go(fi+1);
stackEl.addEventListener('click',e=>e.stopPropagation());stackEl.addEventListener('wheel',e=>e.stopPropagation());
addEventListener('keydown',e=>{if(/TEXTAREA|INPUT/.test(e.target.tagName))return;if(e.key==='ArrowRight')go(fi+1);else if(e.key==='ArrowLeft')go(fi-1);else if(e.key==='Escape')go(0);});
vp.addEventListener('mousedown',e=>{drag={x:e.clientX,y:e.clientY,cx:cam.x,cy:cam.y};moved=false});
addEventListener('mousemove',e=>{if(!drag)return;const dx=e.clientX-drag.x,dy=e.clientY-drag.y;if(Math.abs(dx)+Math.abs(dy)>4){moved=true;vp.classList.add('grab');world.classList.add('free')}
  if(moved){cam.x=drag.cx+dx;cam.y=drag.cy+dy;apply()}});
addEventListener('mouseup',()=>{drag=null;vp.classList.remove('grab');setTimeout(()=>{world.classList.remove('free');moved=false},0)});
vp.addEventListener('click',()=>{if(moved)return;if(fanOpen){st.pick=null;markPick();focus(byId[st.lens]);return}focus(cur?cur.parent:null)});
vp.addEventListener('wheel',e=>{e.preventDefault();world.classList.add('free');const f=Math.exp(-e.deltaY*.0015),s=Math.min(80,Math.max(.15,cam.s*f));
  cam.x=e.clientX-(e.clientX-cam.x)*s/cam.s;cam.y=e.clientY-(e.clientY-cam.y)*s/cam.s;cam.s=s;apply();clearTimeout(vp._t);vp._t=setTimeout(()=>world.classList.remove('free'),120)},{passive:false});
addEventListener('resize',()=>focus(cur));
function setTheme(t){const d=document.documentElement;d.dataset.theme=t==='auto'?(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'):t;$('theme').textContent=d.dataset.theme==='dark'?'☀ 밝게':'☾ 어둡게'}
setTheme(S.theme||'light');$('theme').onclick=()=>setTheme(document.documentElement.dataset.theme==='dark'?'light':'dark');
V=view();renderAll();F=frames();F.forEach((f,i)=>{const d=E('i');d.onclick=()=>go(i);$('dots').append(d)});
if(SP.length){if(SP[SP.length-1].lens!==st.lens){st.lens=SP[SP.length-1].lens;renderAll()}}else if(S.lens_path&&S.lens_path.length&&S.lens_path[0].at!==st.lens){st.lens=S.lens_path[0].at;renderAll()}
go(0);
"""

HTML = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>__TITLE__</title><style>__CSS__</style></head><body>
<div id="vp"><div id="world"><svg id="links"></svg><div id="bp"><div id="ov"></div><div class="trow" id="top"></div></div><svg id="plinks"></svg><div id="proxy"></div>
<div id="lens"><svg class="lo"><rect pathLength="900"/></svg><div class="lt">Lens</div></div>
<div id="stack"></div><div id="fan"></div></div></div>
<div id="crumb" class="ui"></div>
<button id="theme" class="ui" title="밝게 / 어둡게"></button>
<div id="sprints" class="ui"></div>
<div id="legend" class="ui"><svg><line x1="0" y1="4" x2="28" y2="4" stroke="var(--line)" stroke-width="1.6"/></svg><span>확인된 관계</span>
<svg><line x1="0" y1="4" x2="28" y2="4" stroke="var(--line)" stroke-width="1.6" stroke-dasharray="5 4"/></svg><span>예측 · 가설</span>
<svg><line x1="0" y1="4" x2="28" y2="4" stroke="var(--line)" stroke-width="1.6" opacity=".35"/></svg><span>약하거나 간접적</span>
<svg><line x1="0" y1="4" x2="28" y2="4" stroke="var(--own)" stroke-width="2"/></svg><span>바깥 블록이 스스로 반응</span>
<svg><line x1="0" y1="4" x2="28" y2="4" stroke="var(--ok)" stroke-width="2"/></svg><span>함께 쓰면 좋음</span>
<svg><line x1="0" y1="4" x2="28" y2="4" stroke="var(--bad)" stroke-width="2"/></svg><span>서로 부딪힘</span></div>
<div id="bar" class="ui"><button id="prev" aria-label="이전">◀</button><div id="cap"></div><div id="dots"></div><button id="next" aria-label="다음">▶</button></div>
<script>__JS__</script></body></html>"""


def render(spec):
    spec = upgrade(spec)
    data = json.dumps(spec, ensure_ascii=False).replace("</", "<\\/")
    title = str(spec.get("title", "problem-solving")).replace("<", "&lt;")
    return HTML.replace("__CSS__", CSS).replace("__TITLE__", title).replace("__JS__", JS.replace("__SPEC__", data))


if __name__ == "__main__":
    spec = json.load(open(sys.argv[1], encoding="utf-8"))
    open(sys.argv[2], "w", encoding="utf-8").write(render(spec))
    print(sys.argv[2])
