# -*- coding: utf-8 -*-
"""
小红书面经爬虫核心
作者：施晔  学号：2362404008

核心流程：
    1. 用已保存的 storage_state 启动带登录态的浏览器
    2. 逐个关键词打开搜索页
    3. 监听搜索 XHR 响应（/api/sns/web/v1/search/notes...）拿结构化 JSON（主路线）
    4. 模拟滚动加载更多，随机延时降低风控
    5. 若 XHR 没拿到，回退用 DOM 解析（兜底）
    6. 时间过滤（只保留 FILTER_YEAR 及以后）
    7. 关键词规则分类（八股题 / 手撕算法题 / 综合，可多标签）
    8. 按笔记 ID 去重 + 增量保存为 JSON / CSV
"""

import os
import re
import csv
import json
import time
import random
import logging
import datetime
from urllib.parse import quote

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
logger = logging.getLogger("xhs_crawler")


# ============ 工具函数 ============
def _sleep(a=None, b=None):
    """随机延时，模拟人类操作。"""
    a = config.DELAY_MIN if a is None else a
    b = config.DELAY_MAX if b is None else b
    time.sleep(random.uniform(a, b))


def ensure_dirs():
    """确保数据目录存在。"""
    os.makedirs(config.DATA_DIR, exist_ok=True)


def load_seen_ids() -> set:
    """读取已抓过的笔记 ID 集合（用于增量去重）。"""
    if os.path.exists(config.SEEN_IDS_PATH):
        try:
            with open(config.SEEN_IDS_PATH, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception as e:
            logger.warning(f"读取 seen_ids 失败：{e}")
    return set()


def save_seen_ids(seen: set):
    """保存已抓笔记 ID 集合。"""
    try:
        with open(config.SEEN_IDS_PATH, "w", encoding="utf-8") as f:
            json.dump(sorted(seen), f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"写入 seen_ids 失败：{e}")


# ============ 时间解析 / 过滤 ============
def parse_publish_time(raw: str):
    """
    把小红书各种时间文案解析成 datetime（尽力而为）。
    支持：
        - 时间戳（毫秒/秒，int 或纯数字字符串）
        - "X分钟前 / X小时前 / 今天 / 昨天"
        - "X天前"
        - "X月X日" / "X-X" （默认当年）
        - "2026-01-05" / "2026年1月5日" / "01-05"
    解析不出来返回 None。
    """
    now = datetime.datetime.now()

    if raw is None:
        return None

    # 时间戳（数字）
    if isinstance(raw, (int, float)):
        ts = float(raw)
        if ts > 1e12:  # 毫秒
            ts /= 1000.0
        try:
            return datetime.datetime.fromtimestamp(ts)
        except Exception:
            return None

    s = str(raw).strip()
    if not s:
        return None

    # 纯数字字符串当时间戳
    if re.fullmatch(r"\d{10,13}", s):
        ts = float(s)
        if ts > 1e12:
            ts /= 1000.0
        try:
            return datetime.datetime.fromtimestamp(ts)
        except Exception:
            return None

    # 编辑于 / 发布于 等前缀去掉
    s = re.sub(r"^(编辑于|发布于|更新于)\s*", "", s)

    # 刚刚 / 分钟前 / 小时前
    if "刚刚" in s:
        return now
    m = re.search(r"(\d+)\s*分钟前", s)
    if m:
        return now - datetime.timedelta(minutes=int(m.group(1)))
    m = re.search(r"(\d+)\s*小时前", s)
    if m:
        return now - datetime.timedelta(hours=int(m.group(1)))
    if "今天" in s:
        return now
    if "昨天" in s:
        return now - datetime.timedelta(days=1)
    if "前天" in s:
        return now - datetime.timedelta(days=2)
    m = re.search(r"(\d+)\s*天前", s)
    if m:
        return now - datetime.timedelta(days=int(m.group(1)))

    # 完整日期 2026-01-05 / 2026/01/05 / 2026年1月5日
    m = re.search(r"(\d{4})[年\-/](\d{1,2})[月\-/](\d{1,2})", s)
    if m:
        try:
            return datetime.datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except Exception:
            return None

    # X月X日（无年份，默认当年；若比现在晚说明是去年）
    m = re.search(r"(\d{1,2})\s*月\s*(\d{1,2})\s*日?", s)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        try:
            dt = datetime.datetime(now.year, month, day)
            if dt > now + datetime.timedelta(days=1):
                dt = dt.replace(year=now.year - 1)
            return dt
        except Exception:
            return None

    # MM-DD（无年份）
    m = re.fullmatch(r"(\d{1,2})-(\d{1,2})", s)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        try:
            dt = datetime.datetime(now.year, month, day)
            if dt > now + datetime.timedelta(days=1):
                dt = dt.replace(year=now.year - 1)
            return dt
        except Exception:
            return None

    return None


def passes_year_filter(dt) -> bool:
    """时间过滤：只留 config.FILTER_SINCE 之后的。解析不出来的（None）也保留（宁可多抓不漏）。"""
    if dt is None:
        return True
    since = getattr(config, "FILTER_SINCE", None)
    if since is not None:
        return dt >= since
    return dt.year >= config.FILTER_YEAR


# ============ 分类 ============
def classify(text: str):
    """
    根据关键词规则给笔记打分类标签，返回标签列表（可多标签）。
    手撕算法题 / 八股题 / 综合
    """
    text = text or ""
    labels = []
    if any(k in text for k in config.CATEGORY_CODING_KEYWORDS):
        labels.append(config.CAT_CODING)
    if any(k in text for k in config.CATEGORY_BAGU_KEYWORDS):
        labels.append(config.CAT_BAGU)
    if not labels:
        labels.append(config.CAT_OTHER)
    return labels


def extract_companies(text: str):
    """
    从文本里识别公司名，返回标准公司名列表（可多个）。
    识别不到就返回空列表，不瞎猜。
    """
    text = text or ""
    found = []
    for std_name, aliases in config.COMPANY_ALIASES.items():
        if any(alias in text for alias in aliases):
            found.append(std_name)
    return found


def extract_positions(text: str):
    """
    从文本里识别岗位名，返回标准岗位名列表（可多个）。
    识别不到就返回空列表，不瞎猜。
    """
    text = text or ""
    found = []
    for std_name, aliases in config.POSITION_ALIASES.items():
        if any(alias in text for alias in aliases):
            found.append(std_name)
    return found


# ============ XHR 响应解析 ============
def extract_notes_from_api_json(data: dict, keyword: str):
    """
    从搜索接口返回的 JSON 中提取笔记列表。
    小红书接口结构会变，这里做较宽松的解析，尽量兼容。
    返回标准化后的 note dict 列表。
    """
    notes = []
    if not isinstance(data, dict):
        return notes

    items = []
    # 常见结构：data -> items / data -> notes
    d = data.get("data", data)
    if isinstance(d, dict):
        items = d.get("items") or d.get("notes") or d.get("note_list") or []
    elif isinstance(d, list):
        items = d

    for it in items:
        if not isinstance(it, dict):
            continue
        try:
            note = _normalize_api_item(it, keyword)
            if note:
                notes.append(note)
        except Exception as e:
            logger.debug(f"解析单条 XHR item 失败：{e}")
    return notes


def _normalize_api_item(it: dict, keyword: str):
    """把搜索接口里的单个 item 规整成标准笔记字典。"""
    # item 可能是 {model_type:'note', note_card:{...}, id:...} 这种包裹结构
    card = it.get("note_card") or it.get("note") or it
    note_id = it.get("id") or card.get("note_id") or card.get("id")
    if not note_id:
        return None

    title = card.get("display_title") or card.get("title") or ""
    desc = card.get("desc") or card.get("description") or ""

    # 作者
    user = card.get("user") or {}
    author = user.get("nickname") or user.get("nick_name") or user.get("name") or ""

    # 点赞数
    interact = card.get("interact_info") or {}
    liked = interact.get("liked_count") or card.get("liked_count") or card.get("likes") or "0"

    # 时间（接口里常见 time / last_update_time 时间戳）
    raw_time = card.get("time") or card.get("last_update_time") or card.get("create_time")

    # xsec_token 用于拼可访问链接
    token = it.get("xsec_token") or card.get("xsec_token") or ""
    link = build_note_url(note_id, token)

    dt = parse_publish_time(raw_time)
    return _build_note(note_id, title, desc, author, liked, dt, raw_time, link, keyword)


def build_note_url(note_id: str, xsec_token: str = "") -> str:
    """拼接笔记可访问链接。"""
    base = f"https://www.xiaohongshu.com/explore/{note_id}"
    if xsec_token:
        return f"{base}?xsec_token={xsec_token}&xsec_source=pc_search"
    return base


def _build_note(note_id, title, desc, author, liked, dt, raw_time, link, keyword):
    """生成统一结构的笔记记录，并完成分类 + 公司/岗位识别。"""
    text_for_tag = f"{title} {desc}"
    return {
        "note_id": str(note_id),
        "title": (title or "").strip(),
        "desc": (desc or "").strip(),
        "author": (author or "").strip(),
        "liked_count": str(liked),
        # ===== 数据来源 provenance（四项必存）=====
        "keyword": keyword,                  # ① 来源关键词
        "link": link,                        # ② 笔记完整链接 URL
        "publish_time": dt.strftime("%Y-%m-%d %H:%M") if dt else "",  # ③ 发布时间
        "publish_time_raw": str(raw_time) if raw_time is not None else "",
        "crawl_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),  # ④ 抓取时间戳
        # ===== 标签 =====
        "categories": classify(text_for_tag),       # 面经分类（八股/手撕/综合）
        "companies": extract_companies(text_for_tag),  # 公司 tag（识别不到为空）
        "positions": extract_positions(text_for_tag),  # 岗位 tag（识别不到为空）
    }


# ============ DOM 兜底解析 ============
def extract_notes_from_dom(page, keyword: str):
    """
    XHR 拿不到时，从渲染后的 DOM 里兜底解析笔记卡片。
    选择器可能随小红书改版失效，做了多重兜底 + try/except。
    """
    notes = []
    # 小红书搜索结果卡片常见容器
    card_selectors = [
        "section.note-item",
        "div.note-item",
        ".feeds-page .note-item",
    ]
    cards = []
    for sel in card_selectors:
        try:
            cards = page.query_selector_all(sel)
            if cards:
                break
        except Exception:
            continue

    for c in cards:
        try:
            # 链接 + note_id
            a = c.query_selector("a[href*='/explore/'], a[href*='/search_result/']")
            href = a.get_attribute("href") if a else ""
            note_id = ""
            if href:
                m = re.search(r"/(?:explore|search_result)/([0-9a-zA-Z]+)", href)
                if m:
                    note_id = m.group(1)
            if not note_id:
                continue
            link = href if href.startswith("http") else f"https://www.xiaohongshu.com{href}"

            # 标题
            title_el = c.query_selector(".title, .footer .title, span.title")
            title = title_el.inner_text().strip() if title_el else ""

            # 作者
            author_el = c.query_selector(".author .name, .user .name, .name")
            author = author_el.inner_text().strip() if author_el else ""

            # 点赞
            like_el = c.query_selector(".like-wrapper .count, .count, .like .count")
            liked = like_el.inner_text().strip() if like_el else "0"

            note = _build_note(
                note_id, title, "", author, liked,
                None, "", link, keyword,
            )
            notes.append(note)
        except Exception as e:
            logger.debug(f"DOM 解析单卡失败：{e}")
            continue

    return notes


# ============ 排序切换 ============
def try_switch_to_latest(page):
    """
    尽量把搜索结果切到「最新/时间」排序。
    页面改版频繁，做多重兜底；点不到就算了（靠 FILTER_YEAR 过滤）。
    """
    # 有的版本要先点「综合」展开排序下拉
    for sel in config.SORT_TRIGGER_SELECTORS:
        try:
            el = page.query_selector(sel)
            if el:
                el.click()
                page.wait_for_timeout(800)
                break
        except Exception:
            continue
    # 再点「最新」
    for sel in config.SORT_LATEST_SELECTORS:
        try:
            el = page.query_selector(sel)
            if el:
                el.click()
                logger.info(f"  已切换到最新排序（{sel}）")
                page.wait_for_timeout(1200)
                return True
        except Exception:
            continue
    logger.info("  未找到最新排序入口，沿用默认排序（靠年份过滤）")
    return False


# ============ 单关键词抓取 ============
def crawl_keyword(page, keyword: str, flush_cb=None):
    """
    抓取单个关键词的搜索结果，返回去重后的笔记列表。
    flush_cb: 可选回调，签名 flush_cb(notes_list)。每抓到一小批
              （达到 config.INCREMENTAL_SAVE_EVERY 条新增）就调用一次，
              用于「边爬边保存边渲染看板」。
    """
    logger.info(f"开始抓取关键词：{keyword}")

    # 用闭包收集 XHR 拦截到的笔记
    collected = {}  # note_id -> note

    def on_response(response):
        url = response.url
        if not any(k in url for k in config.SEARCH_API_KEYWORDS):
            return
        try:
            data = response.json()
        except Exception:
            return
        for n in extract_notes_from_api_json(data, keyword):
            collected[n["note_id"]] = n
        logger.info(f"  [XHR] 命中搜索接口，目前累计 {len(collected)} 条")

    page.on("response", on_response)

    try:
        url = config.SEARCH_URL_TEMPLATE.format(keyword=quote(keyword))
        page.goto(url, timeout=60000)
    except Exception as e:
        logger.warning(f"打开搜索页失败：{e}")

    _sleep()

    # 尽量切到「最新」排序，优先抓今年的新内容
    try:
        try_switch_to_latest(page)
    except Exception as e:
        logger.debug(f"切换最新排序异常（忽略）：{e}")

    # 记录上次 flush 时已收集的数量，用于「每攒一小批就保存渲染」
    flushed_count = 0

    def _maybe_flush(force=False):
        """达到批量阈值（或 force）时回调 flush_cb，做增量保存 + 渲染。"""
        nonlocal flushed_count
        if flush_cb is None:
            return
        if force or (len(collected) - flushed_count) >= config.INCREMENTAL_SAVE_EVERY:
            try:
                flush_cb(list(collected.values()))
            except Exception as e:
                # 渲染/保存失败绝不中断爬取
                logger.warning(f"增量保存/渲染失败（忽略，继续爬）：{e}")
            flushed_count = len(collected)

    # 模拟滚动加载
    last_count = 0
    for i in range(config.MAX_SCROLL_TIMES):
        try:
            page.mouse.wheel(0, random.randint(1500, 2500))
        except Exception:
            try:
                page.evaluate("window.scrollBy(0, document.body.scrollHeight)")
            except Exception:
                pass
        time.sleep(random.uniform(config.SCROLL_DELAY_MIN, config.SCROLL_DELAY_MAX))

        # 边爬边保存：攒够一小批就立即落盘 + 刷新看板
        _maybe_flush()

        if len(collected) >= config.MAX_NOTES_PER_KEYWORD:
            logger.info(f"  已达单关键词上限 {config.MAX_NOTES_PER_KEYWORD}，停止滚动")
            break
        # 连续两轮没新增，提前结束
        if len(collected) == last_count and i >= 2:
            logger.info("  连续滚动无新增，提前结束")
            break
        last_count = len(collected)

    # 解绑监听，避免影响下一个关键词
    try:
        page.remove_listener("response", on_response)
    except Exception:
        pass

    # XHR 没拿到 → DOM 兜底
    if not collected:
        logger.info("  XHR 未取到数据，启用 DOM 兜底解析")
        for n in extract_notes_from_dom(page, keyword):
            collected[n["note_id"]] = n

    # 本关键词收尾：把剩余未 flush 的也保存渲染一次
    _maybe_flush(force=True)

    notes = list(collected.values())
    logger.info(f"关键词「{keyword}」共抓到 {len(notes)} 条（去重前）")
    return notes


# ============ 存储 ============
def save_results(all_notes):
    """把本次新增笔记追加保存为带时间戳的 JSON + CSV，并更新汇总文件。"""
    ensure_dirs()
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    # 1) 本次快照 JSON
    snap_json = os.path.join(config.DATA_DIR, f"notes_{ts}.json")
    with open(snap_json, "w", encoding="utf-8") as f:
        json.dump(all_notes, f, ensure_ascii=False, indent=2)

    # 2) 本次快照 CSV
    snap_csv = os.path.join(config.DATA_DIR, f"notes_{ts}.csv")
    _write_csv(snap_csv, all_notes)

    # 3) 合并进汇总文件
    merged_list = update_aggregate(all_notes)

    logger.info(f"本次新增 {len(all_notes)} 条；汇总共 {len(merged_list)} 条")
    logger.info(f"快照：{snap_json} / {snap_csv}")
    return snap_json


def update_aggregate(notes):
    """
    把 notes 合并进汇总文件 all_notes.json / all_notes.csv（按 note_id 去重）。
    用于增量边爬边落盘，不产生额外快照文件。返回合并后的完整列表。
    """
    ensure_dirs()
    all_path = os.path.join(config.DATA_DIR, "all_notes.json")
    history = []
    if os.path.exists(all_path):
        try:
            with open(all_path, "r", encoding="utf-8") as f:
                history = json.load(f)
        except Exception:
            history = []
    merged = {n["note_id"]: n for n in history}
    for n in notes:
        merged[n["note_id"]] = n
    merged_list = list(merged.values())
    with open(all_path, "w", encoding="utf-8") as f:
        json.dump(merged_list, f, ensure_ascii=False, indent=2)
    _write_csv(os.path.join(config.DATA_DIR, "all_notes.csv"), merged_list)
    return merged_list


def _write_csv(path, notes):
    """写 CSV（列表型字段用 / 连接）。"""
    fields = [
        "note_id", "title", "desc", "author", "liked_count",
        "keyword", "link", "publish_time", "publish_time_raw", "crawl_time",
        "categories", "companies", "positions",
    ]
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for n in notes:
            row = dict(n)
            row["categories"] = " / ".join(n.get("categories", []))
            row["companies"] = " / ".join(n.get("companies", []))
            row["positions"] = " / ".join(n.get("positions", []))
            writer.writerow({k: row.get(k, "") for k in fields})


# ============ 主入口 ============
def run(keywords=None):
    """
    跑一遍所有关键词：抓取 → 时间过滤 → 增量去重 → 保存。
    返回本次新增的笔记列表。
    """
    keywords = keywords or config.KEYWORDS
    ensure_dirs()

    if not os.path.exists(config.STORAGE_STATE_PATH):
        logger.error(
            f"未找到登录态文件 {config.STORAGE_STATE_PATH}，"
            f"请先运行：python login.py"
        )
        return []

    seen = load_seen_ids()
    new_notes = []

    def _render_dashboard():
        """安全渲染看板，失败不影响爬取。"""
        try:
            import render_html
            render_html.render()
        except Exception as e:
            logger.warning(f"渲染看板失败（忽略）：{e}")

    def process_batch(notes):
        """
        处理一批笔记：去重 + 年份过滤，新增的累计进 new_notes，
        并立即落盘汇总 + 刷新看板（用于边爬边出结果）。
        返回本批真正新增的条数。
        """
        added = 0
        batch_new = []
        for n in notes:
            nid = n["note_id"]
            if nid in seen:
                continue  # 增量去重
            dt = parse_publish_time(n.get("publish_time_raw") or n.get("publish_time"))
            if not passes_year_filter(dt):
                logger.debug(f"  过滤掉旧笔记：{n.get('title')} - {n.get('publish_time')}")
                continue
            seen.add(nid)
            new_notes.append(n)
            batch_new.append(n)
            added += 1
        if batch_new:
            # 增量保存到汇总 + 实时刷新看板（用 try/except 包住，绝不中断爬取）
            try:
                update_aggregate(batch_new)
                save_seen_ids(seen)
            except Exception as e:
                logger.warning(f"增量落盘失败（忽略）：{e}")
            _render_dashboard()
            logger.info(f"  [增量] 本批新增 {added} 条，已刷新看板（累计新增 {len(new_notes)}）")
        return added

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=config.HEADLESS,
            args=config.LAUNCH_ARGS,  # 反自动化检测
        )
        context = browser.new_context(
            storage_state=config.STORAGE_STATE_PATH,
            user_agent=config.USER_AGENT,
            viewport=config.VIEWPORT,
        )
        page = context.new_page()

        for kw in keywords:
            try:
                # flush_cb：每攒一小批就 process_batch（去重+过滤+落盘+渲染）
                crawl_keyword(page, kw, flush_cb=process_batch)
            except Exception as e:
                logger.error(f"抓取关键词「{kw}」出错：{e}")

            _sleep()  # 关键词之间多歇会儿

        browser.close()

    # 收尾：写一份本轮完整快照（带时间戳）
    if new_notes:
        try:
            save_results(new_notes)
        except Exception as e:
            logger.warning(f"写最终快照失败（忽略）：{e}")
    else:
        logger.info("本次没有新增符合条件的笔记。")

    save_seen_ids(seen)
    _render_dashboard()  # 收尾再渲染一次，确保最终状态
    return new_notes


if __name__ == "__main__":
    run()
