# -*- coding: utf-8 -*-
"""自进化引擎 —— 执行层面的观察→反思→优化→持久化闭环。

核心模块：
- FailureAnalyzer: 分类提取失败原因（含 scope：platform_specific / cross_platform / prompt_side）
- GlobalKnowledge: 跨平台共享知识库（profiles/_global.json），2+ 平台确认 → 自动提升
- KnowledgePropagator: 知识传播——本地学到的新模式检查是否该提升为全局
- ExtractionProfile: 每平台提取策略，合并 全局 + 本地 知识
- PollingProfile: 每平台轮询策略（间隔、增长速率、自适应调整）
- StrategyAdapter: 根据诊断结果生成策略适配 + 触发知识传播
"""

import os, json, re, time
from datetime import datetime, timezone, timedelta
from runtime_paths import PROFILES_DIR

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)
GLOBAL_PROFILE_PATH = os.path.join(PROFILES_DIR, "_global.json")
CST = timezone(timedelta(hours=8))


def _ensure_profiles_dir():
    os.makedirs(PROFILES_DIR, exist_ok=True)


# ============================================================
# GlobalKnowledge —— 跨平台共享知识库
# ============================================================

class GlobalKnowledge:
    """跨平台共享知识，存储已验证的通用模式。保存在 profiles/_global.json。

    数据结构：
    {
      "version": 1,
      "cot_patterns": {                          # CoT 关键词 → 确认信息
        "深度思考": {
          "first_seen": "deepseek",
          "confirmations": ["deepseek"],  # 2+ 确认 → 全局生效
          "promoted_at": "2026-06-06T18:50:00+08:00"
        }
      },
      "footer_patterns": [                      # 跨平台通用页尾（自动应用到所有平台）
        "内容由 AI 生成",
        "本回答由 AI 生成"
      ],
      "marker_placement_model": {               # AI 模型 → 标记出现位置
        "deepseek-v4": "after_thinking",
        "deepseek-r1": "after_thinking"
      },
      "known_models": {                         # 平台 → 底层 AI 模型映射
        "deepseek": "deepseek-v4"
      },
      "promotion_rules": {
        "min_confirmations": 2,                  # 至少 N 个平台确认才提升为全局
        "min_content_len": 300
      },
      "evolution_log": []
    }
    """

    @staticmethod
    def load():
        _ensure_profiles_dir()
        if os.path.exists(GLOBAL_PROFILE_PATH):
            try:
                with open(GLOBAL_PROFILE_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                data.setdefault("version", 1)
                data.setdefault("cot_patterns", {})
                # 合并默认页尾关键词（兼容旧版仅有2条的配置文件）
                existing = data.get("footer_patterns", [])
                defaults = GlobalKnowledge._default()["footer_patterns"]
                for kw in defaults:
                    if kw not in existing:
                        existing.append(kw)
                data["footer_patterns"] = existing
                data.setdefault("marker_placement_model", {})
                data.setdefault("known_models", {})
                data.setdefault("promotion_rules", {"min_confirmations": 2, "min_content_len": 300})
                data.setdefault("evolution_log", [])
                return data
            except (json.JSONDecodeError, IOError):
                pass
        return GlobalKnowledge._default()

    @staticmethod
    def _default():
        return {
            "version": 1,
            "cot_patterns": {},
            "footer_patterns": [
                "内容由 AI 生成",
                "本回答由 AI 生成",
                "window.__NUXT__",
                "请仔细甄别",
            ],
            "marker_placement_model": {},
            "known_models": {
                "deepseek": "deepseek-v4",
                "deepseek": "deepseek-v4",
            },
            "promotion_rules": {"min_confirmations": 2, "min_content_len": 300},
            "evolution_log": [],
            "created_at": datetime.now(CST).isoformat(),
        }

    @staticmethod
    def save(data):
        _ensure_profiles_dir()
        data["updated_at"] = datetime.now(CST).isoformat()
        with open(GLOBAL_PROFILE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    @staticmethod
    def get_cot_patterns():
        """获取所有全局 CoT 关键词列表。"""
        data = GlobalKnowledge.load()
        return list(data.get("cot_patterns", {}).keys())

    @staticmethod
    def get_footer_patterns():
        """获取全局页尾特征。"""
        data = GlobalKnowledge.load()
        return data.get("footer_patterns", [])

    @staticmethod
    def get_model_for_platform(platform):
        """推测平台底层使用的 AI 模型。"""
        data = GlobalKnowledge.load()
        return data.get("known_models", {}).get(platform)

    @staticmethod
    def get_marker_placement_for_model(model):
        """获取某 AI 模型已知的标记位置模式。"""
        data = GlobalKnowledge.load()
        return data.get("marker_placement_model", {}).get(model)

    @staticmethod
    def register_platform_model(platform, model_name):
        """注册平台的底层 AI 模型映射。"""
        data = GlobalKnowledge.load()
        if platform not in data.get("known_models", {}):
            data.setdefault("known_models", {})[platform] = model_name
            data["version"] = data.get("version", 1) + 1
            data.setdefault("evolution_log", []).append({
                "time": datetime.now(CST).isoformat(),
                "action": "register_model",
                "detail": f"{platform} → {model_name}",
            })
            GlobalKnowledge.save(data)

    @staticmethod
    def promote_cot_pattern(keyword, source_platform):
        """将一个 CoT 关键词提升为全局（或增加确认计数）。"""
        data = GlobalKnowledge.load()
        cot_map = data.setdefault("cot_patterns", {})
        if keyword not in cot_map:
            cot_map[keyword] = {
                "first_seen": source_platform,
                "confirmations": [source_platform],
                "promoted_at": datetime.now(CST).isoformat(),
            }
        else:
            if source_platform not in cot_map[keyword]["confirmations"]:
                cot_map[keyword]["confirmations"].append(source_platform)
        data["evolution_log"].append({
            "time": datetime.now(CST).isoformat(),
            "action": "promote_cot" if len(cot_map[keyword]["confirmations"]) >= 2 else "register_cot",
            "detail": f"CoT关键词 '{keyword}' ← {source_platform} (确认数: {len(cot_map[keyword]['confirmations'])})",
        })
        data["version"] = data.get("version", 1) + 1
        GlobalKnowledge.save(data)

    @staticmethod
    def is_promoted(keyword):
        """检查某关键词是否已达到全局推广阈值。"""
        data = GlobalKnowledge.load()
        entry = data.get("cot_patterns", {}).get(keyword)
        if not entry:
            return False
        min_conf = data.get("promotion_rules", {}).get("min_confirmations", 2)
        return len(entry.get("confirmations", [])) >= min_conf


# ============================================================
# KnowledgePropagator —— 跨平台知识传播
# ============================================================

class KnowledgePropagator:
    """检测本地学到的模式是否该提升为全局知识。

    规则：
    1. 同一条 CoT 关键词在 2+ 平台出现 → promote 到 GlobalKnowledge
    2. 同一 failure_type 在同一 AI 模型上反复出现 → 记录 marker_placement_model
    3. 页尾特征在 2+ 平台出现 → 提升为全局 footer_pattern
    """

    @staticmethod
    def after_adapt(platform, diagnosis, changes):
        """在 StrategyAdapter 适配完成后调用，检查是否需要跨平台传播。"""
        if not diagnosis or not changes:
            return

        failure_type = diagnosis.get("failure_type", "")

        if failure_type == "cot_interference":
            KnowledgePropagator._propagate_cot_keywords(platform, diagnosis)

        elif failure_type == "content_truncated":
            # 截断是通用问题，但策略已在各平台独立调整
            pass

    @staticmethod
    def _propagate_cot_keywords(platform, diagnosis):
        """传播 CoT 关键词到全局知识库。"""
        keywords = diagnosis.get("cot_keywords_matched", [])
        if not keywords:
            return

        for kw in keywords:
            GlobalKnowledge.promote_cot_pattern(kw, platform)

        # 如果本平台关联了已知 AI 模型，记录标记位置
        model = GlobalKnowledge.get_model_for_platform(platform)
        if model:
            data = GlobalKnowledge.load()
            placement = data.setdefault("marker_placement_model", {})
            if model not in placement:
                placement[model] = "after_thinking"
                data["evolution_log"].append({
                    "time": datetime.now(CST).isoformat(),
                    "action": "infer_marker_placement",
                    "detail": f"模型 {model} 标记位置 → after_thinking (从 {platform} 推断)",
                })
                data["version"] = data.get("version", 1) + 1
                GlobalKnowledge.save(data)

    @staticmethod
    def get_platform_cot_patterns(platform):
        """获取平台应使用的完整 CoT 检测列表：BASE + 全局已推广 + 本地。

        全局推广的 = 已在 2+ 平台确认的关键词，直接生效无需本地重新学习。
        """
        # 基础词
        base = set(FailureAnalyzer.BASE_COT_INDICATORS)

        # 全局已推广的 CoT 关键词（2+ 平台确认）
        global_data = GlobalKnowledge.load()
        global_patterns = set()
        for kw, entry in global_data.get("cot_patterns", {}).items():
            min_conf = global_data.get("promotion_rules", {}).get("min_confirmations", 2)
            if len(entry.get("confirmations", [])) >= min_conf:
                global_patterns.add(kw)

        # 本地平台已学的
        local_patterns = set()
        try:
            profile = ExtractionProfile(platform)
            local_patterns = set(profile.data.get("cot_patterns", []))
        except Exception:
            pass

        return list(base | global_patterns | local_patterns)


# ============================================================
# FailureAnalyzer —— 诊断提取失败原因
# ============================================================

class FailureAnalyzer:
    """分析提取失败/低质量的具体原因，输出结构化诊断。

    诊断输出新增 scope 字段：
    - platform_specific: 仅影响当前平台（新 CoT 关键词、DOM 变化等）
    - cross_platform: 通用模式（已在全局知识库确认，或本质是架构问题）
    - prompt_side: 标记/prompt 格式问题（AI 未遵循格式指令）
    """

    # 已知的 CoT/思考面板特征（会被 global + profile 动态扩展）
    BASE_COT_INDICATORS = [
        "已思考", "深度思考", "思考过程", "思考中",
        "我们被要求", "我们需要构建", "我们需要写", "我们需要回答",
        "根据搜索结果",  # 思考块常以此开头但后面跟着规划而非正文
    ]

    # 内容截断特征
    TRUNCATION_INDICATORS = [
        # 结尾不完整：以非标点结尾且非列表项
    ]

    @staticmethod
    def analyze(raw_text, extracted_content, platform, profile=None):
        """分析提取失败原因。

        返回: {"failure_type": str, "evidence": str, "severity": "high"|"medium"|"low",
                "suggestion": str, "adaptable": bool, "scope": "platform_specific"|"cross_platform"|"prompt_side"}
        如果内容合格返回 None。
        """
        if not extracted_content:
            return _diagnose_no_content(raw_text, platform)

        # 1. CoT 干扰检测（profile 扩展关键词）
        # 合并 COT 检测关键词：BASE + 全局已推广 + 本地已学
        cot_keywords = KnowledgePropagator.get_platform_cot_patterns(platform)

        head = extracted_content.strip()[:300]
        matched_cot = [kw for kw in cot_keywords if kw in head]
        if matched_cot:
            # 判断 scope：命中的关键词是否已在全局知识库中？
            global_keywords = set(GlobalKnowledge.get_cot_patterns())
            new_keywords = [kw for kw in matched_cot if kw not in global_keywords]
            scope = "cross_platform" if not new_keywords else "platform_specific"
            return {
                "failure_type": "cot_interference",
                "evidence": f"内容前300字符命中CoT关键词: {matched_cot}",
                "severity": "high",
                "suggestion": f"跳过标记间CoT内容，取最后一个标记之后的正文；追加关键词到平台档案",
                "adaptable": True,
                "cot_keywords_matched": matched_cot,
                "scope": scope,
                "_new_keywords": new_keywords,
            }

        # 2. 内容截断检测（跨平台通用问题——AI 仍在生成中）
        tail = extracted_content.strip()[-100:]
        if _looks_truncated(tail):
            return {
                "failure_type": "content_truncated",
                "evidence": f"末尾疑似截断: ...{tail[-50:]}",
                "severity": "medium",
                "suggestion": "AI可能仍在生成中，延长等待时间",
                "adaptable": True,
                "scope": "cross_platform",
            }

        # 3. 低质量检测：内容极短但标记足够（prompt 侧——AI 未遵循格式）
        if len(extracted_content) < 500:
            return {
                "failure_type": "low_quality",
                "evidence": f"内容仅{len(extracted_content)}字符",
                "severity": "medium",
                "suggestion": "标记对之间内容过短，尝试取最后一个标记之后的内容",
                "adaptable": False,
                "scope": "prompt_side",
            }

        return None  # 内容合格


def _diagnose_no_content(raw_text, platform):
    """诊断完全无提取内容的情况。"""
    if not raw_text or len(raw_text) < 200:
        return {
            "failure_type": "page_not_loaded",
            "evidence": f"页面仅{len(raw_text) if raw_text else 0}字符",
            "severity": "high",
            "suggestion": "页面可能未完成加载或已被重定向",
            "adaptable": False,
            "scope": "platform_specific",
        }
    return {
        "failure_type": "marker_missing",
        "evidence": f"页面{len(raw_text)}字符但未找到有效标记对",
        "severity": "high",
        "suggestion": "AI可能尚未输出标记，等待更多内容生成",
        "adaptable": False,
        "scope": "prompt_side",
    }


def _looks_truncated(tail):
    """检测内容是否被截断（末尾不自然）。"""
    # 正常结尾标点
    natural_ends = {"。", "）", "》", "\"", "'", "]", "}", "…", "—"}
    # 截断特征：以非自然标点结尾，且最后一段是短句
    if not tail:
        return True
    last_char = tail.strip()[-1] if tail.strip() else ""
    if last_char and last_char not in natural_ends and last_char.isalpha():
        return True
    # 以逗号、分号结尾通常表示未完成
    if last_char in {"，", "；", "、", "：", ",", ";", ":"}:
        return True
    return False


# ============================================================
# ExtractionProfile —— 每平台提取策略档案
# ============================================================

class ExtractionProfile:
    """每平台独立的提取策略档案，存储在 profiles/{platform}_extraction.json。

    自进化：每次诊断出新的失败模式后，更新策略并持久化。
    """

    def __init__(self, platform):
        _ensure_profiles_dir()
        self.platform = platform
        self.path = os.path.join(PROFILES_DIR, f"{platform}_extraction.json")
        self.data = self._load()

    def _default(self):
        return {
            "platform": self.platform,
            "version": 1,
            "cot_patterns": [],
            "marker_placement": "unknown",  # before_thinking | after_thinking | inline
            "stable_threshold": 3,
            "fallback_strategy": "post_last_marker",  # post_last_marker | last_pair | text_after_first
            "evolution_log": [],
            "created_at": datetime.now(CST).isoformat(),
        }

    def _load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                data.setdefault("evolution_log", [])
                data.setdefault("cot_patterns", [])
                data.setdefault("version", 1)
                return data
            except (json.JSONDecodeError, IOError):
                pass
        return self._default()

    def save(self):
        self.data["updated_at"] = datetime.now(CST).isoformat()
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def get_cot_patterns(self):
        """获取该平台全部 CoT 检测关键词（基础 + 全局已推广 + 本地已学）。"""
        return KnowledgePropagator.get_platform_cot_patterns(self.platform)

    def get_stable_threshold(self):
        return self.data.get("stable_threshold", 3)

    def get_marker_placement(self):
        return self.data.get("marker_placement", "unknown")

    def get_fallback_strategy(self):
        return self.data.get("fallback_strategy", "post_last_marker")

    def learn_cot_keyword(self, keyword):
        """学到一个新的 CoT 关键词。"""
        if keyword not in self.data["cot_patterns"]:
            self.data["cot_patterns"].append(keyword)
            self.data["version"] += 1
            self._log_evolution("add_cot_keyword", f"追加CoT关键词: {keyword}")
            self.save()

    def learn_marker_placement(self, placement):
        """学到标记放置模式。"""
        if self.data["marker_placement"] != placement:
            old = self.data["marker_placement"]
            self.data["marker_placement"] = placement
            self.data["version"] += 1
            self._log_evolution("update_marker_placement", f"标记位置: {old} → {placement}")
            self.save()

    def learn_stable_threshold(self, threshold):
        """调整稳定性阈值。"""
        old = self.data["stable_threshold"]
        if old != threshold:
            self.data["stable_threshold"] = threshold
            self.data["version"] += 1
            self._log_evolution("adjust_stable_threshold", f"稳定阈值: {old} → {threshold}")
            self.save()

    def learn_fallback_strategy(self, strategy):
        """更新兜底策略。"""
        if self.data["fallback_strategy"] != strategy:
            old = self.data["fallback_strategy"]
            self.data["fallback_strategy"] = strategy
            self.data["version"] += 1
            self._log_evolution("update_fallback", f"兜底策略: {old} → {strategy}")
            self.save()

    def _log_evolution(self, action, detail):
        self.data["evolution_log"].append({
            "time": datetime.now(CST).isoformat(),
            "action": action,
            "detail": detail,
            "version_after": self.data["version"],
        })

    def get_summary(self):
        return {
            "platform": self.platform,
            "version": self.data["version"],
            "cot_patterns_count": len(self.data["cot_patterns"]),
            "marker_placement": self.data["marker_placement"],
            "evolutions": len(self.data["evolution_log"]),
        }


# ============================================================
# PollingProfile —— 每平台轮询策略
# ============================================================

class PollingProfile:
    """每平台自适应轮询策略，存储在同平台提取档案中。"""

    def __init__(self, platform):
        _ensure_profiles_dir()
        self.platform = platform
        self.path = os.path.join(PROFILES_DIR, f"{platform}_extraction.json")
        self.extraction_profile = ExtractionProfile(platform)
        self.data = self.extraction_profile.data  # 共享同一个文件

    def _default_polling(self):
        return {
            "interval_sec": 2.0,
            "max_wait_sec": 180,
            "growth_rate_cps": 0,        # 平均内容增长速度（字符/秒），0=未测量
            "stability_rounds": 2,        # 连续稳定轮数才认定完成
            "samples": [],                # 最近的采样记录
        }

    def _ensure_polling_section(self):
        if "polling" not in self.data:
            self.data["polling"] = self._default_polling()
        self.data["polling"].setdefault("samples", [])

    def get_interval(self):
        self._ensure_polling_section()
        return self.data["polling"].get("interval_sec", 2.0)

    def get_stability_rounds(self):
        self._ensure_polling_section()
        return self.data["polling"].get("stability_rounds", 2)

    def get_max_wait(self):
        self._ensure_polling_section()
        return self.data["polling"].get("max_wait_sec", 180)

    def record_sample(self, elapsed_sec, content_len):
        """记录一次轮询采样，用于计算内容增长速度。"""
        self._ensure_polling_section()
        samples = self.data["polling"]["samples"]
        samples.append({
            "time": datetime.now(CST).isoformat(),
            "elapsed_sec": elapsed_sec,
            "content_len": content_len,
        })
        # 只保留最近 30 条
        if len(samples) > 30:
            self.data["polling"]["samples"] = samples[-20:]

        # 从样本推算增长速度
        if len(samples) >= 3:
            first = samples[0]
            last = samples[-1]
            dt = last["elapsed_sec"] - first["elapsed_sec"]
            dl = last["content_len"] - first["content_len"]
            if dt > 0 and dl > 0:
                self.data["polling"]["growth_rate_cps"] = round(dl / dt, 1)

        self.extraction_profile.save()

    def adapt_interval(self):
        """根据历史增长速度自适应调整轮询间隔。"""
        self._ensure_polling_section()
        rate = self.data["polling"].get("growth_rate_cps", 0)
        if rate <= 0:
            return 2.0
        if rate > 100:
            new_interval = 2.0
        elif rate > 30:
            new_interval = 3.0
        else:
            new_interval = 5.0

        old = self.data["polling"]["interval_sec"]
        if old != new_interval:
            self.data["polling"]["interval_sec"] = new_interval
            self.extraction_profile._log_evolution(
                "adapt_interval",
                f"轮询间隔: {old}s → {new_interval}s (增速{rate}cps)"
            )
            self.extraction_profile.save()

    def get_no_closing_threshold(self):
        """无结尾标记时的稳定轮数阈值（默认为10，随经验调整）。"""
        self._ensure_polling_section()
        return self.data["polling"].get("no_closing_threshold", 10)

    def update_closing_marker_reliability(self, had_closing):
        """进化：根据AI是否输出结尾标记，调整无标记等待阈值。
        - AI 不输出结尾标记 → 降低阈值（下次少等），最低5
        - AI 输出结尾标记 → 恢复阈值（正常等待），最高10
        """
        self._ensure_polling_section()
        old = self.data["polling"].get("no_closing_threshold", 10)
        if had_closing:
            new = min(10, old + 1)
        else:
            new = max(5, old - 2)
        if old != new:
            self.data["polling"]["no_closing_threshold"] = new
            self.extraction_profile._log_evolution(
                "closing_marker_reliability",
                f"无标记阈值: {old}轮 → {new}轮 ({'有结尾标记' if had_closing else '无结尾标记'})"
            )
            self.extraction_profile.save()

    def adapt_stability_rounds(self):
        """根据增速调整稳定性确认轮数。

        规则：
        - 增速 > 100 cps → 2 轮（快，可能波动）
        - 增速 30-100 → 2 轮
        - 增速 < 30 → 1 轮（慢，波动小，一轮稳定即可）
        """
        self._ensure_polling_section()
        rate = self.data["polling"].get("growth_rate_cps", 0)
        if rate <= 0:
            return 2
        if rate > 30:
            return 2
        return 1

    def get_summary(self):
        self._ensure_polling_section()
        p = self.data["polling"]
        return {
            "interval": p.get("interval_sec", 2.0),
            "growth_rate_cps": p.get("growth_rate_cps", 0),
            "samples": len(p.get("samples", [])),
        }


# ============================================================
# StrategyAdapter —— 根据诊断生成策略适配
# ============================================================

class StrategyAdapter:
    """根据 FailureAnalyzer 的诊断结果，更新 ExtractionProfile。"""

    @staticmethod
    def adapt(profile, diagnosis):
        """根据诊断结果进化提取策略。

        profile: ExtractionProfile 实例
        diagnosis: FailureAnalyzer.analyze() 的输出
        返回: 进化后的策略变更摘要
        """
        if not diagnosis or not diagnosis.get("adaptable"):
            return None

        changes = []
        failure_type = diagnosis["failure_type"]
        scope = diagnosis.get("scope", "platform_specific")

        if failure_type == "cot_interference":
            # 1. 追加命中的 CoT 关键词到档案
            for kw in diagnosis.get("cot_keywords_matched", []):
                if kw not in profile.data["cot_patterns"]:
                    profile.learn_cot_keyword(kw)
                    changes.append(f"追加CoT关键词: {kw} (scope={scope})")

            # 2. 更新标记放置模式
            if "after_thinking" not in str(profile.data.get("marker_placement")):
                profile.learn_marker_placement("after_thinking")
                changes.append("标记位置模式 → after_thinking")

            # 3. 更新兜底策略
            if profile.data.get("fallback_strategy") != "post_last_marker":
                profile.learn_fallback_strategy("post_last_marker")
                changes.append("兜底策略 → post_last_marker")

        elif failure_type == "content_truncated":
            # 截断：增加稳定性确认轮数
            current = profile.data.get("stable_threshold", 3)
            profile.learn_stable_threshold(min(current + 1, 5))
            changes.append(f"稳定阈值: {current} → {current + 1}")

        summary = {"failure_type": failure_type, "scope": scope,
                   "changes": changes, "profile_version": profile.data["version"]}

        # 4. 触发跨平台知识传播
        KnowledgePropagator.after_adapt(profile.platform, diagnosis, changes)

        return summary


# ============================================================
# 便捷函数
# ============================================================

def load_or_create_profile(platform):
    """加载或创建平台的提取档案。"""
    return ExtractionProfile(platform)


def load_or_create_polling(platform):
    """加载或创建平台的轮询档案。"""
    return PollingProfile(platform)


def get_active_cot_patterns(platform):
    """获取某平台的完整 CoT 检测关键词列表（基础 + 已学）。"""
    profile = ExtractionProfile(platform)
    return profile.get_cot_patterns()


if __name__ == "__main__":
    import sys as _sys
    _sys.stdout.reconfigure(encoding='utf-8')

    # 自测
    print("=== FailureAnalyzer ===")
    fake_raw = "页面内容..." * 100
    fake_cot = "深度思考我们被要求写一个关于Python的答复。需要根据搜索结果..." + "正文" * 50
    diag = FailureAnalyzer.analyze(fake_raw, fake_cot, "deepseek")
    print(f"CoT检测: {diag}")

    print("\n=== ExtractionProfile ===")
    profile = ExtractionProfile("deepseek")
    print(f"加载档案 v{profile.data['version']}, CoT关键词: {profile.get_cot_patterns()[:5]}...")
    profile.learn_cot_keyword("深度思考")
    print(f"进化后 v{profile.data['version']}")

    print("\n=== PollingProfile ===")
    polling = PollingProfile("deepseek")
    polling.record_sample(10, 3000)
    polling.record_sample(20, 5500)
    polling.record_sample(30, 8200)
    print(f"增速: {polling.data['polling']['growth_rate_cps']} cps")
    print(f"自适应间隔: {polling.adapt_interval()}s")
    print(f"摘要: {polling.get_summary()}")

    print("\n=== StrategyAdapter ===")
    profile2 = ExtractionProfile("deepseek")
    diag2 = FailureAnalyzer.analyze(fake_raw, fake_cot, "deepseek")
    result = StrategyAdapter.adapt(profile2, diag2)
    print(f"适配结果: {result}")
    print(f"档案版本: {profile2.data['version']}")
    print(f"进化日志: {profile2.data['evolution_log']}")
