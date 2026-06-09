import streamlit as st

from core.auth import require_auth
from core.claude_client import call_claude_structured
from core.doc_generator import draft_to_docx, draft_to_pdf, preprocess_markdown
from core.file_parser import parse_uploaded_file
from core.models import ContractDraft, ReviewResult, RiskLevel
from core.prompts import (
    REVIEW_SYSTEM_PROMPT,
    REVISE_SYSTEM_PROMPT,
    build_review_prompt,
    build_revise_prompt,
)

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

# ─── Session state init ──────────────────────────────────────────────────────

for key, default in [
    ("review_result", None),
    ("review_contract_text", ""),
    ("revised_draft", None),
    ("auto_revision_text", ""),
    ("review_edited_body", ""),
]:
    if key not in st.session_state:
        st.session_state[key] = default

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
    # Reset previous results when new file is uploaded
    st.session_state["review_result"] = None
    st.session_state["revised_draft"] = None
    st.session_state["auto_revision_text"] = ""

    try:
        contract_text = parse_uploaded_file(uploaded)
    except ValueError as e:
        st.error(f"ファイルの読み込みに失敗しました。\n{e}")
        st.stop()

    if "⚠️ [注意] 文字数制限" in contract_text:
        st.warning("契約書が長いため末尾が省略されています。重要な条項が末尾にある場合はご注意ください。")

    with st.spinner("AIがレビュー中です... （10〜30秒かかる場合があります）"):
        try:
            result: ReviewResult = call_claude_structured(
                system=REVIEW_SYSTEM_PROMPT,
                user=build_review_prompt(contract_text),
                model_cls=ReviewResult,
                max_tokens=4096,
            )
        except ValueError as e:
            st.error("AIのレスポンス解析に失敗しました。もう一度お試しください。")
            with st.expander("デバッグ情報（開発者向け）"):
                st.code(str(e))
            st.stop()

    # Auto-generate revision suggestions from risk items
    suggestions = []
    for item in result.risk_items:
        if item.risk_level in (RiskLevel.HIGH, RiskLevel.MEDIUM):
            suggestions.append(f"・{item.category}：{item.issue}")
    if suggestions:
        st.session_state["auto_revision_text"] = (
            "以下のリスク項目を修正してください：\n" + "\n".join(suggestions)
        )

    st.session_state["review_result"] = result
    st.session_state["review_contract_text"] = contract_text
    st.rerun()

# ─── Display review results ──────────────────────────────────────────────────

result: ReviewResult | None = st.session_state["review_result"]

if result:
    st.success("レビューが完了しました。")
    st.divider()

    # Overall Grade
    icon, color, label = GRADE_CONFIG[result.overall_grade]
    st.markdown(
        f"""
        <div style='background:{color}15;border:2px solid {color};border-radius:12px;
                    padding:20px 28px;margin-bottom:16px;'>
            <div style='font-size:3rem;font-weight:bold;color:{color};'>
                {icon} 総合評価: {result.overall_grade}
            </div>
            <div style='font-size:1.1rem;color:{color};font-weight:600;margin-bottom:8px;'>{label}</div>
            <div style='color:#374151;font-size:0.95rem;'>{result.grade_reason}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Risk Summary Table
    st.subheader(f"リスク一覧（{len(result.risk_items)} 件）")

    if result.risk_items:
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
            colors = {
                "高": "background-color:#FEE2E2;color:#991B1B;font-weight:bold",
                "中": "background-color:#FEF3C7;color:#92400E;font-weight:bold",
                "低": "background-color:#DCFCE7;color:#166534;font-weight:bold",
            }
            return colors.get(val, "")

        try:
            styled = df.style.map(_style_risk, subset=["リスクレベル"])
        except AttributeError:
            styled = df.style.applymap(_style_risk, subset=["リスクレベル"])
        st.dataframe(styled, use_container_width=True, hide_index=True)
    else:
        st.info("リスク項目は検出されませんでした。")

    st.divider()

    # Risk Details
    st.subheader("リスク詳細と修正案")
    for item in result.risk_items:
        icon_map = {RiskLevel.HIGH: "🔴", RiskLevel.MEDIUM: "🟡", RiskLevel.LOW: "🟢"}
        label_str = (
            f"{icon_map[item.risk_level]} [{item.risk_level.value}] "
            f"{item.category} — {item.issue[:50]}{'...' if len(item.issue) > 50 else ''}"
        )
        with st.expander(label_str, expanded=(item.risk_level == RiskLevel.HIGH)):
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

    if result.general_notes:
        st.divider()
        st.subheader("総合所見")
        st.info(result.general_notes)

    # ─── 修正して再生成 ────────────────────────────────────────────────────
    st.divider()
    st.subheader("✏️ 修正版を生成する")
    st.caption(
        "レビュー結果をもとにAIが修正版の契約書を生成します。"
        "指示を編集・追記して「修正版を生成する」を押してください。"
    )

    revision_input = st.text_area(
        "修正指示",
        value=st.session_state["auto_revision_text"],
        label_visibility="collapsed",
        height=160,
        placeholder="例：責任制限条項を追加してください。損害賠償の上限を契約金額と同額に設定してください。",
        key="review_revision_input",
    )

    col_gen, col_clr, _ = st.columns([3, 2, 3])
    with col_gen:
        gen_btn = st.button(
            "✏️ 修正版を生成する",
            type="primary",
            use_container_width=True,
            disabled=not bool(revision_input),
        )
    with col_clr:
        if st.button("🗑️ 指示をリセット", use_container_width=True):
            st.session_state["auto_revision_text"] = ""
            st.session_state["revised_draft"] = None
            st.rerun()

    if gen_btn and revision_input:
        contract_text = st.session_state["review_contract_text"]
        with st.spinner("AIが修正版を生成中です... （20〜40秒かかります）"):
            try:
                st.session_state["revised_draft"] = call_claude_structured(
                    system=REVISE_SYSTEM_PROMPT,
                    user=build_revise_prompt(contract_text, revision_input),
                    model_cls=ContractDraft,
                    max_tokens=8192,
                )
                st.session_state["auto_revision_text"] = revision_input
                st.rerun()
            except ValueError as e:
                st.error("修正版の生成に失敗しました。もう一度お試しください。")
                with st.expander("エラー詳細"):
                    st.code(str(e))

    # ─── 修正版の表示 ────────────────────────────────────────────────────────
    revised: ContractDraft | None = st.session_state["revised_draft"]
    if revised:
        # 新規生成時はテキストを初期化
        if st.session_state.get("_last_revised_title") != revised.title + revised.body_markdown[:50]:
            st.session_state["review_edited_body"] = revised.body_markdown
            st.session_state["_last_revised_title"] = revised.title + revised.body_markdown[:50]

        st.divider()
        st.success(f"「{revised.title}」の修正版が生成されました。")

        safe = revised.title.replace(" ", "_").replace("/", "-")

        # ダウンロード用に編集済み本文を使うモデルを生成
        def _build_rev_draft() -> ContractDraft:
            return ContractDraft(
                title=revised.title,
                body_markdown=st.session_state["review_edited_body"],
                notes=revised.notes,
            )

        dl_word_col, dl_pdf_col, _, rst_col = st.columns([3, 3, 2, 1])
        with dl_word_col:
            try:
                st.download_button(
                    "⬇️ Word ダウンロード",
                    draft_to_docx(_build_rev_draft()),
                    f"{safe}_修正版.docx",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    use_container_width=True, type="primary",
                )
            except Exception as e:
                st.error(f"Word生成エラー: {e}")
        with dl_pdf_col:
            try:
                st.download_button(
                    "⬇️ PDF ダウンロード",
                    draft_to_pdf(_build_rev_draft()),
                    f"{safe}_修正版.pdf",
                    "application/pdf",
                    use_container_width=True, type="primary",
                )
            except Exception as e:
                st.error(f"PDF生成エラー: {e}")
        with rst_col:
            if st.button("🔄 再生成"):
                st.session_state["revised_draft"] = None
                st.session_state["review_edited_body"] = ""
                st.rerun()

        if revised.notes:
            st.markdown("---")
            for note in revised.notes:
                st.info(note)

        # ─── 直接編集エリア ───────────────────────────────────────────────
        st.markdown("---")
        st.subheader("📝 修正版を編集")
        st.caption("本文を直接編集できます。編集した内容でWord/PDFをダウンロードできます。")
        rev_edited = st.text_area(
            "rev_body_edit",
            value=st.session_state["review_edited_body"],
            label_visibility="collapsed",
            height=600,
            key="review_body_textarea",
        )
        if rev_edited != st.session_state["review_edited_body"]:
            st.session_state["review_edited_body"] = rev_edited

        # さらにAI修正
        st.markdown("---")
        st.subheader("✏️ さらにAIで修正する")
        st.caption("修正版に対して追加の修正指示を出せます。")
        further_input = st.text_area(
            "追加修正指示",
            label_visibility="collapsed",
            height=100,
            placeholder="例：第5条の支払条件を「納品後2週間以内」に変更してください。",
            key="further_revision_input",
        )
        if st.button("✏️ さらに修正する", type="primary", disabled=not bool(further_input)):
            with st.spinner("AIが修正中です..."):
                try:
                    st.session_state["revised_draft"] = call_claude_structured(
                        system=REVISE_SYSTEM_PROMPT,
                        user=build_revise_prompt(st.session_state["review_edited_body"], further_input),
                        model_cls=ContractDraft,
                        max_tokens=8192,
                    )
                    st.session_state["review_edited_body"] = ""
                    st.rerun()
                except ValueError as e:
                    st.error("修正に失敗しました。もう一度お試しください。")
                    with st.expander("エラー詳細"):
                        st.code(str(e))

    # Disclaimer
    st.divider()
    st.warning(
        "⚠️ **免責事項**: 本レビュー結果はAIによる参考情報です。"
        "法律上の保証または弁護士の法的判断を代替するものではありません。"
        "重要な契約の締結前には必ず弁護士等の法律専門家にご確認ください。"
    )

elif not uploaded:
    st.markdown(
        """
        #### 使い方
        1. 上のアップロードボタンから契約書ファイルを選択してください
        2. **対応形式**: PDF（テキストPDFのみ）/ Word (.docx) / テキスト (.txt)
        3. 「レビュー開始」ボタンを押してください
        4. 10〜30秒でリスク分析結果が表示されます
        5. レビュー結果をもとにAIが**修正版を自動生成**できます

        #### レビュー観点
        - 責任制限 / 損害賠償 / 契約解除
        - 知的財産権帰属 / 再委託 / 反社会的勢力排除
        - 秘密保持 / 支払条件 / 管轄裁判所・準拠法
        """
    )
