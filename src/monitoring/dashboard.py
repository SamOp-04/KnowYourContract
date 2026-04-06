from __future__ import annotations

import pandas as pd
import streamlit as st

from src.evaluation.metrics_store import MetricsStore

FAITHFULNESS_ALERT_THRESHOLD = 0.90

st.set_page_config(page_title="Legal RAG Monitoring", layout="wide")
st.title("Legal Contract Analyzer - Monitoring Dashboard")
st.caption("Real-time quality tracking for faithfulness, relevance, precision, and recall.")

store = MetricsStore()
store.init_db()

col_a, col_b = st.columns([2, 1])
with col_b:
    days = st.slider("Lookback (days)", min_value=1, max_value=30, value=7)
    limit = st.slider("Recent records", min_value=10, max_value=200, value=50, step=10)

trends = store.get_trends(days=days)
recent = store.list_recent(limit=limit)
analytics = store.get_query_analytics()

trends_df = pd.DataFrame(trends)
recent_df = pd.DataFrame(recent)
analytics_df = pd.DataFrame(analytics)

if not recent_df.empty:
    latest = recent_df.iloc[0]
    latest_faithfulness = float(latest.get("faithfulness", 0.0))
    if latest_faithfulness < FAITHFULNESS_ALERT_THRESHOLD:
        st.error(
            "Alert: faithfulness dropped below threshold "
            f"({latest_faithfulness:.2f} < {FAITHFULNESS_ALERT_THRESHOLD:.2f})"
        )
    else:
        st.success(
            "Faithfulness is healthy "
            f"({latest_faithfulness:.2f} >= {FAITHFULNESS_ALERT_THRESHOLD:.2f})"
        )

with col_a:
    st.subheader("RAGAs Trend (Last N Days)")
    if trends_df.empty:
        st.info("No metrics logged yet. Submit queries via API/UI to populate this chart.")
    else:
        trends_df["created_at"] = pd.to_datetime(trends_df["created_at"])
        plot_df = trends_df[
            ["created_at", "faithfulness", "answer_relevance", "context_precision", "context_recall"]
        ].set_index("created_at")
        st.line_chart(plot_df)

st.subheader("Recent Query Metrics")
if recent_df.empty:
    st.info("No recent query records available.")
else:
    display_columns = [
        "created_at",
        "tool_used",
        "used_web_fallback",
        "faithfulness",
        "answer_relevance",
        "context_precision",
        "context_recall",
        "query",
    ]
    st.dataframe(recent_df[display_columns], use_container_width=True, hide_index=True)

st.subheader("Query Analytics")
if analytics_df.empty:
    st.info("No analytics available yet.")
else:
    analytics_plot = analytics_df.set_index("tool_used")[["count", "avg_faithfulness"]]
    st.bar_chart(analytics_plot)
    st.dataframe(analytics_df, use_container_width=True, hide_index=True)
