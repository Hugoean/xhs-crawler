# -*- coding: utf-8 -*-
"""
定时任务入口

功能：
    跑一遍所有关键词，做增量更新（已抓过的不会重复），适合被 cron / launchd 调用。
    跑完顺手把 HTML 看板也重新渲染一次。

用法：
    source venv/bin/activate
    python run.py
"""

import sys
import datetime

import config
import crawler


def main():
    start = datetime.datetime.now()
    print("=" * 60)
    print(f"[{start.strftime('%Y-%m-%d %H:%M:%S')}] 开始本轮抓取")
    print(f"关键词：{', '.join(config.KEYWORDS)}")
    print(f"只保留 {config.FILTER_YEAR} 年及以后的笔记")
    print("=" * 60)

    try:
        new_notes = crawler.run()
    except Exception as e:
        print(f"[错误] 抓取过程异常：{e}")
        return 1

    print(f"\n本轮新增 {len(new_notes)} 条笔记。")

    # 抓完顺便渲染看板（失败不影响主流程）
    try:
        import render_html
        render_html.render()
        print(f"已更新看板：{config.HTML_DASHBOARD_PATH}")
    except Exception as e:
        print(f"[警告] 渲染看板失败（可手动运行 python render_html.py）：{e}")

    end = datetime.datetime.now()
    print(f"[{end.strftime('%Y-%m-%d %H:%M:%S')}] 本轮结束，耗时 {(end - start).seconds}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
