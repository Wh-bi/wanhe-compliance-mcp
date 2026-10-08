#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
mcp_compliance_server.py —— 中文内容合规检查 MCP Server（零外部依赖）
万和 AI 工具箱 · MIT License · https://wanhetools.top/compliance-check

=======================================================================
  商业设计（重要 —— 这是 2026-10-07 重构的核心）
=======================================================================
  免费版（本文件）：**规则子集内嵌**，完全离线，但有**免费额度**
      · 单次检查最多 2000 字符
      · 每个进程会话最多 30 次检查
      · 覆盖高频规则（广告法绝对化用语/医疗功效/违规用语等 12 条）
      ⇒ 目的是「让 Agent 和用户真正用起来」，不是「把付费资产送掉」

  云端版（付费）：全量 21 条规则 + AI 标识判定 + 内容合规 + 17 项问卷
      + 多法规交叉 + 结果按位置去重 + 规则库云端持续更新
      ⇒ 通过 HTTP 402 按次计费，或订阅
      ⇒ 地址：https://wanhetools.top/api/a2m/demo/a2m/resource

  ★ 为什么不是「免费全给」：我们免费全给过一次（SkillHub 免费技能，
    downloads 32 / installs 0），结果是既没收入也没人用。
    免费额度 + 明确升级路径，才能同时拿到「使用」和「转化」。
=======================================================================

零依赖设计：有官方 mcp/fastmcp 库时用官方实现；没有则降级为内置
stdio JSON-RPC，功能完全相同 ⇒ 用户连 pip install 都不需要。
"""

import json
import os
import re
import sys
import traceback
import urllib.error
import urllib.request

SERVER_NAME = "wanhe-compliance"
SERVER_VERSION = "1.1.0"

# ---------------------------------------------------------------------------
# 免费额度（可调）
# ---------------------------------------------------------------------------
FREE_MAX_CHARS = 2000      # 单次检查最大字符数
FREE_MAX_CALLS = 30        # 每个会话最大检查次数

SESSION = {"calls": 0}

CLOUD_ENDPOINT = "https://wanhetools.top/api/a2m/demo/a2m/resource"
UPGRADE_HINT = (
    "\n\n---\n"
    "免费版覆盖高频规则。以下能力在云端版：\n"
    "· 全量 21 条规则（含金融收益承诺、教育效果承诺、贬低同行、虚假紧迫感等）\n"
    "· AI 生成内容标识判定（《AI 生成合成内容标识办法》第4/5条 + GB 45438-2025）\n"
    "· 内容合规检查（违法有害信息、个人信息收集、未成年人保护）\n"
    "· 17 项组织级合规自查问卷（覆盖率评分 + 待整改清单）\n"
    "· 结果按位置去重 · 多法规交叉判定 · 规则库云端持续更新\n"
    "调用方式：POST " + CLOUD_ENDPOINT + "\n"
    "首次返回 HTTP 402 + Payment-Needed 账单头，付款后携带 Payment-Proof 重试即可。\n"
    "¥0.01/次 或 订阅。说明：https://wanhetools.top/compliance-check"
)

# ---------------------------------------------------------------------------
# 免费规则子集（内嵌；从完整引擎里精选高频 12 条）
# 结构：(正则, 类型, 依据, 建议)
# ---------------------------------------------------------------------------
FREE_RULES = [
    (r"最[^，。；！？、\s]{0,3}", "绝对化用语",
     "《广告法》第9条第(三)项：不得使用“国家级”“最高级”“最佳”等用语",
     "删去最字表述，改为可验证的具体描述"),
    (r"(全网|全国|全球|行业内)(最|第一|领先|唯一)", "绝对化用语",
     "《广告法》第9条第(三)项", "删去范围性绝对表述"),
    (r"第一|No\.?1|TOP\s?1|排名第一|销量第一|全网第一", "绝对化用语",
     "《广告法》第9条第(三)项", "删去排名表述，或补可查证第三方数据与统计口径"),
    (r"国家级|世界级|全球级|国际级|免检|特供|专供|国家免检", "违规用语",
     "《广告法》第9条第(二)(三)项", "无法定依据时删去"),
    (r"100%|百分百|绝对(?!化)|彻底|完全无|零风险|无任何副作用", "承诺性用语",
     "《广告法》第9条、第28条（虚假广告）", "改为真实可验证的表述，或删去"),
    (r"(0|零|无)(添加|糖|脂肪|卡路里|防腐剂|香精|色素)", "食品绝对化",
     "《广告法》第9条 + 《食品安全法》标签规定",
     "“0添加/无添加”需符合国家标准定义，否则改为“未添加XX”并说明依据"),
    (r"(治疗|治愈|根治|疗效|药效|包治|秒杀.{0,4}病)", "医疗功效宣传",
     "《广告法》第17条：除医疗、药品、医疗器械广告外，禁止涉及疾病治疗功能",
     "非医疗类产品必须删去全部疾病治疗表述"),
    (r"(适用于|专治|主治|针对|用于|可治|能治|缓解|改善|调理)[^。；！？\n]{0,12}"
     r"(高血压|糖尿病|冠心病|癌|肿瘤|失眠|鼻炎|胃炎|肝炎|肾病|痛风|哮喘|"
     r"抑郁症|颈椎病|关节炎|近视|胃病)",
     "医疗功效·功效声明+疾病名同现",
     "《广告法》第17条、第18条：保健食品广告不得涉及疾病预防、治疗功能",
     "非医疗/药品/器械类商品，不得将功效声明与疾病名同时使用"),
    (r"(替代|代替|取代)[^。；！？\n]{0,6}"
     r"(药物|药品|降糖药|降压药|胰岛素|抗生素|激素)|"
     r"(停用|停服|停药|不用再吃)[^。；！？\n]{0,8}(药|胰岛素|治疗)?",
     "替代药物/停药暗示",
     "《广告法》第17条、第18条；《药品管理法》关于药品广告的规定",
     "严禁暗示可替代药物治疗；必须删去"),
    (r"(增强|提高|提升)(免疫|抵抗力|免疫力)", "保健功效宣传",
     "《广告法》第17条、第18条（保健食品广告禁止性规定）",
     "保健食品须标注“本品不能代替药物”；普通食品不得宣称保健功能"),
    (r"(纯天然|纯手工|古法|祖传|秘制).{0,4}(配方|工艺|制作)?", "易被认定虚假的表述",
     "《广告法》第28条（虚假广告）",
     "需有可验证依据；无法证明时改为客观描述"),
    (r"(消炎|杀菌|抗炎|排毒|祛湿|壮阳|丰胸|瘦身|减肥)",
     "功效宣传（高风险）", "《广告法》第17条、第18条",
     "普通商品不得宣称上述功效；需按具体法规逐项核对"),
]

# 清理：把“免责声明”类文档里为解释而写的中文引号去掉（避免被守卫误报）
# （上面规则的“依据”字段里保留了法条原文引号，那是必要内容）

CN_QUOTE_MAP = {"\u201c": "", "\u201d": ""}


def _normalize(s):
    for k, v in CN_QUOTE_MAP.items():
        s = s.replace(k, v)
    return s


# ---------------------------------------------------------------------------
# 法条引用识别（2026-10-07 新增，与沙箱引擎同步）
# ---------------------------------------------------------------------------
# 合规写作必然引用法条，而法条原文里就包含被禁用的词
#   ——「《广告法》第9条禁止使用免检、特供等用语」是引用，不是违规使用。
_CITE_QUOTES = "\u300c\u300d\u300e\u300f\u201c\u201d\"\'\u300a\u300b\u3010\u3011\u3014\u3015<>"
_CITE_MARKERS = (
    "等用语", "等表述", "等词", "等字样", "等说法", "等措辞",
    "这类", "此类", "所谓", "称为", "叫做",
    "禁止使用", "不得使用", "禁止出现", "不得出现", "禁用", "违禁",
)
_LAW_NAME = re.compile(r"\u300a[^\u300b]{2,30}(法|办法|规定|条例|标准|细则|通知|意见)\u300b")
_CLAUSE = re.compile(r"第\s*[0-9\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341\u767e]+\s*(条|款|项)|GB\s*\d+")


def _is_citation(text, start, end):
    """判断命中是否处于"引用/元语言"语境"""
    l = text[start - 1] if start > 0 else ""
    r = text[end] if end < len(text) else ""
    # 注意：必须排除空串 —— `"" in "任意字符串"` 在 Python 里返回 True
    if (l and l in _CITE_QUOTES) or (r and r in _CITE_QUOTES):
        return True
    win = text[max(0, start - 14):min(len(text), end + 14)]
    for mk in _CITE_MARKERS:
        i = win.find(mk)
        if i >= 0:
            mk_pos = max(0, start - 14) + i
            dist = min(abs(mk_pos - end), abs(mk_pos + len(mk) - start))
            if dist <= 8:
                return True
    s = 0
    for x in ("\u3002", "\uff1b", "\uff01", "\uff1f", "\n"):
        j = text.rfind(x, 0, start)
        if j > s:
            s = j + 1
    e = len(text)
    for x in ("\u3002", "\uff1b", "\uff01", "\uff1f", "\n"):
        j = text.find(x, end)
        if j >= 0:
            e = min(e, j)
    sent = text[s:e]
    return bool(_LAW_NAME.search(sent) or _CLAUSE.search(sent))


def split_citations(issues, text):
    kept, suppressed = [], []
    for it in issues:
        m = re.search(r"第\s*(\d+)\s*字符", it.get("position", ""))
        if not m:
            kept.append(it)
            continue
        st = int(m.group(1)) - 1
        en = st + len(it.get("matched") or "")
        if _is_citation(text, st, en):
            it2 = dict(it)
            it2["suppressed_reason"] = "引用法规/讨论法条语境"
            suppressed.append(it2)
        else:
            kept.append(it)
    return kept, suppressed


def _dedupe(issues):
    """同一位置被多条命中时只保留最长的一条"""
    def pos(it):
        m = re.search(r"\d+", it.get("position", ""))
        return int(m.group(0)) if m else 0
    issues = sorted(issues, key=lambda x: (pos(x), -len(x.get("matched") or "")))
    kept, used = [], []
    for it in issues:
        p = pos(it)
        span = max(1, len(it.get("matched") or ""))
        if any(not (p + span <= s or p >= s + ln) for s, ln in used):
            continue
        kept.append(it)
        used.append((p, span))
    return kept


def check_text(text):
    """免费规则子集检查（离线）"""
    issues = []
    for rule in FREE_RULES:
        rx, typ, basis, fix = rule
        try:
            for m in re.finditer(rx, text):
                issues.append({
                    "type": typ,
                    "position": "第 " + str(m.start() + 1) + " 字符起",
                    "matched": m.group(0),
                    "basis": basis,
                    "suggestion": fix,
                })
        except re.error:
            continue
    issues = _dedupe(issues)
    # 引用识别（2026-10-07，与沙箱引擎同步）：
    # 把「引用法规/讨论法条」与「真的违规使用」分开 —— 合规写作必然引用法条
    issues, _suppressed = split_citations(issues, text)
    counts = {"risk": len(issues), "warn": 0, "info": 0, "total": len(issues)}
    return {
        "ok": True,
        "engine": "wanhe-compliance-rules-free-v1",
        "tier": "free",
        "verdict": "存在高风险问题" if issues else "未发现规则覆盖的问题",
        "summary": ("共 " + str(len(issues)) + " 条（高风险 " + str(len(issues))
                    + " · 待确认 0 · 提示 0）") if issues else
                   "未发现免费规则覆盖的问题（不等于完全合规）",
        "counts": counts,
        "issues": issues,
        "suppressed": _suppressed,
        "coverage": {
            "rules_in_free": len(FREE_RULES),
            "rules_in_cloud": 21,
            "note": "免费版覆盖高频规则；云端版含全量规则与 AI 标识判定",
        },
    }


def check_ai_label_free(text):
    """免费版只做基础提示，完整判定在云端"""
    hints = [
        (r"AI\s*(生成|绘制|创作|写作|辅助|合成)", "AI 生成/合成表述"),
        (r"AIGC", "AIGC"),
        (r"人工智能(生成|合成|创作)", "人工智能生成"),
        (r"文生图|文生视频|数字人|深度合成|换脸|AI\s*换声", "合成内容形态"),
        (r"generated by AI|AI-generated|synthetic media", "英文 AI 生成表述"),
    ]
    hits = []
    for rx, label in hints:
        for m in re.finditer(rx, text, re.I):
            hits.append({"type": label, "matched": m.group(0),
                         "position": "第 " + str(m.start() + 1) + " 字符起"})
    return {
        "ok": True,
        "tier": "free",
        "detected_ai_mentions": hits,
        "note": ("免费版仅检测文本中的 AI 表述。完整判定（是否需要显式标识、"
                 "是否需写入隐式元数据标识、依据《人工智能生成合成内容标识办法》"
                 "第4/5条与 GB 45438-2025）在云端版。"),
        "reminder": ("显式标识与隐式标识是两件事，缺一不可：只加文字标识、"
                     "没写文件元数据，仍算不合规。"),
    }


# ---------------------------------------------------------------------------
# MCP 工具定义
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 英文规则（免费版内嵌 12 条 · 与沙箱英文引擎同源，取高频项）
# ---------------------------------------------------------------------------
# 为什么内嵌：MCP 包要能独立发布，不能依赖 sandbox 目录。
# 规则来源：sandbox/compliance_engine_en.py（该引擎有 28/28 回归测试）。
# 边界同中文：免费给高频 12 条，完整 18 条 + 图片审计 + 问卷走云端。

FREE_RULES_EN = [
    # ── AI 披露（EU AI Act Art.50 语境）
    (r"\b(deep\s?fake|deepfake)s?\b",
     "AI disclosure: deep fake",
     "EU AI Act Art.50(4): deployers of deep fakes must disclose that content "
     "is artificially generated or manipulated",
     "Add a clear visible disclosure and machine-readable provenance "
     "where possible", "risk"),
    (r"\b(AI|artificial intelligence|synthetic)\b[^.]{0,120}"
     r"\b(without|no|lacking|missing)\b[^.]{0,60}"
     r"\b(disclosure|label|labell?ing|marking|provenance|content credentials|"
     r"metadata|watermark)\b",
     "AI disclosure: synthetic content unmarked",
     "EU AI Act Art.50(2): synthetic content must be marked in a "
     "machine-readable format",
     "Add machine-readable marking (e.g. C2PA Content Credentials) and a "
     "visible label", "risk"),
    (r"\bchat\s?bots?\b[^.]{0,140}\b(does not|doesn't|do not|don't|without|no|"
     r"fails to)\b[^.]{0,60}\b(tell|inform|notify|disclose|reveal)\b",
     "AI disclosure: chatbot interaction not disclosed",
     "EU AI Act Art.50(1): users must be informed they interact with an AI system",
     "Add an upfront notice that the user is interacting with an AI system",
     "risk"),

    # ── 夸大 / 绝对化
    (r"\b(the best|the cheapest|the greatest|number one|#1|world'?s best|"
     r"unbeatable|unmatched|the most advanced)\b",
     "Unsubstantiated superlative",
     "EU: Unfair Commercial Practices Directive 2005/29/EC Annex I; "
     "US: FTC Guides on endorsements",
     "Replace with a specific verifiable claim, or remove", "risk"),
    (r"\b(100\s?%|guaranteed|risk[\s-]?free|zero risk|no risk|"
     r"absolutely safe|perfectly safe)\b",
     "Absolute / guarantee claim",
     "EU: UCPD 2005/29/EC; US: FTC Act Section 5",
     "Only use with substantiation; otherwise rephrase", "risk"),
    (r"\b(forever|permanently valid|permanently available|"
     r"never\s+(be\s+)?(expires?|withdrawn|ends?|revoked|changed)|"
     r"eternal(ly)?\s+guarantee)\b",
     "Indefinite promise",
     "EU: UCPD 2005/29/EC (misleading commercial practices)",
     "State the actual duration and conditions", "warn"),

    # ── 健康功效
    (r"\b(cures?|heals?|treats?|reverses?)\b[^.]{0,40}\b"
     r"(diabetes|cancer|heart disease|hypertension|high blood pressure|"
     r"asthma|arthritis|depression|insomnia|alzheimer'?s?)\b",
     "Health claim: disease treatment",
     "EU: Regulation (EC) No 1924/2006; US: FDA (drug claims require approval)",
     "Remove disease-treatment claims from non-medicinal products", "risk"),
    (r"\b(stop|instead of|replace)\b[^.]{0,40}\b(taking )?(your )?"
     r"(medication|medicine|prescription|pills?|drugs?)\b",
     "Health claim: substitute for medication",
     "EU: Regulation (EC) No 1924/2006; national medicines advertising rules",
     "Never suggest replacing prescribed treatment", "risk"),

    # ── 金融承诺
    (r"\bguaranteed\b[^.]{0,30}\b(returns?|profit|income|yield|roi)\b",
     "Financial claim: guaranteed returns",
     "EU: MiFID II / PRIIPs; US: SEC / FINRA rules on performance claims",
     "Remove any guarantee of investment performance", "risk"),
    (r"\b(can\s?not|cannot|can'?t)\s+lose\b",
     "Financial claim: cannot lose",
     "EU: MiFID II; US: FINRA 2210 (misleading statements)",
     "Remove absolute loss-prevention claims", "risk"),
    (r"\b(risk[\s-]?free|zero risk|no risk)\b[^.]{0,40}"
     r"\b(invest|investment|trading|returns?|profit)\b",
     "Financial claim: risk-free investment",
     "EU: MiFID II; US: SEC Rule 10b-5 / FINRA 2210",
     "Describe actual risks; remove risk-free framing", "risk"),

    # ── 漂绿
    (r"\b(100\s?%|fully|completely|totally)\b[^.]{0,24}"
     r"\b(eco[\s-]?friendly|environmentally friendly|sustainable|green|"
     r"carbon neutral|climate neutral)\b",
     "Green claim: absolute environmental claim",
     "EU: UCPD 2005/29/EC as amended by Directive (EU) 2024/825 "
     "(substantiation required)",
     "Substantiate with verifiable data or narrow the claim", "risk"),
]

# 英文引用识别（与沙箱英文引擎同源的四类正面证据）
_EN_CITE_QUOTES = "\u201c\u201d\u2018\u2019\u300c\u300d\u300e\u300f\"'<>"
_EN_CITE_MARKERS = (
    "such as", "e.g.", "for example", "including", "referred to as",
    "known as", "must not", "shall not", "prohibited", "not permitted",
    "is prohibited", "is banned", "unlawful", "illegal", "flags", "detect",
    "check", "identifies", "example", "claims like", "terms such",
)
_EN_META_MARKERS = (
    "checklist", "flags ", "detects ", "checks for", "identifies ",
    "scanner", "audit tool", "rule engine", "this tool", "the tool ",
    "guidance says", "guidelines", "handbook", "policy states",
    "prohibited terms", "banned words",
)
_EN_PROHIBITION_MARKERS = (
    "must not be described as", "shall not be described as",
    "must be substantiated", "must not claim", "shall not claim",
    "must not use", "shall not use", "must not state", "shall not state",
    "terms such as", "words such as", "claims such as", "phrases such as",
)
_EN_LAW = re.compile(
    r"\b(Article|Art\.|Section|Sec\.|Clause|Recital|Regulation|Directive|"
    r"GDPR|CCPA|FTC|UCPD|MiFID)\s*\(?\s*\d", re.I)


def _en_is_citation(text, start, end):
    """英文引用识别 —— 只依赖四类**正面证据**。

    ★ 重要教训（2026-10-08）：**"否定"不能作为引用信号**。
      承诺性违规天然含否定（cannot lose / never withdrawn / does not disclose），
      若把它当引用信号，会把该报的违规全部抑制掉。
      这是我们在英文引擎上写错 3 轮才改对的。
    """
    l = text[start - 1] if start > 0 else ""
    r = text[end] if end < len(text) else ""
    # 必须显式排除空串（`"" in "任意字符串"` 在 Python 里返回 True）
    if (l and l in _EN_CITE_QUOTES) and (r and r in _EN_CITE_QUOTES):
        return True, "wrapped in quotes"
    if (l and l in _EN_CITE_QUOTES) or (r and r in _EN_CITE_QUOTES):
        return True, "adjacent to quote mark"

    win = text[max(0, start - 20):min(len(text), end + 20)].lower()
    for mk in _EN_CITE_MARKERS:
        i = win.find(mk)
        if i >= 0:
            mk_pos = max(0, start - 20) + i
            dist = min(abs(mk_pos - end), abs(mk_pos + len(mk) - start))
            if dist <= 80:
                return True, "citation marker: " + mk

    wide = text[max(0, start - 200):min(len(text), end + 200)].lower()
    for mk in _EN_META_MARKERS:
        if mk in wide:
            return True, "meta-discussion marker: " + mk
    for mk in _EN_PROHIBITION_MARKERS:
        if mk in wide:
            return True, "prohibition citation: " + mk

    s = 0
    for x in (".", "!", "?", ";", "\n"):
        j = text.rfind(x, 0, start)
        if j > s:
            s = j + 1
    e = len(text)
    for x in (".", "!", "?", ";", "\n"):
        j = text.find(x, end)
        if j >= 0:
            e = min(e, j)
    if _EN_LAW.search(text[s:e]):
        return True, "same sentence cites a law/regulation"
    return False, ""


def _lang_of(text):
    """自动判定语言：含中日韩字符 ⇒ zh，否则 en"""
    if re.search(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]", text):
        return "zh"
    return "en"


def check_text_en(text):
    """英文检查（结构与 check_text 对齐）"""
    issues = []
    for rx, typ, basis, suggestion, sev in FREE_RULES_EN:
        for m in re.finditer(rx, text, re.I):
            issues.append({
                "type": typ,
                "matched": m.group(0),
                "position": "char " + str(m.start() + 1),
                "_start": m.start(),
                "basis": basis,
                "suggestion": suggestion,
                "severity": sev,
            })
    # 去重（同位置留最长）
    by = {}
    for it in issues:
        k = it["_start"]
        if k not in by or len(it["matched"]) > len(by[k]["matched"]):
            by[k] = it
    issues = sorted(by.values(), key=lambda x: x["_start"])

    kept, suppressed = [], []
    for it in issues:
        st = it["_start"]
        is_c, why = _en_is_citation(text, st, st + len(it["matched"]))
        if is_c:
            it2 = dict(it)
            it2["suppressed_reason"] = why
            suppressed.append(it2)
        else:
            kept.append(it)

    for it in kept + suppressed:
        it.pop("_start", None)

    n_risk = sum(1 for i in kept if i["severity"] == "risk")
    n_warn = sum(1 for i in kept if i["severity"] == "warn")
    return {
        "ok": True,
        "engine": "wanhe-compliance-rules-free-en-v1",
        "tier": "free",
        "lang": "en",
        "verdict": ("High-risk issues found" if n_risk else
                    ("Review recommended" if n_warn else "No issues found")),
        "summary": (str(len(kept)) + " issue(s) (high risk " + str(n_risk) +
                    " / review " + str(n_warn) + ")"),
        "counts": {"risk": n_risk, "warn": n_warn, "info": 0, "total": len(kept)},
        "issues": kept,
        "suppressed": suppressed,
        "suppressed_note": ("Items above appear in a citation / meta-discussion "
                            "context and were not counted as violations.")
        if suppressed else "",
        "free_rules": len(FREE_RULES_EN),
        "disclaimer": ("Deterministic rule engine, not legal advice. Absence of "
                       "findings does not mean the content is compliant."),
    }


TOOLS = [
    {
        "name": "check_content",
        "description": (
            "检查一段中文内容的广告法合规风险，返回逐条问题清单："
            "问题类型 / 原文位置 / 命中文本 / 依据法条 / 修改建议。"
            "覆盖：绝对化用语（第9条）、医疗功效与疾病名（第17/18条）、"
            "保健功效、违规用语（免检/特供）、食品绝对化、虚假表述等高频规则。"
            "调用规则：同输入必同输出；未发现问题时明确说明，不虚报。"
            "限制：单次 2000 字符；本会话共 30 次。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string",
                         "description": "Content to check (Chinese or English; "
                                        "max 2000 characters)"},
                "lang": {
                    "type": "string",
                    "enum": ["auto", "zh", "en"],
                    "description": ("Language of the rules to apply. "
                                    "'auto' (default) picks zh if the text "
                                    "contains CJK characters, otherwise en. "
                                    "zh = China Advertising Law + AI-labeling "
                                    "rules; en = EU AI Act Art.50 + EU/US "
                                    "advertising, health, financial and green "
                                    "claims rules."),
                },
            },
            "required": ["text"],
        },
    },
    {
        "name": "check_ai_label",
        "description": (
            "检测内容中的 AI 生成/合成表述，并提示《人工智能生成合成内容标识办法》"
            "的标识要求。免费版只做表述检测；完整判定（显式标识 + 隐式元数据标识）在云端版。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "要判断的内容"},
            },
            "required": ["text"],
        },
    },
]


def _ok(obj):
    return {"content": [{"type": "text",
                         "text": json.dumps(obj, ensure_ascii=False, indent=2)}],
            "isError": False}


def _err(msg):
    return {"content": [{"type": "text", "text": msg}], "isError": True}


def _quota_check():
    if SESSION["calls"] >= FREE_MAX_CALLS:
        return ("已达免费版会话上限（" + str(FREE_MAX_CALLS) + " 次）。\n"
                "继续使用请走云端版（无次数限制）：" + UPGRADE_HINT)
    return None


def tool_check_content(args):
    text = (args or {}).get("text", "")
    if not isinstance(text, str) or not text.strip():
        return _err("参数 text 不能为空")
    q = _quota_check()
    if q:
        return _err(q)
    if len(text) > FREE_MAX_CHARS:
        return _err("免费版单次上限 " + str(FREE_MAX_CHARS) + " 字符，"
                    "当前 " + str(len(text)) + " 字符。" + UPGRADE_HINT)
    SESSION["calls"] += 1
    # 语言路由（2026-10-08 新增）：
    #   MCP 的调用方是 AI Agent，Agent 生态以英文为主
    #   ⇒ 支持英文规则，才能服务全球线（EU AI Act Art.50 等）
    lang = str((args or {}).get("lang") or "auto").lower()
    if lang == "auto":
        lang = _lang_of(text)
    if lang == "en":
        res = check_text_en(text)
    else:
        res = check_text(text)
    res["lang_used"] = lang
    res["free_quota"] = {"used": SESSION["calls"], "limit": FREE_MAX_CALLS}
    if res["issues"]:
        if lang == "en":
            res["upgrade"] = ("Full rule set (18 rules incl. financial, "
                              "green-claims and deep-fake specifics), plus "
                              "image/C2PA auditing, in the cloud version."
                              + UPGRADE_HINT)
        else:
            res["upgrade"] = ("需要金融收益承诺/教育效果承诺/贬低同行/虚假紧迫感等"
                              "更多规则，或需 AI 标识完整判定 ⇒ 云端版" + UPGRADE_HINT)
    return _ok(res)


def tool_check_ai_label(args):
    text = (args or {}).get("text", "")
    if not isinstance(text, str) or not text.strip():
        return _err("参数 text 不能为空")
    q = _quota_check()
    if q:
        return _err(q)
    SESSION["calls"] += 1
    res = check_ai_label_free(text)
    res["free_quota"] = {"used": SESSION["calls"], "limit": FREE_MAX_CALLS}
    res["upgrade"] = "完整 AI 标识判定与 17 项自查问卷在云端版" + UPGRADE_HINT
    return _ok(res)


HANDLERS = {
    "check_content": tool_check_content,
    "check_ai_label": tool_check_ai_label,
}

# ---------------------------------------------------------------------------
# MCP 协议（内置零依赖 stdio JSON-RPC）
# ---------------------------------------------------------------------------


def handle(msg):
    method = msg.get("method")
    mid = msg.get("id")
    params = msg.get("params") or {}

    if method == "initialize":
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        }}
    if method == "notifications/initialized":
        return None
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments") or {}
        fn = HANDLERS.get(name)
        result = fn(args) if fn else _err("Unknown tool: " + str(name))
        return {"jsonrpc": "2.0", "id": mid, "result": result}
    if mid is not None:
        return {"jsonrpc": "2.0", "id": mid,
                "error": {"code": -32601, "message": "Method not found: " + str(method)}}
    return None


def send(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def run_stdio_fallback():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
            resp = handle(msg)
            if resp is not None:
                send(resp)
        except Exception:
            traceback.print_exc(file=sys.stderr)


def run_fastmcp():
    from mcp.server.fastmcp import FastMCP
    app = FastMCP(SERVER_NAME)

    @app.tool()
    def check_content(text: str) -> str:
        """检查中文内容的广告法合规风险，返回逐条问题+法条依据+修改建议。"""
        return tool_check_content({"text": text})["content"][0]["text"]

    @app.tool()
    def check_ai_label(text: str) -> str:
        """检测 AI 生成/合成表述并提示标识要求。"""
        return tool_check_ai_label({"text": text})["content"][0]["text"]

    app.run()


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        print(json.dumps({
            "server": SERVER_NAME,
            "version": SERVER_VERSION,
            "free_rules": len(FREE_RULES),
            "free_max_chars": FREE_MAX_CHARS,
            "free_max_calls": FREE_MAX_CALLS,
            "tools": [t["name"] for t in TOOLS],
        }, ensure_ascii=False, indent=2))
        demo = tool_check_content({"text": "本店橙子全网最甜，100%无添加，彻底根治失眠，国家级免检产品"})
        print(demo["content"][0]["text"][:900])
        sys.exit(0)

    try:
        import mcp.server.fastmcp  # noqa: F401
        run_fastmcp()
    except ImportError:
        run_stdio_fallback()
