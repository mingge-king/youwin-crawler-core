# ggzy-crawler-core

**Drop in a list of URLs. Auto-detects 6 CMS types. Tested on a 2012 i3 — 20M+ records/day. Zero config, zero cloud cost.**

**扔一批网址进去，自动识别6种CMS。测试跑在2012年的i3上，一天2000万+条产出，零配置，零云成本。**

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Why? / 为什么做这个

Large-scale web data collection faces a fragmentation problem: target sites run on at least 6 different CMS engines, each with different search interfaces, pagination patterns, and anti-bot measures. Manually configuring 1700+ sites is impossible.

大规模数据采集面临站点碎片化的问题：目标平台至少搭载 6 种不同架构的内容管理系统，各类检索接口、分页逻辑、反爬策略各不相同，人工为 1700 余个站点逐一配置规则几乎无法实现。

**ggzy-crawler-core** auto-detects site structure using pure rule engines and generates crawl configs at runtime. No manual config per site. No LLM in the hot path.

**ggzy-crawler-core** 依靠纯规则引擎自动识别站点结构，运行时动态生成爬取配置，无需单个站点手动配置，核心业务流程不接入大语言模型。

## Quick Start / 快速上手

```bash
pip install ggzy-crawler-core
playwright install chromium
```

```python
from ggzy_crawler import crawl

# 告诉系统：爬哪个站 + 找什么内容
result = crawl(
    "https://example.gov.cn",
    keywords=["招标", "中标", "2025"],  # 要找什么
    max_pages=5,                         # 每个关键词最多翻几页
)

print(f"引擎: {result['stats']['engine']}, CMS: {result['stats']['cms']}")
print(f"找到 {result['stats']['total_items']} 条")

for item in result["items"][:5]:
    print(f"  {item['text'][:60]}")
    print(f"  -> {item['href']}")
```

### 分步使用 / Step-by-step

```python
from ggzy_crawler import probe, quick_config, extract_list

# 1. 探测站点 / Probe
result = probe("https://example.gov.cn")
print(f"CMS: {result.cms_signature}, 搜索: {result.has_search}")

# 2. 生成配置 / Generate config
config = quick_config("https://example.gov.cn", "Example Site")

# 3. 按关键词爬取 / Crawl with intent
items, _ = extract_list(config, keywords=["招标", "中标", "2025"], page=1)
```

## What It Detects / 探测能力

| Feature / 能力 | Method / 方法 |
|---------|--------|
| **CMS Type / CMS类型** | 15 种 CMS 签名 (epoint, TRS, huilan, cmstop, asp.net, java, ...) |
| **Search API / 搜索接口** | IRS POST/GET 变体, 通用 JSON API, XHR 监听 |
| **Pagination / 翻页** | URL参数型, 路径型, 偏移量型, 表单型, JS翻页 |
| **Link Types / 链接分类** | 站内 / 外站 / 微信短链接 / PDF+DOC 附件 |
| **Browser Needed / 是否需要浏览器** | Vue/React/Nuxt SPA检测, 小页面启发式 |
| **WeChat Articles / 微信文章** | 短链接302→迁移页跳转按钮→正文提取 |

## Architecture / 架构

```
探测 Probe → 探索 Explore → 策略 Strategize → 爬取 Crawl
                                              ↓ (失败)
                                       LLM诊断 → 补充规则
```

**Design principles / 设计原则:**

1. **规则优先，LLM做后手.** CSS选择器/正则/DOM模式走热路径，LLM 只在失败后诊断、补充新规则
2. **自举式配置.** 不需要每个站点手工配参数，探测引擎运行时搞定一切
3. **6级失败处理.** DNS不通→重试→引擎降级→标记失败→人工介入

## Modules / 模块

| Module / 模块 | Purpose / 用途 |
|--------|---------|
| `explorer.py` | 站点探测：搜索框检测、CMS识别、策略生成 |
| `cms_detector.py` | 15种CMS签名 + 自动推导正则模式 |
| `list_extractor.py` | 通用列表提取：HTTP/浏览器/JSON API 三种引擎，多关键词轮换 |
| `wechat_handler.py` | 微信文章提取：短链接→迁移页→长链接→正文 |
| `detail_extractor.py` | 字段映射表驱动的详情页提取 |
| `search_extractor.py` | 搜索表单提交 + 结果解析 |
| `anti_bot.py` | Playwright浏览器 + stealth反检测 + 通用交互引擎 |
| `html_cleaner.py` | HTML→干净Markdown管道 (35+锅炉选择器黑名单) |
| `fetcher.py` | HTTP客户端：重试+域名限速+熔断 |

## Engine Types / 引擎类型

```python
# HTTP + CSS选择器 (最快)
config = {"engine": "list_pagination", "list": {"item_selector": "a[href*='.html']", ...}}

# Playwright 浏览器渲染 (JS动态加载的站点)
config = {"engine": "list_pagination_browser", "list": {"item_selector": "...", "wait_ms": 3000}}

# 直接调 JSON API (API驱动站点最快方案)
config = {"engine": "api_json", "api": {"url_template": "/api/search", ...}}

# 搜索表单提交
config = {"engine": "search_query", "search": {"url": "/search/", "params": {...}}}
```

## Failure Classification / 失败分级

| Level / 级别 | Description / 描述 | Action / 处理 |
|-------|-------------|--------|
| L1 | DNS 不通 | 直接拒绝 |
| L2 | 首页打不开 | 重试 |
| L3 | 未发现搜索 | 降级为 list_pagination |
| L4 | 搜索失败 | 标记 failed，等待复查 |
| L5 | 翻页异常 | 标记 done，回收重试 |
| L6 | 需要登录 | 标记 paused，等人工配置 |

## Requirements / 依赖

- Python 3.10+
- Playwright (浏览器引擎和微信处理)
- Scrapling (CSS选择器)
- 可选: playwright-stealth (反检测)
- 可选: pycryptodome (AES解密，部分站点API加密)

## License

MIT — see LICENSE file.

## Proven / 实战验证

**Run on a 13-year-old desktop with zero cloud cost.**
**跑在一台 13 年前的老爷机上，零云服务成本。**

| Metric / 指标 | Value / 数值 |
|-------|--------|
| **Hardware / 硬件** | Intel i3-3220 (2012, 双核2C4T), 16GB DDR3, Windows 10 |
| **Parallel Workers / 并行数** | 48 workers 常驻 |
| **Sites Managed / 管理站点** | 1700+ 站点同时调度 |
| **Throughput / 产出** | 20,000,000+ 条/天 |
| **Uptime / 运行** | 7×24 稳定运行 |
| **Storage / 存储** | 2200+ 站点目录，原始 JSON 不可篡改 |
| **Monthly Cost / 月成本** | ¥0 (电费不算) |

The same i3 that ran Windows XP in 2012 now powers a 48-worker crawler fleet. No GPU, no SSD array, no Kubernetes — just a Python process and a lot of regex.

**If a $30 used desktop can do this, so can yours.** You don't need cloud credits. You don't need a server rack. A discarded office PC and an internet connection is all it takes to monitor thousands of sites at scale.

同一颗 i3，2012 年跑 Windows XP，现在跑 48 个并行爬虫。没有 GPU、没有 SSD 阵列、没有 Kubernetes——一个 Python 进程加一堆正则表达式。

**一台两百块的旧电脑能做到的事，你的也可以。** 不需要云服务器，不需要机房，一台报废的办公电脑加一根网线，就能大规模监控上千个网站的数据更新。
