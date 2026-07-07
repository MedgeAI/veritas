"""Finding category registry.

Centralizes finding category metadata (label, pattern key, ID prefix,
review question, etc.) so that adding a new category only requires
a single registry entry instead of touching multiple files.

See PRD "Veritas-抽象层治理与架构演进-PRD.md" §WP5 for design rationale.
"""

from __future__ import annotations

from dataclasses import dataclass

from engine.static_audit.models import IssueCategory


@dataclass(frozen=True)
class FindingCategoryDefinition:
    """Declarative definition of a finding category.

    Attributes:
        category: Canonical category key (matches producer output).
        label: Human-readable Chinese label for reports.
        pattern_key: Key used by pattern_key_for_finding for grouping.
        id_prefix: Prefix used by assign_ids when generating finding IDs.
        review_question: Default review question text for review tasks.
        issue_category: High-level issue classification.
        context_only: Whether this category is display-only (lower priority).
        is_pair_forensics: Whether this category belongs to pair forensics.
        in_source_data_patterns: Whether this category is a source data pattern.
        pattern_sort_order: Sort order for pattern display (lower = higher).
    """

    category: str
    label: str
    pattern_key: str
    id_prefix: str
    review_question: str
    issue_category: IssueCategory = "consistency"
    context_only: bool = False
    is_pair_forensics: bool = False
    in_source_data_patterns: bool = False
    pattern_sort_order: int | None = None


_REGISTRY: dict[str, FindingCategoryDefinition] = {}


def register(defn: FindingCategoryDefinition) -> FindingCategoryDefinition:
    """Register a category definition.

    Raises ValueError if the same category is registered twice.
    """
    if defn.category in _REGISTRY:
        raise ValueError(f"Duplicate finding category registration: {defn.category!r}")
    _REGISTRY[defn.category] = defn
    return defn


def get(category: str) -> FindingCategoryDefinition | None:
    """Look up a category definition. Returns None if not registered."""
    return _REGISTRY.get(category)


def all_definitions() -> list[FindingCategoryDefinition]:
    """Return all registered definitions (used for deriving legacy constants)."""
    return list(_REGISTRY.values())


def pair_forensics_categories() -> frozenset[str]:
    """Derive: set of all categories with is_pair_forensics=True."""
    return frozenset(d.category for d in _REGISTRY.values() if d.is_pair_forensics)


def source_data_pattern_keys() -> frozenset[str]:
    """Derive: set of all categories with in_source_data_patterns=True."""
    return frozenset(
        d.category for d in _REGISTRY.values() if d.in_source_data_patterns
    )


# =============================================================================
# Pair forensics categories (source data numeric pattern detection)
# =============================================================================

REPEATED_MEASUREMENT_VALUE = register(
    FindingCategoryDefinition(
        category="repeated_measurement_value",
        label="重复展示数值",
        pattern_key="repeated_measurement_value",
        id_prefix="RMV",
        review_question=(
            "多个 cell 出现相同展示值，需确认它们是否为独立样本、"
            "合法重复测量或四舍五入后的重复。"
        ),
        issue_category="consistency",
        context_only=False,
        is_pair_forensics=True,
        in_source_data_patterns=False,
        pattern_sort_order=None,
    )
)

ROW_OFFSET_SCALAR_MULTIPLE = register(
    FindingCategoryDefinition(
        category="row_offset_scalar_multiple",
        label="固定行偏移标量关系",
        pattern_key="paired_offset_ratio_reuse",
        id_prefix="ROS",
        review_question=(
            "同一列在固定行偏移下呈固定倍数关系，"
            "需确认是否来自单位换算、归一化或复制派生。"
        ),
        issue_category="consistency",
        context_only=False,
        is_pair_forensics=True,
        in_source_data_patterns=False,
        pattern_sort_order=None,
    )
)

LONG_FORMAT_PAIRED_RATIO_REUSE = register(
    FindingCategoryDefinition(
        category="long_format_paired_ratio_reuse",
        label="配对比例复用",
        pattern_key="paired_offset_ratio_reuse",
        id_prefix="LPR",
        review_question=(
            "long-format pair 在固定 pair id 偏移下复用相同比例，"
            "需确认 pair id 是否代表独立样本/患者。"
        ),
        issue_category="consistency",
        context_only=False,
        is_pair_forensics=True,
        in_source_data_patterns=False,
        pattern_sort_order=None,
    )
)

DUPLICATE_ROW_VECTOR = register(
    FindingCategoryDefinition(
        category="duplicate_row_vector",
        label="行向量重复",
        pattern_key="row_vector_reuse",
        id_prefix="DRV",
        review_question=(
            "多行低宽度数值向量重复，需确认重复行是否代表同一样本、模板行或独立测量。"
        ),
        issue_category="consistency",
        context_only=True,
        is_pair_forensics=True,
        in_source_data_patterns=False,
        pattern_sort_order=None,
    )
)

LONG_FORMAT_WITHIN_PAIR_RATIO_ENRICHMENT = register(
    FindingCategoryDefinition(
        category="long_format_within_pair_ratio_enrichment",
        label="配对内部比例富集",
        pattern_key="paired_offset_ratio_reuse",
        id_prefix="LPE",
        review_question=(
            "多个 long-format pair 出现相同比例富集，"
            "需确认是否由阈值化/归一化预期产生。"
        ),
        issue_category="consistency",
        context_only=False,
        is_pair_forensics=True,
        in_source_data_patterns=False,
        pattern_sort_order=None,
    )
)

ROW_OFFSET_PARTIAL_COPY_ROUNDING_BIAS = register(
    FindingCategoryDefinition(
        category="row_offset_partial_copy_rounding_bias",
        label="行偏移复制/舍入偏差",
        pattern_key="partial_copy_rounding_bias",
        id_prefix="RBR",
        review_question=(
            "固定行偏移同时出现精度变化和部分复用，需确认后半区是否为独立原始记录。"
        ),
        issue_category="consistency",
        context_only=False,
        is_pair_forensics=True,
        in_source_data_patterns=False,
        pattern_sort_order=None,
    )
)

FRACTIONAL_TAIL_REUSE = register(
    FindingCategoryDefinition(
        category="fractional_tail_reuse",
        label="小数尾部复用",
        pattern_key="fractional_tail_reuse",
        id_prefix="FTR",
        review_question=(
            "同一 sheet 内多个不同数值复用相同小数尾部，"
            "需确认是否由相同分母、归一化或展示规则导致。"
        ),
        issue_category="consistency",
        context_only=False,
        is_pair_forensics=True,
        in_source_data_patterns=False,
        pattern_sort_order=None,
    )
)

SMALL_N_FIXED_DIFFERENCE = register(
    FindingCategoryDefinition(
        category="small_n_fixed_difference",
        label="小样本固定差关系",
        pattern_key="small_n_fixed_difference",
        id_prefix="SNF",
        review_question=(
            "短向量列之间存在精确固定差值，"
            "需确认是否为合法派生关系或独立条件间的异常一致。"
        ),
        issue_category="consistency",
        context_only=False,
        is_pair_forensics=True,
        in_source_data_patterns=False,
        pattern_sort_order=None,
    )
)

SMALL_N_FIXED_RATIO = register(
    FindingCategoryDefinition(
        category="small_n_fixed_ratio",
        label="小样本固定倍率关系",
        pattern_key="small_n_fixed_ratio",
        id_prefix="SNR",
        review_question=(
            "短向量列之间存在精确固定倍率，"
            "需确认是否为合法单位换算/归一化或独立条件间的异常一致。"
        ),
        issue_category="consistency",
        context_only=False,
        is_pair_forensics=True,
        in_source_data_patterns=False,
        pattern_sort_order=None,
    )
)

CROSS_SHEET_FRACTIONAL_TAIL_REUSE = register(
    FindingCategoryDefinition(
        category="cross_sheet_fractional_tail_reuse",
        label="跨 Sheet 小数尾部复用",
        pattern_key="cross_sheet_fractional_tail_reuse",
        id_prefix="CFT",
        review_question=(
            "不同 sheet 的同类数值序列连续复用小数尾部，"
            "需确认这些 figure 是否独立以及原始未舍入值是否支持该模式。"
        ),
        issue_category="consistency",
        context_only=False,
        is_pair_forensics=True,
        in_source_data_patterns=False,
        pattern_sort_order=None,
    )
)

BINARY_ARITHMETIC_RELATION = register(
    FindingCategoryDefinition(
        category="binary_arithmetic_relation",
        label="三列乘除关系",
        pattern_key="binary_arithmetic_relation",
        id_prefix="BAR",
        review_question=(
            "三列之间存在精确乘除关系（A*B=C / A/B=C / B/A=C），"
            "需确认是否为独立测量或合法派生列。"
        ),
        issue_category="consistency",
        context_only=False,
        is_pair_forensics=True,
        in_source_data_patterns=False,
        pattern_sort_order=None,
    )
)

SHIFTED_PASTE = register(
    FindingCategoryDefinition(
        category="shifted_paste",
        label="行错位粘贴候选",
        pattern_key="shifted_paste",
        id_prefix="SHP",
        review_question=(
            "列对之间存在位移粘贴关系（平移后小数部分一致、整数部分固定偏移），"
            "需确认是否为独立数据或复制移位。"
        ),
        issue_category="consistency",
        context_only=False,
        is_pair_forensics=True,
        in_source_data_patterns=False,
        pattern_sort_order=None,
    )
)

COPY_PASTE_MODIFY = register(
    FindingCategoryDefinition(
        category="copy_paste_modify",
        label="保留小数改写候选",
        pattern_key="copy_paste_modify",
        id_prefix="CPM",
        review_question=(
            "列对之间小数部分相同但整数部分存在固定差值，"
            "需确认是否为合法修改或机械复制。"
        ),
        issue_category="consistency",
        context_only=False,
        is_pair_forensics=True,
        in_source_data_patterns=False,
        pattern_sort_order=None,
    )
)

INTERNAL_SEQUENCE_RELATION = register(
    FindingCategoryDefinition(
        category="internal_sequence_relation",
        label="列内序列关系",
        pattern_key="internal_sequence_relation",
        id_prefix="ISR",
        review_question=("单列内出现等差或等比序列，需确认是否为独立测量或人为填充。"),
        issue_category="consistency",
        context_only=False,
        is_pair_forensics=True,
        in_source_data_patterns=False,
        pattern_sort_order=None,
    )
)

DECIMAL_TAIL_MATCH_SHIFTED = register(
    FindingCategoryDefinition(
        category="decimal_tail_match_shifted",
        label="小数窗口错位匹配",
        pattern_key="decimal_tail_match_shifted",
        id_prefix="DTS",
        review_question=(
            "不同数值在位移 ±1 位后小数尾部仍然匹配，"
            "需确认是否由计算过程或单位换算导致。"
        ),
        issue_category="consistency",
        context_only=False,
        is_pair_forensics=True,
        in_source_data_patterns=False,
        pattern_sort_order=None,
    )
)

STRICT_LINEAR_RELATION = register(
    FindingCategoryDefinition(
        category="strict_linear_relation",
        label="严格线性关系",
        pattern_key="strict_linear_relation",
        id_prefix="SLR",
        review_question=(
            "列对之间存在严格线性关系（R² ≥ 0.999999），需确认是否为独立测量或派生列。"
        ),
        issue_category="consistency",
        context_only=False,
        is_pair_forensics=True,
        in_source_data_patterns=False,
        pattern_sort_order=None,
    )
)

# =============================================================================
# Numeric/source-data categories (non-pair pattern detection)
# =============================================================================

DUPLICATE_NUMERIC_COLUMNS = register(
    FindingCategoryDefinition(
        category="duplicate_numeric_columns",
        label="数值列重复",
        pattern_key="duplicate_numeric_columns",
        id_prefix="DC",
        review_question=(
            "数值列高度相同，需确认这些列是否为索引列、设计列、"
            "共享时间点、全零矩阵或同一指标的合法重复展示。"
        ),
        issue_category="consistency",
        context_only=False,
        is_pair_forensics=False,
        in_source_data_patterns=True,
        pattern_sort_order=None,
    )
)

FIXED_DIFFERENCE = register(
    FindingCategoryDefinition(
        category="fixed_difference",
        label="固定差关系",
        pattern_key="formula_derivation",
        id_prefix="FD",
        review_question=(
            "列之间存在精确固定差值，需确认是否为合法派生关系或独立条件间的异常一致。"
        ),
        issue_category="consistency",
        context_only=False,
        is_pair_forensics=False,
        in_source_data_patterns=False,
        pattern_sort_order=None,
    )
)

FIXED_RATIO = register(
    FindingCategoryDefinition(
        category="fixed_ratio",
        label="固定比例关系",
        pattern_key="formula_derivation",
        id_prefix="FR",
        review_question=(
            "列之间存在精确固定倍率，"
            "需确认是否为合法单位换算/归一化或独立条件间的异常一致。"
        ),
        issue_category="consistency",
        context_only=False,
        is_pair_forensics=False,
        in_source_data_patterns=False,
        pattern_sort_order=None,
    )
)

FORMULA_DERIVED_COLUMNS = register(
    FindingCategoryDefinition(
        category="formula_derived_columns",
        label="公式派生列",
        pattern_key="formula_derivation",
        id_prefix="FC",
        review_question=(
            "部分列由相邻单元格或同列历史值按固定公式派生，"
            "需确认论文图表引用的是原始测量值还是派生值，并要求作者说明公式来源。"
        ),
        issue_category="consistency",
        context_only=False,
        is_pair_forensics=False,
        in_source_data_patterns=False,
        pattern_sort_order=None,
    )
)

# =============================================================================
# Visual forensics categories (image similarity and integrity detection)
# =============================================================================

COPY_MOVE_SINGLE = register(
    FindingCategoryDefinition(
        category="copy_move_single",
        label="单图内局部相似",
        pattern_key="visual_forensics",
        id_prefix="VFC",
        review_question=(
            "单图内检测到局部区域相似，需确认是否为同一主体、合法复用或导出伪影。"
        ),
        issue_category="matching",
        context_only=False,
        is_pair_forensics=False,
        in_source_data_patterns=False,
        pattern_sort_order=None,
    )
)

COPY_MOVE_CROSS = register(
    FindingCategoryDefinition(
        category="copy_move_cross",
        label="跨图局部相似",
        pattern_key="visual_forensics",
        id_prefix="VFC",
        review_question=(
            "跨图检测到局部区域相似，需确认是否为同一主体、合法复用或导出伪影。"
        ),
        issue_category="matching",
        context_only=False,
        is_pair_forensics=False,
        in_source_data_patterns=False,
        pattern_sort_order=None,
    )
)

EXACT_DUPLICATE = register(
    FindingCategoryDefinition(
        category="exact_duplicate",
        label="字节级完全重复",
        pattern_key="visual_forensics",
        id_prefix="VFC",
        review_question=(
            "检测到字节级完全相同图像，需确认是否为同一图像的不同引用或合法复用。"
        ),
        issue_category="matching",
        context_only=True,
        is_pair_forensics=False,
        in_source_data_patterns=False,
        pattern_sort_order=None,
    )
)

DHASH_SIMILAR = register(
    FindingCategoryDefinition(
        category="dhash_similar",
        label="感知哈希相似",
        pattern_key="visual_forensics",
        id_prefix="VFC",
        review_question=(
            "检测到感知哈希相似的图像，需确认是否为同一主体的不同处理版本或合法复用。"
        ),
        issue_category="matching",
        context_only=True,
        is_pair_forensics=False,
        in_source_data_patterns=False,
        pattern_sort_order=None,
    )
)

OVERLAP_REUSE_CROSS_PANEL = register(
    FindingCategoryDefinition(
        category="overlap_reuse_cross_panel",
        label="跨 Panel 局部重叠",
        pattern_key="visual_forensics",
        id_prefix="VFC",
        review_question=(
            "跨 Panel 检测到局部区域重叠，需确认是否为同一主体的裁剪复用或导出伪影。"
        ),
        issue_category="matching",
        context_only=False,
        is_pair_forensics=False,
        in_source_data_patterns=False,
        pattern_sort_order=None,
    )
)

FORGED_REGION_SUSPICIOUS = register(
    FindingCategoryDefinition(
        category="forged_region_suspicious",
        label="区域完整性记录",
        pattern_key="visual_forensics",
        id_prefix="VFC",
        review_question=("检测到区域完整性差异，需确认是否为常规图像编辑或导出伪影。"),
        issue_category="matching",
        context_only=False,
        is_pair_forensics=False,
        in_source_data_patterns=False,
        pattern_sort_order=None,
    )
)

# =============================================================================
# PaperFraud categories (rule-based detection from external tool)
# =============================================================================

PAPERFRAUD_METHODOLOGY_REVIEW = register(
    FindingCategoryDefinition(
        category="paperfraud.methodology_review",
        label="方法学提示",
        pattern_key="paperfraud.methodology_review",
        id_prefix="PMR",
        review_question=(
            "PaperFraud 规则库提示方法学问题，需确认论文方法描述是否完整且可复现。"
        ),
        issue_category="completeness",
        context_only=True,
        is_pair_forensics=False,
        in_source_data_patterns=False,
        pattern_sort_order=None,
    )
)

PAPERFRAUD_FRAUD_DETECTION = register(
    FindingCategoryDefinition(
        category="paperfraud.fraud_detection",
        label="数值取证提示",
        pattern_key="paperfraud.fraud_detection",
        id_prefix="PFD",
        review_question=(
            "PaperFraud 规则库提示数值取证问题，"
            "需确认论文数值是否可由原始数据和统计流程解释。"
        ),
        issue_category="matching",
        context_only=False,
        is_pair_forensics=False,
        in_source_data_patterns=False,
        pattern_sort_order=None,
    )
)

# =============================================================================
# PaperConan detector categories (WP4: PaperConan 独有 detector 深度接入)
# =============================================================================
# GRIM/GRIMMER have applicability_premise gating in review_question text:
# they only apply when the integer-valued premise holds or is pending
# confirmation. They must not conclude against continuous measurements.

GRIM_INCONSISTENT = register(
    FindingCategoryDefinition(
        category="grim_inconsistent",
        label="GRIM 不一致",
        pattern_key="grim_inconsistent",
        id_prefix="GRIM",
        review_question=(
            "GRIM 检测报告的均值/比例与样本量 n 在整数计数下不一致。"
            "仅在数据确为整数计数（integer-valued premise）成立或待确认时进入复核，"
            "不可对连续测量下确定性结论。"
            "需确认报告值是否可由整数 n 计算得到。"
        ),
        issue_category="consistency",
        context_only=False,
        is_pair_forensics=False,
        in_source_data_patterns=False,
        pattern_sort_order=None,
    )
)

GRIMMER_INCONSISTENT = register(
    FindingCategoryDefinition(
        category="grimmer_inconsistent",
        label="GRIMMER 不一致",
        pattern_key="grimmer_inconsistent",
        id_prefix="GRMR",
        review_question=(
            "GRIMMER 检测报告的方差/标准差与样本量 n 在整数计数下不一致。"
            "仅在数据确为整数计数（integer-valued premise）成立或待确认时进入复核，"
            "不可对连续测量下确定性结论。"
            "需确认离散度指标是否可由整数 n 计算得到。"
        ),
        issue_category="consistency",
        context_only=False,
        is_pair_forensics=False,
        in_source_data_patterns=False,
        pattern_sort_order=None,
    )
)

LAST_DIGIT_CHI_SQUARE = register(
    FindingCategoryDefinition(
        category="last_digit_chi_square",
        label="末位数字卡方检验异常",
        pattern_key="last_digit_chi_square",
        id_prefix="LDX",
        review_question=(
            "末位数字分布偏离均匀分布（卡方检验显著，BH-FDR 校正后），"
            "需确认数据是否为真实测量或存在人为构造/修约。"
        ),
        issue_category="consistency",
        context_only=False,
        is_pair_forensics=False,
        in_source_data_patterns=False,
        pattern_sort_order=None,
    )
)

ROW_PAIR_DIGIT_COUPLING = register(
    FindingCategoryDefinition(
        category="row_pair_digit_coupling",
        label="行对数字耦合",
        pattern_key="row_pair_digit_coupling",
        id_prefix="RPD",
        review_question=(
            "行对之间数字位存在异常耦合（如末位/十位同步变化），"
            "需确认是否为独立测量或复制-微调痕迹。"
        ),
        issue_category="consistency",
        context_only=False,
        is_pair_forensics=False,
        in_source_data_patterns=False,
        pattern_sort_order=None,
    )
)

INTEGER_DIFF_SHARED_FRACTION = register(
    FindingCategoryDefinition(
        category="integer_diff_shared_fraction",
        label="整数差共享小数",
        pattern_key="integer_diff_shared_fraction",
        id_prefix="IDS",
        review_question=(
            "数值对之间整数部分不同但小数部分完全相同，"
            "需确认是否为复制-修改整数部分或合法独立测量。"
        ),
        issue_category="consistency",
        context_only=False,
        is_pair_forensics=False,
        in_source_data_patterns=False,
        pattern_sort_order=None,
    )
)

PARTIAL_CONSTANT_OFFSET = register(
    FindingCategoryDefinition(
        category="partial_constant_offset",
        label="部分固定偏移",
        pattern_key="partial_constant_offset",
        id_prefix="PCO",
        review_question=(
            "列对之间部分行呈固定偏移而其他行不呈该关系，"
            "需确认是否为合法派生关系或选择性复制。"
        ),
        issue_category="consistency",
        context_only=False,
        is_pair_forensics=False,
        in_source_data_patterns=False,
        pattern_sort_order=None,
    )
)

CROSS_SHEET_DECIMAL_TAIL_REUSE_PAPERCONAN = register(
    FindingCategoryDefinition(
        category="cross_sheet_decimal_tail_reuse",
        label="跨 Sheet 小数尾部复用（PaperConan）",
        pattern_key="cross_sheet_decimal_tail_reuse",
        id_prefix="CDT",
        review_question=(
            "PaperConan 检测到不同 sheet 的数值序列复用小数尾部，"
            "需确认这些 figure 是否独立以及原始未舍入值是否支持该模式。"
        ),
        issue_category="consistency",
        context_only=False,
        is_pair_forensics=False,
        in_source_data_patterns=False,
        pattern_sort_order=None,
    )
)

WITHIN_TABLE_FRACTION_REUSE = register(
    FindingCategoryDefinition(
        category="within_table_fraction_reuse",
        label="表内小数复用",
        pattern_key="within_table_fraction_reuse",
        id_prefix="WTF",
        review_question=(
            "同一表内多个数值复用相同的小数/分数模式，"
            "需确认是否为固定分母、归一化或独立测量。"
        ),
        issue_category="consistency",
        context_only=False,
        is_pair_forensics=False,
        in_source_data_patterns=False,
        pattern_sort_order=None,
    )
)

RECURRING_ROW_VECTOR = register(
    FindingCategoryDefinition(
        category="recurring_row_vector",
        label="循环行向量",
        pattern_key="recurring_row_vector",
        id_prefix="RRV",
        review_question=(
            "多行出现相同或高度相似的数值向量模式，"
            "需确认是否为独立样本、模板行或批量填充。"
        ),
        issue_category="consistency",
        context_only=False,
        is_pair_forensics=False,
        in_source_data_patterns=False,
        pattern_sort_order=None,
    )
)
