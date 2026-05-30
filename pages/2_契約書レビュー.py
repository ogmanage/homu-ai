import streamlit as st

from core.auth import require_auth
from core.claude_client import call_claude_structured
from core.file_parser import parse_uploaded_file
from core.models import ReviewResult, RiskLevel
from core.prompts import REVIEW_SYSTEM_PROMPT, build_review_prompt

st.set_page_config(page_title="契約書レビュー | 法務AI", page_icon="🔍", layout="wide")
require_auth()

# ─── Constants ───────────────────────────────────────────────────────────────

GRADE_CONFIG = {
    "A": ("🟢", "#21C55D", "リスク極めて低"),
    "B": ("🟡", "#F59E0B", "軽微なリスク"),
    "C": ("🟠", "#F97316", "要対処リスクあり"),
    "D": ("🔴", "#EF4444", "重大リスクあり"),
    "E": ("🚨", "#7F1D1D", "締結前に弁護士必須"),
}

RISK_COLOR = {
    RiskLevel.HIGH: "#EF4444",
    RiskLevel.MEDIUM: "#F97316",
    RiskLevel.LOW: "#21C55D",
}


def _risk_badge(level: RiskLevel) -> str:
    color = RISK_COLOR[level]
    return f'<span style="background:{color};color:white;padding:2px 10px;border-radius:12px;font-size:0.8rem;font-weight:bold">{level.value}</span>'


# ─── Page ────────────────────────────────────────────────────────────────────

st.title("🔍 契約書レビュー")
st.caption("PDF・Word・テキストファイルをアップロードしてAIがリスク分析します。")

st.divider()

# ─── Upload ──────────────────────────────────────────────────────────────────

uploaded = st.file_uploader(
    "契約書をアップロード（PDF / Word / テキスト）",
    type=["pdf", "docx", "txt"],
    help="最大20MBまで対応。スキャンPDFはテキスト抽出できません。",
)

if uploaded:
    col_info, col_btn = st.columns([3, 1])
    with col_info:
        size_kb = uploaded.size / 1024
        st.info(f"📄 **{uploaded.name}** — {size_kb:.1f} KB")
    with col_btn:
        start_btn = st.button("🔍 レビュー開始", type="primary", use_container_width=True)
else:
    start_btn = False

# ─── Review execution ────────────────────────────────────────────────────────

if start_btn and uploaded:
    # Parse file
    try:
        contract_text = parse_uploaded_file(uploaded)
    except ValueError as e:
        st.error(f"ファイルの読み込みに失敗しました。\n{e}")
        st.stop()

    if "⚠️ [注意] 文字数制限" in contract_text:
        st.warning("契約書が長いため末尾が省略されています。重要な条項が末尾にある場合はご注意ください。")

    # Call Claude
    with st.spinner("AIがレビュー中です... （10〜30秒かかる場合があります）"):
        try:
            result: ReviewResult = call_claude_structured(
                system=REVIEW_SYSTEM_PROMPT,
                user=build_review_prompt(contract_text),
                model_cls=ReviewResult,
                max_tokens=4096,
            )
        except ValueError as e:
            st.error(f"AIのレスポンス解析に失敗しました。もう一度お試しください。")
            with st.expander("デバッグ情報（開発者向け）"):
                st.code(str(e))
            st.stop()

    st.success("レビューが完了しました。")
    st.divider()

    # ─── Overall Grade ───────────────────────────────────────────────────────
    icon, color, label = GRADE_CONFIG[result.overall_grade]
    st.markdown(
        f"""
        <div style='background:{color}15;border:2px solid {color};border-radius:12px;padding:20px 28px;margin-bottom:16px;'>
            <div style='font-size:3rem;font-weight:bold;color:{color};'>{icon} 総合評価: {result.overall_grade}</div>
            <div style='font-size:1.1rem;color:{color};font-weight:600;margin-bottom:8px;'>{label}</div>
            <div style='color:#374151;font-size:0.95rem;'>{result.grade_reason}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ─── Risk Summary Table ──────────────────────────────────────────────────
    st.subheader(f"リスク一覧（{len(result.risk_items)} 件）")

    if result.risk_items:
        # Build table data
        import pandas as pd
        rows = [
            {
                "カテゴリ": item.category,
                "リスクレベル": item.risk_level.value,
                "指摘事項": item.issue,
                "法的根拠": item.law_basis,
            }
            for item in result.risk_items
        ]
        df = pd.DataFrame(rows)

        def _style_risk(val):
            colors = {"高": "background-color:#FEE2E2;color:#991B1B;font-weight:bold",
                      "中": "background-color:#FEF3C7;color:#92400E;font-weight:bold",
                      "低": "background-color:#DCFCE7;color:#166534;font-weight:bold"}
            return colors.get(val, "")

        styled = df.style.applymap(_style_risk, subset=["リスクレベル"])
        st.dataframe(styled, use_container_width=True, hide_index=True)
    else:
        st.info("リスク項目は検出されませんでした。")

    st.divider()

    # ─── Risk Details with Expanders ─────────────────────────────────────────
    st.subheader("リスク詳細と修正案")

    for i, item in enumerate(result.risk_items, 1):
        icon_map = {RiskLevel.HIGH: "🔴", RiskLevel.MEDIUM: "🟡", RiskLevel.LOW: "🟢"}
        expander_label = f"{icon_map[item.risk_level]} [{item.risk_level.value}] {item.category} — {item.issue[:50]}{'...' if len(item.issue) > 50 else ''}"

        with st.expander(expander_label, expanded=(item.risk_level == RiskLevel.HIGH)):
            col_a, col_b = st.columns(2)
            with col_a:
                st.markdown("**現行条文**")
                if item.current_clause:
                    st.code(item.current_clause, language=None)
                else:
                    st.caption("（該当条文なし / 条項自体が欠如）")

            with col_b:
                st.markdown("**修正提案**")
                st.success(item.suggested_clause)

            st.markdown(f"**修正理由**: {item.reason}")
            st.caption(f"法的根拠: {item.law_basis}")

    # ─── General Notes ───────────────────────────────────────────────────────
    if result.general_notes:
        st.divider()
        st.subheader("総合所見")
        st.info(result.general_notes)

    # ─── Disclaimer ──────────────────────────────────────────────────────────
    st.divider()
    st.warning(
        "⚠️ **免責事項**: 本レビュー結果はAIによる参考情報です。"
        "法律上の保証または弁護士の法的判断を代替するものではありません。"
        "重要な契約の締結前には必ず弁護士等の法律専門家にご確認ください。"
    )

elif not uploaded:
    # Help text when no file is uploaded
    st.markdown(
        """
        #### 使い方
        1. 上のアップロードボタンから契約書ファイルを選択してください
        2. **対応形式**: PDF（テキストPDFのみ）/ Word (.docx) / テキスト (.txt)
        3. 「レビュー開始」ボタンを押してください
        4. 10〜30秒でリスク分析結果が表示されます

        #### レビュー観点
        - 責任制限 / 損害賠償 / 契約解除
        - 知的財産権帰属 / 再委託 / 反社会的勢力排除
        - 秘密保持 / 支払条件 / 管轄裁判所・準拠法
        """
    )
