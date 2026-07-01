# -*- coding: utf-8 -*-
"""
看板渲染脚本

功能：
    读取 data/all_notes.json，渲染成一个自包含（无外部依赖）的 HTML 看板。
    顶部用 Tab 切换：全部 / 八股题 / 手撕算法题 / 综合。
    每条笔记一张卡片，按发布时间倒序，显示标题/作者/时间/点赞/关键词/分类标签/链接。

用法：
    source venv/bin/activate
    python render_html.py
"""

import os
import json
import html
import datetime

import config


def _load_notes():
    """读取汇总笔记数据。"""
    path = os.path.join(config.DATA_DIR, "all_notes.json")
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _sort_key(note):
    """排序键：发布时间倒序，解析不出时间的排后面。"""
    pt = note.get("publish_time", "")
    try:
        return datetime.datetime.strptime(pt, "%Y-%m-%d %H:%M")
    except Exception:
        return datetime.datetime.min


def _esc(s):
    """HTML 转义。"""
    return html.escape(str(s or ""))


def _card_html(note):
    """单条笔记卡片 HTML。"""
    cats = note.get("categories", [])
    cat_class = "全部"  # data 属性用于 Tab 过滤
    badges = ""
    for c in cats:
        cls = {
            config.CAT_CODING: "badge-coding",
            config.CAT_BAGU: "badge-bagu",
            config.CAT_OTHER: "badge-other",
        }.get(c, "badge-other")
        badges += f'<span class="badge {cls}">{_esc(c)}</span>'

    # 公司 tag（识别不到则不展示）
    company_tags = "".join(
        f'<span class="tag tag-company">🏢 {_esc(c)}</span>'
        for c in note.get("companies", [])
    )
    # 岗位 tag（识别不到则不展示）
    position_tags = "".join(
        f'<span class="tag tag-position">💼 {_esc(pp)}</span>'
        for pp in note.get("positions", [])
    )

    cats_attr = " ".join(cats)
    title = _esc(note.get("title") or "(无标题)")
    desc = _esc(note.get("desc", ""))
    if len(desc) > 120:
        desc = desc[:120] + "…"
    author = _esc(note.get("author") or "匿名")
    ptime = _esc(note.get("publish_time") or note.get("publish_time_raw") or "未知时间")
    liked = _esc(note.get("liked_count", "0"))
    keyword = _esc(note.get("keyword", ""))
    crawl_time = _esc(note.get("crawl_time", ""))
    link = _esc(note.get("link", "#"))

    # 公司/岗位 tag 行（都没有则不渲染该行）
    tag_row = ""
    if company_tags or position_tags:
        tag_row = f'<div class="card-tags">{company_tags}{position_tags}</div>'

    return f"""
    <div class="card" data-cats="{_esc(cats_attr)}">
      <div class="card-head">{badges}</div>
      <a class="card-title" href="{link}" target="_blank" rel="noopener">{title}</a>
      <div class="card-desc">{desc}</div>
      {tag_row}
      <div class="card-meta">
        <span title="作者">@{author}</span>
        <span title="发布时间">🕒 发布 {ptime}</span>
        <span title="点赞">❤ {liked}</span>
      </div>
      <div class="card-prov">
        <span title="来源搜索关键词">🔍 来源：{keyword}</span>
        <span title="抓取时间戳">⏱ 抓取：{crawl_time}</span>
      </div>
      <div class="card-foot">
        <a class="open-link" href="{link}" target="_blank" rel="noopener" title="{link}">打开完整笔记 ↗</a>
      </div>
    </div>"""


def render():
    """渲染并写出 HTML 看板，返回输出路径。"""
    notes = _load_notes()
    notes.sort(key=_sort_key, reverse=True)

    # 统计各分类数量
    total = len(notes)
    n_coding = sum(1 for n in notes if config.CAT_CODING in n.get("categories", []))
    n_bagu = sum(1 for n in notes if config.CAT_BAGU in n.get("categories", []))
    n_other = sum(1 for n in notes if config.CAT_OTHER in n.get("categories", []))

    cards = "\n".join(_card_html(n) for n in notes)
    gen_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    page = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>大模型面经看板</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
    background: #f5f6f8; color: #222;
  }}
  header {{
    background: linear-gradient(135deg, #ff2442, #ff6b6b);
    color: #fff; padding: 24px 32px;
  }}
  header h1 {{ margin: 0 0 6px; font-size: 24px; }}
  header .sub {{ font-size: 13px; opacity: .9; }}
  .tabs {{
    display: flex; gap: 8px; padding: 16px 32px 0; flex-wrap: wrap;
    position: sticky; top: 0; background: #f5f6f8; z-index: 10;
  }}
  .tab {{
    padding: 8px 18px; border-radius: 20px; cursor: pointer;
    background: #fff; border: 1px solid #e2e4e8; font-size: 14px; user-select: none;
  }}
  .tab.active {{ background: #ff2442; color: #fff; border-color: #ff2442; }}
  .grid {{
    display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
    gap: 16px; padding: 20px 32px 40px;
  }}
  .card {{
    background: #fff; border-radius: 12px; padding: 16px;
    box-shadow: 0 1px 4px rgba(0,0,0,.06); display: flex; flex-direction: column;
    transition: transform .15s, box-shadow .15s;
  }}
  .card:hover {{ transform: translateY(-3px); box-shadow: 0 6px 18px rgba(0,0,0,.12); }}
  .card-head {{ margin-bottom: 8px; }}
  .badge {{
    display: inline-block; font-size: 12px; padding: 2px 10px;
    border-radius: 10px; margin-right: 6px; color: #fff;
  }}
  .badge-coding {{ background: #2f6fed; }}
  .badge-bagu {{ background: #19b36b; }}
  .badge-other {{ background: #999; }}
  .card-title {{
    font-size: 16px; font-weight: 600; color: #1a1a1a; text-decoration: none;
    line-height: 1.4; margin-bottom: 8px;
  }}
  .card-title:hover {{ color: #ff2442; }}
  .card-desc {{ font-size: 13px; color: #666; line-height: 1.5; flex: 1; margin-bottom: 10px; }}
  .card-tags {{ display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 10px; }}
  .tag {{ font-size: 12px; padding: 2px 9px; border-radius: 6px; border: 1px solid transparent; }}
  .tag-company {{ background: #fff3e6; color: #d46b08; border-color: #ffd591; }}
  .tag-position {{ background: #e6f4ff; color: #0958d9; border-color: #91caff; }}
  .card-meta {{ display: flex; gap: 14px; font-size: 12px; color: #888; margin-bottom: 8px; flex-wrap: wrap; }}
  .card-prov {{ display: flex; gap: 14px; font-size: 11px; color: #aaa; margin-bottom: 10px;
    flex-wrap: wrap; border-top: 1px dashed #f0f0f0; padding-top: 8px; }}
  .card-foot {{ display: flex; justify-content: flex-end; align-items: center;
    border-top: 1px solid #f0f0f0; padding-top: 10px; font-size: 12px; }}
  .open-link {{ color: #ff2442; text-decoration: none; }}
  .empty {{ padding: 60px; text-align: center; color: #aaa; }}
</style>
</head>
<body>
<header>
  <h1>大模型 / LLM 面经看板</h1>
  <div class="sub">
    共 {total} 条 ｜ 八股题 {n_bagu} ｜ 手撕算法题 {n_coding} ｜ 综合 {n_other}
    ｜ 生成时间 {gen_time}  </div>
</header>

<div class="tabs">
  <div class="tab active" data-filter="全部">全部 ({total})</div>
  <div class="tab" data-filter="{config.CAT_BAGU}">{config.CAT_BAGU} ({n_bagu})</div>
  <div class="tab" data-filter="{config.CAT_CODING}">{config.CAT_CODING} ({n_coding})</div>
  <div class="tab" data-filter="{config.CAT_OTHER}">{config.CAT_OTHER} ({n_other})</div>
</div>

<div class="grid" id="grid">
{cards if cards.strip() else '<div class="empty">暂无数据，请先运行 python run.py 抓取。</div>'}
</div>

<script>
  // Tab 切换：根据卡片 data-cats 是否包含目标分类来显示/隐藏
  const tabs = document.querySelectorAll('.tab');
  const cards = document.querySelectorAll('.card');
  tabs.forEach(tab => {{
    tab.addEventListener('click', () => {{
      tabs.forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      const f = tab.dataset.filter;
      cards.forEach(c => {{
        const cats = c.dataset.cats || '';
        c.style.display = (f === '全部' || cats.indexOf(f) !== -1) ? '' : 'none';
      }});
    }});
  }});
</script>
</body>
</html>"""

    with open(config.HTML_DASHBOARD_PATH, "w", encoding="utf-8") as f:
        f.write(page)

    print(f"[完成] 看板已生成：{config.HTML_DASHBOARD_PATH}（共 {total} 条）")
    return config.HTML_DASHBOARD_PATH


if __name__ == "__main__":
    render()
