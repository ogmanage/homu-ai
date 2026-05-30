import streamlit as st

from core.auth import require_auth
from core.claude_client import call_claude_structured
from core.file_parser import parse_uploaded_file
from core.models import ComparisonResult, ClauseChange

from core.prompts import COMPARE_SYSTEM_PROMPT, build_compare_prompt

st.set_page_config(page_title="契約書比較 | 法務AI", page_icon="🔄", layout="wide")
require_auth()

st.title("🔄 契約書比較")
st.caption("旧版と新版の契約書をアップロードして変更点を分析します。")
st.divider()

# ─── File Upload ─────────────────────────────────────────────────────────────

col_old, col_new = st.columns(2, gap="large")

with col_old:
    st.subheader("旧契約書（変更前）")
    old_file = st.file_uploader(
        "旧版をアップロード",
        type=["pdf", "docx", "txt"],
        key="old_contract",
        label_visibility="collapsed",
    )
    if old_file:
        st.info(f"📄 {old_file.name} — {old_file.size / 1024:.1f} KB")

with col_new:
    st.subheader("新契約書（変更後）")
    new_file = st.file_uploader(
        "新版をアップロード",
        type=["pdf", "docx", "txt"],
        key="new_contract",
        label_visibility="collapsed",
    )
    if new_file:
        st.info(f"📄 {new_file.name} — {new_file.size / 1024:.1f} KB")

st.divider()

compare_btn = st.button(
    "🔄 比較・分析を開始",
    type="primary",
    disabled=(old_file is None or new_file is None),
)

if old_file is None or new_file is None:
    if not (old_file and new_file):
        missing = []
        if not old_file:
            missing.append("旧契約書")
        if not new_file:
            missing.append("新契約書")
        st.caption(f"※ {' / '.join(missing)} をアップロードしてください")

# ─── Comparison Execution ─────────────────────────────────────────────────────

if compare_btn and old_file and new_file:
    # Parse both files
    try:
        old_text = parse_uploaded_file(old_file)
    except ValueError as e:
        st.error(f"旧契約書の読み込みに失敗しました。\n{e}")
        st.stop()

    try:
        new_text = parse_uploaded_file(new_file)
    except ValueError as e:
        st.error(f"新契約書の読み込みに失敗しました。\n{e}")
        st.stop()

    with st.spinner("AIが2つの契約書を比較中です... （20〜40秒かかる場合があります）"):
        try:
            result: ComparisonResult = call_claude_structured(
                system=COMPARE_SYSTEM_PROMPT,
                user=build_compare_prompt(old_text, new_text),
                model_cls=ComparisonResult,
                max_tokens=4096,
            )
        except ValueError as e:
            st.error("比較分析に失敗しました。もう一度お試しください。")
            with st.expander("デバッグ情報（開発者向け）"):
                st.code(str(e))
            st.stop()

    st.success("比較分析が完了しました。")
    st.divider()

    # ─── Summary ─────────────────────────────────────────────────────────────
    st.subheader("比較サマリー")
    st.info(result.summary)

    # ─── Change Count Metrics ─────────────────────────────────────────────────
    additions = sum(1 for c in result.changes if c.change_type == "追加")
    deletions = sum(1 for c in result.changes if c.change_type == "削除")
    modifications = sum(1 for c in result.changes if c.change_type == "変更")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("総変更数", len(result.changes))
    m2.metric("追加", additions, delta=f"+{additions}" if additions else None)
    m3.metric("削除", deletions, delta=f"-{deletions}" if deletions else None, delta_color="inverse")
    m4.metric("変更", modifications)

    st.divider()

    # ─── Changes Table ────────────────────────────────────────────────────────
    if result.changes:
        st.subheader("変更点一覧")

        import pandas as pd
        rows = [
            {
                "条項": c.clause_number,
                "変更種別": c.change_type,
                "説明": c.explanation[:80] + ("..." if len(c.explanation) > 80 else ""),
            }
            for c in result.changes
        ]
        df = pd.DataFrame(rows)

        TYPE_STYLE = {
            "追加": "background-color:#DCFCE7;color:#166534;font-weight:bold",
            "削除": "background-color:#FEE2E2;color:#991B1B;font-weight:bold",
            "変更": "background-color:#FEF3C7;color:#92400E;font-weight:bold",
        }

        def _style_type(val):
            return TYPE_STYLE.get(val, "")

        st.dataframe(
            df.style.applymap(_style_type, subset=["変更種別"]),
            use_container_width=True,
            hide_index=True,
        )

        st.divider()

        # ─── Change Details ───────────────────────────────────────────────────
        st.subheader("変更詳細")

        CHANGE_ICON = {"追加": "🟢", "削除": "🔴", "変更": "🟡"}

        for change in result.changes:
            icon = CHANGE_ICON.get(change.change_type, "⚪")
            label = f"{icon} [{change.change_type}] {change.clause_number}"
            with st.expander(label):
                if change.change_type == "変更":
                    col_l, col_r = st.columns(2)
                    with col_l:
                        st.markdown("**変更前**")
                        st.markdown(
                            f'<div style="background:#FEE2E2;padding:10px;border-radius:6px;font-size:0.9rem;">'
                            f"{change.old_text or '（なし）'}</div>",
                            unsafe_allow_html=True,
                        )
                    with col_r:
                        st.markdown("**変更後**")
                        st.markdown(
                            f'<div style="background:#DCFCE7;padding:10px;border-radius:6px;font-size:0.9rem;">'
                            f"{change.new_text or '（なし）'}</div>",
                            unsafe_allow_html=True,
                        )
                elif change.change_type == "追加":
                    st.markdown("**追加された条文**")
                    st.markdown(
                        f'<div style="background:#DCFCE7;padding:10px;border-radius:6px;font-size:0.9rem;">'
                        f"{change.new_text or '（テキストなし）'}</div>",
                        unsafe_allow_html=True,
                    )
                elif change.change_type == "削除":
                    st.markdown("**削除された条文**")
                    st.markdown(
                        f'<div style="background:#FEE2E2;padding:10px;border-radius:6px;font-size:0.9rem;">'
                        f"{change.old_text or '（テキストなし）'}</div>",
                        unsafe_allow_html=True,
                    )

                st.markdown(f"**影響・説明**: {change.explanation}")

    # ─── Risk Assessment ──────────────────────────────────────────────────────
    st.divider()
    st.subheader("変更によるリスク評価")
    st.warning(result.risk_assessment)

    # ─── Disclaimer ───────────────────────────────────────────────────────────
    st.divider()
    st.warning(
        "⚠️ **免責事項**: 本比較結果はAIによる参考情報です。"
        "法律上の保証または弁護士の法的判断を代替するものではありません。"
        "契約変更の最終判断前には必ず弁護士等の法律専門家にご確認ください。"
    )

elif not (old_file and new_file):
    # Help text
    st.markdown(
        """
        #### 使い方
        1. 左に**旧契約書**（変更前）をアップロードしてください
        2. 右に**新契約書**（変更後）をアップロードしてください
        3. 「比較・分析を開始」ボタンを押してください

        #### 出力内容
        - 追加・削除・変更された条項の一覧
        - 各変更の法的影響の説明
        - 自社に不利な変更点の強調
        - 変更全体によるリスク評価

        #### 対応ファイル形式
        PDF（テキストPDFのみ）/ Word (.docx) / テキスト (.txt)
        """
    )
