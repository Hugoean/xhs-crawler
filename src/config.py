# -*- coding: utf-8 -*-
"""
配置文件
集中管理：搜索关键词、过滤年份、延时、各类文件路径、浏览器参数等。
"""

import os
import datetime

# ============ 路径配置 ============
# 项目根目录（本文件在 src/ 下，故取上一级）
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 数据输出目录（JSON / CSV 都放这里）
DATA_DIR = os.path.join(BASE_DIR, "data")

# 登录态保存路径（storage_state，扫码登录一次后复用）
STORAGE_STATE_PATH = os.path.join(BASE_DIR, "xhs_storage_state.json")

# 增量去重用的「已抓笔记 ID」记录文件
SEEN_IDS_PATH = os.path.join(DATA_DIR, "seen_ids.json")

# 日志文件
LOG_PATH = os.path.join(BASE_DIR, "crawler.log")

# 渲染出的 HTML 看板路径
HTML_DASHBOARD_PATH = os.path.join(BASE_DIR, "面经看板.html")


# ============ 业务配置 ============
# 要搜索的关键词列表（覆盖大模型 / LLM 面经多种说法，自动去重）。
# 关键词越多覆盖越全，但每轮越久越易被风控；靠定时多轮增量累积爬全今年的。
_RAW_KEYWORDS = [
    # 基础 5 个
    "大模型评测面经",
    "大模型算法面经",
    "LLM面试",
    "大模型面经",
    "AI算法面经",
    # 扩充覆盖面
    "大模型评测实习",
    "LLM评测面经",
    "大模型测评面试",
    "算法岗面经 大模型",
    "大模型一面",
    "大模型二面",
    "AIGC面经",
    "大模型 实习 面经",
    "大模型算法实习",
]
# 去重并保持原有顺序
KEYWORDS = list(dict.fromkeys(_RAW_KEYWORDS))

# 只保留此日期（含）之后发布的笔记。设为 2025-07-01：覆盖上一届秋招(2025下半年)+2026，
# 既保留美团这类高质量 2025 面经，又过滤掉太老的内容。
FILTER_SINCE = datetime.datetime(2025, 7, 1)
FILTER_YEAR = 2026  # 兼容旧引用（实际过滤以 FILTER_SINCE 为准）

# 每抓到这么多条「新增」笔记就触发一次增量保存 + 看板渲染（不必等全爬完）
INCREMENTAL_SAVE_EVERY = 15

# 每个关键词最多向下滚动加载多少次（次数越多抓得越多，但越慢越容易被风控）
MAX_SCROLL_TIMES = 8

# 每个关键词期望抓到的笔记数量上限（达到后提前停止滚动）
MAX_NOTES_PER_KEYWORD = 60


# ============ 反爬 / 延时配置 ============
# 随机延时区间（秒），用于模拟人类操作，降低被风控概率
DELAY_MIN = 1.5
DELAY_MAX = 4.0

# 每次滚动之间的随机等待区间（秒）
SCROLL_DELAY_MIN = 1.0
SCROLL_DELAY_MAX = 2.5


# ============ 浏览器配置 ============
# 是否无头模式。默认 False，方便观察页面 / 手动过验证码
HEADLESS = False

# 浏览器视窗大小
VIEWPORT = {"width": 1280, "height": 900}

# 浏览器启动参数（反自动化检测，降低被风控概率）
LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
]

# UA（尽量贴近真实 Chrome）
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# 小红书搜索页 URL 模板（关键词需 URL 编码后填入）
SEARCH_URL_TEMPLATE = (
    "https://www.xiaohongshu.com/search_result?keyword={keyword}"
    "&source=web_search_result_notes"
)

# 小红书首页（登录用）
HOME_URL = "https://www.xiaohongshu.com"

# 「最新/时间」排序入口选择器（尽量切到最新排序；拿不到就靠 FILTER_YEAR 过滤）。
# 小红书改版频繁，列多个兜底，依次尝试点击。
SORT_LATEST_SELECTORS = [
    "text=最新",
    "text=最新发布",
    ".filter-tag:has-text('最新')",
    ".dropdown-items .item:has-text('最新')",
    "span:has-text('最新')",
]
# 触发排序下拉的入口（有的版本需先点「综合」/「筛选」展开）
SORT_TRIGGER_SELECTORS = [
    "text=综合",
    ".filter .icon",
    ".sort-container",
]

# 需要拦截的搜索接口关键字（命中即尝试解析其 JSON 响应）
SEARCH_API_KEYWORDS = [
    "/api/sns/web/v2/search/notes",
    "/api/sns/web/v1/search/notes",
]


# ============ 分类规则 ============
# 命中以下关键词 → 归类为「手撕算法题」
CATEGORY_CODING_KEYWORDS = [
    "手撕", "代码", "LeetCode", "leetcode", "力扣",
    "算法题", "写代码", "coding", "Coding", "白板", "ACM", "笔试",
]

# 命中以下关键词 → 归类为「八股题」
CATEGORY_BAGU_KEYWORDS = [
    "问到", "八股", "原理", "概念", "介绍一下",
    "讲讲", "区别", "为什么", "什么是", "面试题",
]

# 分类标签名
CAT_CODING = "手撕算法题"
CAT_BAGU = "八股题"
CAT_OTHER = "综合"


# ============ 公司 / 岗位识别词典 ============
# 公司识别：key=标准公司名，value=匹配用的别名/简称列表（命中任一即识别为该公司）
# 识别不到就留空，不瞎猜。
COMPANY_ALIASES = {
    "字节跳动": ["字节", "字节跳动", "抖音", "ByteDance", "bytedance", "TikTok", "tiktok", "豆包"],
    "腾讯": ["腾讯", "Tencent", "tencent", "微信", "WXG", "TEG", "混元"],
    "阿里巴巴": ["阿里", "阿里巴巴", "Alibaba", "alibaba", "淘宝", "天猫", "通义", "达摩院", "阿里云"],
    "蚂蚁": ["蚂蚁", "蚂蚁集团", "支付宝", "Ant Group"],
    "百度": ["百度", "Baidu", "baidu", "文心", "文心一言"],
    "美团": ["美团", "Meituan", "meituan"],
    "快手": ["快手", "Kuaishou", "kuaishou", "可灵"],
    "智谱": ["智谱", "智谱AI", "智谱清言", "ChatGLM", "Zhipu", "zhipu"],
    "月之暗面": ["月之暗面", "Moonshot", "moonshot", "Kimi", "kimi"],
    "MiniMax": ["MiniMax", "minimax", "海螺AI"],
    "深度求索": ["深度求索", "DeepSeek", "deepseek", "幻方"],
    "百川智能": ["百川", "百川智能", "Baichuan", "baichuan"],
    "零一万物": ["零一万物", "零一", "01.AI"],
    "商汤": ["商汤", "SenseTime", "sensetime", "日日新"],
    "科大讯飞": ["科大讯飞", "讯飞", "iFLYTEK", "星火"],
    "小红书": ["小红书", "RedNote", "rednote"],
    "拼多多": ["拼多多", "PDD", "pdd", "Temu", "temu"],
    "华为": ["华为", "Huawei", "huawei", "盘古", "诺亚方舟", "2012实验室"],
    "网易": ["网易", "NetEase", "netease", "有道"],
    "京东": ["京东", "京东言犀"],
    "滴滴": ["滴滴", "DiDi", "didi"],
    "微软": ["微软", "Microsoft", "MSRA", "微软亚研"],
    "OpenAI": ["OpenAI", "openai", "ChatGPT"],
    "英伟达": ["英伟达", "NVIDIA", "nvidia"],
    "vivo": ["vivo", "蓝心"],
    "OPPO": ["OPPO", "oppo"],
    "小米": ["小米", "Xiaomi", "xiaomi", "MiLM"],
    "理想汽车": ["理想汽车", "Li Auto"],
    "蔚来": ["蔚来", "NIO"],
}

# 岗位识别：key=标准岗位名，value=匹配用别名列表（命中任一即识别）
POSITION_ALIASES = {
    "大模型评测": ["大模型评测", "模型评测", "评测工程师", "Evaluation", "benchmark", "评估工程师"],
    "大模型算法": ["大模型算法", "大模型工程师", "LLM算法", "AGI", "预训练", "对齐", "RLHF", "Agent工程师"],
    "算法工程师": ["算法工程师", "算法岗", "机器学习", "Machine Learning", "ML工程师", "MLE", "深度学习"],
    "LLM": ["LLM", "大语言模型", "大模型", "GPT"],
    "NLP": ["NLP", "自然语言", "自然语言处理"],
    "CV": ["CV", "计算机视觉", "图像算法", "视觉算法"],
    "推荐/搜索": ["推荐算法", "搜索算法", "搜广推", "推荐系统", "广告算法"],
    "数据": ["数据工程师", "数据挖掘", "数据分析", "数据科学", "Data Scientist", "数仓"],
    "测开": ["测开", "测试开发", "测试工程师", "SDET"],
    "后端": ["后端开发", "服务端", "Java开发", "Go开发"],
}
