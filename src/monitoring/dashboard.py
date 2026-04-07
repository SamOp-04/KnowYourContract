import pandas as pd
import streamlit as st
from src.evaluation.metrics_store import MetricsStore

try:
    from streamlit.errors import StreamlitAPIException
except Exception:
    StreamlitAPIException = Exception  # type: ignore[assignment]

FAITHFULNESS_ALERT_THRESHOLD = 0.90


def _safe_set_page_config() -> None:
    try:
        st.set_page_config(page_title="Legal RAG Monitoring", layout="wide")
    except StreamlitAPIException:
        # Streamlit allows set_page_config only once per run.
        pass

def main() -> None:
    _safe_set_page_config()
    st.title("Legal Contract Analyzer - Monitoring Dashboard")
    st.caption("Real-time quality tracking for faithfulness, relevance, precision, and recall.")

    store = MetricsStore()
    trends = store.get_trends(days=7)
    if not trends:
        st.info("No recent metrics available to display.")
        return

    df = pd.DataFrame(trends)
    if df.empty:
        st.info("No data rows available in trends.")
        return

    df["created_at"] = pd.to_datetime(df["created_at"])
    time_series = df.set_index("created_at")

    st.subheader("Quality Score Trends (Last 7 Days)")
    metrics_to_plot = ["faithfulness", "answer_relevance", "context_precision", "context_recall"]
    st.line_chart(time_series[metrics_to_plot])

    st.subheader("Current Averages")
    cols = st.columns(4)
    cols[0].metric("Avg Faithfulness", f"{df['faithfulness'].mean():.2f}")
    cols[1].metric("Avg Relevance", f"{df['answer_relevance'].mean():.2f}")
    cols[2].metric("Avg Precision", f"{df['context_precision'].mean():.2f}")
    cols[3].metric("Avg Recall", f"{df['context_recall'].mean():.2f}")

    faithfulness_mean = df['faithfulness'].mean()
    if faithfulness_mean < FAITHFULNESS_ALERT_THRESHOLD:
        st.warning(
            f"Alert: Average faithfulness ({faithfulness_mean:.2f}) is below threshold "
            f"({FAITHFULNESS_ALERT_THRESHOLD:.2f})."
        )

    st.subheader("Recent Queries")
    recent = store.list_recent(limit=10)
    recent_df = pd.DataFrame(recent)
    if not recent_df.empty:
        display_columns = ["id", "query", "tool_used", "faithfulness", "answer_relevance"]
        st.dataframe(recent_df[display_columns], use_container_width=True, hide_index=True)

    st.subheader("Query Analytics")
    analytics = store.get_query_analytics()
    analytics_df = pd.DataFrame(analytics)
    if analytics_df.empty:
        st.info("No analytics available yet.")
    else:
        analytics_plot = analytics_df.set_index("tool_used")[['count', 'avg_faithfulness']]
        st.bar_chart(analytics_plot)
        st.dataframe(analytics_df, use_container_width=True, hide_index=True)

if __name__ == "__main__":
    main()
