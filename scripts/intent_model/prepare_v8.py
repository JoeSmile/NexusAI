"""8-class intent data remap + pre_sales/after_sales synthesis (65-slice8, 2026-08-24).

Old 7-class (WaveS emotional) -> new 8-class (enterprise SaaS):
  knowledge_query/function/greeting  keep
  chat                    -> conversation
  crisis                  -> DROP (guardrails owns safety)
  advice                  -> coarse split by keyword:
                             pre_sales    : 咨询/产品/报价/方案/多少钱/购买/试用/介绍下产品...
                             after_sales  : 退款/投诉/发票/故障/报障/退货/售后/客服...
                             content_analysis: 分析/评估/竞品/数据/趋势/风险/优化建议...
                             else         -> conversation
Synthesis: template-based pre_sales / after_sales samples (deterministic, no LLM cost).
Output: data/intent/train/train_pool_v8.jsonl + data/intent/golden/golden_v8.csv + stats.
"""
from __future__ import annotations

import csv
import json
import random
import re
from collections import Counter
from pathlib import Path

BASE = Path(__file__).resolve().parents[2] / "data" / "intent"

NEW_LABELS = ["greeting", "pre_sales", "after_sales", "content_creation",
              "content_analysis", "knowledge_query", "function", "conversation"]

PRE_SALES_KW = re.compile(r"咨询|产品|报价|方案|多少钱|价格|购买|试用|开通|介绍|功能|怎么收费|套餐|演示|对接|合作|采购|贵公司|你们公司")
AFTER_SALES_KW = re.compile(r"退款|投诉|发票|故障|报障|退货|售后|客服|无法使用|登录不上|报错|赔偿|升级问题|续费|到期|取消")
ANALYSIS_KW = re.compile(r"分析|评估|竞品|数据|趋势|风险|优化建议|对比.*产品|市场|调研|洞察|指标|复盘")
# v8.1 semantic-migration keywords
CREATION_KW = re.compile(r"写|生成|创作|文案|脚本|口播|周报|推文|软文|笔记|稿|邀请函|公告|总结|纪要")
ANALYSIS_KW2 = re.compile(r"梳理|热点|选题|挖掘|洞察|调研|复盘")
AFTER_SALES_KW2 = re.compile(r"密码|账号|登录|发票|报销|退款|投诉|报错|IT|支持|故障|工单|到期|续费|验证码|手机号|席位|存储|数据导出|扣费|订阅")

random.seed(42)


# v8.2: farewell words -> conversation (golden/train consistency, 08-24)
FAREWELL_KW = re.compile(r"再见|拜拜|回见|拜拜啊|再见啊|再见呀")

def remap_old_label(label: str, text: str) -> str | None:
    """Map old 7-class label to new 8-class. None => drop (crisis).
    v8.1 (08-24): semantic migration for old labels folded under function/
    knowledge_query in the 7-class era (write/analyze phrasing -> content
    classes; account/invoice/support issues -> after_sales).
    v8.2: farewell words (再见/拜拜) -> conversation (greeting = 开场问候)."""
    l = label.strip().lower()
    if l == "greeting":
        if FAREWELL_KW.search(text):
            return "conversation"
        return "greeting"
    if l == "function":
        # 7-class era folded content writing/analysis into "function"
        if CREATION_KW.search(text):
            return "content_creation"
        if ANALYSIS_KW2.search(text):
            return "content_analysis"
        return "function"
    if l == "knowledge_query":
        if AFTER_SALES_KW2.search(text):
            return "after_sales"
        return "knowledge_query"
    if l == "chat":
        return "conversation"
    if l == "crisis":
        return None
    if l == "conversation":
        # v8.3: "在吗" openers are greeting semantics (opening), not chit-chat
        if "在吗" in text:
            return "greeting"
        return "conversation"
    if l == "advice":
        if PRE_SALES_KW.search(text):
            return "pre_sales"
        if AFTER_SALES_KW.search(text):
            return "after_sales"
        if ANALYSIS_KW.search(text):
            return "content_analysis"
        return "conversation"
    return "conversation"


# ---- template synthesis for pre_sales / after_sales (the two near-zero classes) ----

PRE_SALES_TEMPLATES = [
    "你们{prod}多少钱", "{prod}怎么收费", "我想了解一下{prod}", "介绍一下{prod}的功能",
    "你们公司是做什么的", "{prod}和{other}有什么区别", "能对比一下{prod}和{other}吗",
    "我们想采购{prod}", "怎么开通{prod}", "有试用吗", "支持私有化部署吗",
    "{prod}适合我们这种{scene}公司吗", "报价方案发我看看", "你们有哪些套餐",
    "我想预约个产品演示", "怎么对接你们的系统", "{prod}支持{feat}吗", "合作有什么要求",
    "你们的产品能解决{problem}吗", "跟我们现有的{other}系统能集成吗",
    "{prod}的免费版有什么限制", "按年付有折扣吗", "能签框架合同吗",
    "你们在{scene}行业有案例吗", "实施周期多长", "需要专门运维吗", "数据存在哪里",
    "能私有化到我们机房吗", "支持信创环境吗", "国产化适配做到什么程度",
    "API 调用量怎么算", "并发数上限多少", "培训和支持包含在价格里吗",
    "能不能先做一个概念验证", "给我们出个技术方案", "售前顾问什么时候能联系",
    "对标你们和{other}的定价", "有教育优惠吗", "团队版和旗舰版差别在哪",
]
PRE_SALES_PROD = ["NexusAI", "你们的中台", "智能助手", "内容平台", "知识库", "大模型平台"]
PRE_SALES_OTHER = ["ChatGPT", "飞书", "钉钉", "Agentium", "自研系统", "之前的系统"]
PRE_SALES_SCENE = ["电商", "金融", "教育", "制造", "SaaS"]
PRE_SALES_FEAT = ["多租户", "审计", "私有化", "SSO", "审批流", "多模态"]
PRE_SALES_PROBLEM = ["内容生产效率低", "知识库管理混乱", "合规审计困难", "多模型接入成本高"]

AFTER_SALES_TEMPLATES = [
    "怎么申请退款", "我要退款", "账单有问题，想投诉", "开发票", "发票怎么开",
    "系统报错了，{err}", "{prod}登录不上了", "功能突然无法使用", "账号被锁了怎么办",
    "续费流程怎么走", "我们合同要到期了", "想取消订阅", "售后客服电话是多少",
    "你们服务出问题了，要赔偿", "工单提交了没人处理", "这个 bug 什么时候修",
    "使用过程中频繁报错", "数据导不出来", "权限配置有问题",
    "退款什么时候到账", "退款申请被拒了", "发票抬头怎么改", "发票多久能开出来",
    "扣错钱了怎么办", "重复扣费了", "试用期怎么取消自动续费", "停用账号流程",
    "数据导出权限在哪开", "接口一直报超时", "模型回答经常中断", "附件上传失败",
    "语音转写一直转圈", "审核为什么被驳回", "我的工单还没人跟进", "投诉你们客服态度",
    "合同里说的服务没兑现", "SLA 不达标要补偿", "登录验证码收不到", "手机号换绑",
    "管理员权限找谁开通", "团队席位不够了", "存储空间满了怎么清理", "历史数据找不到了",
    "版本升级后功能不见了", "新版本不兼容旧数据", "回滚到上一版", "培训资料在哪下载",
    "服务要停用了，数据怎么迁走", "我们准备换供应商，导出全部数据",
]
AFTER_SALES_ERR = ["接口 500 了", "页面白屏", "模型一直转圈", "报错 429"]
AFTER_SALES_PROD = ["NexusAI", "你们平台", "系统", "后台", "编辑器"]

GREETING_TEMPLATES = [
    "在吗", "在不在", "哈喽在吗", "你好在吗", "hello在吗", "嗨在吗",
    "早上好在吗", "你好呀", "早上好", "中午好", "下午好", "晚上好",
    "哈喽", "嗨你好", "hello你好", "师傅你好", "大佬好",
]

# content_creation / content_analysis existing samples are ~zero too -> small template set
CREATION_TEMPLATES = [
    "帮我写个口播稿", "写一段社媒文案", "帮我写周报", "生成一份短视频脚本",
    "写个产品宣传文案", "帮我写会议纪要", "生成一份报价单文案",
    "帮我写个朋友圈文案", "写一篇公众号推文", "生成商品详情页文案",
    "帮我写邮件正文", "写个活动通知", "帮我起草一份公告", "生成节日问候文案",
    "帮我写简历自我评价", "写个演讲稿开头", "帮我写封感谢信", "写个推广软文",
    "帮我写小红书笔记", "生成一个直播话术", "写个面试自我介绍", "帮我起草合同模板",
    "帮我写周报总结", "生成季度复盘报告", "写个项目总结",
]
ANALYSIS_TEMPLATES = [
    "帮我分析下热点", "挖掘一下今天的选题", "分析下竞品动态", "做个市场趋势分析",
    "帮我分析这组数据", "复盘一下上个月的内容效果", "分析下用户反馈",
    "分析下这个竞品的定价策略", "帮我看看这个行业报告", "分析下关键词热度",
    "对比一下我们和竞品的流量", "分析用户画像", "看看哪个选题数据最好",
    "分析一下投诉集中的问题", "帮我做个竞品功能对比", "分析下转化率下降的原因",
    "分析下这批问卷结果", "看看市场机会在哪里", "分析下友商的增长策略",
]


def synthesize(n: int, templates: list[str], fillers: list[list[str]], label: str) -> list[dict]:
    out = []
    pick = lambda lst: random.choice(lst) if lst else ""
    for _ in range(n):
        t = random.choice(templates)
        text = t.format(prod=pick(fillers[0]), other=pick(fillers[1]),
                        scene=pick(fillers[2]), feat=pick(fillers[3]),
                        problem=pick(fillers[4]), err=pick(fillers[5]))
        out.append({"text": text, "label": label, "label_source": "template_v8"})
    return out


def main() -> None:
    # 1) load existing pools
    rows: list[dict] = []
    tp = BASE / "train" / "train_pool.jsonl"
    for line in tp.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    # weak labels pool (rule-engine high-confidence hits, not in train_pool)
    wp = BASE / "pools" / "weak_labels.jsonl"
    if wp.exists():
        for line in wp.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
        print(">> merged weak_labels:", wp)
    # golden 500 -> also remap (separate file)
    golden_rows: list[dict] = []
    gp = BASE / "golden" / "golden_500.csv"
    with gp.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            golden_rows.append({"text": r["text"], "label": r["label"], "label_source": r.get("label_source", "golden_holdout")})

    def remap_all(rs: list[dict]) -> tuple[list[dict], Counter]:
        kept, dropped = [], Counter()
        for r in rs:
            new = remap_old_label(r["label"], r["text"])
            if new is None:
                dropped["crisis_dropped"] += 1
                continue
            kept.append({"text": r["text"], "label": new, "label_source": r.get("label_source", "remap")})
        return kept, dropped

    kept, dropped = remap_all(rows)
    golden_kept, _ = remap_all(golden_rows)

    # 2) synthesize missing classes
    syn_greet = synthesize(60, GREETING_TEMPLATES, [[], [], [], [], [], []], "greeting")
    syn_pre = synthesize(400, PRE_SALES_TEMPLATES,
                         [PRE_SALES_PROD, PRE_SALES_OTHER, PRE_SALES_SCENE, PRE_SALES_FEAT, PRE_SALES_PROBLEM, []],
                         "pre_sales")
    syn_after = synthesize(400, AFTER_SALES_TEMPLATES,
                           [AFTER_SALES_PROD, ["x"], ["x"], ["x"], ["x"], AFTER_SALES_ERR], "after_sales")
    syn_creation = synthesize(150, CREATION_TEMPLATES, [["x"], ["x"], ["x"], ["x"], ["x"], []], "content_creation")
    syn_analysis = synthesize(150, ANALYSIS_TEMPLATES, [["x"], ["x"], ["x"], ["x"], ["x"], []], "content_analysis")

    all_rows = kept + syn_greet + syn_pre + syn_after + syn_creation + syn_analysis
    # dedup by text
    seen, deduped = set(), []
    for r in all_rows:
        if r["text"] not in seen:
            seen.add(r["text"])
            deduped.append(r)

    dist = Counter(r["label"] for r in deduped)
    print("=== new train distribution (8-class) ===")
    for lb in NEW_LABELS:
        print(f"  {lb:20s} {dist[lb]:5d}")
    print("dropped:", dict(dropped))

    # 3) write outputs
    out_tp = BASE / "train" / "train_pool_v8.jsonl"
    with out_tp.open("w", encoding="utf-8") as f:
        for r in deduped:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # golden v8: remapped + synthesized pre/after (golden needs every class)
    gdist = Counter(r["label"] for r in golden_kept)
    print("=== golden remapped (pre-synthesis) ===", dict(gdist))
    g_syn_pre = synthesize(40, PRE_SALES_TEMPLATES,
                           [PRE_SALES_PROD, PRE_SALES_OTHER, PRE_SALES_SCENE, PRE_SALES_FEAT, PRE_SALES_PROBLEM, []],
                           "pre_sales")
    g_syn_after = synthesize(40, AFTER_SALES_TEMPLATES,
                             [AFTER_SALES_PROD, ["x"], ["x"], ["x"], ["x"], AFTER_SALES_ERR], "after_sales")
    g_syn_creation = synthesize(30, CREATION_TEMPLATES, [["x"], ["x"], ["x"], ["x"], ["x"], []], "content_creation")
    g_syn_analysis = synthesize(30, ANALYSIS_TEMPLATES, [["x"], ["x"], ["x"], ["x"], ["x"], []], "content_analysis")
    golden_v8 = golden_kept + g_syn_pre + g_syn_after + g_syn_creation + g_syn_analysis
    # v8.3: dedup golden (synthesis with small template space can repeat)
    gseen, gdedup = set(), []
    for r in golden_v8:
        if r["text"] not in gseen:
            gseen.add(r["text"])
            gdedup.append(r)
    golden_v8 = gdedup

    out_g = BASE / "golden" / "golden_v8.csv"
    with out_g.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["text", "label", "label_source"])
        for r in golden_v8:
            w.writerow([r["text"], r["label"], r["label_source"]])
    gv8 = Counter(r["label"] for r in golden_v8)
    print("=== golden v8 ===")
    for lb in NEW_LABELS:
        print(f"  {lb:20s} {gv8[lb]:5d}")
    print("total train:", len(deduped), "| golden:", len(golden_v8))
    print("done ->", out_tp, out_g)


if __name__ == "__main__":
    main()
