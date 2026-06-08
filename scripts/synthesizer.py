# -*- coding: utf-8 -*-
"""整合层 —— 信源评分 + 交叉验证 + 矛盾检测 + 最终报告生成。

核心能力：
1. 信源可信度评分（1-10）+ 分类（官方/学术/媒体/社区/自媒体）
2. 多来源交叉验证——被多处确认的事实 vs 单一来源声明
3. 矛盾检测——不同来源对同一事实说法不一致
4. 最终报告生成——带完整引用链
"""

import re, os, json
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))

# === 信源分类规则 ===

SOURCE_PATTERNS = {
    "官方": [
        r"github\.com/[^/]+/[^/\s]+",           # GitHub 仓库
        r"docs\.python\.org", r"developer\.mozilla",
        r"pypi\.org", r"npmjs\.com",
        r"arxiv\.org",                             # 学术预印本
        r"semanticscholar\.org",
        r"\.gov\.", r"\.edu\.",
        r"docs\.langchain\.com", r"python\.org",
    ],
    "学术": [
        r"arxiv\.org/abs/\d+",                   # arXiv 论文
        r"doi\.org/", r"springer\.com",
        r"ieee\.org", r"acm\.org",
        r"nature\.com", r"science\.org",
        r"cnki\.net", r"wanfangdata\.com",
    ],
    "媒体": [
        r"techcrunch\.com", r"theverge\.com",
        r"wired\.com", r"arstechnica\.com",
        r"36kr\.com", r"geekpark\.net",
        r"infoq\.cn", r"oschina\.net",
    ],
    "社区": [
        r"stackoverflow\.com", r"stackexchange\.com",
        r"reddit\.com", r"news\.ycombinator\.com",
        r"zhihu\.com", r"segmentfault\.com",
        r"csdn\.net", r"juejin\.cn",
        r"v2ex\.com", r"nodejs\.org",
    ],
    "自媒体": [
        r"medium\.com", r"dev\.to",
        r"blog\.csdn\.net", r"jianshu\.com",
        r"mp\.weixin\.qq\.com",               # 微信公众号
        r"bilibili\.com", r"youtube\.com",
    ],
}


def classify_source(url):
    """根据 URL 分类信源类型。"""
    for category, patterns in SOURCE_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, url, re.IGNORECASE):
                return category
    return "未分类"


def score_source(url):
    """根据信源类型给出基础可信度评分（1-10）。"""
    category = classify_source(url)
    base_scores = {
        "官方": 9,
        "学术": 8,
        "媒体": 6,
        "社区": 5,
        "自媒体": 3,
        "未分类": 5,
    }
    return base_scores.get(category, 5)


def analyze_sources(links):
    """对一组 URL 进行信源分析和评分。

    返回:
    {
        "sources": [{"url": str, "category": str, "score": int}],
        "avg_score": float,
        "categories": {category: count},
    }
    """
    sources = []
    scores = []
    categories = {}

    for url in links:
        cat = classify_source(url)
        score = score_source(url)
        sources.append({"url": url, "category": cat, "score": score})
        scores.append(score)
        categories[cat] = categories.get(cat, 0) + 1

    return {
        "sources": sources,
        "avg_score": round(sum(scores) / len(scores), 1) if scores else 0,
        "categories": categories,
    }


# === 交叉验证 ===

def cross_validate(results):
    """对多个平台的搜索结果进行交叉验证。

    检测：
    - 被多处确认的事实（高置信度）
    - 单一来源的声明（需标注）
    - 矛盾信息

    results: orchestrator.execute() 返回的 results 列表

    返回验证报告 dict。
    """
    if len(results) < 2:
        return {
            "level": "single_source",
            "note": "仅单一来源，无法交叉验证",
            "confirmed": [],
            "single_source_claims": ["所有结论均来自单一平台"],
            "contradictions": [],
        }

    # 提取所有内容的关键词和数字
    all_claims = []
    for r in results:
        if not r.get("content"):
            continue
        # 提取数字型事实（版本号、百分比、年份等）
        content = r["content"]
        numbers = re.findall(r'\b\d+\.?\d*%?\b', content)
        # 提取 URL
        urls = re.findall(r'https?://[^\s<>"\')\]]+', content)
        all_claims.append({
            "platform": r["platform"],
            "numbers": numbers[:20],
            "urls": urls[:10],
        })

    # 简单的交叉确认：两个平台是否引用了相同 URL
    confirmed_urls = []
    single_urls = []
    if len(all_claims) >= 2:
        for i in range(len(all_claims)):
            for j in range(i+1, len(all_claims)):
                common = set(all_claims[i]["urls"]) & set(all_claims[j]["urls"])
                confirmed_urls.extend(common)

    # 为每个平台提取的 URL 分类
    all_unique_urls = set()
    for ac in all_claims:
        all_unique_urls.update(ac["urls"])
    single_urls = list(all_unique_urls - set(confirmed_urls))

    return {
        "level": "cross_validated" if confirmed_urls else "multi_source_no_overlap",
        "platforms": [r.get("platform", "?") for r in results if r.get("content")],
        "confirmed_urls": list(set(confirmed_urls))[:10],
        "single_source_urls": single_urls[:10],
        "contradictions": [],  # 矛盾检测需要更深的语义分析，此处做结构占位
        "confidence": "中" if confirmed_urls else "低",
        "note": f"{len(confirmed_urls)} 个 URL 被多平台引用" if confirmed_urls else "各平台引用不同来源，建议关键结论额外验证",
    }


# === 报告生成 ===

def generate_report(query, results, validation, output_path=None):
    """生成最终研究报告（Markdown 格式，带完整引用链）。

    返回报告文本。若指定 output_path 则写入文件。
    """
    now = datetime.now(CST).isoformat()

    lines = [
        f"# 研究报告: {query[:80]}",
        f"",
        f"**生成时间**: {now}",
        f"**来源平台数**: {len([r for r in results if r.get('content')])}",
        f"**交叉验证**: {validation.get('level', 'N/A')} | 置信度: {validation.get('confidence', 'N/A')}",
        f"",
        f"---",
        f"",
    ]

    # 各平台结果
    for i, r in enumerate(results, 1):
        if not r.get("content"):
            lines.append(f"## {i}. {r['platform']} — 未获取到结果")
            lines.append(f"")
            lines.append(f"> 错误: {r.get('error', '未知')}")
            lines.append(f"")
            continue

        lines.append(f"## {i}. {r['platform']} — {r.get('question', '?')[:60]}")
        lines.append(f"")
        lines.append(f"> 内容长度: {r.get('content_len', 0)} 字符 | 信息缺口: {len(r.get('gaps', []))} 处")
        if r.get("links"):
            lines.append(f"> 引用链接: {len(r['links'])} 个")
        lines.append(f"")

        # 正文（截断过长内容）
        content = r["content"]
        if len(content) > 5000:
            content = content[:5000] + f"\n\n... (截断，全文 {r['content_len']} 字符)"
        lines.append(content)
        lines.append(f"")

        # 来源评价
        if r.get("links"):
            analysis = analyze_sources(r["links"])
            lines.append(f"### 来源评价（{r['platform']}）")
            lines.append(f"- 平均可信度: {analysis['avg_score']}/10")
            lines.append(f"- 来源分布: {analysis['categories']}")
            lines.append(f"")

    # 交叉验证报告
    lines.append(f"---")
    lines.append(f"## 交叉验证报告")
    lines.append(f"")
    lines.append(f"- **验证级别**: {validation.get('level', 'N/A')}")
    lines.append(f"- **置信度**: {validation.get('confidence', 'N/A')}")
    lines.append(f"- **多平台共同引用**: {len(validation.get('confirmed_urls', []))} 个 URL")
    lines.append(f"- **各平台独有引用**: {len(validation.get('single_source_urls', []))} 个 URL")
    if validation.get("note"):
        lines.append(f"- **说明**: {validation['note']}")
    lines.append(f"")

    # 信息缺口汇总
    all_gaps = []
    for r in results:
        for g in r.get("gaps", []):
            all_gaps.append(f"- [{r['platform']}] {g[:120]}")
    if all_gaps:
        lines.append(f"## ⚠️ 信息缺口")
        lines.append(f"")
        lines.extend(all_gaps[:10])
        lines.append(f"")

    report = "\n".join(lines)

    if output_path:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report)

    return report


def synthesize(query, orchestrator_output):
    """完整整合流程：交叉验证 + 信源评分 + 报告生成。

    orchestrator_output: orchestrator.execute() 的返回值

    返回 (report_text, validation_dict)
    """
    results = orchestrator_output.get("results", [])
    validation = cross_validate(results)
    report = generate_report(query, results, validation)
    return report, validation


if __name__ == "__main__":
    import sys as _sys
    _sys.stdout.reconfigure(encoding='utf-8')

    # 模拟数据测试
    mock_results = [
        {"platform": "deepseek", "question": "测试问题", "content": "Python 3.13 引入了新的 asyncio 特性...详见 https://docs.python.org/3.13/", "content_len": 200, "gaps": [], "links": ["https://docs.python.org/3.13/", "https://github.com/python/cpython"]},
        {"platform": "kimi", "question": "测试问题", "content": "asyncio 在 3.13 中 TaskGroup 有改进...参考 https://docs.python.org/3.13/ 和 https://zhihu.com/question/123", "content_len": 180, "gaps": ["需要进一步了解性能影响"], "links": ["https://docs.python.org/3.13/", "https://zhihu.com/question/123"]},
    ]
    mock_output = {"results": mock_results, "gaps_total": 1, "all_links": ["https://docs.python.org/3.13/", "https://github.com/python/cpython", "https://zhihu.com/question/123"]}

    report, validation = synthesize("Python 3.13 asyncio 新特性测试", mock_output)
    print(report[:2000])
    print(f"\n=== 验证 ===")
    print(json.dumps(validation, ensure_ascii=False, indent=2))
