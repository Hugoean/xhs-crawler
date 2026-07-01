# -*- coding: utf-8 -*-
"""
小红书面经爬虫 · 正式版（最终方案）
日期：2026-06-28

方案：用已登录的 Playwright 上下文，读页面内嵌 window.__INITIAL_STATE__（SSR 注入）
      —— 搜索页提取每条笔记 id + xsecToken，再用 token 打开详情页读完整正文 desc。
      不碰加密 API、不逆向签名、不靠脆弱 DOM。配 stealth 反检测 + 随机延时防封号。

用法：
    python crawl_final.py [目标篇数, 默认100]
只保留 config.FILTER_YEAR(=2026) 及以后发布的笔记。增量去重，边爬边刷新看板。
"""
import os
import sys
import json
import time
import random
import subprocess
from urllib.parse import quote

from playwright.sync_api import sync_playwright

import config
import crawler

TARGET = int(sys.argv[1]) if len(sys.argv) > 1 else 100

# ---- 反检测注入脚本（抹掉自动化指纹）----
STEALTH_JS = """
    Object.defineProperty(navigator,'webdriver',{get:()=>undefined});
    Object.defineProperty(navigator,'languages',{get:()=>['zh-CN','zh']});
    Object.defineProperty(navigator,'plugins',{get:()=>[1,2,3,4,5]});
    window.chrome = window.chrome || {runtime:{}};
"""

# ---- 遍历搜索页 state，提取 id + xsecToken ----
EXTRACT_TOKENS_JS = r"""
() => {
  const out = []; const s = window.__INITIAL_STATE__; if (!s) return out;
  const seen = new Set();
  function walk(o, d) {
    if (!o || d > 7 || typeof o !== 'object') return;
    const id = o.id || o.noteId;
    const tok = o.xsecToken || o.xsec_token;
    if (id && tok && typeof id === 'string' && /^[0-9a-z]+$/.test(id) && !seen.has(id)) {
      seen.add(id);
      const nc = o.noteCard || o.note || {};
      out.push({ id: id, token: tok, title: (nc.displayTitle || nc.title || '') });
    }
    for (const k in o) { try { walk(o[k], d + 1); } catch (e) {} }
  }
  walk(s, 0); return out;
}
"""

# ---- 详情页 state 取正文 ----
DETAIL_JS = r"""
(nid) => {
  const s = window.__INITIAL_STATE__; if (!s || !s.note) return null;
  const ndm = s.note.noteDetailMap || {};
  let e = ndm[nid];
  if (!e || !e.note) { for (const k in ndm) { if (ndm[k] && ndm[k].note) { e = ndm[k]; break; } } }
  if (!e || !e.note) return null;
  const n = e.note; const ii = n.interactInfo || {};
  return {
    title: n.title || '', desc: n.desc || '',
    author: (n.user || {}).nickname || '',
    liked: String(ii.likedCount || ''), collected: String(ii.collectedCount || ''),
    comment: String(ii.commentCount || ''), time: n.time || ''
  };
}
"""


# ============ 工具 ============
def render():
    """刷新看板（失败不中断）。"""
    try:
        subprocess.run([sys.executable, "render_html.py"], check=False, cwd=config.BASE_DIR)
    except Exception as e:
        print("[warn] 渲染失败:", e)


def merge_write(notes_map):
    """合并进 data/all_notes.json（按 note_id 去重）。"""
    crawler.ensure_dirs()
    path = os.path.join(config.DATA_DIR, "all_notes.json")
    hist = {}
    if os.path.exists(path):
        try:
            for n in json.load(open(path, encoding="utf-8")):
                hist[n["note_id"]] = n
        except Exception:
            pass
    hist.update(notes_map)
    json.dump(list(hist.values()), open(path, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    return len(hist)


def collect_tokens(page, keyword):
    """打开搜索页、滚动、从 __INITIAL_STATE__ 提取候选（id+token）。"""
    try:
        page.goto(config.SEARCH_URL_TEMPLATE.format(keyword=quote(keyword)), timeout=60000)
        page.wait_for_selector("section.note-item, .note-item", timeout=20000)
    except Exception:
        print(f"   [warn]「{keyword}」搜索结果未加载（可能限流）")
        return []
    time.sleep(2)
    for _ in range(6):  # 多滚动加载更多
        try:
            page.mouse.wheel(0, random.randint(1800, 2800))
        except Exception:
            pass
        time.sleep(random.uniform(1.2, 2.2))
    try:
        return page.evaluate(EXTRACT_TOKENS_JS)
    except Exception as e:
        print("   [warn] 提取 token 失败:", e)
        return []


def read_detail(page, nid, token):
    """用 token goto 详情页，轮询读 __INITIAL_STATE__ 拿正文。"""
    url = f"https://www.xiaohongshu.com/explore/{nid}?xsec_token={token}&xsec_source=pc_search"
    try:
        page.goto(url, timeout=60000, wait_until="domcontentloaded")
    except Exception as e:
        print("   [warn] goto 详情失败:", e)
    for _ in range(6):
        time.sleep(random.uniform(1.0, 1.8))
        try:
            d = page.evaluate(DETAIL_JS, nid)
        except Exception:
            d = None
        if d and (d.get("desc") or d.get("title")):
            return d, url
    return None, url


# ============ 主流程 ============
def main():
    if not os.path.exists(config.STORAGE_STATE_PATH):
        print("[错误] 未登录，请先运行：python login.py")
        return
    crawler.ensure_dirs()
    seen = crawler.load_seen_ids()
    result = {}      # 本轮抓到的（note_id -> note）
    skip_old = 0     # 被年份过滤掉的数量

    print(f"🎯 目标 {TARGET} 篇『今年({config.FILTER_YEAR})』面经，多关键词 + __INITIAL_STATE__ 方案\n")
    with sync_playwright() as p:
        b = p.chromium.launch(headless=False, args=config.LAUNCH_ARGS)
        ctx = b.new_context(storage_state=config.STORAGE_STATE_PATH,
                            user_agent=config.USER_AGENT, viewport=config.VIEWPORT)
        ctx.add_init_script(STEALTH_JS)
        page = ctx.new_page()

        for kw in config.KEYWORDS:
            if len(result) >= TARGET:
                break
            print(f"🔍 关键词：{kw}")
            cands = collect_tokens(page, kw)
            print(f"   提取到 {len(cands)} 条候选，逐篇读正文……")

            for c in cands:
                if len(result) >= TARGET:
                    break
                nid, token = c["id"], c["token"]
                if nid in seen or nid in result:
                    continue
                d, url = read_detail(page, nid, token)
                if not d:
                    continue
                dt = crawler.parse_publish_time(d.get("time"))
                # 年份过滤：只留今年及以后（解析不出时间的保留）
                if not crawler.passes_year_filter(dt):
                    skip_old += 1
                    seen.add(nid)
                    continue
                note = crawler._build_note(nid, d["title"], d["desc"], d["author"],
                                           d.get("liked") or "0", dt, d.get("time"), url, kw)
                note["collected_count"] = d.get("collected", "")
                note["comment_count"] = d.get("comment", "")
                result[nid] = note
                seen.add(nid)

                n_done = len(result)
                ymd = note["publish_time"][:10] or "未知日期"
                print(f"  📄[{n_done}/{TARGET}] {d['title'][:32]} | {ymd} | 正文{len(d['desc'])}字 | {note['categories']}")

                # 增量落盘 + 刷看板（每篇）
                merge_write(result)
                crawler.save_seen_ids(seen)
                render()
                time.sleep(random.uniform(2.5, 4.5))  # 防限流

            time.sleep(random.uniform(3, 5))  # 关键词间歇

        if result:
            crawler.save_results(list(result.values()))
        b.close()

    got = sum(1 for n in result.values() if len(n.get("desc", "")) > 10)
    print("\n" + "=" * 60)
    print(f"✅ 完成：抓到今年面经 {len(result)} 篇（{got} 篇有正文），过滤旧笔记 {skip_old} 篇")
    print(f"   数据：data/all_notes.json / all_notes.csv")
    print(f"   看板：面经看板.html")


if __name__ == "__main__":
    main()
