# -*- coding: utf-8 -*-
"""
扫码登录脚本

功能：
    用 Playwright 打开小红书首页，弹出二维码后提示用户用手机 App 扫码登录；
    登录成功后把浏览器的 storage_state（cookie + localStorage）保存到本地 JSON，
    供后续 crawler.py / run.py 复用，不必每次扫码。

用法：
    source venv/bin/activate
    python login.py
"""

import sys

from playwright.sync_api import sync_playwright

import config


def is_logged_in(page) -> bool:
    """
    粗略判断当前页面是否已登录。
    小红书登录后页面上一般不再出现「登录」按钮，且会出现用户头像 / 侧边栏。
    这里用多种特征做兜底判断，任意命中即认为已登录。
    """
    try:
        # 特征 1：页面存在「发布」「我」等已登录才有的入口
        for sel in [
            "text=发布笔记",
            ".user .name",          # 侧边栏用户名
            ".main-container .user", # 用户区域
            "li.user",
        ]:
            if page.query_selector(sel):
                return True

        # 特征 2：页面已不存在明显的「登录」按钮
        login_btn = page.query_selector(".login-btn, .reds-button:has-text('登录')")
        if login_btn is None:
            # 再确认确实进入了主站（URL 不在登录页）
            if "xiaohongshu.com" in page.url:
                return True
    except Exception:
        pass
    return False


def main():
    print("=" * 60)
    print("小红书扫码登录")
    print("=" * 60)
    print("即将打开浏览器，请用【小红书 App】扫码登录。")
    print("登录成功后脚本会自动保存登录态，无需手动操作。")
    print("（若长时间未检测到登录，可在登录后回到终端按回车手动确认）")
    print("-" * 60)

    with sync_playwright() as p:
        # headless 必须 False，否则没法扫码
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            user_agent=config.USER_AGENT,
            viewport=config.VIEWPORT,
        )
        page = context.new_page()

        try:
            page.goto(config.HOME_URL, timeout=60000)
        except Exception as e:
            print(f"[警告] 打开首页超时或失败：{e}，可继续等待页面加载。")

        # 主动点一下登录按钮，弹出二维码（不同版本按钮选择器不一定一致，做兜底）
        for sel in [".login-btn", "text=登录", ".side-bar .login"]:
            try:
                btn = page.query_selector(sel)
                if btn:
                    btn.click()
                    break
            except Exception:
                continue

        print("\n请在弹出的浏览器里扫码登录，正在轮询登录状态……")

        # 轮询最多 180 秒，检测是否登录成功
        logged = False
        for i in range(60):
            if is_logged_in(page):
                logged = True
                break
            page.wait_for_timeout(3000)  # 每 3 秒检测一次
            print(f"  等待登录中…（{(i + 1) * 3}s）", end="\r")

        if not logged:
            # 给用户一个手动兜底：登录完了在终端按回车
            print("\n未自动检测到登录状态。如果你已在浏览器完成扫码，请按回车继续保存登录态。")
            try:
                input()
            except Exception:
                pass

        # 不管自动还是手动，都尝试保存登录态
        context.storage_state(path=config.STORAGE_STATE_PATH)
        print(f"\n[完成] 登录态已保存到：{config.STORAGE_STATE_PATH}")
        print("现在可以运行：python run.py 开始抓取。")

        browser.close()


if __name__ == "__main__":
    sys.exit(main())
