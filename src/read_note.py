# -*- coding: utf-8 -*-
"""
单篇笔记读取脚本

功能：
    接收一个小红书笔记 URL（命令行参数），用已保存的登录态 storage_state 打开详情页，
    抽取：标题、正文全文、作者、发布时间、点赞/收藏/评论数，以及（若能拿到）前若干条评论。
    优先从拦截到的笔记详情 XHR（/api/sns/web/v1/feed 等）拿结构化数据，DOM 兜底。
    结果打印到终端并存一份 JSON 到 data/。

用法：
    source venv/bin/activate
    python read_note.py "https://www.xiaohongshu.com/explore/xxxx?xsec_token=yyy&xsec_source=pc_search"

注意：URL 里带的 xsec_token / xsec_source 参数务必原样保留（直接整段加引号传入即可）。
"""

import os
import re
import sys
import json
import time
import random
import logging
import datetime

from playwright.sync_api import sync_playwright

import config


# ============ 日志 ============
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(config.LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("xhs_read_note")

# 笔记详情接口关键字（命中即尝试解析）
FEED_API_KEYWORDS = [
    "/api/sns/web/v1/feed",
]
# 评论接口关键字
COMMENT_API_KEYWORDS = [
    "/api/sns/web/v2/comment/page",
    "/api/sns/web/v1/comment/page",
]


def _extract_note_id(url: str) -> str:
    """从 URL 里抽取笔记 ID。"""
    m = re.search(r"/(?:explore|discovery/item|search_result)/([0-9a-zA-Z]+)", url)
    return m.group(1) if m else ""


def _parse_feed_json(data: dict):
    """从 /feed 接口 JSON 里解析笔记详情，返回 dict 或 None。"""
    if not isinstance(data, dict):
        return None
    d = data.get("data", data)
    items = []
    if isinstance(d, dict):
        items = d.get("items") or []
    if not items:
        return None

    it = items[0]
    card = it.get("note_card") or it.get("note") or it
    user = card.get("user") or {}
    interact = card.get("interact_info") or {}

    note = {
        "note_id": it.get("id") or card.get("note_id") or "",
        "title": card.get("title") or card.get("display_title") or "",
        "content": card.get("desc") or card.get("description") or "",
        "author": user.get("nickname") or user.get("nick_name") or "",
        "author_id": user.get("user_id") or user.get("userid") or "",
        "publish_time_raw": card.get("time") or card.get("last_update_time") or "",
        "liked_count": str(interact.get("liked_count", "")),
        "collected_count": str(interact.get("collected_count", "")),
        "comment_count": str(interact.get("comment_count", "")),
        "share_count": str(interact.get("share_count", "")),
    }
    # 时间戳转可读
    note["publish_time"] = _ts_to_str(note["publish_time_raw"])
    return note


def _parse_comments_json(data: dict, limit=10):
    """从评论接口 JSON 里解析前若干条评论。"""
    comments = []
    if not isinstance(data, dict):
        return comments
    d = data.get("data", data)
    raw = []
    if isinstance(d, dict):
        raw = d.get("comments") or []
    for c in raw[:limit]:
        if not isinstance(c, dict):
            continue
        user = c.get("user_info") or c.get("user") or {}
        comments.append({
            "author": user.get("nickname") or "",
            "content": c.get("content") or "",
            "like_count": str(c.get("like_count", "")),
            "time": _ts_to_str(c.get("create_time") or ""),
        })
    return comments


def _ts_to_str(ts):
    """时间戳（秒/毫秒）转字符串，失败返回原值字符串。"""
    if not ts:
        return ""
    try:
        v = float(ts)
        if v > 1e12:
            v /= 1000.0
        return datetime.datetime.fromtimestamp(v).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(ts)


def _dom_fallback(page):
    """DOM 兜底解析笔记详情（XHR 没拿到时使用）。"""
    note = {}

    def _txt(selectors):
        for sel in selectors:
            try:
                el = page.query_selector(sel)
                if el:
                    t = el.inner_text().strip()
                    if t:
                        return t
            except Exception:
                continue
        return ""

    note["title"] = _txt(["#detail-title", ".note-content .title", ".title"])
    note["content"] = _txt(["#detail-desc", ".note-content .desc", ".desc"])
    note["author"] = _txt([".author-wrapper .username", ".author .name", ".username"])
    note["publish_time"] = _txt([".bottom-container .date", ".date", ".publish-date"])
    note["liked_count"] = _txt([".like-wrapper .count", ".interact-container .like .count"])
    note["collected_count"] = _txt([".collect-wrapper .count", ".collect .count"])
    note["comment_count"] = _txt([".chat-wrapper .count", ".comment .count"])

    # 评论兜底
    comments = []
    try:
        for el in page.query_selector_all(".comment-item, .parent-comment .comment-inner")[:10]:
            try:
                author = el.query_selector(".author, .name")
                content = el.query_selector(".content, .note-text")
                comments.append({
                    "author": author.inner_text().strip() if author else "",
                    "content": content.inner_text().strip() if content else "",
                    "like_count": "",
                    "time": "",
                })
            except Exception:
                continue
    except Exception:
        pass
    note["comments"] = comments
    return note


def read_note(url: str):
    """打开单篇笔记并抽取信息，返回结果 dict。"""
    if not os.path.exists(config.STORAGE_STATE_PATH):
        logger.error(f"未找到登录态文件 {config.STORAGE_STATE_PATH}，请先运行：python login.py")
        return None

    note_id = _extract_note_id(url)
    logger.info(f"准备读取笔记：{note_id or '(未识别ID)'}  URL={url}")

    feed_note = {"_got": False}
    comments_box = {"list": []}

    def on_response(response):
        u = response.url
        try:
            if any(k in u for k in FEED_API_KEYWORDS):
                parsed = _parse_feed_json(response.json())
                if parsed:
                    feed_note.update(parsed)
                    feed_note["_got"] = True
                    logger.info("  [XHR] 命中笔记详情接口 /feed")
            elif any(k in u for k in COMMENT_API_KEYWORDS):
                cs = _parse_comments_json(response.json())
                if cs:
                    comments_box["list"] = cs
                    logger.info(f"  [XHR] 命中评论接口，取到 {len(cs)} 条评论")
        except Exception as e:
            logger.debug(f"解析响应失败：{e}")

    result = None
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=config.HEADLESS)
        context = browser.new_context(
            storage_state=config.STORAGE_STATE_PATH,
            user_agent=config.USER_AGENT,
            viewport=config.VIEWPORT,
        )
        page = context.new_page()
        page.on("response", on_response)

        try:
            # URL 原样传入（保留 xsec_token 等参数）
            page.goto(url, timeout=60000)
        except Exception as e:
            logger.warning(f"打开笔记页失败/超时：{e}")

        # 等页面渲染 + 接口返回
        time.sleep(random.uniform(2.5, 4.0))
        # 向下滚动触发评论加载
        for _ in range(3):
            try:
                page.mouse.wheel(0, random.randint(1200, 2000))
            except Exception:
                pass
            time.sleep(random.uniform(1.0, 2.0))

        # 优先用 XHR 结果，否则 DOM 兜底
        if feed_note.get("_got"):
            result = {k: v for k, v in feed_note.items() if k != "_got"}
            result["comments"] = comments_box["list"]
            logger.info("使用 XHR 结构化数据")
        else:
            logger.info("XHR 未取到，使用 DOM 兜底解析")
            result = _dom_fallback(page)

        # 补充 provenance 字段
        result.setdefault("note_id", note_id)
        result["source_url"] = url
        result["crawl_time"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        try:
            page.remove_listener("response", on_response)
        except Exception:
            pass
        browser.close()

    return result


def _save(result):
    """保存结果 JSON 到 data/。"""
    os.makedirs(config.DATA_DIR, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    nid = result.get("note_id") or "note"
    path = os.path.join(config.DATA_DIR, f"note_{nid}_{ts}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return path


def _print_result(r):
    """把结果打印到终端。"""
    print("\n" + "=" * 60)
    print("笔记详情")
    print("=" * 60)
    print(f"标题    ：{r.get('title', '')}")
    print(f"作者    ：{r.get('author', '')}")
    print(f"发布时间：{r.get('publish_time', '') or r.get('publish_time_raw', '')}")
    print(f"点赞    ：{r.get('liked_count', '')}")
    print(f"收藏    ：{r.get('collected_count', '')}")
    print(f"评论数  ：{r.get('comment_count', '')}")
    print(f"链接    ：{r.get('source_url', '')}")
    print("-" * 60)
    print("正文：")
    print(r.get("content", "") or "(未取到正文)")
    print("-" * 60)
    comments = r.get("comments", [])
    print(f"评论（前 {len(comments)} 条）：")
    if not comments:
        print("  (未取到评论)")
    for i, c in enumerate(comments, 1):
        print(f"  {i}. @{c.get('author','')} [{c.get('like_count','')}赞]：{c.get('content','')}")
    print("=" * 60)


def main():
    if len(sys.argv) < 2:
        print("用法：python read_note.py \"<小红书笔记URL>\"")
        print("提示：URL 里的 xsec_token 等参数请原样保留，整段加引号传入。")
        return 1

    url = sys.argv[1].strip()
    result = read_note(url)
    if not result:
        print("读取失败（请确认已登录 + URL 正确）。")
        return 1

    _print_result(result)
    path = _save(result)
    print(f"\n[已保存] {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
