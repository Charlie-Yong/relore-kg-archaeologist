"""Generate publication-quality report figures from verified Phase 2 experiment JSONs."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import FancyBboxPatch

ROOT = Path(__file__).resolve().parents[1]
V2_DIR = ROOT / "evaluation/itsdangerous-v2-20261126"
V1_DIR = ROOT / "evaluation/itsdangerous-final-20261121"
FIG_DIR = ROOT / "reports/figures"
FONT_PATH = "/System/Library/Fonts/STHeiti Medium.ttc"


def setup_fonts() -> None:
    if Path(FONT_PATH).exists():
        font_manager.fontManager.addfont(FONT_PATH)
        prop = font_manager.FontProperties(fname=FONT_PATH)
        plt.rcParams["font.sans-serif"] = [prop.get_name(), "PingFang SC", "Heiti TC", "DejaVu Sans"]
    else:
        plt.rcParams["font.sans-serif"] = ["PingFang SC", "STHeiti", "Arial Unicode MS", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    plt.rcParams["figure.facecolor"] = "white"
    plt.rcParams["axes.facecolor"] = "#FAFBFD"
    plt.rcParams["axes.edgecolor"] = "#CBD5E1"
    plt.rcParams["axes.linewidth"] = 0.9


def load_data() -> dict:
    return {
        "scaling": json.loads((V2_DIR / "scaling-benchmark.json").read_text(encoding="utf-8")),
        "incremental": json.loads((V2_DIR / "incremental-summary.json").read_text(encoding="utf-8")),
        "extraction": json.loads((V2_DIR / "extraction-v2-summary.json").read_text(encoding="utf-8")),
        "pareto": json.loads((V2_DIR / "qa-pareto-summary.json").read_text(encoding="utf-8")),
        "unseen": json.loads((V2_DIR / "qa-unseen-summary.json").read_text(encoding="utf-8")),
        "blinker": json.loads((V2_DIR / "blinker-generalization.json").read_text(encoding="utf-8")),
        "qa_v1": json.loads((V1_DIR / "qa-summary.json").read_text(encoding="utf-8")),
    }


def _box(ax, x, y, w, h, title, body, fc="#EFF6FF", ec="#2563EB", title_color="#1E3A8A"):
    patch = FancyBboxPatch(
        (x, y), w, h,
        boxstyle="round,pad=0.012,rounding_size=0.018",
        facecolor=fc, edgecolor=ec, linewidth=1.6,
    )
    ax.add_patch(patch)
    ax.text(x + w / 2, y + h - 0.032, title, ha="center", va="top",
            fontsize=10.5, fontweight="bold", color=title_color)
    ax.text(x + w / 2, y + h / 2 - 0.018, body, ha="center", va="center",
            fontsize=8.6, color="#334155", linespacing=1.32)


def draw_fig1_architecture() -> None:
    fig, ax = plt.subplots(figsize=(13.2, 6.2), dpi=220)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    ax.text(0.5, 0.965, "HistoryKG 系统总体架构与工程优化主线（v2 期末增强版）",
            ha="center", va="top", fontsize=14, fontweight="bold", color="#0F172A")
    ax.text(0.5, 0.922, "官方历史冻结采集 -> Neo4j/FTS5 混合存储 -> 按需 Cypher 子图检索 -> 快速可追溯问答",
            ha="center", va="top", fontsize=9.8, color="#475569")

    # 4 vertical columns
    _box(ax, 0.02, 0.50, 0.22, 0.36, "1. 静态历史与 API 冻结采集",
         "• Git bare clone + Python AST\n  (只读静态解析，零目标代码执行)\n• GitHub REST + 分页元数据\n• 只读 GraphQL PR->Closes 采集\n• C5 SHA-256 内容锚点冻结",
         fc="#EEF2FF", ec="#4F46E5", title_color="#312E81")
    _box(ax, 0.27, 0.50, 0.22, 0.36, "2. 契约校验与混合存储",
         "• Pydantic 1.4.2 严格双层校验\n• Neo4j 5.26 显式图谱\n  (分批事务提交 + 范围索引)\n• apply_delta 增量演化\n• SQLite FTS5 trigram 全文/SHA索引",
         fc="#ECFEFF", ec="#0891B2", title_color="#164E63")
    _box(ax, 0.52, 0.50, 0.22, 0.36, "3. Cypher 按需子图检索引擎",
         "• 5 类问题意图识别\n• targeted_cypher_paths 定向遍历\n• 迭代加深 paths(hop=1..3)\n• IDF 权重 + 1-hop 决策扩展\n• 讨论 7500B / 总窗 12000B 配额",
         fc="#F0FDF4", ec="#16A34A", title_color="#14532D")
    _box(ax, 0.77, 0.50, 0.21, 0.36, "4. 可追溯生成与双模式 UI",
         "• PROMPT_V2 去噪抽取(0 bot 误报)\n• reasoning_effort=none 快速直答\n  (中位 3.40s / 17/17 满分)\n• 偏移校验逐句[1][2]原文证据\n• 假前提诚实拒答 + 4项遥测条",
         fc="#FFF7ED", ec="#EA580C", title_color="#7C2D12")

    for x0 in (0.242, 0.492, 0.742):
        ax.annotate("", xy=(x0 + 0.025, 0.68), xytext=(x0, 0.68),
                    arrowprops=dict(arrowstyle="-|>,head_width=0.4,head_length=0.6",
                                    lw=2.0, color="#64748B"))

    # Bottom cross-cutting validation band
    _box(ax, 0.02, 0.12, 0.96, 0.30, "横向工程保障、统计审计与端到端闭环指标（2026-11-26 实测）",
         "• 扩展性优化：10x 图谱（40,670 实体 / 116,740 关系）按需子图检索较全量快照提速 7.80x（P50: 23.52s -> 3.02s）\n"
         "• 增量演化与等价性：T1→T2→T3 增量 apply_delta 耗时 1.68s（对比全量重建 2.66s 提速 1.59x），指纹与数量 100% 一致\n"
         "• 泛化与公平对照：无硬编码改造一键迁移 pallets-eco/blinker（Closes=5, 12/13=92.3%）；Codex E 诚实双口径对照 + 8道未见题盲测（+27.3pp）",
         fc="#F8FAFC", ec="#475569", title_color="#0F172A")

    ax.annotate("", xy=(0.38, 0.495), xytext=(0.38, 0.43),
                arrowprops=dict(arrowstyle="<->", lw=1.4, color="#64748B"))
    ax.annotate("", xy=(0.63, 0.495), xytext=(0.63, 0.43),
                arrowprops=dict(arrowstyle="<->", lw=1.4, color="#64748B"))

    plt.tight_layout()
    fig.savefig(FIG_DIR / "fig1_architecture.png", dpi=220, bbox_inches="tight", pad_inches=0.2)
    plt.close(fig)


def draw_fig2_schema_and_evidence(data: dict) -> None:
    blinker = data["blinker"]
    b_ents = sum(blinker["entity_counts"].values())
    b_rels = sum(blinker["relation_counts"].values())

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13.4, 5.8), dpi=220,
                                    gridspec_kw={"width_ratios": [1.15, 1.0]})

    # Left: Schema topology
    ax1.set_xlim(0, 1)
    ax1.set_ylim(0, 1)
    ax1.axis("off")
    ax1.set_title("A. 知识图谱 9 类实体与核心关系拓扑", fontsize=12, fontweight="bold", color="#0F172A", pad=10)

    nodes = [
        ("Issue", 0.05, 0.72, 0.20, 0.14, "#DBEAFE", "#2563EB"),
        ("PullRequest", 0.39, 0.72, 0.22, 0.14, "#DBEAFE", "#2563EB"),
        ("Commit", 0.73, 0.72, 0.22, 0.14, "#E0E7FF", "#4F46E5"),
        ("Decision", 0.05, 0.40, 0.20, 0.14, "#FEF3C7", "#D97706"),
        ("File", 0.40, 0.40, 0.20, 0.14, "#DCFCE7", "#16A34A"),
        ("Release", 0.73, 0.40, 0.22, 0.14, "#FCE7F3", "#DB2777"),
        ("Developer", 0.05, 0.10, 0.20, 0.14, "#F3E8FF", "#9333EA"),
        ("Function", 0.40, 0.10, 0.20, 0.14, "#DCFCE7", "#15803D"),
        ("Project", 0.73, 0.10, 0.22, 0.14, "#F1F5F9", "#475569"),
    ]
    for label, x, y, w, h, fc, ec in nodes:
        p = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.008,rounding_size=0.02",
                           facecolor=fc, edgecolor=ec, lw=1.5)
        ax1.add_patch(p)
        ax1.text(x + w / 2, y + h / 2, label, ha="center", va="center",
                 fontsize=9.5, fontweight="bold", color="#0F172A")

    edges = [
        (0.39, 0.79, 0.255, 0.79, "Closes / ClaimsToClose"),
        (0.615, 0.79, 0.725, 0.79, "MergedAs"),
        (0.80, 0.715, 0.56, 0.545, "Touches"),
        (0.84, 0.715, 0.84, 0.545, "ReachableIn"),
        (0.50, 0.395, 0.50, 0.245, "Defines"),
        (0.15, 0.545, 0.15, 0.715, "ABOUT"),
        (0.18, 0.245, 0.42, 0.715, "Authored / Merged"),
        (0.84, 0.245, 0.84, 0.395, "HasRelease"),
    ]
    for x1, y1, x2, y2, lbl in edges:
        ax1.annotate("", xy=(x2, y2), xytext=(x1, y1),
                     arrowprops=dict(arrowstyle="-|>", lw=1.3, color="#475569"))
        ax1.text((x1 + x2) / 2, (y1 + y2) / 2 + 0.015, lbl, ha="center", va="bottom",
                 fontsize=7.6, color="#1E293B",
                 bbox=dict(boxstyle="round,pad=0.12", fc="white", ec="none", alpha=0.85))

    ax1.text(0.5, 0.01,
             f"双仓验证规模 — ItsDangerous: 4,067 实体 / 11,674 关系 | Blinker: {b_ents:,} 实体 / {b_rels:,} 关系",
             ha="center", va="bottom", fontsize=8.4, color="#334155", fontweight="bold")

    # Right: 5-tier provenance strength + real PR #152 path
    ax2.set_xlim(0, 1)
    ax2.set_ylim(0, 1)
    ax2.axis("off")
    ax2.set_title("B. 证据强弱分级体系与可追溯路径实例", fontsize=12, fontweight="bold", color="#0F172A", pad=10)

    tiers = [
        ("[官方API]", "merged=true / GraphQL Closes / Release 元数据 (最高权威)", "#DCFCE7", "#15803D", 0.79),
        ("[Git实证]", "merge_commit_sha diff / tag ancestor 标签可达验证", "#DBEAFE", "#1D4ED8", 0.65),
        ("[AST静态]", "Python AST 提取类与函数签名边界 (zero code exec)", "#E0E7FF", "#4338CA", 0.51),
        ("[文本声称]", "PR 正文 Closes #146 等正则线索 (需与官方Closes区分)", "#FEF3C7", "#B45309", 0.37),
        ("[LLM抽取]", "PROMPT_V2 决定与理由实体 + 原文偏移锚点", "#FCE7F3", "#BE185D", 0.23),
    ]
    for tag, desc, fc, ec, y in tiers:
        p = FancyBboxPatch((0.03, y), 0.94, 0.105, boxstyle="round,pad=0.006,rounding_size=0.015",
                           facecolor=fc, edgecolor=ec, lw=1.3)
        ax2.add_patch(p)
        ax2.text(0.055, y + 0.052, tag, ha="left", va="center", fontsize=9.2, fontweight="bold", color=ec)
        ax2.text(0.24, y + 0.052, desc, ha="left", va="center", fontsize=8.3, color="#1E293B")

    _box(ax2, 0.03, 0.02, 0.94, 0.175, "端到端多跳溯源实例 (ItsDangerous simplejson 移除问题)",
         "Decision(弃用 simplejson) -[ABOUT]-> Issue #146 <-[ClaimsToClose]- PR #152\n"
         "-[MergedAs]-> Commit(981ade6e) -[Touches]-> src/itsdangerous/_json.py\n"
         "-[ReachableIn]-> Release(2.0.0) [Git实证 + 官方API 交叉验证]",
         fc="#F8FAFC", ec="#334155", title_color="#0F172A")

    plt.tight_layout()
    fig.savefig(FIG_DIR / "fig2_schema_and_evidence_chain.png", dpi=220, bbox_inches="tight", pad_inches=0.2)
    plt.close(fig)


def draw_fig3_extraction(data: dict) -> None:
    ext = data["extraction"]
    o1, o2 = ext["orig30"]["v1"], ext["orig30"]["v2"]
    h1, h2 = ext["heldout20"]["v1"], ext["heldout20"]["v2"]

    # Conditional points for heldout20 (1 unresolved ref disclosed explicitly)
    def cond(arm):
        tp, fp, fn = arm["tp"], arm["fp"], arm["fn"]
        p = tp / (tp + fp)
        r = tp / (tp + fn)
        f1 = 2 * tp / (2 * tp + fp + fn)
        rat = arm["rationale_covered"] / arm["rationale_eligible"]
        return [p * 100, r * 100, f1 * 100, rat * 100]

    o1_vals = [o1["precision"] * 100, o1["recall"] * 100, o1["f1"] * 100, o1["rationale_coverage"] * 100]
    o2_vals = [o2["precision"] * 100, o2["recall"] * 100, o2["f1"] * 100, o2["rationale_coverage"] * 100]
    h1_vals = cond(h1)
    h2_vals = cond(h2)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13.2, 5.4), dpi=220,
                                    gridspec_kw={"width_ratios": [1.3, 1.0]})

    labels = ["Precision", "Recall", "F1", "Rationale 覆盖"]
    x = list(range(len(labels)))
    w = 0.19
    b1 = ax1.bar([i - 1.5 * w for i in x], o1_vals, w, label="orig30 Prompt v1", color="#94A3B8")
    b2 = ax1.bar([i - 0.5 * w for i in x], o2_vals, w, label="orig30 Prompt v2", color="#2563EB")
    b3 = ax1.bar([i + 0.5 * w for i in x], h1_vals, w, label="heldout20 v1 (条件统计*)", color="#CBD5E1", hatch="//", edgecolor="#64748B")
    b4 = ax1.bar([i + 1.5 * w for i in x], h2_vals, w, label="heldout20 v2 (条件统计*)", color="#059669", hatch="//", edgecolor="#065F46")

    for bars in (b1, b2, b3, b4):
        for bar in bars:
            val = bar.get_height()
            ax1.text(bar.get_x() + bar.get_width() / 2, val + 1.2, f"{val:.1f}%",
                     ha="center", va="bottom", fontsize=7.3, color="#0F172A")

    ax1.set_xticks(x)
    ax1.set_xticklabels(labels, fontsize=9.8)
    ax1.set_ylim(0, 95)
    ax1.set_ylabel("百分比 (%)", fontsize=10)
    ax1.set_title("A. Prompt v1 vs v2 抽取与理由覆盖率对比（双数据集）", fontsize=11.5, fontweight="bold")
    ax1.grid(axis="y", linestyle="--", alpha=0.45)
    ax1.legend(loc="upper right", fontsize=8.2, frameon=True)
    ax1.text(0.01, 0.96, "*heldout20 含 1 条 unresolved_ref（仅基于已解析 14 条金标准计算条件比率）",
             transform=ax1.transAxes, va="top", fontsize=7.6, color="#475569")

    # Right: FP Breakdown
    arms = ["orig30\nv1", "orig30\nv2", "heldout20\nv1", "heldout20\nv2"]
    errs = [
        ext["orig30"]["v1_errors"]["fp_breakdown"],
        ext["orig30"]["v2_errors"]["fp_breakdown"],
        ext["heldout20"]["v1_errors"]["fp_breakdown"],
        ext["heldout20"]["v2_errors"]["fp_breakdown"],
    ]
    cats = [
        ("bot_bump", "机器人/Dependabot 误报", "#EF4444"),
        ("plain_bug_or_nondecision", "普通 Bug/非决定", "#F59E0B"),
        ("status_mismatch", "proposed/accepted 误判", "#6366F1"),
        ("other_fp", "其他误报", "#64748B"),
    ]
    bottom = [0] * 4
    for key, cname, color in cats:
        vals = [e.get(key, 0) for e in errs]
        ax2.bar(arms, vals, 0.52, bottom=bottom, label=cname, color=color)
        for i, v in enumerate(vals):
            if v > 0:
                ax2.text(i, bottom[i] + v / 2, str(v), ha="center", va="center",
                         color="white", fontsize=9, fontweight="bold")
        bottom = [b + v for b, v in zip(bottom, vals)]
    for i, tot in enumerate(bottom):
        ax2.text(i, tot + 0.35, f"总FP={tot}", ha="center", va="bottom",
                 fontsize=8.6, fontweight="bold", color="#0F172A")

    ax2.set_ylim(0, max(bottom) + 3.2)
    ax2.set_ylabel("误报条数 (False Positives)", fontsize=10)
    ax2.set_title("B. 误报类型拆解：v2 彻底消除 Bot 依赖升级噪声", fontsize=11.5, fontweight="bold")
    ax2.grid(axis="y", linestyle="--", alpha=0.45)
    ax2.legend(loc="upper right", fontsize=8.2, frameon=True)

    plt.tight_layout()
    fig.savefig(FIG_DIR / "fig3_extraction_v2.png", dpi=220, bbox_inches="tight", pad_inches=0.2)
    plt.close(fig)


def draw_fig4_qa_pareto_and_unseen(data: dict) -> None:
    pareto = data["pareto"]
    unseen = data["unseen"]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13.6, 5.6), dpi=220,
                                    gridspec_kw={"width_ratios": [1.08, 1.12]})

    # Left: Pareto Frontier (common 6 questions)
    fb = pareto["frozen_baselines"]
    vp = pareto["v2_pareto_arms"]
    e_valid = pareto["codex_e_audit"]["valid_prose_4"]

    points = [
        ("O 纯大模型", fb["O"]["median_seconds"], fb["O"]["accuracy"] * 100, "#94A3B8", "o", (8, -4)),
        ("A_v1 纯文本", fb["A"]["median_seconds"], fb["A"]["accuracy"] * 100, "#64748B", "s", (8, -6)),
        ("B_v1 深度思考", fb["B"]["median_seconds"], fb["B"]["accuracy"] * 100, "#38BDF8", "o", (-68, -22)),
        ("C 双检索", fb["C"]["median_seconds"], fb["C"]["accuracy"] * 100, "#818CF8", "^", (-30, 12)),
        ("D 双证据极重", fb["D"]["median_seconds"], fb["D"]["accuracy"] * 100, "#4F46E5", "D", (-88, -22)),
        ("Codex E (全部6题)", fb["E"]["median_seconds"], fb["E"]["accuracy"] * 100, "#F97316", "X", (-92, 12)),
        ("Codex E (仅有效4题)", e_valid["median_seconds"], e_valid["accuracy"] * 100, "#EA580C", "P", (-96, -34)),
        ("B_v2_low 低思考", vp["B_v2_fast_low"]["median_seconds"], vp["B_v2_fast_low"]["accuracy"] * 100, "#059669", "s", (4, 10)),
        ("B_v2_fast (无思考最优)", vp["B_v2_fast_nothink"]["median_seconds"], vp["B_v2_fast_nothink"]["accuracy"] * 100, "#DC2626", "*", (-12, -28)),
    ]
    for name, lat, acc, col, marker, offset in points:
        sz = 230 if marker == "*" else 85
        ax1.scatter([lat], [acc], color=col, marker=marker, s=sz, zorder=5, edgecolors="white", linewidth=0.9)
        ax1.annotate(
            f"{name}\n({acc:.1f}%, {lat:.1f}s)",
            xy=(lat, acc), xytext=offset, textcoords="offset points",
            fontsize=7.6, fontweight="bold" if "B_v2_fast" in name else "normal",
            color="#991B1B" if "B_v2_fast" in name else "#1E293B",
            arrowprops=dict(arrowstyle="-", lw=0.7, color="#94A3B8"),
        )

    # Pareto curve highlight: B_v2_fast_nothink -> B_v2_fast_low -> D
    p_x = [vp["B_v2_fast_nothink"]["median_seconds"], vp["B_v2_fast_low"]["median_seconds"], fb["D"]["median_seconds"]]
    p_y = [100.0, 100.0, 100.0]
    ax1.plot(p_x, p_y, linestyle="--", color="#DC2626", linewidth=1.4, alpha=0.65, label="100% 准确率 Pareto 最优线")

    ax1.set_xscale("log")
    ax1.set_xlim(1.6, 520)
    ax1.set_ylim(0, 118)
    ax1.set_xlabel("单题中位延迟 (秒, 对数坐标)", fontsize=10)
    ax1.set_ylabel("公共 6 题准确率 (%)", fontsize=10)
    ax1.set_title("A. 延迟-准确率 Pareto 前沿与 Codex E 双口径对比", fontsize=11.3, fontweight="bold")
    ax1.grid(True, which="both", linestyle="--", alpha=0.35)
    ax1.legend(loc="lower right", fontsize=8.2)

    # Right: Sealed Unseen 8Q
    u_arms = unseen["results"]
    qids = [r["id"] for r in u_arms["B_v2_fast"]["per_question"]]
    x = list(range(len(qids)))
    w = 0.26
    for idx, (arm_key, lbl, col) in enumerate([
        ("A_v2", f"A_v2 纯文本 ({u_arms['A_v2']['accuracy']*100:.1f}%, {u_arms['A_v2']['median_seconds']}s)", "#94A3B8"),
        ("B_v2_fast", f"B_v2_fast 图谱+子图 ({u_arms['B_v2_fast']['accuracy']*100:.1f}%, {u_arms['B_v2_fast']['median_seconds']}s)", "#2563EB"),
        ("B_v2_deep", f"B_v2_deep 深度思考 ({u_arms['B_v2_deep']['accuracy']*100:.1f}%, {u_arms['B_v2_deep']['median_seconds']}s)", "#0F766E"),
    ]):
        pcts = [r["score"] / r["max"] * 100 for r in u_arms[arm_key]["per_question"]]
        ax2.bar([i + (idx - 1) * w for i in x], pcts, w, label=lbl, color=col)

    ax2.set_xticks(x)
    ax2.set_xticklabels(["U1\n决策理由", "U2\n拒收边界", "U3\nPR改动", "U4\nPR改动2",
                         "U5\n发布日", "U6\n版本标签", "U7\n源码顺序", "U8\n假前提"], fontsize=8.1)
    ax2.set_ylim(0, 134)
    ax2.set_ylabel("单题得分率 (%)", fontsize=10)
    ax2.set_title("B. 8 道全新未见题盲测：B_v2_fast (+27.3pp vs A_v2)", fontsize=11.3, fontweight="bold")
    ax2.grid(axis="y", linestyle="--", alpha=0.45)
    ax2.legend(loc="upper right", fontsize=7.9, frameon=True)

    plt.tight_layout()
    fig.savefig(FIG_DIR / "fig4_qa_pareto_and_unseen.png", dpi=220, bbox_inches="tight", pad_inches=0.2)
    plt.close(fig)


def draw_fig5_scaling_incremental_blinker(data: dict) -> None:
    sc = data["scaling"]["scales"]
    inc = data["incremental"]["stages"]
    bl = data["blinker"]["qa_results"]

    fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(14.4, 4.9), dpi=220)

    # Panel 1: 1x/5x/10x scaling
    labels = ["1x\n(4k/12k)", "5x\n(20k/58k)", "10x\n(41k/117k)"]
    snap_p50 = [sc[k]["snapshot"]["overall_p50_ms"] / 1000 for k in ("1x", "5x", "10x")]
    cyp_p50 = [sc[k]["cypher_subgraph"]["overall_p50_ms"] / 1000 for k in ("1x", "5x", "10x")]
    x = [0, 1, 2]
    ax1.plot(x, snap_p50, "-o", color="#DC2626", lw=2.2, ms=7, label="全量 snapshot")
    ax1.plot(x, cyp_p50, "-s", color="#2563EB", lw=2.2, ms=7, label="按需 cypher_subgraph")
    for i, (sv, cv, k) in enumerate(zip(snap_p50, cyp_p50, ("1x", "5x", "10x"))):
        ax1.text(i, sv + 1.0, f"{sv:.2f}s", ha="center", fontsize=8.2, color="#991B1B", fontweight="bold")
        if i == 0:
            ax1.text(0.05, cv - 0.8, f"{cv:.2f}s ({sc[k]['speedup_p50']}x)",
                     ha="left", va="top", fontsize=8.0, color="#1E40AF", fontweight="bold")
        else:
            ax1.text(i, cv + 0.8, f"{cv:.2f}s ({sc[k]['speedup_p50']}x)",
                     ha="center", fontsize=8.0, color="#1E40AF", fontweight="bold")
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels, fontsize=9)
    ax1.set_xlim(-0.3, 2.35)
    ax1.set_ylim(-2.2, max(snap_p50) * 1.18)
    ax1.set_ylabel("检索 P50 延迟 (秒)", fontsize=9.8)
    ax1.set_title("A. 图谱规模扩展与提速倍数", fontsize=11, fontweight="bold")
    ax1.grid(True, linestyle="--", alpha=0.45)
    ax1.legend(loc="upper left", fontsize=8.2)

    # Panel 2: T1->T2->T3 Incremental vs Full Rebuild
    t_labels = ["T1 初始\n(<=2018-10)", "T2 增量\n(<=2021-05)", "T3 增量\n(全历史)"]
    ents = [inc["T1_initial"]["entities"], inc["T2_delta"]["entities"], inc["T3_delta"]["entities"]]
    rels = [inc["T1_initial"]["relations"], inc["T2_delta"]["relations"], inc["T3_delta"]["relations"]]
    lat_bar_x = [0, 1, 2]
    ax2.bar([i - 0.18 for i in lat_bar_x], ents, 0.34, label="实体数", color="#0EA5E9")
    ax2.bar([i + 0.18 for i in lat_bar_x], rels, 0.34, label="关系数", color="#6366F1")
    for i, (e, r) in enumerate(zip(ents, rels)):
        ax2.text(i - 0.18, e + 220, f"{e:,}", ha="center", fontsize=7.6)
        ax2.text(i + 0.18, r + 220, f"{r:,}", ha="center", fontsize=7.6)
    ax2.set_xticks(lat_bar_x)
    ax2.set_xticklabels(t_labels, fontsize=8.5)
    ax2.set_ylim(0, max(rels) * 1.24)
    ax2.set_ylabel("图谱对象数", fontsize=9.8)
    ax2.set_title("B. 时序增量演化 (100% 指纹等价)", fontsize=11, fontweight="bold")
    ax2.grid(axis="y", linestyle="--", alpha=0.45)
    ax2.legend(loc="upper left", fontsize=8.0)
    t3d = inc["T3_delta"]["delta_ms"] / 1000
    t3f = inc["T3_delta"]["full_rebuild_ms"] / 1000
    ax2.text(0.5, 0.78, f"T3 apply_delta={t3d:.2f}s vs 重建={t3f:.2f}s\n提速 {inc['T3_delta']['speedup_vs_full_rebuild']}x",
             transform=ax2.transAxes, ha="center", fontsize=8.0,
             bbox=dict(boxstyle="round,pad=0.3", fc="#EFF6FF", ec="#3B82F6"))

    # Panel 3: Blinker zero-code-change transfer
    bl_qids = [r["id"] for r in bl["B_v2_fast"]["per_question"]]
    bx = list(range(len(bl_qids)))
    a_pct = [r["score"] / r["max"] * 100 for r in bl["A_v2"]["per_question"]]
    b_pct = [r["score"] / r["max"] * 100 for r in bl["B_v2_fast"]["per_question"]]
    ax3.bar([i - 0.18 for i in bx], a_pct, 0.35, label=f"A_v2 ({bl['A_v2']['accuracy']*100:.1f}%, {bl['A_v2']['median_seconds']}s)", color="#94A3B8")
    ax3.bar([i + 0.18 for i in bx], b_pct, 0.35, label=f"B_v2_fast ({bl['B_v2_fast']['accuracy']*100:.1f}%, {bl['B_v2_fast']['median_seconds']}s)", color="#16A34A")
    ax3.set_xticks(bx)
    ax3.set_xticklabels(["BL1\n发布日", "BL2\nCloses链", "BL3\n版本", "BL4\nSignal源码", "BL5\n决定原因", "BL6\n假前提"], fontsize=8.0)
    ax3.set_ylim(0, 134)
    ax3.set_ylabel("得分率 (%)", fontsize=9.8)
    ax3.set_title("C. 第二仓库 blinker 零改代码迁移", fontsize=11, fontweight="bold")
    ax3.grid(axis="y", linestyle="--", alpha=0.45)
    ax3.legend(loc="upper right", fontsize=7.8, frameon=True)

    plt.tight_layout()
    fig.savefig(FIG_DIR / "fig5_generalization_evolution.png", dpi=220, bbox_inches="tight", pad_inches=0.2)
    plt.close(fig)


def main() -> None:
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    setup_fonts()
    data = load_data()
    draw_fig1_architecture()
    draw_fig2_schema_and_evidence(data)
    draw_fig3_extraction(data)
    draw_fig4_qa_pareto_and_unseen(data)
    draw_fig5_scaling_incremental_blinker(data)
    print("QA_V1_TOTALS=", json.dumps({k: v["all"] for k, v in data["qa_v1"]["totals"].items()}, ensure_ascii=False))
    print("GENERATED_FIGURES=", sorted(p.name for p in FIG_DIR.glob("fig*.png")))


if __name__ == "__main__":
    main()
