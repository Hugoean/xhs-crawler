# -*- coding: utf-8 -*-
"""
面经题库静态 HTML 生成器（服务端渲染，零 JS 依赖，绝不变骨架）
读取：data/题库数据D.json（80题）、data/手撕题映射.json、data/手撕占比统计.json
输出：output/大模型评测_面经题库.html
"""
import json, os, html as _h

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # src/ 的上一级 = 项目根
D = json.load(open(os.path.join(BASE, "data/题库数据D.json"), encoding="utf-8"))
SHOU = json.load(open(os.path.join(BASE, "data/手撕题映射.json"), encoding="utf-8"))
TREND = json.load(open(os.path.join(BASE, "data/手撕占比统计.json"), encoding="utf-8"))
OUT_DIR = os.path.join(BASE, "output")
os.makedirs(OUT_DIR, exist_ok=True)
OUT = os.path.join(OUT_DIR, "大模型评测_面经题库.html")

def esc(s): return _h.escape(str(s or ""))

themes = D.get("themes", [])
thname = {t[0]: t[1] for t in themes}
thicon = {t[0]: t[2] for t in themes}
questions = D.get("questions", [])
NOTES = D.get("notes", [])
import re as _re
# 从 all_notes.json 建 note_id→发布日期 映射（给来源加时间）
ALL = []
try:
    ALL = json.load(open(os.path.join(BASE, "data/all_notes.json"), encoding="utf-8"))
except Exception:
    pass
def _nid(u):
    m = _re.search(r'/explore/([0-9a-zA-Z]+)', u or ""); return m.group(1) if m else ""
date_by_id = {_nid(n.get("link", "")): (n.get("publish_time", "") or "")[:10] for n in ALL}

def prio(c):
    if c >= 5: return ("p0", "🔴 P0·高频必刷")
    if c >= 3: return ("p1", "🟠 P1·重点")
    return ("p2", "🟡 P2·了解")

# 分组
bytheme = {t[0]: [] for t in themes}
for q in questions:
    bytheme.setdefault(q.get("th", "其他"), []).append(q)
for k in bytheme: bytheme[k].sort(key=lambda x: -x.get("count", 0))

n_ans = sum(1 for q in questions if (q.get("a") or "").strip())

CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;background:#f5f6f8;color:#1f2430;line-height:1.7}
a{color:#2563eb;text-decoration:none}a:hover{text-decoration:underline}
.layout{display:flex;align-items:flex-start}
/* 左侧目录 */
.sidebar{position:fixed;top:0;left:0;width:250px;height:100vh;overflow-y:auto;background:#11182a;color:#cdd5e4;padding:18px 14px}
.sidebar h1{font-size:16px;color:#fff;margin-bottom:4px}
.sidebar .sub{font-size:12px;color:#8a95ad;margin-bottom:14px}
.sidebar .grp{font-size:12px;color:#7c89a6;margin:16px 0 6px;letter-spacing:1px}
.sidebar a{display:flex;align-items:center;gap:8px;color:#cdd5e4;padding:6px 10px;border-radius:7px;font-size:13.5px}
.sidebar a:hover{background:#1e2942;text-decoration:none}
.sidebar a .badge{margin-left:auto;background:#2b3a5e;color:#9fb3d8;font-size:11px;padding:1px 7px;border-radius:10px}
.sidebar a .p0c{margin-left:auto;color:#ff6b6b;font-size:11px;font-weight:700}
/* 主体 */
/* 主体：占满侧栏右侧整块空间(flex:1)，内容在其中水平居中 */
.main{flex:1;min-width:0;margin-left:250px;padding:30px 24px;display:flex;justify-content:center}
.wrap{width:100%;max-width:980px}
section{scroll-margin-top:16px;margin-bottom:34px}
h2.sec{font-size:21px;margin-bottom:14px;padding-bottom:8px;border-bottom:2px solid #e3e7ee;display:flex;align-items:center;gap:8px}
.stats{display:flex;gap:14px;flex-wrap:wrap;margin-bottom:24px}
.stat{background:#fff;border-radius:12px;padding:16px 22px;box-shadow:0 1px 4px rgba(0,0,0,.06);min-width:130px}
.stat b{font-size:26px;color:#2563eb}.stat span{display:block;font-size:12.5px;color:#6b7488;margin-top:2px}
/* 卡片 */
.card{background:#fff;border-radius:12px;padding:16px 18px;margin-bottom:12px;box-shadow:0 1px 4px rgba(0,0,0,.06);scroll-margin-top:16px}
.card .qhead{display:flex;align-items:flex-start;gap:8px;flex-wrap:wrap}
.prio{font-size:12px;font-weight:700;padding:2px 9px;border-radius:6px;white-space:nowrap}
.prio.p0{background:#ffe5e5;color:#d6336c}.prio.p1{background:#fff0e0;color:#e8590c}.prio.p2{background:#fff8db;color:#b8860b}
.cnt{background:#eef2ff;color:#3b5bdb;font-size:12px;font-weight:700;padding:2px 8px;border-radius:6px}
.na{background:#e6fcf5;color:#0ca678;font-size:12px;padding:2px 8px;border-radius:6px}
.na.手撕算法题{background:#fff0f6;color:#c2255c}
.qtext{font-size:15.5px;font-weight:600;margin:8px 0;flex-basis:100%}
.comp{background:#fff4e6;color:#e8590c;font-size:11.5px;padding:1px 7px;border-radius:5px}
.subs{margin:6px 0 4px 4px;padding-left:14px;border-left:3px solid #eceff4}
.subs li{font-size:13.5px;color:#4a5468;margin:2px 0}
details{margin-top:10px;background:#f8fafc;border-radius:8px;padding:0 12px;border:1px solid #eceff4}
details summary{cursor:pointer;padding:9px 0;font-size:13.5px;color:#2563eb;font-weight:600;list-style:none}
details summary::-webkit-details-marker{display:none}
details[open]{padding-bottom:12px}
.ans{font-size:13.8px;color:#2b3344;white-space:pre-wrap;padding-top:4px;line-height:1.78;tab-size:2;word-break:break-word;overflow-wrap:anywhere}
.ans code,.ans pre{font-family:ui-monospace,Menlo,monospace;font-size:12.8px;background:#eef1f5;padding:1px 4px;border-radius:4px}
.ans-html{white-space:normal}
.ans-html ul,.ans-html ol{margin:4px 0 4px 20px}
.ans-html li{margin:4px 0}
.ans-html p{margin:6px 0}
.ans-html b,.ans-html strong{color:#1f2d4d}
.ans-html pre{white-space:pre-wrap;padding:8px;display:block;margin:6px 0}
.ans.todo{color:#e8590c}
.src{font-size:11px;color:#aab2c2;margin-top:8px}
.src a{color:#aab2c2}
/* 手撕专区 */
table.shou{width:100%;border-collapse:collapse;background:#fff;border-radius:10px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,.06)}
table.shou th,table.shou td{padding:9px 11px;text-align:left;font-size:13px;border-bottom:1px solid #eef1f5;vertical-align:top}
table.shou th{background:#11182a;color:#cdd5e4;font-size:12.5px}
table.shou tr:hover td{background:#f8fafc}
.rk{font-weight:700;color:#d6336c}
.path{font-family:ui-monospace,Menlo,monospace;font-size:12px;background:#f1f3f5;padding:1px 6px;border-radius:4px;color:#364fc7}
.tag-new{background:#d3f9d8;color:#2b8a3e;font-size:11px;padding:1px 6px;border-radius:5px}
.tag-lc{background:#e7f5ff;color:#1971c2;font-size:11px;padding:1px 6px;border-radius:5px}
/* 趋势图 */
.bars{background:#fff;border-radius:10px;padding:16px 18px;box-shadow:0 1px 4px rgba(0,0,0,.06)}
.barrow{display:flex;align-items:center;gap:10px;margin:7px 0}
.barrow .lab{width:120px;font-size:13px;color:#444}
.barrow .track{flex:1;background:#eef1f5;border-radius:6px;height:20px;position:relative}
.barrow .fill{height:100%;border-radius:6px;background:linear-gradient(90deg,#4dabf7,#3b5bdb)}
.barrow .val{width:84px;font-size:12.5px;color:#555;text-align:right}
.note{font-size:13px;color:#6b7488;margin-top:10px}
.intro{background:#fff;border-left:4px solid #3b5bdb;border-radius:8px;padding:12px 16px;margin-bottom:14px;font-size:13.5px;color:#444}
.top li{background:#fff;border-radius:8px;padding:9px 12px;margin-bottom:6px;box-shadow:0 1px 3px rgba(0,0,0,.05);font-size:14px;list-style:none}
footer{margin:40px 0 20px;color:#9aa3b2;font-size:12.5px;text-align:center}
"""

def card_html(q):
    cls, lab = prio(q.get("count", 0))
    comps = "".join(f'<span class="comp">🏢{esc(c)}</span> ' for c in (q.get("comps") or []))
    subs = ""
    if q.get("subs"):
        subs = '<ul class="subs">' + "".join(f"<li>↳ {esc(s)}</li>" for s in q["subs"]) + "</ul>"
    a = (q.get("a") or "").strip()
    if a:
        # 有的答案本身是 HTML(含<ul><li><b>)→原样渲染；纯文本/代码→转义+保留缩进
        is_html = bool(_re.search(r'</?(ul|ol|li|p|br|b|strong|em|code|pre|h[1-6])\b', a, _re.I))
        body = f'<div class="ans ans-html">{a}</div>' if is_html else f'<div class="ans">{esc(a)}</div>'
        ans = f'<details><summary>💡 展开 AI 答案</summary>{body}</details>'
    elif q.get("pp"):
        ans = '<details><summary>🔗 个人项目题（需结合自身经历）</summary><div class="ans todo">这道题与你的具体项目/实习/论文强相关，需结合自身经历准备，不提供通用答案。</div></details>'
    else:
        ans = '<details><summary>💡 展开答案（AI 补充中…）</summary><div class="ans todo">答案由 AI 联网补充中，稍后更新。</div></details>'
    srcs = q.get("notes") or []
    srchtml = ""
    links = []
    for idx in srcs[:6]:
        if isinstance(idx, int) and 0 <= idx < len(NOTES):
            nt = NOTES[idx]
            d = date_by_id.get(_nid(nt.get("u", "")), "")
            dtxt = f' · {d}' if d else ""
            links.append(f'<a href="{esc(nt.get("u",""))}" target="_blank" title="{esc(nt.get("t",""))}">📄{esc(nt.get("c") or "原文")}{dtxt}</a>')
    if links:
        srchtml = '<div class="src">📍 来源面经（点开看原文思考）：' + " · ".join(links) + "</div>"
    return (f'<div class="card" id="{esc(q.get("id"))}">'
            f'<div class="qhead"><span class="prio {cls}">{lab}</span>'
            f'<span class="cnt">被问 {q.get("count",0)}×</span>'
            f'<span class="na {esc(q.get("na"))}">{esc(q.get("na"))}</span>{comps}'
            f'<div class="qtext">{esc(q.get("q"))}</div></div>'
            f'{subs}{ans}{srchtml}</div>')

# 手撕专区
def shou_html():
    rows = ""
    for i, s in enumerate(sorted(SHOU, key=lambda x: -x.get("频率", 0)), 1):
        freq = s.get("频率", 0)
        pr = "🔴" if freq >= 9 else ("🟠" if freq >= 5 else "🟡")
        lc = s.get("leetcode", "")
        lclinks = ""
        if lc:
            for u in [x.strip() for x in lc.split(";") if x.strip()]:
                lclinks += f'<a class="tag-lc" href="{esc(u)}" target="_blank">LeetCode↗</a> '
        prac = s.get("练习文件", "")
        ans = s.get("答案文件", "")
        local = ""
        if prac:
            local += f'练习 <span class="path">{esc(prac)}</span> '
        if ans:
            local += f'答案 <span class="path">{esc(ans)}</span> '
        newtag = '<span class="tag-new">✅新增</span>' if s.get("状态") == "✅新增" else ""
        cell = (lclinks + local) or "—"
        rows += (f'<tr><td><span class="rk">#{i}</span></td>'
                 f'<td>{pr} {freq}次</td><td>{esc(s.get("题型"))} {newtag}</td>'
                 f'<td>{esc(s.get("类型"))}</td><td>{cell}</td></tr>')
    return (f'<section id="sec-shousi"><h2 class="sec">🔪 手撕题专区（序号=优先级，按真实面经频率）</h2>'
            f'<div class="intro">真实面经中 <b>65% 考手撕</b>，必刷。深度学习手撕 → 本地 <span class="path">llm_handwrite/practice/</span> 默写，答案在 <span class="path">solutions/</span>；算法题 → 刷力扣。LoRA/对比学习/KL 为新补充本地实现。</div>'
            f'<table class="shou"><tr><th>优先级</th><th>频率</th><th>题型</th><th>类型</th><th>练习入口 / 链接</th></tr>{rows}</table></section>')

# 趋势图
def trend_html():
    rows = ""
    for k, v in TREND.items():
        pct = v.get("占比", 0)
        rows += (f'<div class="barrow"><span class="lab">{esc(k)}</span>'
                 f'<span class="track"><span class="fill" style="width:{pct}%"></span></span>'
                 f'<span class="val">{pct}% ({v.get("有手撕",0)}/{v.get("总数",0)})</span></div>')
    return (f'<section id="sec-trend"><h2 class="sec">📈 手撕占比 · 时间趋势</h2>'
            f'<div class="bars">{rows}<div class="note">整体约 2/3 的面经考手撕，4-5 月最高(75-78%)，6 月样本少回落。结论：手撕是大概率事件，必须准备。</div></div></section>')

# Top榜
top = sorted(questions, key=lambda x: -x.get("count", 0))[:12]
tophtml = "".join(f'<li><a href="#{esc(q.get("id"))}"><span class="prio {prio(q.get("count",0))[0]}">{prio(q.get("count",0))[1]}</span> {q.get("count",0)}× {esc(q.get("q"))}</a></li>' for q in top)

# 导航
nav = '<div class="grp">📌 专区 / 榜单</div>'
nav += '<a href="#sec-top"><span>🔥</span><span>高频 Top 榜</span></a>'
nav += '<a href="#sec-shousi"><span>🔪</span><span>手撕题专区</span></a>'
nav += '<a href="#sec-trend"><span>📈</span><span>手撕占比趋势</span></a>'
nav += '<div class="grp">📚 主题分区</div>'
for t in themes:
    lst = bytheme.get(t[0], [])
    if not lst: continue
    p0 = sum(1 for x in lst if x.get("count", 0) >= 5)
    p0h = f'<span class="p0c">🔴{p0}</span>' if p0 else f'<span class="badge">{len(lst)}</span>'
    nav += f'<a href="#sec-{esc(t[0])}"><span>{esc(t[2])}</span><span>{esc(t[1].split("（")[0])}</span>{p0h}</a>'

# 主题分区
secs = ""
for t in themes:
    lst = bytheme.get(t[0], [])
    if not lst: continue
    cards = "".join(card_html(q) for q in lst)
    secs += f'<section id="sec-{esc(t[0])}"><h2 class="sec">{esc(t[2])} {esc(t[1])} <span style="font-size:13px;color:#999">({len(lst)}题)</span></h2>{cards}</section>'

HTML = f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>大模型评测岗 · 面经题库</title><style>{CSS}</style></head><body>
<div class="layout">
<nav class="sidebar"><h1>📚 大模型评测面经题库</h1><div class="sub">100篇面经 · {len(questions)}题去重</div>{nav}</nav>
<main class="main"><div class="wrap">
<div class="stats">
<div class="stat"><b>{len(questions)}</b><span>去重后总题数</span></div>
<div class="stat"><b>100</b><span>覆盖面经篇数</span></div>
<div class="stat"><b>{n_ans}</b><span>AI 已作答</span></div>
<div class="stat"><b>{len(themes)}</b><span>主题分区</span></div>
</div>
{shou_html()}
{trend_html()}
<section id="sec-top"><h2 class="sec">🔥 高频 Top 12</h2><ul class="top">{tophtml}</ul></section>
{secs}
<footer>生成 2026-06-28 · 数据来源：小红书大模型评测面经 100 篇<br>提示：优先级按真实面经提问次数排（🔴P0被问≥5次必刷）。答案 AI 补充中。</footer>
</div></main></div></body></html>"""

open(OUT, "w", encoding="utf-8").write(HTML)
print(f"✅ 已生成静态题库：{OUT}")
print(f"   {len(questions)} 题，{n_ans} 题有答案，{len(themes)} 个主题分区")
print(f"   文件大小：{os.path.getsize(OUT)} bytes")
