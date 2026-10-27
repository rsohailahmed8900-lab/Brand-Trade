"""
analysis.py - data loading, table joining and metric helpers for the
Brand Traders sales dashboard.  No Streamlit imports here, so everything
in this module can be unit-tested or reused in a notebook.
"""
from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pandas as pd

TABLES = [
    "customers",
    "employees",
    "orders",
    "order_details",
    "products",
    "categories",
    "shippers",
]

# Foreign-key relationships used to join the tables (child -> parent)
RELATIONSHIPS = [
    ("order_details.orderID", "orders.orderID"),
    ("order_details.productID", "products.productID"),
    ("orders.customerID", "customers.customerID"),
    ("orders.employeeID", "employees.employeeID"),
    ("orders.shipperID", "shippers.shipperID"),
    ("products.categoryID", "categories.categoryID"),
    ("employees.reportsTo", "employees.employeeID"),
]


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #
def read_csv_flexible(src) -> pd.DataFrame:
    """Read a CSV from a path, bytes or an uploaded-file object.

    Tries several encodings because some exports (e.g. customer names with
    accents) are not UTF-8.
    """
    if hasattr(src, "getvalue"):
        raw = src.getvalue()
    elif isinstance(src, (bytes, bytearray)):
        raw = bytes(src)
    else:
        raw = Path(src).read_bytes()

    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return pd.read_csv(io.StringIO(raw.decode(enc)))
        except UnicodeDecodeError:
            continue
    raise ValueError("Could not decode CSV file")


def load_tables_from_folder(folder: str | Path) -> dict[str, pd.DataFrame]:
    folder = Path(folder)
    tables = {}
    for name in TABLES:
        p = folder / f"{name}.csv"
        if p.exists():
            tables[name] = read_csv_flexible(p)
    return tables


def load_tables_from_uploads(files) -> dict[str, pd.DataFrame]:
    tables = {}
    for f in files:
        stem = Path(f.name).stem.lower().strip()
        if stem in TABLES:
            tables[stem] = read_csv_flexible(f)
    return tables


def missing_tables(tables: dict[str, pd.DataFrame]) -> list[str]:
    return [t for t in TABLES if t not in tables]


# --------------------------------------------------------------------------- #
# Joining
# --------------------------------------------------------------------------- #
def build_master(t: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Join all seven tables into one line-item level DataFrame.

    Grain: one row per order line (order_details row).
    """
    orders = t["orders"].copy()
    for c in ("orderDate", "requiredDate", "shippedDate"):
        orders[c] = pd.to_datetime(orders[c], errors="coerce")

    od = t["order_details"].rename(columns={"unitPrice": "salePrice"})
    prod = t["products"].rename(columns={"unitPrice": "listPrice"})
    cust = t["customers"].rename(
        columns={
            "companyName": "customerName",
            "city": "customerCity",
            "country": "customerCountry",
        }
    )
    emp = t["employees"][["employeeID", "employeeName", "title"]].rename(
        columns={"title": "employeeTitle"}
    )
    ship = t["shippers"].rename(columns={"companyName": "shipperName"})
    cat = t["categories"][["categoryID", "categoryName"]]

    m = (
        od.merge(orders, on="orderID", how="left")
        .merge(prod, on="productID", how="left")
        .merge(cat, on="categoryID", how="left")
        .merge(
            cust[
                [
                    "customerID",
                    "customerName",
                    "contactName",
                    "customerCity",
                    "customerCountry",
                ]
            ],
            on="customerID",
            how="left",
        )
        .merge(emp, on="employeeID", how="left")
        .merge(ship, on="shipperID", how="left")
    )

    # ---- derived measures -------------------------------------------------
    m["grossSales"] = m["salePrice"] * m["quantity"]
    m["discountAmount"] = m["grossSales"] * m["discount"]
    m["revenue"] = m["grossSales"] - m["discountAmount"]

    m["orderMonth"] = m["orderDate"].dt.to_period("M").dt.to_timestamp()
    m["year"] = m["orderDate"].dt.year
    m["quarter"] = (
        m["orderDate"].dt.year.astype("Int64").astype(str)
        + "-Q"
        + m["orderDate"].dt.quarter.astype("Int64").astype(str)
    )
    m["weekday"] = m["orderDate"].dt.day_name()

    m["daysToShip"] = (m["shippedDate"] - m["orderDate"]).dt.days
    m["daysLate"] = (m["shippedDate"] - m["requiredDate"]).dt.days
    m["isLate"] = np.where(
        m["shippedDate"].notna(), (m["daysLate"] > 0).astype(float), np.nan
    )
    return m


def order_level(m: pd.DataFrame) -> pd.DataFrame:
    """Collapse the master table to one row per order.

    Needed for order-grain measures such as freight (stored once per order,
    so summing it on the line-item table would double count).
    """
    o = (
        m.groupby("orderID")
        .agg(
            orderDate=("orderDate", "first"),
            orderMonth=("orderMonth", "first"),
            requiredDate=("requiredDate", "first"),
            shippedDate=("shippedDate", "first"),
            customerID=("customerID", "first"),
            customerName=("customerName", "first"),
            customerCountry=("customerCountry", "first"),
            employeeName=("employeeName", "first"),
            shipperName=("shipperName", "first"),
            freight=("freight", "first"),
            daysToShip=("daysToShip", "first"),
            daysLate=("daysLate", "first"),
            isLate=("isLate", "first"),
            lines=("productID", "count"),
            units=("quantity", "sum"),
            revenue=("revenue", "sum"),
            discountAmount=("discountAmount", "sum"),
        )
        .reset_index()
    )
    return o


# --------------------------------------------------------------------------- #
# Data quality
# --------------------------------------------------------------------------- #
def quality_checks(t: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Referential-integrity and completeness checks across the tables."""
    rows = []
    for child, parent in RELATIONSHIPS:
        ct, cc = child.split(".")
        pt, pc = parent.split(".")
        if ct not in t or pt not in t:
            continue
        vals = t[ct][cc].dropna()
        orphans = int((~vals.isin(t[pt][pc])).sum())
        rows.append(
            {
                "Check": f"{child} → {parent}",
                "Rows checked": len(vals),
                "Orphan keys": orphans,
                "Status": "✅ OK" if orphans == 0 else "⚠️ Orphans",
            }
        )
    if "orders" in t:
        shipped_missing = int(t["orders"]["shippedDate"].isna().sum())
        rows.append(
            {
                "Check": "orders.shippedDate is empty (not yet shipped)",
                "Rows checked": len(t["orders"]),
                "Orphan keys": shipped_missing,
                "Status": "ℹ️ Pending" if shipped_missing else "✅ OK",
            }
        )
    for name, df in t.items():
        dup = int(df.duplicated().sum())
        rows.append(
            {
                "Check": f"{name}: fully duplicated rows",
                "Rows checked": len(df),
                "Orphan keys": dup,
                "Status": "✅ OK" if dup == 0 else "⚠️ Duplicates",
            }
        )
    return pd.DataFrame(rows).rename(columns={"Orphan keys": "Issues found"})


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #
def kpis(m: pd.DataFrame, o: pd.DataFrame) -> dict:
    n_orders = o["orderID"].nunique()
    revenue = m["revenue"].sum()
    shipped = o["isLate"].dropna()
    return {
        "revenue": revenue,
        "orders": n_orders,
        "customers": m["customerID"].nunique(),
        "units": int(m["quantity"].sum()),
        "aov": revenue / n_orders if n_orders else 0.0,
        "discount": m["discountAmount"].sum(),
        "freight": o["freight"].sum(),
        "late_pct": shipped.mean() * 100 if len(shipped) else 0.0,
        "avg_days_to_ship": o["daysToShip"].mean(),
    }


def monthly_summary(m: pd.DataFrame) -> pd.DataFrame:
    g = (
        m.groupby("orderMonth")
        .agg(revenue=("revenue", "sum"), orders=("orderID", "nunique"),
             units=("quantity", "sum"))
        .reset_index()
        .sort_values("orderMonth")
    )
    g["revenue_ma3"] = g["revenue"].rolling(3, min_periods=1).mean()
    g["mom_pct"] = g["revenue"].pct_change() * 100
    return g


def customer_table(m: pd.DataFrame) -> pd.DataFrame:
    """Per-customer summary with a simple value tier and an activity flag."""
    ref_date = m["orderDate"].max()
    c = (
        m.groupby(["customerID", "customerName", "customerCountry", "customerCity"])
        .agg(
            revenue=("revenue", "sum"),
            orders=("orderID", "nunique"),
            units=("quantity", "sum"),
            last_order=("orderDate", "max"),
            first_order=("orderDate", "min"),
        )
        .reset_index()
    )
    c["aov"] = c["revenue"] / c["orders"]
    c["days_since_last_order"] = (ref_date - c["last_order"]).dt.days
    c = c.sort_values("revenue", ascending=False).reset_index(drop=True)
    c["cum_share"] = c["revenue"].cumsum() / c["revenue"].sum()
    n = len(c)
    top_cut, mid_cut = int(np.ceil(n * 0.2)), int(np.ceil(n * 0.6))
    c["tier"] = "Low value (bottom 40%)"
    c.loc[: mid_cut - 1, "tier"] = "Mid value (next 40%)"
    c.loc[: top_cut - 1, "tier"] = "Top value (top 20%)"
    c["status"] = np.where(c["days_since_last_order"] > 90, "Inactive 90d+", "Active")
    return c


def shipper_table(o: pd.DataFrame) -> pd.DataFrame:
    return (
        o.groupby("shipperName")
        .agg(
            orders=("orderID", "count"),
            total_freight=("freight", "sum"),
            avg_freight=("freight", "mean"),
            avg_days_to_ship=("daysToShip", "mean"),
            late_pct=("isLate", lambda s: s.dropna().mean() * 100),
        )
        .reset_index()
    )


def employee_table(m: pd.DataFrame) -> pd.DataFrame:
    e = (
        m.groupby(["employeeName", "employeeTitle"])
        .agg(
            revenue=("revenue", "sum"),
            orders=("orderID", "nunique"),
            customers=("customerID", "nunique"),
            units=("quantity", "sum"),
        )
        .reset_index()
    )
    e["aov"] = e["revenue"] / e["orders"]
    return e.sort_values("revenue", ascending=False).reset_index(drop=True)


def product_table(m: pd.DataFrame) -> pd.DataFrame:
    p = (
        m.groupby(["productID", "productName", "categoryName", "discontinued"])
        .agg(
            revenue=("revenue", "sum"),
            units=("quantity", "sum"),
            orders=("orderID", "nunique"),
            avg_sale_price=("salePrice", "mean"),
            avg_discount=("discount", "mean"),
        )
        .reset_index()
    )
    return p.sort_values("revenue", ascending=False).reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Auto-generated written report
# --------------------------------------------------------------------------- #
def _money(x: float) -> str:
    return f"${x:,.0f}"


def generate_report(m: pd.DataFrame, o: pd.DataFrame, scope: str) -> str:
    """Return a Markdown analysis report computed from the (filtered) data."""
    k = kpis(m, o)
    rev = k["revenue"]
    L: list[str] = []
    L.append("# Brand Traders – Sales Analysis Report\n")
    L.append(f"**Scope:** {scope}\n")

    # 1. headline
    L.append("## 1. Headline numbers")
    L.append(f"- **Total revenue:** {_money(rev)} (after discounts) from **{k['orders']:,} orders** "
             f"and **{k['customers']:,} customers**.")
    L.append(f"- **Average order value:** {_money(k['aov'])}; **units sold:** {k['units']:,}.")
    L.append(f"- **Discounts given:** {_money(k['discount'])} "
             f"({k['discount'] / (rev + k['discount']) * 100:.1f}% of gross sales).")
    L.append(f"- **Freight charged:** {_money(k['freight'])}.\n")

    # 2. time
    mon = monthly_summary(m)
    L.append("## 2. Sales trend")
    full = mon.iloc[1:-1] if len(mon) >= 8 else mon  # first/last month are usually partial
    if len(full):
        best = full.loc[full["revenue"].idxmax()]
        worst = full.loc[full["revenue"].idxmin()]
        L.append(f"- Strongest complete month: **{best['orderMonth']:%b %Y}** ({_money(best['revenue'])}); "
                 f"weakest: **{worst['orderMonth']:%b %Y}** ({_money(worst['revenue'])}).")
        if len(full) >= 6:
            last3 = full["revenue"].tail(3).mean()
            prev3 = full["revenue"].iloc[-6:-3].mean()
            chg = (last3 / prev3 - 1) * 100 if prev3 else np.nan
            L.append(f"- Last 3 complete months average {_money(last3)}/month, "
                     f"**{chg:+.1f}%** versus the 3 months before.")
    q = m.groupby("quarter")["revenue"].sum()
    if len(q):
        L.append(f"- Best quarter: **{q.idxmax()}** ({_money(q.max())}).")
    L.append("")

    # 3. products
    L.append("## 3. Products & categories")
    cat = m.groupby("categoryName")["revenue"].sum().sort_values(ascending=False)
    if len(cat):
        L.append(f"- Top category: **{cat.index[0]}** with {_money(cat.iloc[0])} "
                 f"({cat.iloc[0] / rev * 100:.1f}% of revenue). "
                 f"Smallest: **{cat.index[-1]}** ({cat.iloc[-1] / rev * 100:.1f}%).")
    prod = product_table(m)
    if len(prod):
        top5 = prod.head(5)
        L.append(f"- Top product: **{prod.loc[0, 'productName']}** ({_money(prod.loc[0, 'revenue'])}). "
                 f"The top 5 products generate {top5['revenue'].sum() / rev * 100:.1f}% of revenue.")
        disc = prod[prod["discontinued"] == 1]
        if len(disc):
            L.append(f"- **{len(disc)} discontinued products** still produced "
                     f"{_money(disc['revenue'].sum())} ({disc['revenue'].sum() / rev * 100:.1f}%) in this period.")
    L.append("")

    # 4. customers
    L.append("## 4. Customers & markets")
    ct = customer_table(m)
    if len(ct):
        top_share = ct[ct["tier"] == "Top value (top 20%)"]["revenue"].sum() / rev * 100
        L.append(f"- Top customer: **{ct.loc[0, 'customerName']}** ({_money(ct.loc[0, 'revenue'])}).")
        L.append(f"- The top 20% of customers ({(ct['tier'] == 'Top value (top 20%)').sum()}) "
                 f"drive **{top_share:.1f}%** of revenue.")
        rep = (ct["orders"] > 1).mean() * 100
        L.append(f"- **{rep:.0f}%** of customers placed more than one order; "
                 f"{(ct['status'] == 'Inactive 90d+').sum()} customers have been inactive for 90+ days "
                 f"before the last order date in the data.")
    country = m.groupby("customerCountry")["revenue"].sum().sort_values(ascending=False)
    if len(country):
        top3 = country.head(3)
        L.append("- Top markets: " + ", ".join(f"**{c}** ({_money(v)})" for c, v in top3.items())
                 + f" – together {top3.sum() / rev * 100:.1f}% of revenue.")
    L.append("")

    # 5. employees
    L.append("## 5. Sales team")
    emp = employee_table(m)
    if len(emp):
        L.append(f"- Top performer: **{emp.loc[0, 'employeeName']}** ({_money(emp.loc[0, 'revenue'])}, "
                 f"{emp.loc[0, 'orders']} orders).")
        best_aov = emp.loc[emp["aov"].idxmax()]
        L.append(f"- Highest average order value: **{best_aov['employeeName']}** ({_money(best_aov['aov'])}).")
    L.append("")

    # 6. logistics
    L.append("## 6. Shipping & delivery")
    sh = shipper_table(o)
    if len(sh):
        fast = sh.loc[sh["avg_days_to_ship"].idxmin()]
        cheap = sh.loc[sh["avg_freight"].idxmin()]
        L.append(f"- Fastest carrier: **{fast['shipperName']}** ({fast['avg_days_to_ship']:.1f} days to ship on average).")
        L.append(f"- Lowest average freight: **{cheap['shipperName']}** ({_money(cheap['avg_freight'])}/order).")
        worst_late = sh.loc[sh["late_pct"].idxmax()]
        L.append(f"- Overall late-shipment rate: **{k['late_pct']:.1f}%** "
                 f"(highest: {worst_late['shipperName']} at {worst_late['late_pct']:.1f}%).")
    pending = int(o["shippedDate"].isna().sum())
    if pending:
        L.append(f"- **{pending} orders** have no shipped date yet.")
    L.append("")

    # 7. discounting
    L.append("## 7. Discount effectiveness")
    disc_lines = m[m["discount"] > 0]
    if len(disc_lines):
        L.append(f"- {len(disc_lines) / len(m) * 100:.1f}% of order lines carry a discount, "
                 f"producing {disc_lines['revenue'].sum() / rev * 100:.1f}% of revenue.")
        avg_q_d = disc_lines["quantity"].mean()
        avg_q_n = m[m["discount"] == 0]["quantity"].mean()
        if not np.isnan(avg_q_n):
            L.append(f"- Discounted lines sell **{avg_q_d:.1f}** units on average versus "
                     f"**{avg_q_n:.1f}** for full-price lines.")
    else:
        L.append("- No discounted lines in the selected scope.")
    L.append("")

    # 8. recommendations
    L.append("## 8. Suggested actions")
    recs = []
    if len(ct):
        recs.append("Protect the top-value customer tier with account reviews and loyalty offers; "
                    "run a win-back campaign for customers inactive 90+ days.")
    if len(country):
        recs.append(f"Concentration check: the top 3 markets hold {country.head(3).sum() / rev * 100:.0f}% of revenue – "
                    "explore growth in under-penetrated countries.")
    if len(sh) and k["late_pct"] > 5:
        recs.append("Late shipments exceed 5% – review carrier SLAs and the order-to-ship process.")
    if len(prod) and (prod["discontinued"] == 1).any():
        recs.append("Plan replacement SKUs for discontinued products that still sell.")
    if len(cat):
        recs.append(f"Cross-sell from **{cat.index[0]}** (largest category) into smaller categories.")
    for r in recs:
        L.append(f"- {r}")
    return "\n".join(L)
