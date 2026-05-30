import streamlit as st

from core.auth import require_auth
from core.claude_client import call_claude_structured
from core.doc_generator import draft_to_docx, draft_to_pdf
from core.models import ContractDraft
from core.prompts import DRAFT_SYSTEM_PROMPT, build_draft_prompt, REVISE_SYSTEM_PROMPT, build_revise_prompt

st.set_page_config(page_title="契約書作成 | 法務AI", page_icon="📝", layout="wide")
require_auth()

st.markdown("""
<style>
/* カードボタン（選択済み） */
div[data-testid="stButton"] button[kind="primary"] {
    height: 80px !important;
    border-radius: 14px !important;
    font-size: 0.85rem !important;
    font-weight: 700 !important;
    background: #1E3A5F !important;
    border: 2px solid #1E3A5F !important;
    color: white !important;
    line-height: 1.4 !important;
}
/* カードボタン（未選択） */
div[data-testid="stButton"] button[kind="secondary"] {
    height: 80px !important;
    border-radius: 14px !important;
    font-size: 0.85rem !important;
    font-weight: 500 !important;
    background: white !important;
    border: 2px solid #E2E8F0 !important;
    color: #374151 !important;
    line-height: 1.4 !important;
}
div[data-testid="stButton"] button[kind="secondary"]:hover {
    border-color: #93C5FD !important;
    background: #F8FAFF !important;
}
/* ステップ見出し */
.step { display:flex; align-items:center; gap:10px; margin:28px 0 14px; }
.snum { width:26px;height:26px;background:#1E3A5F;color:white;border-radius:50%;
        font-size:0.78rem;font-weight:700;display:flex;align-items:center;justify-content:center; }
.stitle { font-size:1rem;font-weight:700;color:#1E3A5F; }
.lbl { font-size:0.82rem;font-weight:600;color:#475569;margin-bottom:3px; }
.req { color:#EF4444; }
.hint { background:#F0F9FF;border-left:3px solid #38BDF8;padding:10px 14px;
        border-radius:0 8px 8px 0;font-size:0.83rem;color:#0369A1;margin:4px 0 18px; }
</style>
""", unsafe_allow_html=True)

# ─── データ ──────────────────────────────────────────────────────────────────
CONTRACT_OPTIONS = [
    ("🔒", "NDA",        "NDA（秘密保持契約）"),
    ("💼", "業務委託",    "業務委託契約"),
    ("💻", "SES",        "SES契約"),
    ("📋", "準委任",      "準委任契約"),
    ("🏗", "請負",        "請負契約"),
    ("📜", "利用規約",    "利用規約"),
    ("🛒", "売買",        "売買契約"),
    ("🤝", "パートナー",  "パートナー契約"),
    ("🏢", "業務提携",    "業務提携契約"),
    ("👥", "雇用",        "雇用契約"),
]

HINTS = {
    "NDA（秘密保持契約）": "秘密情報の定義・期間・競業避止の有無を「特記事項」に書くと精度が上がります。",
    "業務委託契約":        "成果物・検収条件・知的財産の帰属を「特記事項」に書くと詳細な条項が生成されます。",
    "SES契約":             "エンジニアの常駐提供契約です。スキル要件・常駐場所を「特記事項」に記入できます。",
    "準委任契約":          "成果保証なし・業務遂行義務の契約です。月次報告・途中解約条件を追記できます。",
    "請負契約":            "成果物の完成を約束する契約です。納期・検収期間・瑕疵担保期間を追記できます。",
    "利用規約":            "サービス利用者向けのルール文書です。禁止事項・サービス内容を「特記事項」に書いてください。",
    "売買契約":            "商品の売買契約です。検査方法・所有権移転タイミングを「特記事項」に追記できます。",
    "パートナー契約":      "協業パートナーとの役割分担契約です。費用負担・収益分配を追記できます。",
    "業務提携契約":        "企業間の協力関係を定める契約です。独占・非独占の別を「特記事項」に書くと反映されます。",
    "雇用契約":            "労働基準法に準拠した雇用契約です。試用期間・リモート可否を「特記事項」に記入できます。",
}

# ─── ページヘッダー ───────────────────────────────────────────────────────────
st.title("📝 契約書作成")
st.caption("必要事項を入力するだけで、AIが完成版の契約書ドラフトを自動生成します。")
st.divider()

# ─── STEP 1 ──────────────────────────────────────────────────────────────────
st.markdown('<div class="step"><div class="snum">1</div><div class="stitle">契約書の種類を選択</div></div>', unsafe_allow_html=True)

if "sel" not in st.session_state:
    st.session_state["sel"] = 0

row1_cols = st.columns(5, gap="small")
row2_cols = st.columns(5, gap="small")

for i, (icon, short, _) in enumerate(CONTRACT_OPTIONS):
    target_col = row1_cols[i] if i < 5 else row2_cols[i - 5]
    with target_col:
        is_sel = st.session_state["sel"] == i
        if st.button(
            f"{icon}\n{short}",
            key=f"ct{i}",
            use_container_width=True,
            type="primary" if is_sel else "secondary",
        ):
            st.session_state["sel"] = i
            st.session_state["draft"] = None
            st.rerun()

sel = st.session_state["sel"]
contract_type_key = CONTRACT_OPTIONS[sel][2]
hint = HINTS.get(contract_type_key, "")
if hint:
    st.markdown(f'<div class="hint">💡 {hint}</div>', unsafe_allow_html=True)

# ─── STEP 2 ──────────────────────────────────────────────────────────────────
st.markdown('<div class="step"><div class="snum">2</div><div class="stitle">当事者情報</div></div>', unsafe_allow_html=True)

c1, c2 = st.columns(2, gap="large")
with c1:
    st.markdown('<div class="lbl">甲（発注者・委託者・開示者）<span class="req"> *</span></div>', unsafe_allow_html=True)
    party_a = st.text_input("pa", label_visibility="collapsed", placeholder="例：株式会社〇〇")
with c2:
    st.markdown('<div class="lbl">乙（受注者・受託者・受領者）<span class="req"> *</span></div>', unsafe_allow_html=True)
    party_b = st.text_input("pb", label_visibility="collapsed", placeholder="例：株式会社△△")

c3, c4 = st.columns(2, gap="large")
with c3:
    st.markdown('<div class="lbl">契約開始日</div>', unsafe_allow_html=True)
    start_date = st.date_input("sd", label_visibility="collapsed")
with c4:
    st.markdown('<div class="lbl">契約終了日</div>', unsafe_allow_html=True)
    end_date = st.date_input("ed", label_visibility="collapsed")

# ─── STEP 3 ──────────────────────────────────────────────────────────────────
st.markdown('<div class="step"><div class="snum">3</div><div class="stitle">契約内容</div></div>', unsafe_allow_html=True)

st.markdown('<div class="lbl">業務内容・取引内容</div>', unsafe_allow_html=True)
business_content = st.text_area("bc", label_visibility="collapsed", height=90,
    placeholder="例：Webシステムの設計・開発・保守運用。具体的な機能要件は別途仕様書にて定める。")

c5, c6 = st.columns(2, gap="large")
with c5:
    st.markdown('<div class="lbl">契約金額（任意）</div>', unsafe_allow_html=True)
    contract_amount = st.text_input("amt", label_visibility="collapsed", placeholder="例：月額500,000円（税別）")
with c6:
    st.markdown('<div class="lbl">支払条件（任意）</div>', unsafe_allow_html=True)
    payment_terms = st.text_input("pay", label_visibility="collapsed", placeholder="例：月末締め翌月末払い")

st.markdown('<div class="lbl">特記事項・追加要望（任意）</div>', unsafe_allow_html=True)
special_notes = st.text_area("sp", label_visibility="collapsed", height=75,
    placeholder="例：競業避止条項を含めてほしい / 秘密保持期間は契約終了後3年 / 知的財産は甲に帰属させたい")

# ─── 生成ボタン ───────────────────────────────────────────────────────────────
st.markdown("<br>", unsafe_allow_html=True)
can_go = bool(party_a and party_b)
if not can_go:
    st.caption("※ 甲・乙の会社名を入力すると生成できます")

gen_btn = st.button(f"✨  {contract_type_key}を生成する", type="primary", disabled=not can_go)

# ─── 生成処理 ─────────────────────────────────────────────────────────────────
if "draft" not in st.session_state:
    st.session_state["draft"] = None

if gen_btn and can_go:
    params = {
        "甲（委託者/発注者）": party_a, "乙（受託者/受注者）": party_b,
        "契約開始日": str(start_date), "契約終了日": str(end_date),
        "業務内容": business_content, "契約金額": contract_amount,
        "支払条件": payment_terms,
        "管轄裁判所": "東京地方裁判所", "準拠法": "日本法",
        "特記事項": special_notes,
    }
    with st.spinner("AIが契約書を生成中です... （20〜40秒かかります）"):
        try:
            st.session_state["draft"] = call_claude_structured(
                system=DRAFT_SYSTEM_PROMPT,
                user=build_draft_prompt(contract_type_key, params),
                model_cls=ContractDraft, max_tokens=8192,
            )
        except ValueError as e:
            st.error("生成に失敗しました。もう一度お試しください。")
            with st.expander("エラー詳細"):
                st.code(str(e))

result: ContractDraft | None = st.session_state["draft"]

if result:
    st.divider()
    st.success(f"「{result.title}」の生成が完了しました。")

    dl1, dl2, _, rst = st.columns([2, 2, 3, 1])
    safe = result.title.replace(" ", "_").replace("/", "-")
    with dl1:
        try:
            st.download_button("📄 Wordダウンロード", draft_to_docx(result), f"{safe}.docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                use_container_width=True)
        except Exception as e:
            st.error(f"Word生成エラー: {e}")
    with dl2:
        try:
            st.download_button("📑 PDFダウンロード", draft_to_pdf(result), f"{safe}.pdf",
                "application/pdf", use_container_width=True)
        except Exception:
            st.warning("PDF生成失敗（Wordは正常）")
    with rst:
        if st.button("🔄 再生成"):
            st.session_state["draft"] = None
            st.rerun()

    if result.notes:
        st.markdown("---")
        for note in result.notes:
            st.info(note)

    st.markdown("---")
    st.subheader("契約書プレビュー")
    with st.container(border=True):
        st.markdown(result.body_markdown)

    # ─── 修正・再生成 ─────────────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("✏️ 修正して再生成")
    st.caption("気になる箇所を日本語で指示すると、AIが修正した契約書を再生成します。")
    revision_input = st.text_area(
        "修正指示",
        label_visibility="collapsed",
        height=100,
        placeholder="例：第3条の支払条件を「納品後2週間以内」に変更してください。また第7条に著作権の二次利用禁止を追記してください。",
        key="revision_input",
    )
    if st.button("✏️ この内容で修正する", type="primary", disabled=not bool(revision_input)):
        with st.spinner("AIが契約書を修正中です..."):
            try:
                st.session_state["draft"] = call_claude_structured(
                    system=REVISE_SYSTEM_PROMPT,
                    user=build_revise_prompt(result.body_markdown, revision_input),
                    model_cls=ContractDraft,
                    max_tokens=8192,
                )
                st.rerun()
            except ValueError as e:
                st.error("修正に失敗しました。もう一度お試しください。")
                with st.expander("エラー詳細"):
                    st.code(str(e))
