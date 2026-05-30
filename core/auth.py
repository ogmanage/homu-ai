import streamlit as st


def require_auth() -> None:
    """全ページの先頭で呼ぶ。認証済みならそのまま通過、未認証ならパスワード入力画面を表示してst.stop()。"""
    if st.session_state.get("authenticated"):
        return

    st.markdown(
        """
        <div style='text-align:center; padding: 60px 0 20px;'>
            <h1 style='font-size:2.2rem; color:#1E3A5F;'>⚖️ 法務AI</h1>
            <p style='color:#64748B; font-size:1rem;'>社内利用限定システムです。パスワードを入力してください。</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        with st.form("auth_form", clear_on_submit=True):
            password = st.text_input("パスワード", type="password", placeholder="パスワードを入力")
            submitted = st.form_submit_button("ログイン", use_container_width=True)

        if submitted:
            correct = st.secrets.get("APP_PASSWORD", "")
            if password == correct:
                st.session_state["authenticated"] = True
                st.rerun()
            else:
                st.error("パスワードが正しくありません。")

    st.stop()
