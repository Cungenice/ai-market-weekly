"""产业舆情：双轨信源的准入、初判与规则兜底。

轨道先由域名判定，再谈内容判断：
- 官方轨：`*.gov.cn` 与部委域名。政策与重大项目必须落在这一轨，否则降级并标注「媒体口径」。
- 白名单轨：只认 `config/weekly.yaml` 里显式列出的媒体域名，其余一律不进。

这里的函数只做「能不能进」与「大概属哪类」，最终的脉络与属性由模型在枚举内选择；
模型不可用时，同一套枚举退回规则判断，保证没有模型也能出刊。
"""

from __future__ import annotations

import urllib.parse

from . import settings as S

THREAD_ORDER = ("产业政策", "重大项目", "投融资", "重要产业动态", "其他")
TRACK_LABELS = {"official": "官方", "media": "白名单媒体"}

LOCAL_SUFFIX = ".gov.cn"
DEPARTMENT_NAMES = {
    "www.gov.cn": "中国政府网",
    "gov.cn": "中国政府网",
    "miit.gov.cn": "工业和信息化部",
    "ndrc.gov.cn": "国家发展改革委",
    "cac.gov.cn": "国家互联网信息办公室",
    "most.gov.cn": "科学技术部",
    "mof.gov.cn": "财政部",
    "mofcom.gov.cn": "商务部",
    "sasac.gov.cn": "国务院国资委",
}

# AI 主体词：必须出现在标题里，避免正文顺带一提就被收进来
AI_ANCHORS = ("人工智能", "大模型", "生成式", "通用人工智能", "AGI", "具身智能", "智能体",
              "算力", "智算", "大模型", "机器学习", "深度学习", "AI")
# 产业事件词：区分「产业动态」与「泛科技评论」
EVENT_TERMS = ("发布", "印发", "出台", "实施", "落地", "签约", "开工", "投产", "获批", "批复",
               "备案", "试点", "规划", "方案", "意见", "通知", "办法", "条例", "规范", "监管",
               "融资", "并购", "收购", "投资", "基金", "增资", "上市", "IPO", "合作", "共建",
               "上线", "开源", "突破", "中标", "订单", "扩产", "组建", "揭牌", "验收")
# 观点、传闻、行情复盘类不进产业舆情：它们不改变产业格局
OPINION_TERMS = ("传闻", "或将", "有望", "押注", "观点", "研报", "评级", "目标价", "股价",
                 "涨幅", "跌幅", "涨停", "跌停", "收盘", "盘中")
# 海外宏观与市场情绪类噪音：与本栏目「产业治理」立场无关
NOISE_TERMS = ("美债", "美联储", "华尔街", "纳指", "标普", "道指", "加息", "降息", "非农",
               "CPI", "PMI", "隔夜美股")

THREAD_HINTS = {
    "产业政策": ("政策", "规划", "方案", "意见", "通知", "办法", "条例", "规范", "监管", "备案",
                 "试点", "支持", "补贴", "行动", "指导意见", "管理办法", "白皮书"),
    "重大项目": ("基地", "项目", "开工", "投产", "建设", "园区", "智算中心", "算力中心", "创新平台",
                 "签约", "落地", "揭牌", "验收", "扩产"),
    "投融资": ("融资", "并购", "收购", "上市", "IPO", "基金", "投资", "增资", "战略投资",
               "估值", "轮", "募资"),
    "重要产业动态": ("发布", "开源", "突破", "合作", "共建", "生态", "产品", "模型", "中标",
                     "订单", "上线", "联盟"),
}

ATTRIBUTE_HINTS = {
    "政策发布": ("印发", "出台", "发布", "通知", "意见", "办法", "条例", "规划", "方案", "监管"),
    "项目进展": ("开工", "投产", "签约", "落地", "建设", "验收", "揭牌", "扩产"),
    "资本事件": ("融资", "并购", "收购", "上市", "IPO", "基金", "增资", "战略投资", "募资"),
    "产业合作": ("合作", "共建", "战略协议", "联盟", "生态"),
    "技术产品": ("发布", "开源", "突破", "上线", "模型", "芯片", "产品"),
}


def feeds() -> list[dict]:
    return list(S.cfg("intel.feeds", []) or [])


def _media_map() -> dict[str, str]:
    return {str(row["domain"]).lower(): str(row["name"])
            for row in (S.cfg("intel.media_whitelist", []) or [])}


def thread_labels() -> list[str]:
    return [str(row["label"]) for row in (S.cfg("intel.threads", []) or [])]


def attribute_labels() -> list[str]:
    return [str(row["label"]) for row in (S.cfg("intel.attributes", []) or [])]


def thread_brief() -> str:
    return "；".join(f"{row['label']}：{row['def']}" for row in (S.cfg("intel.threads", []) or []))


def attribute_brief() -> str:
    return "；".join(f"{row['label']}：{row['def']}" for row in (S.cfg("intel.attributes", []) or []))


def host_of(url: str) -> str:
    return (urllib.parse.urlsplit(url).hostname or "").lower().removeprefix("www.")


def track_of_host(host: str) -> str | None:
    host = (host or "").lower().removeprefix("www.")
    if not host:
        return None
    if host == "gov.cn" or host.endswith(LOCAL_SUFFIX):
        return "official"
    # 白名单按后缀匹配：m.caixin.com、finance.caixin.com 都算同一家
    if any(host == domain or host.endswith("." + domain) for domain in _media_map()):
        return "media"
    return None


def site_name(url: str) -> str:
    host = host_of(url)
    if host in DEPARTMENT_NAMES:
        return DEPARTMENT_NAMES[host]
    for domain, name in DEPARTMENT_NAMES.items():
        if host.endswith("." + domain):
            return name
    for domain, name in _media_map().items():
        if host == domain or host.endswith("." + domain):
            return name
    if host.endswith(LOCAL_SUFFIX):
        return f"地方政府网站（{host}）"
    return host or "来源未标注"


def prefilter(title: str, snippet: str) -> bool:
    """相关性前置过滤：宁严勿宽。标题里既要有 AI 主体，也要有产业事件。"""
    head = (title or "").strip()
    if not head:
        return False
    if any(term in head for term in S.cfg("intel.exclude_terms", []) or []):
        return False
    if any(term in head for term in OPINION_TERMS):
        return False
    if any(term in head for term in NOISE_TERMS):
        return False
    if not any(term in head for term in AI_ANCHORS):
        return False
    pool = head + " " + (snippet or "")
    return any(term in pool for term in EVENT_TERMS)


def hints(text: str) -> tuple[str, str]:
    """规则初判：给模型一个参考，也给无模型时的兜底一个落点。"""
    thread = "重要产业动态"
    for label in ("产业政策", "重大项目", "投融资", "重要产业动态"):
        if any(term in text for term in THREAD_HINTS[label]):
            thread = label
            break
    attribute = "其他"
    best = 0
    for label, terms in ATTRIBUTE_HINTS.items():
        score = sum(1 for term in terms if term in text)
        if score > best:
            attribute, best = label, score
    return thread, attribute


def rule_note(item: dict) -> str:
    """无模型时的研判句：给判断框架，不复述标题，也不编造原文没有的事实。

    同一类型下备了多种说法，按条目编号轮换，避免整栏读起来像复读模板。
    """
    thread = item.get("thread") or "重要产业动态"
    attribute = item.get("attribute") or "其他"
    variants = _NOTE_TABLE.get((thread, attribute)) or _NOTE_TABLE.get((thread, "其他")) \
        or ("属产业侧信息，判断依据应来自原文而不是标题",)
    index = 0
    sid = str(item.get("id") or "")
    if sid[1:].isdigit():
        index = int(sid[1:]) % len(variants)
    return variants[index] + "。"


_NOTE_TABLE = {
    ("产业政策", "政策发布"): (
        "政策原件已发布，可读的是适用对象与支持方式；配套细则与试点名单决定落地强度",
        "这类文件先改变预期再改变资源分配，真正起作用的是申报条件与执行主体",
        "从发布到见效隔着细则一层，短期看的是谁被纳入、谁被排除",
    ),
    ("重大项目", "项目进展"): (
        "项目推进到公开节点，看投资规模、建设周期与承接主体，通稿口径与实际开工常有落差",
        "节点信息只说明进度不说明回报，值得跟的是设备进场与产能爬坡",
        "落地环节最容易高估，要看资金到位节奏而不是签约时的表述",
    ),
    ("投融资", "资本事件"): (
        "资本事件改变的是资金与估值参照，看投资方结构、轮次与是否附带业绩或回购条款",
        "钱进来只是开始，值得跟的是这笔钱被指定投向哪一段产能或研发",
        "单轮金额不说明产业位置，出资方结构与后续追加意愿更值得记",
    ),
    ("重要产业动态", "技术产品"): (
        "能力边界的变化要看可复现指标与商用客户，而不是发布会的表述强度",
        "产品发布与规模化落地之间隔着交付能力，看的是首批客户与复购",
        "技术进展只有落到具体场景才算产业变量，其余仍属实验室口径",
    ),
    ("重要产业动态", "产业合作"): (
        "合作框架本身不构成约束，看是否落到订单、排期与排他安排",
        "联合建设的价值在于分工是否清晰，模糊的框架协议往往止步于意向",
        "生态合作要看谁出场景、谁出算力，投入不对等的合作通常推进缓慢",
    ),
    ("产业政策", "其他"): (
        "政策信息进入公开口径，看约束对象与执行主体，短期影响取决于细则而非标题",
        "这类信息的落点在合规成本，企业端的调整通常滞后一个披露周期",
    ),
    ("重大项目", "其他"): (
        "项目信息落在建设周期上，看资金到位与投产节点，而不是签约金额",
        "基建类项目的信号意义大于当期财务意义，观察点在后续招标",
    ),
    ("投融资", "其他"): (
        "资本动作要看交易结构与对价，单轮金额不足以说明产业位置",
        "资金流向比金额更有信息量，留意出手方是产业资本还是财务投资人",
    ),
}


def cap(items: list[dict]) -> list[dict]:
    """配额：总量、单脉络、媒体占比三道闸，防止媒体把官方口径挤出版面。"""
    total = int(S.cfg("intel.max_items", 12))
    per_thread = int(S.cfg("intel.max_per_thread", 4))
    media_share = float(S.cfg("intel.max_media_share", 0.6))

    def order(row: dict) -> tuple:
        thread = row.get("thread") or "其他"
        rank = THREAD_ORDER.index(thread) if thread in THREAD_ORDER else len(THREAD_ORDER)
        return (rank, row.get("track") != "official", -row["published"].timestamp())

    kept: list[dict] = []
    per: dict[str, int] = {}
    media_used = 0
    for row in sorted(items, key=order):
        thread = row.get("thread") or "其他"
        if per.get(thread, 0) >= per_thread:
            continue
        if row.get("track") == "media" and media_used + 1 > max(1, int(total * media_share)):
            continue
        kept.append(row)
        per[thread] = per.get(thread, 0) + 1
        if row.get("track") == "media":
            media_used += 1
        if len(kept) >= total:
            break
    return kept


def group(items: list[dict]) -> list[tuple[str, list[dict]]]:
    """按脉络分组，组内官方在前、媒体在后。空组不返回。"""
    buckets: dict[str, list[dict]] = {}
    for row in items:
        buckets.setdefault(row.get("thread") or "其他", []).append(row)
    ordered: list[tuple[str, list[dict]]] = []
    for label in THREAD_ORDER:
        rows = buckets.get(label)
        if not rows:
            continue
        rows.sort(key=lambda row: (row.get("track") != "official", -row["published"].timestamp()))
        ordered.append((label, rows))
    return ordered


def counts(items: list[dict]) -> dict[str, int]:
    official = sum(1 for row in items if row.get("track") == "official")
    return {"official": official, "media": len(items) - official, "total": len(items)}
