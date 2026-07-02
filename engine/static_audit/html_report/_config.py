"""Configuration constants for HTML report generation.

Centralizes all user-facing text, display limits, thresholds, and heuristic parameters
so they can be adjusted without modifying rendering logic.

All constants in this module are Phase 1 of html_report/ cleanup.
Phase 2 (XSS escaping) comes after.
"""

from __future__ import annotations

# =============================================================================
# Display Limits (How many items to show in various sections)
# =============================================================================

#: Maximum number of evidence cards to display in the appendix
MAX_EVIDENCE_CARDS = 8

#: Maximum number of primary patterns to show in "必须立即追问" section
MAX_PRIMARY_PATTERNS = 20

#: Maximum number of evidence clusters to build and display
MAX_EVIDENCE_CLUSTERS = 6

#: Maximum number of manual tasks to show in the table
MAX_MANUAL_TASKS_DISPLAY = 10

#: Maximum number of paperfraud rule matches to display
MAX_PAPERFRAUD_RULES_DISPLAY = 12

#: Maximum number of pair forensics findings to display
MAX_PAIR_FORENSICS_FINDINGS = 12

#: Maximum number of pair forensics review tasks to display
MAX_PAIR_FORENSICS_REVIEW_TASKS = 12

#: Maximum number of pair forensics clusters to display
MAX_PAIR_FORENSICS_CLUSTERS = 12

#: Maximum number of visual figures to display
MAX_VISUAL_FIGURES = 20

#: Maximum number of visual findings to display
MAX_VISUAL_FINDINGS = 20

#: Maximum number of visual review queue tasks to display
MAX_VISUAL_REVIEW_QUEUE = 20

#: Maximum number of visual clusters to display
MAX_VISUAL_CLUSTERS = 20

#: Maximum number of visual panel thumbnails per figure
MAX_VISUAL_PANELS_PER_FIGURE = 12

#: Maximum number of visual relationships to display
MAX_VISUAL_RELATIONSHIPS = 30

#: Maximum number of investigation records to display
MAX_INVESTIGATION_RECORDS = 20

#: Maximum number of canonical mappings to display
MAX_CANONICAL_MAPPINGS = 12

#: Maximum number of source mappings to display in claim impact matrix
MAX_SOURCE_MAPPINGS = 14

#: Maximum number of benign explanations to collect per cluster
MAX_BENIGN_EXPLANATIONS_PER_CLUSTER = 5

#: Maximum number of agent benign explanations to collect from reviews
MAX_AGENT_BENIGN_FROM_REVIEWS = 3

#: Maximum number of agent benign explanations to collect from findings
MAX_AGENT_BENIGN_FROM_FINDINGS = 2

#: Maximum number of claims to display per pattern/cluster
MAX_CLAIMS_PER_GROUP = 5

#: Maximum number of claims to display per cluster
MAX_CLAIMS_PER_CLUSTER = 4

#: Maximum number of manual tasks to display per cluster
MAX_TASKS_PER_CLUSTER = 3

#: Maximum number of signals to display per cluster
MAX_SIGNALS_PER_CLUSTER = 4

#: Maximum number of clusters to show in brief list
MAX_CLUSTERS_IN_BRIEF = 4

#: Maximum number of manual tasks to display per pattern
MAX_TASKS_PER_PATTERN = 3

#: Maximum number of sample rows to display in evidence cards
MAX_SAMPLE_ROWS = 8

#: Maximum number of claims to show in hero pattern list
MAX_HERO_PATTERNS = 3

#: Maximum number of action questions in hero section
MAX_HERO_ACTIONS = 3

#: Maximum number of sheets to display in pattern cluster headlines
MAX_SHEETS_IN_HEADLINE = 3

#: Maximum number of category labels to display in cluster headlines
MAX_CATEGORIES_IN_HEADLINE = 3

# =============================================================================
# Text Truncation Lengths
# =============================================================================

#: Maximum length for first claim text display
MAX_CLAIM_TEXT_LENGTH = 700

#: Maximum length for hero action question text
MAX_ACTION_QUESTION_LENGTH = 150

#: Maximum length for summary text values
MAX_SUMMARY_VALUE_LENGTH = 90

#: Maximum length for pattern title text
MAX_PATTERN_TITLE_LENGTH = 78

#: Maximum length for pattern thesis text
MAX_PATTERN_THESIS_LENGTH = 260

#: Maximum length for cluster claim text
MAX_CLUSTER_CLAIM_LENGTH = 260

#: Maximum length for step detail text
MAX_STEP_DETAIL_LENGTH = 120

#: Maximum length for evidence sample text
MAX_EVIDENCE_SAMPLE_LENGTH = 220

#: Maximum length for hypothesis/detail in investigation table
MAX_INVESTIGATION_DETAIL_LENGTH = 220

#: Maximum length for figure caption text
MAX_FIGURE_CAPTION_LENGTH = 200

#: Maximum length for claim text in mapping tables
MAX_CLAIM_TEXT_IN_MAPPING = 260

#: Maximum number of pattern titles to show in summary
MAX_PATTERN_TITLES_IN_SUMMARY = 3

#: Maximum number of limitation items to collect from bundle/judge
MAX_LIMITATIONS_FROM_BUNDLE = 5
MAX_LIMITATIONS_FROM_JUDGE = 5

# =============================================================================
# Verdict Labels and Thresholds
# =============================================================================

#: Verdict labels shown in the hero section
VERDICT_LABELS = {
    "fail": "需优先复核",
    "warning": "需人工复核",
    "pass": "未见高优先级项",
}

#: Verdict headlines shown in the hero section
VERDICT_HEADLINES = {
    "fail": "发现高优先级复核项",
    "warning": "发现待核对记录",
    "pass": "未见高优先级复核项",
}

#: Audit depth labels based on coverage level
AUDIT_DEPTH_LABELS = {
    "v0": "V0 coverage",
    "v1": "V1 coverage",
    "v2": "V2 coverage",
    "v3": "V3 coverage",
    "v4": "V4 coverage",
}

#: Risk level labels for display
RISK_LABELS = {
    "critical": "最高优先级",
    "high": "高优先级",
    "medium": "中优先级",
    "low": "低优先级",
    "info": "提示",
    "context": "上下文记录",
}

#: Risk level numeric scores for sorting/comparison
RISK_SCORES = {
    "critical": 4,
    "high": 3,
    "medium": 2,
    "low": 1,
    "info": 0,
    "context": 0,
}

#: Issue category labels (chapter titles)
ISSUE_CATEGORY_LABELS = {
    "consistency": "一致性问题",
    "matching": "匹配问题",
    "completeness": "完整性问题",
}

#: Chapter numbers for issue categories
CHAPTER_NUMBERS = {
    "consistency": "一",
    "matching": "二",
    "completeness": "三",
}

#: Status labels for tool steps and artifacts
STATUS_LABELS = {
    "ran": "已执行",
    "reused": "已复用",
    "skipped": "已跳过",
    "warning": "警告",
    "failed": "失败",
    "not_run": "未运行",
    "not_provided": "未提供",
    "missing_material": "材料缺失",
    "selected": "已选择",
    "unsupported": "暂不支持",
    "present": "已生成",
    "missing": "缺失",
    "ok": "正常",
    "not_available": "不可用",
}

#: Category labels for finding types
CATEGORY_LABELS = {
    "duplicate_numeric_columns": "数值列重复",
    "fixed_difference": "固定差关系",
    "fixed_ratio": "固定比例关系",
    "formula_derived_columns": "公式派生列",
    "row_offset_scalar_multiple": "固定行偏移标量关系",
    "long_format_paired_ratio_reuse": "配对比例复用",
    "duplicate_row_vector": "行向量重复",
    "long_format_within_pair_ratio_enrichment": "配对内部比例富集",
    "row_offset_partial_copy_rounding_bias": "行偏移复制/舍入偏差",
    "repeated_measurement_value": "重复展示数值",
    "fractional_tail_reuse": "小数尾部复用",
    "small_n_fixed_difference": "小样本固定差关系",
    "small_n_fixed_ratio": "小样本固定倍率关系",
    "cross_sheet_fractional_tail_reuse": "跨 Sheet 小数尾部复用",
    "copy_move_single": "单图内局部相似",
    "copy_move_cross": "跨图局部相似",
    "exact_duplicate": "字节级完全重复",
    "dhash_similar": "感知哈希相似",
    "overlap_reuse_cross_panel": "跨 Panel 局部重叠",
    "forged_region_suspicious": "区域完整性记录",
    "paperfraud.methodology_review": "方法学提示",
    "paperfraud.fraud_detection": "数值取证提示",
}

#: Confidence badge HTML for source type indicators
CONFIDENCE_BADGES = {
    "rule": '<span class="conf-badge conf-rule">仅原始记录</span>',
    "data": '<span class="conf-badge conf-data">证据记录</span>',
    "agent": '<span class="conf-badge conf-agent">复核摘要</span>',
}

# =============================================================================
# Pattern Definitions (title, thesis, review_question)
# =============================================================================

PATTERN_DEFINITIONS = {
    "paired_offset_ratio_reuse": {
        "title": "配对样本固定行偏移与比例复用",
        "thesis": "多个 Source Data sheet 中，配对样本在固定行偏移后反复出现标量关系或两组比例复用；规律只在这里描述一次，具体 sheet/行/列作为证据记录保留。",
        "review_question": "确认这些固定偏移和比例复用是否来自合法配对排序、归一化分母或批量派生，而不是同一数据的重复改写。",
    },
    "row_vector_reuse_rounding": {
        "title": "低维行向量重复与舍入偏差",
        "thesis": "若干 figure 的 Source Data 出现行向量重复、部分复制或四舍五入偏差；该规律可能是模板行、censoring 行或真实重复，也可能提示需要追溯导出过程。",
        "review_question": "核对重复行是否有实验或统计语义，例如 censoring 模板、分组标签、重复测量，或导出时批量复制。",
    },
    "row_vector_reuse": {
        "title": "行向量重复候选",
        "thesis": "Source Data 中存在多行共享相同数值向量；该信号需要结合样本 ID、分组标签、零值矩阵和导出模板判断，不能直接推定为异常。",
        "review_question": "核对重复行是否有实验或统计语义，例如 censoring 模板、分组标签、重复测量、全零矩阵，或导出时批量复制。",
    },
    "duplicate_numeric_columns": {
        "title": "数值列重复候选",
        "thesis": "Source Data 中存在数值列高度相同；需要确认这些列是否为索引列、设计列、共享时间点、全零矩阵或同一指标的合法重复展示。",
        "review_question": "核对重复列的列标题、单位、sheet 注释和对应 figure panel，确认是否为合法索引/设计列、派生列或数据复制。",
    },
    "partial_copy_rounding_bias": {
        "title": "部分复制或舍入偏差候选",
        "thesis": "Source Data 中出现行偏移后的部分复用或舍入后相似；需要追溯导出、四舍五入、格式化和上游计算过程。",
        "review_question": "核对这些相似行/列是否由合法四舍五入、格式化导出或批量处理产生，并要求提供上游原始表格或脚本。",
    },
    "small_n_publication_patterns": {
        "title": "小样本数值复用候选",
        "thesis": "Source Data 中出现重复展示值、小数尾部复用或短向量固定关系；这些模式需要结合原始计数、归一化公式和展示精度复核。",
        "review_question": "核对这些 cell 是否对应独立样本/独立实验，并要求提供原始未舍入数值、计数分母和生成脚本。",
    },
    "formula_derivation": {
        "title": "公式派生列与固定倍数转换",
        "thesis": "部分列由相邻单元格或同列历史值按固定公式派生。公式本身不是异常,但它会改变 claim 对\"原始测量值\"的可追溯性。",
        "review_question": "确认论文图表引用的是原始测量值还是派生值，并要求作者说明公式来源、单位换算或归一化逻辑。",
    },
    "visual_forensics": {
        "title": "视觉证据相似或复用候选",
        "thesis": "视觉工具生成了需要人工确认的图像、panel、相似关系或区域级候选；这些信号只能作为复核入口，不能直接作为诚信结论。",
        "review_question": "核对原图、panel、caption、相似方法、分数和最强良性解释，确认是否对应同一主体、合法复用或导出伪影。",
    },
    "numeric_forensics": {
        "title": "PDF 数字取证候选",
        "thesis": "PDF 或表格数字检查生成了统计线索；需要排除 OCR、表格解析、四舍五入和展示层转写造成的伪影。",
        "review_question": "回到原始表格、Source Data 或结果文件，确认数字关系是否能由原始数据和统计流程解释。",
    },
    "execution_evidence": {
        "title": "执行证据与 claim 对账候选",
        "thesis": "运行命令、日志或结果文件与论文 claim 之间存在待核对项；该类 finding 需要回到 runtime manifest 和输出产物验证。",
        "review_question": "核对命令、环境、stdout/stderr、exit code、结果文件 hash 和表述映射是否一致。",
    },
    "other": {
        "title": "其他未归类技术异常",
        "thesis": "这些证据尚未被归入稳定领域规律，需保留原始记录后人工判断。",
        "review_question": "逐条核对 finding 的数据语义、生成过程和论文 claim 影响。",
    },
}

# =============================================================================
# Heuristic Thresholds
# =============================================================================

#: Minimum number of source data patterns to trigger multi-pattern summary
MIN_SOURCE_DATA_PATTERNS_FOR_MULTI_SUMMARY = 2

#: Pattern keys considered as source data patterns
SOURCE_DATA_PATTERN_KEYS = {
    "paired_offset_ratio_reuse",
    "row_vector_reuse_rounding",
    "row_vector_reuse",
    "duplicate_numeric_columns",
    "partial_copy_rounding_bias",
    "small_n_publication_patterns",
    "formula_derivation",
}

#: Pattern sort order (lower = higher priority)
PATTERN_SORT_ORDER = {
    "paired_offset_ratio_reuse": 0,
    "row_vector_reuse": 1,
    "duplicate_numeric_columns": 2,
    "partial_copy_rounding_bias": 3,
    "small_n_publication_patterns": 4,
    "row_vector_reuse_rounding": 5,
    "formula_derivation": 6,
    "visual_forensics": 7,
    "numeric_forensics": 8,
    "execution_evidence": 9,
    "other": 10,
}

#: Categories that trigger context-only display (lower priority)
CONTEXT_ONLY_CATEGORIES = {"duplicate_row_vector"}

#: Pair forensics categories that belong to pair analysis
PAIR_FORENSICS_CATEGORIES = {
    "row_offset_scalar_multiple",
    "long_format_paired_ratio_reuse",
    "duplicate_row_vector",
    "long_format_within_pair_ratio_enrichment",
    "row_offset_partial_copy_rounding_bias",
    "repeated_measurement_value",
    "fractional_tail_reuse",
    "small_n_fixed_difference",
    "small_n_fixed_ratio",
    "cross_sheet_fractional_tail_reuse",
}

# =============================================================================
# Text Replacement Rules (for cleaning report text)
# =============================================================================

#: Text replacements to make report language more neutral/factual
HUMAN_TEXT_REPLACEMENTS = (
    ("可疑伪造区域", "区域完整性记录"),
    ("伪造区域", "区域完整性记录"),
    ("伪造检测", "完整性检测"),
    ("非伪造的图像编辑", "常规图像编辑"),
    ("篡改可能性", "完整性差异"),
    ("图像 manipulations", "图像局部复用问题"),
    ("manipulations", "局部复用问题"),
    ("copy-move 伪造", "局部复用记录"),
    ("增加了机械构造的可能性", "需要确认是否由固定公式或导出流程造成"),
    ("机械构造", "固定生成过程"),
    ("极为罕见", "需要重点确认"),
    ("异常模式指向", "记录集中在"),
    ("异常模式", "记录模式"),
    ("异常狭窄", "过窄"),
    ("异常", "偏离预期"),
    ("可疑模式", "集中模式"),
    ("可疑", "需复核"),
    ("疑似人工凑整", "末位数字集中"),
    ("人为凑整信号", "末位数字集中"),
    ("疑似 p 值集中", "p 值集中"),
    ("疑似", "需复核"),
    ("p-hacking", "p 值集中"),
    ("风险较低", "优先级较低"),
    ("初步判断为", "当前记录显示为"),
    (
        "高 score 表示神经网络认为这些区域存在完整性差异",
        "score 较高，需查看 heatmap 和原图",
    ),
    ("虽然可能是", "需确认是否为"),
    ("可能表示", "需确认是否为"),
    ("可能反映", "需确认是否反映"),
    ("可能来自", "需确认是否来自"),
    ("可能由", "需确认是否由"),
    ("可能是", "需确认是否为"),
    ("造假", "数据完整性问题"),
    ("学术不端", "最终判断"),
    ("duplicate_numeric_columns", "数值列重复"),
    ("duplicate_row_vector", "行向量重复"),
    ("paired_difference_too_narrow", "配对差异过窄"),
    ("paired_ratio_reuse", "配对比例复用"),
    ("repeated_measurement_value", "重复展示数值"),
    ("fractional_tail_reuse", "小数尾部复用"),
    ("small_n_fixed_difference", "小样本固定差关系"),
    ("small_n_fixed_ratio", "小样本固定倍率关系"),
    ("cross_sheet_fractional_tail_reuse", "跨 Sheet 小数尾部复用"),
    ("row_offset_exact_reuse", "固定行偏移重复"),
    ("paperfraud.fraud_detection", "数值取证提示"),
    ("paperfraud.methodology_review", "方法学提示"),
    ("fraud_detection", "数值取证提示"),
    ("fraud-pattern", "取证提示"),
    ("PaperFraud", "规则库"),
    ("claim-to-evidence", "论文表述与证据"),
    ("claim-to-code", "论文表述与代码"),
    ("finding reviews", "复核记录"),
    ("finding review", "复核记录"),
    ("manual tasks", "复核任务"),
    ("Agent review output", "复核输出"),
    ("copy-move", "局部相似"),
    ("copy_move", "局部相似"),
    ("support_rate", "支持率"),
    ("findings", "记录"),
    ("finding", "记录"),
    ("claims", "论文表述"),
    ("claim", "论文表述"),
    ("critical", "高优先级"),
    ("clusters", "证据簇"),
    ("cluster", "证据簇"),
    ("visual.局部相似_dense", "visual.copy_move_dense"),
    ("visual.局部相似", "visual.copy_move"),
    ("论文表述_extractor", "claim_extractor"),
    ("opencode Agent", "opencode 复核"),
    ("Agent Investigation Tool", "调查工具"),
    ("AgentInvestigationPlanner", "调查规划器"),
    ("规则库 规则库", "规则库"),
)

# =============================================================================
# Signal Detection Tokens (for heuristic scoring)
# =============================================================================

#: Tokens that indicate row vector signal (lower priority)
ROW_VECTOR_SIGNAL_TOKENS = ("drv-", "duplicate_row_vector", "row vector", "行向量重复")

#: Tokens that indicate stronger signal (higher priority)
STRONGER_SIGNAL_TOKENS = (
    "dc-",
    "fr-",
    "fd-",
    "prr-",
    "pds-",
    "roe-",
    "vfc-",
    "数值列重复",
    "固定比例",
    "固定差",
    "配对比例",
    "配对差异",
    "区域完整性",
    "trufor",
    "copy",
)

# =============================================================================
# Default/Fallback Text
# =============================================================================

#: Default action questions when no tasks are available
DEFAULT_ACTION_QUESTIONS = [
    "核对材料清单、PDF 解析、Source Data、图像和代码材料是否完整。",
    "要求作者补充缺失的原始数据、导出过程、分析脚本或结果文件。",
    "把后续生成的复核记录与论文表述逐条对账，确认是否需要补充材料或说明。",
]

#: Default review question for generic findings
DEFAULT_REVIEW_QUESTION = "请人工复核该记录的证据定位、论文表述影响和良性解释。"

#: Default task items when no manual tasks are available
DEFAULT_CLUSTER_TASK_ITEMS = [
    "核对 Source Data 的 workbook/sheet/column header、row offset、merged cells 和 figure panel 语义。",
    "要求作者提供原始分析脚本或数据导出过程，解释该结构性模式是否来自合法归一化或批量派生。",
]

#: Generic benign explanation when no specific explanation is available
GENERIC_BENIGN_EXPLANATIONS = [
    "该模式可能来自合法的归一化、批量派生、配对样本排序或模板化导出。",
    "需要结合原始 artifact、导出参数、字段定义和论文 claim 语义判断。",
]

#: Disclaimer text shown in verdict
VERDICT_DISCLAIMER = "这些记录只用于安排人工复核，不作诚信结论。"

#: Footer disclaimer text
FOOTER_DISCLAIMER = "报告只展示技术记录和复核入口，关键结论必须人工确认。"

#: Limitation disclaimer (always shown)
LIMITATION_DISCLAIMER = "本报告不做最终科研诚信判定，只展示技术记录和人工复核入口。"

# =============================================================================
# Section Titles (Chinese)
# =============================================================================

SECTION_TITLES = {
    "primary_patterns": "必须立即追问",
    "secondary_patterns": "提示性记录",
    "layered_view": "分层复核视图",
    "evidence_ledger": "原始证据记录",
    "claim_impact": "论文表述对照",
    "manual_review": "人工复核清单",
    "paperfraud_rules": "规则库提示",
    "coverage": "覆盖范围与限制",
    "visual_evidence": "图像证据",
    "appendix": "技术附录",
    "hero_patterns": "重点事实",
    "hero_coverage": "覆盖范围",
    "hero_actions": "下一步动作",
    "hero_first_look": "先看这里",
}

# =============================================================================
# Pattern Sort Order Helper
# =============================================================================


def get_pattern_sort_order(pattern_key: str) -> int:
    """Return the sort order for a pattern key (lower = higher priority)."""
    return PATTERN_SORT_ORDER.get(pattern_key, 7)
