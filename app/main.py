"""Streamlit 入口。

这一层只做三件事：收集输入、调 pipeline.api、把结果渲染出来。
不允许出现任何判定逻辑 —— 「多少分算推进」这种事属于 scorer，
一旦渗进 UI，同一个结论就会有两个来源。
"""

from __future__ import annotations

import sys
from pathlib import Path

# 让 `streamlit run app/main.py` 免安装即可运行
ROOT = Path(__file__).resolve().parent.parent
for p in (str(ROOT / "src"), str(ROOT), str(ROOT / "app")):
    if p not in sys.path:
        sys.path.insert(0, p)

import streamlit as st  # noqa: E402

from pipeline import api  # noqa: E402

from views import checker_view, match_view, question_view, ranking_view, trace_view  # noqa: E402

st.set_page_config(page_title="智能简历解析与试题生成引擎", page_icon="📋", layout="wide")

st.markdown(
    """
    <style>
      .block-container { padding-top: 2.2rem; max-width: 1400px; }
      .stTabs [data-baseweb="tab"] { font-size: 0.95rem; }
      mark { background: #fff3bf; padding: 0 .15em; border-radius: 2px; }
      .quote { border-left: 3px solid #adb5bd; padding: .2rem .8rem; margin: .3rem 0;
               color: #495057; background: #f8f9fa; font-size: .88rem; }
    </style>
    """,
    unsafe_allow_html=True,
)


def sidebar() -> None:
    mode = api.runtime_mode()
    with st.sidebar:
        st.subheader("运行模式")
        if mode["demo_mode"]:
            st.success("演示模式：回放内置缓存，不调用真实模型")
        else:
            st.info(f"实时模式：{mode['provider']} / {mode['model']}")
            if mode["api_key_configured"]:
                st.success("API Key：已安全加载（不会显示）")
            else:
                st.warning("API Key：尚未配置")
        st.caption("缓存：" + ("开启" if mode["cache_enabled"] else "关闭"))

        st.divider()
        st.subheader("输入")

        sample_button = "一键运行内置 Demo" if mode["demo_mode"] else "载入样例数据"
        if st.button(sample_button, width="stretch"):
            jd_text, resumes = api.sample_inputs()
            st.session_state["jd_text"] = jd_text
            st.session_state["sample_resumes"] = resumes
            # file_uploader 不能直接赋空值；换一个 widget key 可可靠清除旧上传。
            st.session_state["uploader_generation"] = (
                st.session_state.get("uploader_generation", 0) + 1
            )
            st.session_state.pop("result", None)
            st.session_state.pop("error", None)
            if mode["demo_mode"]:
                _run([])

        st.text_area("JD（可直接粘贴）", key="jd_text", height=220,
                     placeholder="把职位描述粘贴到这里…")

        uploaded = st.file_uploader(
            "简历（可多选，支持 PDF / Word / txt）",
            type=["pdf", "docx", "txt", "md"], accept_multiple_files=True,
            key=f"resume_uploader_{st.session_state.get('uploader_generation', 0)}",
        )

        n_sample = len(st.session_state.get("sample_resumes", []))
        if uploaded:
            st.caption(f"已选择 {len(uploaded)} 份简历")
        elif n_sample:
            st.caption(f"使用样例简历 {n_sample} 份")

        if st.button("开始筛选", type="primary", width="stretch"):
            _run(uploaded)


def _run(uploaded) -> None:
    resumes = (
        [(f.name, f.getvalue()) for f in uploaded]
        if uploaded
        else st.session_state.get("sample_resumes", [])
    )
    jd_text = st.session_state.get("jd_text", "")

    # Demo 回放只包含内置样例。提前拦截自定义输入，避免把实现细节和缓存键
    # 直接暴露给使用者；实时模式仍可正常处理任意 JD 与简历。
    if api.runtime_mode()["demo_mode"] and not api.is_sample_input(jd_text, resumes):
        st.session_state.pop("result", None)
        st.session_state["error"] = (
            "当前是无 API Key 的演示模式，只能回放内置样例。"
            "请点击左侧「一键运行内置 Demo」；如需分析自己的 JD 和简历，"
            "请在 .env 中设置 DEMO_MODE=0 并配置 LLM_API_KEY。"
        )
        return

    try:
        with st.spinner("解析中…提取、匹配、出题与校验会依次进行"):
            result = api.run(jd_text, resumes)
            # 页面展示与 SQLite 持久化必须使用同一个 run_id，便于后续回看 trace。
            run_id = api.persist(result)
            payload = api.result_to_dict(result, run_id=run_id)
        st.session_state["result"] = payload
    except Exception as e:  # noqa: BLE001
        # 演示模式下缓存未命中是最常见的失败，给出可执行的下一步而不是一串堆栈
        st.session_state.pop("result", None)
        st.session_state["error"] = f"{type(e).__name__}: {e}"


def main() -> None:
    st.title("智能简历解析与试题生成引擎")
    st.caption("从非结构化简历到结构化决策建议：匹配打分 · 推进决策 · 面试题目 · 独立校验")

    sidebar()

    if err := st.session_state.pop("error", None):
        st.error(err)

    payload = st.session_state.get("result")
    if not payload:
        if api.runtime_mode()["demo_mode"]:
            st.info("点击左侧「一键运行内置 Demo」，即可看到完整筛选流程。")
        else:
            st.info("载入样例或上传自己的简历，再点「开始筛选」。")
        with st.expander("这个系统做了什么"):
            st.markdown(
                "1. **JD 拆解**成可逐条判定的加权要求项，标出硬性门槛\n"
                "2. **简历提取**，每个字段都挂上原文出处\n"
                "3. **逐条匹配判定**，模型只回答满足与否并引用原文\n"
                "4. **代码加权算分**并给出推进 / 待定 / 淘汰的决策，硬性项一票否决\n"
                "5. 只为**值得面试的候选人**生成 10 道题与 3-5 个追问\n"
                "6. **Checker 独立校验**：出处对不上原文的结论会被打回重写"
            )
        return

    tabs = st.tabs(["候选人排序", "匹配详情", "题目与追问", "校验与修订", "调用链"])
    with tabs[0]:
        ranking_view.render(payload)
    with tabs[1]:
        match_view.render(payload)
    with tabs[2]:
        question_view.render(payload)
    with tabs[3]:
        checker_view.render(payload)
    with tabs[4]:
        trace_view.render(api.trace_stats(), api.trace_rows())


main()
