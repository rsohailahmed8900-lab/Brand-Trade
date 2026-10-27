"""
Brand Traders – Sales Analysis Dashboard
Run with:  streamlit run app.py
"""
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import analysis as A

st.set_page_config(
    page_title="Brand Traders – Sales Analysis",
    page_icon="📊",
    layout="wide",
)

st.markdown(
    """
    <style>
      [data-testid="stMetric"] {
          background: rgba(120,120,140,0.08);
          border: 1px solid rgba(120,120,140,0.18);
          padding: 14px 16px; border-radius: 12px;
      }
      [data-testid="stMetricValue"] { font-size: 1.55rem; }
      .block-container { padding-top: 2rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

PALETTE = px.colors.qualitative.Set2
APP_DIR = Path(__file__).parent


def show(fig, height=380):
    fig.update_layout(
        height=height,
        margin=dict(l=10, r=10, t=50, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    )
    st.plotly_chart(fig, width="stretch")


def money(x):
    return f"${x:,.0f}"


# --------------------------------------------------------------------------- #
# Data loading (cached)
# --------------------------------------------------------------------------- #
@st.cache_data(show_spinner="Loading tables…")
def load_default():
    for folder in (APP_DIR / "data", APP_DIR):
        t = A.load_tables_from_folder(folder)
        if not A.missing_tables(t):
            return t, str(folder)
    return {}, ""


@st.cache_data(show_spinner="Joining tables…")
def prepare(tables: dict):
    master = A.build_master(tables)
    return master


with st.sidebar:
    st.title("📊 Brand Traders")
    st.caption("Sales analysis across 7 related tables")

    uploads = st.file_uploader(
        "Upload the 7 CSV files (optional)",
        type="csv",
        accept_multiple_files=True,
        help="Leave empty to use the CSVs in the app's data/ folder. "
        "Files must be named: " + ", ".join(f"{t}.csv" for t in A.TABLES),
    )

tables, source = {}, ""
if uploads:
    tables = A.load_tables_from_uploads(uploads)
    source = "uploaded files"
    miss = A.missing_tables(tables)
    if miss:
        st.error(f"Missing uploaded tables: {', '.join(m + '.csv' for m in miss)}")
        st.stop()
else:
    tables, source = load_default()
    if not tables:
        st.error(
            "No data found. Put the 7 CSV files in a `data/` folder next to app.py "
            "or upload them from the sidebar."
        )
        st.stop()

master_all = prepare(tables)

# --------------------------------------------------------------------------- #
# Sidebar filters
# --------------------------------------------------------------------------- #
with st.sidebar:
    st.divider()
    st.subheader("Filters")
    dmin, dmax = master_all["orderDate"].min().date(), master_all["orderDate"].max().date()
    date_rng = st.date_input("Order date range", (dmin, dmax), min_value=dmin, max_value=dmax)
    if isinstance(date_rng, tuple) and len(date_rng) == 2:
        d0, d1 = date_rng
    else:
        d0, d1 = dmin, dmax

    countries = sorted(master_all["customerCountry"].dropna().unique())
    sel_countries = st.multiselect("Customer country", countries, default=countries)
    cats = sorted(master_all["categoryName"].dropna().unique())
    sel_cats = st.multiselect("Category", cats, default=cats)
    emps = sorted(master_all["employeeName"].dropna().unique())
    sel_emps = st.multiselect("Sales employee", emps, default=emps)
    ships = sorted(master_all["shipperName"].dropna().unique())
    sel_ships = st.multiselect("Shipper", ships, default=ships)

mask = (
    (master_all["orderDate"].dt.date >= d0)
    & (master_all["orderDate"].dt.date <= d1)
    & master_all["customerCountry"].isin(sel_countries)
    & master_all["categoryName"].isin(sel_cats)
    & master_all["employeeName"].isin(sel_emps)
    & master_all["shipperName"].isin(sel_ships)
)
m = master_all[mask].copy()

st.title("Brand Traders – Sales Analysis")
st.caption(f"Data source: {source} · {len(m):,} order lines in the current selection")

if m.empty:
    st.warning("No data matches the current filters. Widen the filters in the sidebar.")
    st.stop()

o = A.order_level(m)
K = A.kpis(m, o)

scope_txt = (
    f"{d0:%d %b %Y} – {d1:%d %b %Y}; "
    f"{len(sel_countries)}/{len(countries)} countries, {len(sel_cats)}/{len(cats)} categories, "
    f"{len(sel_emps)}/{len(emps)} employees, {len(sel_ships)}/{len(ships)} shippers"
)

# --------------------------------------------------------------------------- #
# KPI row
# --------------------------------------------------------------------------- #
c = st.columns(6)
c[0].metric("Revenue", money(K["revenue"]))
c[1].metric("Orders", f"{K['orders']:,}")
c[2].metric("Customers", f"{K['customers']:,}")
c[3].metric("Avg order value", money(K["aov"]))
c[4].metric("Discounts given", money(K["discount"]))
c[5].metric("Late shipments", f"{K['late_pct']:.1f}%")

tab_over, tab_prod, tab_cust, tab_emp, tab_ship, tab_model, tab_report = st.tabs(
    [
        "📈 Overview",
        "📦 Products & Categories",
        "👥 Customers & Markets",
        "🧑‍💼 Employees",
        "🚚 Shipping",
        "🗂️ Data Model & Quality",
        "📝 Report",
    ]
)

# --------------------------------------------------------------------------- #
# Overview
# --------------------------------------------------------------------------- #
with tab_over:
    mon = A.monthly_summary(m)

    left, right = st.columns([3, 2])
    with left:
        fig = go.Figure()
        fig.add_bar(x=mon["orderMonth"], y=mon["revenue"], name="Revenue",
                    marker_color=PALETTE[0], opacity=0.55)
        fig.add_scatter(x=mon["orderMonth"], y=mon["revenue_ma3"], name="3-month avg",
                        mode="lines", line=dict(color=PALETTE[1], width=3))
        fig.update_layout(title="Monthly revenue", yaxis_title="Revenue ($)")
        show(fig)
    with right:
        fig = px.bar(mon, x="orderMonth", y="orders", title="Orders per month",
                     color_discrete_sequence=[PALETTE[2]])
        fig.update_layout(xaxis_title=None, yaxis_title="Orders")
        show(fig)

    st.caption(f"Note: the first and last months in the selection ({mon['orderMonth'].iloc[0]:%b %Y} and "
               f"{mon['orderMonth'].iloc[-1]:%b %Y}) may be partial, which can exaggerate dips.")

    l2, r2 = st.columns(2)
    with l2:
        q = m.groupby("quarter", as_index=False)["revenue"].sum().sort_values("quarter")
        q["qoq_pct"] = q["revenue"].pct_change() * 100
        fig = px.bar(q, x="quarter", y="revenue", title="Quarterly revenue",
                     text=q["qoq_pct"].map(lambda v: "" if pd.isna(v) else f"{v:+.0f}%"),
                     color_discrete_sequence=[PALETTE[3]])
        fig.update_traces(textposition="outside")
        fig.update_layout(xaxis_title=None, yaxis_title="Revenue ($)")
        show(fig)
        st.caption("Labels show quarter-over-quarter change. First and last quarters may be partial.")
    with r2:
        order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        wd = (m.groupby("weekday")["revenue"].sum().reindex(order).dropna().reset_index())
        fig = px.bar(wd, x="weekday", y="revenue", title="Revenue by weekday of order",
                     color_discrete_sequence=[PALETTE[4]])
        fig.update_layout(xaxis_title=None, yaxis_title="Revenue ($)")
        show(fig)

    # year-over-year monthly comparison
    mm = m.assign(month_no=m["orderDate"].dt.month,
                  month=m["orderDate"].dt.strftime("%b"))
    yoy = mm.groupby(["year", "month_no", "month"], as_index=False)["revenue"].sum()
    yoy["Year"] = yoy["year"].astype(str)
    fig = px.line(yoy.sort_values(["Year", "month_no"]), x="month", y="revenue", color="Year",
                  markers=True, title="Year-over-year comparison by month",
                  color_discrete_sequence=PALETTE)
    fig.update_layout(xaxis_title=None, yaxis_title="Revenue ($)", legend_title="Year")
    show(fig)

    with st.expander("Monthly table"):
        st.dataframe(
            mon.rename(columns={"orderMonth": "Month", "revenue": "Revenue", "orders": "Orders",
                                "units": "Units", "revenue_ma3": "3-mo avg", "mom_pct": "MoM %"})
            .style.format({"Revenue": "${:,.0f}", "3-mo avg": "${:,.0f}", "MoM %": "{:+.1f}%",
                           "Month": lambda d: f"{d:%b %Y}"}),
            width="stretch", hide_index=True,
        )

# --------------------------------------------------------------------------- #
# Products & Categories
# --------------------------------------------------------------------------- #
with tab_prod:
    prod = A.product_table(m)
    c1, c2, c3 = st.columns([1, 1, 2])
    metric_choice = c1.radio("Rank by", ["Revenue", "Units"], horizontal=True)
    top_n = c2.slider("Top N products", 5, 30, 10)
    mcol = "revenue" if metric_choice == "Revenue" else "units"

    left, right = st.columns(2)
    with left:
        top = prod.nlargest(top_n, mcol).sort_values(mcol)
        fig = px.bar(top, x=mcol, y="productName", orientation="h", color="categoryName",
                     title=f"Top {top_n} products by {metric_choice.lower()}",
                     color_discrete_sequence=PALETTE)
        fig.update_layout(yaxis_title=None, xaxis_title=metric_choice, legend_title="Category")
        show(fig, height=460)
    with right:
        cat = m.groupby("categoryName", as_index=False)["revenue"].sum()
        fig = px.pie(cat, names="categoryName", values="revenue", hole=0.5,
                     title="Revenue share by category", color_discrete_sequence=PALETTE)
        fig.update_traces(textposition="inside", textinfo="percent+label")
        show(fig, height=460)

    l2, r2 = st.columns(2)
    with l2:
        cm = m.groupby(["orderMonth", "categoryName"], as_index=False)["revenue"].sum()
        fig = px.area(cm, x="orderMonth", y="revenue", color="categoryName",
                      title="Category revenue over time", color_discrete_sequence=PALETTE)
        fig.update_layout(xaxis_title=None, yaxis_title="Revenue ($)", legend_title="Category")
        show(fig)
    with r2:
        tm = px.treemap(prod[prod["revenue"] > 0], path=["categoryName", "productName"],
                        values="revenue", title="Revenue treemap (category → product)",
                        color_discrete_sequence=PALETTE)
        show(tm)

    l3, r3 = st.columns(2)
    with l3:
        fig = px.scatter(prod, x="avg_sale_price", y="units", size="revenue", color="categoryName",
                         hover_name="productName", title="Price vs. units sold (bubble = revenue)",
                         color_discrete_sequence=PALETTE)
        fig.update_layout(xaxis_title="Average sale price ($)", yaxis_title="Units sold",
                          legend_title="Category")
        show(fig)
    with r3:
        dd = prod.assign(Status=prod["discontinued"].map({0: "Active", 1: "Discontinued"}))
        dd = dd.groupby("Status", as_index=False)["revenue"].sum()
        fig = px.bar(dd, x="Status", y="revenue", title="Active vs. discontinued products – revenue",
                     color="Status", color_discrete_sequence=[PALETTE[0], PALETTE[1]])
        fig.update_layout(showlegend=False, xaxis_title=None, yaxis_title="Revenue ($)")
        show(fig)

    st.subheader("Product table")
    st.dataframe(
        prod.rename(columns={"productName": "Product", "categoryName": "Category",
                             "revenue": "Revenue", "units": "Units", "orders": "Orders",
                             "avg_sale_price": "Avg price", "avg_discount": "Avg discount"})
        .drop(columns=["productID"])
        .style.format({"Revenue": "${:,.0f}", "Avg price": "${:,.2f}", "Avg discount": "{:.1%}"}),
        width="stretch", hide_index=True,
    )

# --------------------------------------------------------------------------- #
# Customers & Markets
# --------------------------------------------------------------------------- #
with tab_cust:
    ct = A.customer_table(m)
    left, right = st.columns(2)
    with left:
        n = st.slider("Top N customers", 5, 25, 10, key="topcust")
        top = ct.head(n).sort_values("revenue")
        fig = px.bar(top, x="revenue", y="customerName", orientation="h", color="customerCountry",
                     title=f"Top {n} customers by revenue", color_discrete_sequence=PALETTE)
        fig.update_layout(yaxis_title=None, xaxis_title="Revenue ($)", legend_title="Country")
        show(fig, height=440)
    with right:
        ctry = m.groupby("customerCountry", as_index=False).agg(
            revenue=("revenue", "sum"), orders=("orderID", "nunique"),
            customers=("customerID", "nunique"))
        fig = px.choropleth(ctry, locations="customerCountry", locationmode="country names",
                            color="revenue", hover_data=["orders", "customers"],
                            color_continuous_scale="Blues", title="Revenue by country")
        fig.update_geos(showframe=False, showcoastlines=False, projection_type="natural earth")
        show(fig, height=500)

    l2, r2 = st.columns(2)
    with l2:
        fig = go.Figure()
        fig.add_scatter(x=np.arange(1, len(ct) + 1) / len(ct) * 100, y=ct["cum_share"] * 100,
                        mode="lines", fill="tozeroy", line=dict(color=PALETTE[0]))
        fig.add_hline(y=80, line_dash="dot", line_color="grey")
        fig.update_layout(title="Pareto: cumulative revenue vs. share of customers",
                          xaxis_title="% of customers (ranked by revenue)",
                          yaxis_title="% of revenue")
        show(fig)
    with r2:
        tier = ct.groupby("tier", as_index=False).agg(customers=("customerID", "count"),
                                                      revenue=("revenue", "sum"))
        fig = px.bar(tier, x="tier", y="revenue", text="customers", title="Revenue by customer value tier",
                     color="tier", color_discrete_sequence=PALETTE)
        fig.update_traces(texttemplate="%{text} customers", textposition="outside")
        fig.update_layout(showlegend=False, xaxis_title=None, yaxis_title="Revenue ($)")
        show(fig)

    l3, r3 = st.columns(2)
    with l3:
        fig = px.histogram(ct, x="orders", nbins=20, title="Distribution of orders per customer",
                           color_discrete_sequence=[PALETTE[2]])
        fig.update_layout(xaxis_title="Orders placed", yaxis_title="Customers")
        show(fig)
    with r3:
        fig = px.scatter(ct, x="orders", y="aov", size="revenue", color="status",
                         hover_name="customerName", title="Order frequency vs. average order value",
                         color_discrete_sequence=PALETTE)
        fig.update_layout(xaxis_title="Orders", yaxis_title="Avg order value ($)", legend_title="")
        show(fig)

    st.subheader("Customers at risk (inactive 90+ days)")
    risk = ct[ct["status"] != "Active"].sort_values("revenue", ascending=False)
    st.dataframe(
        risk[["customerName", "customerCountry", "revenue", "orders", "last_order", "days_since_last_order"]]
        .rename(columns={"customerName": "Customer", "customerCountry": "Country", "revenue": "Revenue",
                         "orders": "Orders", "last_order": "Last order",
                         "days_since_last_order": "Days inactive"})
        .style.format({"Revenue": "${:,.0f}", "Last order": lambda d: f"{d:%Y-%m-%d}"}),
        width="stretch", hide_index=True,
    )
    with st.expander("All customers"):
        st.dataframe(ct.drop(columns=["cum_share"]), width="stretch", hide_index=True)

# --------------------------------------------------------------------------- #
# Employees
# --------------------------------------------------------------------------- #
with tab_emp:
    emp = A.employee_table(m)
    left, right = st.columns(2)
    with left:
        fig = px.bar(emp.sort_values("revenue"), x="revenue", y="employeeName", orientation="h",
                     title="Revenue by employee", color_discrete_sequence=[PALETTE[0]])
        fig.update_layout(yaxis_title=None, xaxis_title="Revenue ($)")
        show(fig)
    with right:
        fig = px.scatter(emp, x="orders", y="aov", size="revenue", text="employeeName",
                         title="Orders handled vs. average order value",
                         color_discrete_sequence=[PALETTE[1]])
        fig.update_traces(textposition="top center")
        fig.update_layout(xaxis_title="Orders", yaxis_title="Avg order value ($)")
        show(fig)

    em = m.groupby(["orderMonth", "employeeName"], as_index=False)["revenue"].sum()
    fig = px.line(em, x="orderMonth", y="revenue", color="employeeName",
                  title="Monthly revenue by employee", color_discrete_sequence=PALETTE)
    fig.update_layout(xaxis_title=None, yaxis_title="Revenue ($)", legend_title="Employee")
    show(fig)

    heat = m.pivot_table(index="employeeName", columns="categoryName", values="revenue", aggfunc="sum").fillna(0)
    fig = px.imshow(heat, aspect="auto", color_continuous_scale="Blues",
                    title="Revenue heatmap: employee × category")
    show(fig, height=420)

    st.dataframe(
        emp.rename(columns={"employeeName": "Employee", "employeeTitle": "Title", "revenue": "Revenue",
                            "orders": "Orders", "customers": "Customers", "units": "Units",
                            "aov": "Avg order value"})
        .style.format({"Revenue": "${:,.0f}", "Avg order value": "${:,.0f}"}),
        width="stretch", hide_index=True,
    )

# --------------------------------------------------------------------------- #
# Shipping
# --------------------------------------------------------------------------- #
with tab_ship:
    sh = A.shipper_table(o)
    c = st.columns(4)
    c[0].metric("Total freight", money(K["freight"]))
    c[1].metric("Avg freight / order", money(o["freight"].mean()))
    c[2].metric("Avg days to ship", f"{K['avg_days_to_ship']:.1f}")
    c[3].metric("Not yet shipped", f"{int(o['shippedDate'].isna().sum())}")

    left, right = st.columns(2)
    with left:
        fig = px.bar(sh, x="shipperName", y="orders", color="shipperName",
                     title="Orders by shipper", color_discrete_sequence=PALETTE)
        fig.update_layout(showlegend=False, xaxis_title=None)
        show(fig)
    with right:
        fig = px.bar(sh, x="shipperName", y="avg_freight", color="shipperName",
                     title="Average freight per order", color_discrete_sequence=PALETTE)
        fig.update_layout(showlegend=False, xaxis_title=None, yaxis_title="Freight ($)")
        show(fig)

    l2, r2 = st.columns(2)
    with l2:
        fig = px.histogram(o.dropna(subset=["daysToShip"]), x="daysToShip", color="shipperName",
                           barmode="overlay", nbins=30, opacity=0.65,
                           title="Days from order to shipment", color_discrete_sequence=PALETTE)
        fig.update_layout(xaxis_title="Days", yaxis_title="Orders", legend_title="Shipper")
        show(fig)
    with r2:
        fig = px.bar(sh, x="shipperName", y="late_pct", color="shipperName",
                     title="Late shipment rate (shipped after required date)",
                     color_discrete_sequence=PALETTE)
        fig.update_layout(showlegend=False, xaxis_title=None, yaxis_title="% late")
        show(fig)

    l3, r3 = st.columns(2)
    with l3:
        fig = px.scatter(o, x="revenue", y="freight", color="shipperName", opacity=0.7,
                         hover_name="customerName", title="Freight vs. order value",
                         color_discrete_sequence=PALETTE)
        fig.update_layout(xaxis_title="Order value ($)", yaxis_title="Freight ($)", legend_title="Shipper")
        show(fig)
    with r3:
        fc = (o.groupby("customerCountry", as_index=False)["freight"].mean()
              .sort_values("freight", ascending=False).head(15))
        fig = px.bar(fc, x="customerCountry", y="freight", title="Avg freight by destination (top 15)",
                     color_discrete_sequence=[PALETTE[4]])
        fig.update_layout(xaxis_title=None, yaxis_title="Avg freight ($)")
        show(fig)

    st.dataframe(
        sh.rename(columns={"shipperName": "Shipper", "orders": "Orders", "total_freight": "Total freight",
                           "avg_freight": "Avg freight", "avg_days_to_ship": "Avg days to ship",
                           "late_pct": "Late %"})
        .style.format({"Total freight": "${:,.0f}", "Avg freight": "${:,.2f}",
                       "Avg days to ship": "{:.1f}", "Late %": "{:.1f}%"}),
        width="stretch", hide_index=True,
    )

# --------------------------------------------------------------------------- #
# Data Model & Quality
# --------------------------------------------------------------------------- #
with tab_model:
    st.subheader("How the tables are related")
    st.graphviz_chart(
        """
        digraph G {
          rankdir=LR; node [shape=box, style="rounded,filled", fillcolor="#e8f1fb", fontname="Helvetica"];
          order_details -> orders      [label="orderID"];
          order_details -> products    [label="productID"];
          orders -> customers          [label="customerID"];
          orders -> employees          [label="employeeID"];
          orders -> shippers           [label="shipperID"];
          products -> categories       [label="categoryID"];
          employees -> employees       [label="reportsTo"];
        }
        """
    )
    st.markdown(
        "The **order_details** table is the grain of the analysis (one row per product on an order). "
        "It is joined to *orders*, then outwards to products, categories, customers, employees and shippers. "
        "**Revenue** = `unitPrice × quantity × (1 − discount)`. Freight is stored once per order, so "
        "freight metrics are computed on a one-row-per-order table to avoid double counting."
    )

    st.subheader("Table summary")
    summ = pd.DataFrame(
        [{"Table": n, "Rows": len(df), "Columns": ", ".join(df.columns)} for n, df in tables.items()]
    )
    st.dataframe(summ, width="stretch", hide_index=True)

    st.subheader("Referential integrity & quality checks")
    st.dataframe(A.quality_checks(tables), width="stretch", hide_index=True)

    st.subheader("Joined dataset (current filters)")
    show_cols = ["orderID", "orderDate", "customerName", "customerCountry", "employeeName",
                 "shipperName", "categoryName", "productName", "salePrice", "quantity", "discount",
                 "revenue", "freight", "shippedDate"]
    st.dataframe(m[show_cols].head(500), width="stretch", hide_index=True)
    st.download_button("⬇️ Download joined dataset (CSV)", m.to_csv(index=False).encode("utf-8"),
                       file_name="brand_traders_joined.csv", mime="text/csv")

# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #
with tab_report:
    report_md = A.generate_report(m, o, scope_txt)
    st.markdown(report_md)
    st.download_button("⬇️ Download report (Markdown)", report_md.encode("utf-8"),
                       file_name="brand_traders_report.md", mime="text/markdown")
    st.caption("The report is generated from the filters currently applied in the sidebar.")
