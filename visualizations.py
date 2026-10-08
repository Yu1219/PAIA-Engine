"""
visualizations.py — Plotly chart generators for the PAIA Engine.

Provides pie charts for categorical/boolean attributes and
histograms for numerical distributions, all styled with a
consistent dark theme.
"""

import plotly.express as px
import plotly.graph_objects as go
import pandas as pd

# ─── Theme ────────────────────────────────────────────────────────────
DARK_BG = "#0e1117"
CARD_BG = "#1a1d29"
ACCENT = "#5ce1e6"
ACCENT2 = "#a855f7"
GRID_COLOR = "rgba(92, 225, 230, 0.08)"
FONT_COLOR = "#e2e8f0"

PALETTE = [
    "#5ce1e6", "#a855f7", "#f472b6", "#34d399", "#fbbf24",
    "#60a5fa", "#f87171", "#c084fc", "#2dd4bf", "#fb923c",
    "#818cf8", "#e879f9", "#4ade80", "#facc15", "#38bdf8",
]

LAYOUT_DEFAULTS = dict(
    paper_bgcolor=DARK_BG,
    plot_bgcolor=CARD_BG,
    font=dict(family="Inter, sans-serif", color=FONT_COLOR, size=13),
    margin=dict(l=40, r=40, t=50, b=60),
    hoverlabel=dict(bgcolor=CARD_BG, font_size=13, font_color=FONT_COLOR),
)


# ─── Pie Chart ────────────────────────────────────────────────────────

def plot_pie(df: pd.DataFrame, column: str, title: str | None = None) -> go.Figure:
    """Create an interactive pie chart for a categorical/boolean column.

    For boolean columns, shows True/False distribution.
    For string columns, shows value counts (top 12, rest grouped as 'Other').
    For integer columns (counts), shows zero vs non-zero distribution.
    """
    series = df[column].dropna()
    if series.empty:
        fig = go.Figure()
        fig.update_layout(
            **LAYOUT_DEFAULTS,
            title=dict(text=title or column, x=0.5, font=dict(size=16)),
            annotations=[dict(text="No data available", showarrow=False,
                              font=dict(size=16, color=FONT_COLOR))],
        )
        return fig

    # Prepare value counts
    if series.dtype == bool or set(series.unique()).issubset({True, False, 0, 1}):
        labels = series.map({True: "Yes", False: "No", 1: "Yes", 0: "No"})
        counts = labels.value_counts()
    elif pd.api.types.is_numeric_dtype(series):
        labels = series.apply(lambda x: "Has Sites" if x > 0 else "None")
        counts = labels.value_counts()
    else:
        # String column: split multi-value fields on "; "
        all_vals = []
        for v in series:
            if isinstance(v, str):
                all_vals.extend([x.strip() for x in v.split(";") if x.strip()])
        counts = pd.Series(all_vals).value_counts()
        if len(counts) > 12:
            top = counts.head(11)
            other = counts.iloc[11:].sum()
            counts = pd.concat([top, pd.Series({"Other": other})])

    fig = go.Figure(
        data=[go.Pie(
            labels=counts.index.tolist(),
            values=counts.values.tolist(),
            hole=0.45,
            marker=dict(colors=PALETTE[:len(counts)],
                        line=dict(color=DARK_BG, width=2)),
            textinfo="label+percent",
            textfont=dict(size=12, color=FONT_COLOR),
            hovertemplate="<b>%{label}</b><br>Count: %{value}<br>Percent: %{percent}<extra></extra>",
        )]
    )
    pie_layout = {
        **LAYOUT_DEFAULTS,
        "margin": dict(l=20, r=160, t=50, b=60),
    }
    fig.update_layout(
        **pie_layout,
        title=dict(text=title or column, x=0.5,
                   font=dict(size=16, color=FONT_COLOR)),
        showlegend=True,
        legend=dict(
            font=dict(size=11),
            bgcolor="rgba(0,0,0,0)",
            orientation="v",
            yanchor="middle",
            y=0.5,
            xanchor="left",
            x=1.02,
        ),
        height=550,
    )
    return fig


# ─── Histogram ────────────────────────────────────────────────────────

def plot_histogram(
    df: pd.DataFrame,
    column: str,
    title: str | None = None,
    nbins: int = 30,
) -> go.Figure:
    """Create a histogram for a numerical column."""
    series = df[column].dropna()
    if series.empty:
        fig = go.Figure()
        fig.update_layout(
            **LAYOUT_DEFAULTS,
            title=dict(text=title or column, x=0.5, font=dict(size=16)),
            annotations=[dict(text="No data available", showarrow=False,
                              font=dict(size=16, color=FONT_COLOR))],
        )
        return fig

    fig = go.Figure(
        data=[go.Histogram(
            x=series,
            nbinsx=nbins,
            marker=dict(
                color=ACCENT,
                line=dict(color=ACCENT2, width=1),
                opacity=0.82,
            ),
            hovertemplate="Range: %{x}<br>Count: %{y}<extra></extra>",
        )]
    )
    fig.update_layout(
        **LAYOUT_DEFAULTS,
        title=dict(text=title or column, x=0.5,
                   font=dict(size=16, color=FONT_COLOR)),
        xaxis=dict(
            title=column,
            gridcolor=GRID_COLOR,
            zeroline=False,
        ),
        yaxis=dict(
            title="Count",
            gridcolor=GRID_COLOR,
            zeroline=False,
        ),
        bargap=0.06,
        height=420,
    )
    return fig


# ─── Summary Stats Card ──────────────────────────────────────────────

def summary_stats(df: pd.DataFrame, column: str) -> dict:
    """Return summary statistics for a numeric column."""
    series = df[column].dropna()
    if series.empty:
        return {}
    return {
        "Count": int(series.count()),
        "Mean": round(float(series.mean()), 2),
        "Median": round(float(series.median()), 2),
        "Std Dev": round(float(series.std()), 2),
        "Min": round(float(series.min()), 2),
        "Max": round(float(series.max()), 2),
    }
