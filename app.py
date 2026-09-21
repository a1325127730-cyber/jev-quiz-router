from __future__ import annotations

import asyncio
import os

import streamlit as st
from dotenv import load_dotenv

from quiz_router.io import export_excel_bytes, load_questions, results_dataframe
from quiz_router.pipeline import QuizPipeline
from quiz_router.providers import DemoProvider, JevProvider, OpenAICompatibleReasoner

load_dotenv()
st.set_page_config(page_title="Jev Quiz Router", page_icon="⚡", layout="wide")
st.title("⚡ Jev Quiz Router")
st.caption("Jev 快速首答 · 低置信度 System-2 复核 · Excel 结果与错题分析")

with st.sidebar:
    st.header("运行设置")
    demo = st.toggle("演示模式（无需密钥）", value=not bool(os.getenv("TYPESAFE_API_KEY")))
    threshold = st.slider("Jev 置信度阈值", 0.0, 1.0, 0.85, 0.01)
    concurrency = st.slider("并发数", 1, 32, 8)
    use_reasoner = st.toggle("低置信度交给推理模型", value=True)
    st.info("演示模式只验证流程，答案是确定性占位值，不能用于真实做题。")

uploaded = st.file_uploader("上传题库", type=["csv", "xlsx", "xlsm"])
st.markdown("列名支持：`题号/ID`、`题干/question`、`A`～`H`、可选 `标准答案`、`科目`。")

if uploaded:
    try:
        questions = load_questions(uploaded, filename=uploaded.name)
        st.success(f"已读取 {len(questions)} 道题")
        preview = [
            {"题号": q.id, "题干": q.stem, **q.options, "标准答案": q.correct_answer}
            for q in questions[:20]
        ]
        st.dataframe(preview, use_container_width=True)
    except Exception as error:
        st.error(str(error))
        questions = []

    if questions and st.button("开始自动答题", type="primary", use_container_width=True):
        progress_bar = st.progress(0, text="准备中")
        status = st.empty()

        if demo:
            jev = DemoProvider("jev-demo")
            reasoner = DemoProvider("reasoning-demo") if use_reasoner else None
        else:
            try:
                jev = JevProvider(
                    api_key=os.getenv("TYPESAFE_API_KEY", ""),
                    model=os.getenv("TYPESAFE_MODEL", "jev-latest"),
                    base_url=os.getenv("TYPESAFE_BASE_URL", "https://api.typesafe.ai/v1"),
                )
                reasoning_key = os.getenv("REASONING_API_KEY", "")
                reasoner = None
                if use_reasoner and reasoning_key:
                    reasoner = OpenAICompatibleReasoner(
                        api_key=reasoning_key,
                        model=os.getenv("REASONING_MODEL", "gpt-5.6"),
                        base_url=os.getenv("REASONING_BASE_URL", "https://api.openai.com/v1"),
                    )
            except Exception as error:
                st.error(str(error))
                st.stop()

        pipeline = QuizPipeline(
            jev=jev,
            reasoner=reasoner,
            confidence_threshold=threshold,
            concurrency=concurrency,
            demo=demo,
        )

        def report(done, total, record):
            progress_bar.progress(done / total, text=f"{done}/{total} · {record.status}")
            status.caption(f"最近完成：第 {record.question_id} 题 · 路线 {record.route}")

        async def execute():
            try:
                return await pipeline.run(questions, progress=report)
            finally:
                await pipeline.aclose()

        records = asyncio.run(execute())
        frame = results_dataframe(questions, records)
        answered = int((frame["状态"] == "answered").sum())
        review = int((frame["状态"] == "needs_review").sum())
        failed = int((frame["状态"] == "failed").sum())
        col1, col2, col3 = st.columns(3)
        col1.metric("已回答", answered)
        col2.metric("待复核", review)
        col3.metric("失败", failed)
        st.dataframe(frame, use_container_width=True)
        st.download_button(
            "下载 Excel 结果",
            export_excel_bytes(questions, records),
            file_name="jev_quiz_results.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
