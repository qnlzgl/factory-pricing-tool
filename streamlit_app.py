
import io
import numpy as np
import pandas as pd
import streamlit as st

st.set_page_config(page_title="阶梯定价 & 报价工具", layout="wide")

st.title("阶梯定价 & 报价工具（含保本价 / 目标利润）")
st.caption("上传工厂面价表（Excel），选择产品与型号，配置运费/固定成本与利润率，自动计算保本价与阶梯报价。")

# -----------------------------
# Helpers
# -----------------------------
def coerce_numeric(x):
    try:
        # remove common currency/unit artifacts
        if isinstance(x, str):
            s = x.strip().replace(',', '')
            # handle trailing non-numeric
            s = ''.join(ch for ch in s if (ch.isdigit() or ch in '.-'))
            if s == '' or s == '-' or s == '.':
                return np.nan
            return float(s)
        return float(x)
    except Exception:
        return np.nan

def tidy_sheet(df: pd.DataFrame):
    """
    Try to clean the sheet so that the first column acts as the 'MODEL' key
    and other columns are numeric price columns.
    """
    # Drop fully empty columns/rows
    df = df.copy()
    df = df.dropna(how="all").dropna(axis=1, how="all")
    # Use first row as header if plausible
    # If the first row contains many strings and the second row is numbers -> header row
    # Otherwise keep existing headers.
    header_row_is_first = True
    if df.shape[0] >= 2:
        first = df.iloc[0]
        second = df.iloc[1]
        first_str_ratio = (first.astype(str) != first.astype(str).astype(float, errors="ignore")).mean()
        second_num_ratio = pd.to_numeric(second, errors="coerce").notna().mean()
        if second_num_ratio < 0.2:
            header_row_is_first = True
        # else keep default
    # Reset columns names
    df.columns = [str(c).strip() for c in df.columns]
    # If the first column header is empty or like "Unnamed: 0", name it MODEL
    first_col = df.columns[0] if len(df.columns) else "MODEL"
    if (not first_col) or str(first_col).lower().startswith("unnamed"):
        first_col = "MODEL"
        df.rename(columns={df.columns[0]: "MODEL"}, inplace=True)
    else:
        # Normalize likely model header names
        if str(first_col).strip().lower() in ["型号", "model", "code", "item", "品号", "料号"]:
            df.rename(columns={df.columns[0]: "MODEL"}, inplace=True)
        else:
            # still rename the first col to MODEL, keep old in col_meta
            df.rename(columns={df.columns[0]: "MODEL"}, inplace=True)

    # Trim strings in MODEL
    df["MODEL"] = df["MODEL"].astype(str).str.strip()
    # Coerce all other columns numeric where possible
    value_cols = [c for c in df.columns if c != "MODEL"]
    for c in value_cols:
        df[c] = df[c].apply(coerce_numeric)
    return df

@st.cache_data(show_spinner=False)
def load_all_sheets(file_bytes: bytes):
    xls = pd.ExcelFile(io.BytesIO(file_bytes))
    sheets = {}
    for name in xls.sheet_names:
        try:
            df = pd.read_excel(io.BytesIO(file_bytes), sheet_name=name, header=0)
        except Exception:
            df = pd.read_excel(io.BytesIO(file_bytes), sheet_name=name, header=None)
        sheets[name] = tidy_sheet(df)
    return sheets

def get_price(sheets_dict, sheet_name, product_col, model_code):
    df = sheets_dict[sheet_name]
    # exact match first
    row = df.loc[df["MODEL"].astype(str).str.strip()==str(model_code).strip()]
    if row.empty:
        # try normalize like "4- 01" -> "4-01"
        m = str(model_code).replace(" ", "")
        row = df.loc[df["MODEL"].astype(str).str.replace(" ", "")==m]
    if row.empty:
        return np.nan
    if product_col not in df.columns:
        return np.nan
    return row.iloc[0][product_col]

def price_with_margin(unit_cost, fixed_cost_per_order, qty, margin_pct, margin_mode="Revenue margin"):
    """
    margin_mode:
      - 'Revenue margin' : price = (cost + fixed/qty) / (1 - m)
      - 'Markup on cost' : price = (cost + fixed/qty) * (1 + m)
    """
    unit_allin_cost = unit_cost + (fixed_cost_per_order / max(qty,1))
    m = margin_pct / 100.0
    if margin_mode == "Markup on cost":
        return unit_allin_cost * (1 + m), unit_allin_cost
    else:
        # Revenue margin
        if (1 - m) <= 0:
            return np.nan, unit_allin_cost
        return unit_allin_cost / (1 - m), unit_allin_cost

# -----------------------------
# Sidebar: Data & Global Config
# -----------------------------
st.sidebar.header("1) 上传价目表 Excel")
uploaded = st.sidebar.file_uploader("上传Excel（含工厂**面价**）", type=["xlsx", "xls"])

default_bytes = None
try:
    # Try to read default file from working dir (for convenience in this demo)
    with open("PT+G.xlsx", "rb") as f:
        default_bytes = f.read()
except Exception:
    pass

file_bytes = None
if uploaded is not None:
    file_bytes = uploaded.read()
elif default_bytes is not None:
    st.sidebar.info("未上传文件，已加载示例：PT+G.xlsx")
    file_bytes = default_bytes

if not file_bytes:
    st.stop()

sheets_dict = load_all_sheets(file_bytes)
sheet_names = list(sheets_dict.keys())
st.sidebar.success(f"已读取 {len(sheet_names)} 个Sheet：{', '.join(sheet_names)}")

st.sidebar.header("2) 成本与费用设置")
factory_discount = st.sidebar.number_input("工厂给价系数（含税开票价 = 面价 × 系数）", min_value=0.0, max_value=1.0, value=0.5, step=0.01)
ff_min_charge = st.sidebar.number_input("货代起步费（按3m³计，RMB/票）", min_value=0.0, value=700.0, step=10.0)
other_fixed = st.sidebar.number_input("其他固定成本（RMB/票）", min_value=0.0, value=0.0, step=10.0)
fixed_cost_total = ff_min_charge + other_fixed

st.sidebar.header("3) 阶梯利润设置")
tiers_default = pd.DataFrame({
    "min_qty":[1, 100, 500, 1000],
    "margin_mode":["Revenue margin"]*4,
    "margin_pct":[35.0, 30.0, 25.0, 22.0]
})
tiers = st.sidebar.data_editor(tiers_default, num_rows="dynamic", use_container_width=True)
tiers = tiers.sort_values("min_qty")

st.sidebar.header("4) 币种与显示")
currency = st.sidebar.text_input("币种符号", value="RMB")
show_vat = st.sidebar.checkbox("价格含税", value=True)

# -----------------------------
# Build order lines
# -----------------------------
st.header("下单明细")
colA, colB = st.columns([1,2])

with colA:
    st.write("选择对应Sheet、产品列与型号，然后输入数量。")
    # Prepare a pool of choices
    default_sheet = sheet_names[0]
    default_cols = [c for c in sheets_dict[default_sheet].columns if c!="MODEL"]

# Prepare an editable grid for order items
if "order_df" not in st.session_state:
    # seed with two example lines; user can adjust to真实型号/列名
    example_sheet = sheet_names[0]
    example_cols = [c for c in sheets_dict[example_sheet].columns if c!="MODEL"]
    c1 = example_cols[0] if example_cols else ""
    c2 = example_cols[1] if len(example_cols)>1 else c1
    st.session_state.order_df = pd.DataFrame({
        "sheet":[example_sheet, example_sheet],
        "product_col":[c1, c2],
        "model":["4-01", "BL"],  # 用户可改为例如 '4-G01' 或实际型号
        "qty":[100, 100]
    })

order_df = st.data_editor(
    st.session_state.order_df,
    num_rows="dynamic",
    use_container_width=True,
    key="order_editor"
)

# -----------------------------
# Compute pricing
# -----------------------------
if order_df.empty:
    st.stop()

calc_rows = []
total_qty = 0
for i, r in order_df.iterrows():
    sheet = r.get("sheet", sheet_names[0])
    if sheet not in sheets_dict:
        base_price = np.nan
    else:
        product_col = r.get("product_col", None)
        model_code = r.get("model", "")
        df_sheet = sheets_dict[sheet]
        # If product_col invalid, try to guess first available column
        if product_col not in df_sheet.columns:
            value_cols = [c for c in df_sheet.columns if c!="MODEL"]
            product_col = value_cols[0] if value_cols else None
        base_price = get_price(sheets_dict, sheet, product_col, model_code)
    qty = float(r.get("qty", 0) or 0)
    total_qty += qty
    cost_unit = (base_price or 0) * factory_discount
    calc_rows.append({
        "line": i+1,
        "sheet": sheet,
        "product_col": product_col,
        "model": r.get("model",""),
        "面价": base_price,
        "给我成本(面价×系数)": cost_unit,
        "数量": qty
    })

calc_df = pd.DataFrame(calc_rows)

st.subheader("行项成本（未分摊固定费用）")
st.dataframe(calc_df, use_container_width=True)

# Breakeven per-unit (含固定成本分摊)
st.subheader("保本价（分摊固定成本后）")
if total_qty <= 0:
    st.warning("数量为0，无法计算。")
    st.stop()

# allocate fixed costs proportionally by each line's qty
calc_df["固定成本分摊/件"] = (fixed_cost_total / total_qty)
calc_df["保本单价"] = (calc_df["给我成本(面价×系数)"] + calc_df["固定成本分摊/件"]).round(4)

st.dataframe(calc_df[["line","sheet","product_col","model","数量","面价","给我成本(面价×系数)","固定成本分摊/件","保本单价"]], use_container_width=True)

# Tiered pricing per line
st.subheader("阶梯报价（按行计算）")
tier_tables = []
for i, r in calc_df.iterrows():
    row_tables = []
    for _, tr in tiers.iterrows():
        min_qty = int(tr["min_qty"])
        mode = tr["margin_mode"]
        m = float(tr["margin_pct"])
        # Use this tier's quantity (>=min_qty). For preview, we compute price at that exact qty and also show per-unit.
        price_unit, unit_allin_cost = price_with_margin(
            unit_cost=r["给我成本(面价×系数)"],
            fixed_cost_per_order=fixed_cost_total * (r["数量"] / max(total_qty,1.0)),  # proportional share for preview
            qty=max(min_qty,1),
            margin_pct=m,
            margin_mode=mode
        )
        row_tables.append({
            "line": int(r["line"]),
            "型号": r["model"],
            "列": r["product_col"],
            "阶梯起订量": min_qty,
            "利润方式": mode,
            "利润%": m,
            f"{currency}/件（含分摊固定成本）": None if pd.isna(price_unit) else round(price_unit, 4),
            "该档保本单价": round(unit_allin_cost, 4) if unit_allin_cost==unit_allin_cost else None
        })
    tt = pd.DataFrame(row_tables)
    tier_tables.append(tt)

if tier_tables:
    show_tiers = pd.concat(tier_tables, ignore_index=True)
    st.dataframe(show_tiers, use_container_width=True)

# Order summary (at user-selected target margin & total order qty)
st.subheader("整单汇总（以每行实际数量计算）")
target_margin_mode = st.selectbox("整单目标利润方式", ["Revenue margin","Markup on cost"])
target_margin_pct = st.number_input("整单目标利润（%）", min_value=0.0, max_value=99.0, value=25.0, step=0.5)

order_rows = []
for i, r in calc_df.iterrows():
    unit_price, unit_allin = price_with_margin(
        unit_cost=r["给我成本(面价×系数)"],
        fixed_cost_per_order=fixed_cost_total * (r["数量"]/max(total_qty,1.0)),
        qty=max(int(r["数量"]),1),
        margin_pct=target_margin_pct,
        margin_mode=target_margin_mode
    )
    order_rows.append({
        "line": int(r["line"]),
        "型号": r["model"],
        "列": r["product_col"],
        "数量": int(r["数量"]),
        "保本单价": round(unit_allin,4) if unit_allin==unit_allin else None,
        f"目标{target_margin_pct:.1f}%单价": round(unit_price,4) if unit_price==unit_price else None,
        "小计(目标)": None if (unit_price!=unit_price) else round(unit_price*float(r["数量"]),2)
    })

order_df_priced = pd.DataFrame(order_rows)
total_target = order_df_priced["小计(目标)"].replace({np.nan:0}).sum()
st.dataframe(order_df_priced, use_container_width=True)
st.markdown(f"**整单目标金额：{currency} {total_target:,.2f}**")

# Downloadable quote
st.subheader("导出")
out = {
    "行项成本": calc_df,
    "阶梯报价示例": show_tiers if tier_tables else pd.DataFrame(),
    "整单报价": order_df_priced
}
buffer = io.BytesIO()
with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
    for name, df in out.items():
        df.to_excel(writer, index=False, sheet_name=name[:31] or "Sheet")
st.download_button("下载Excel报价", data=buffer.getvalue(), file_name="报价结果.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

st.divider()
st.caption("提示：保本价 = （给我成本 + 固定成本/件）。若按**含税到岸**或其他条款计价，可在“成本与费用设置”中加入额外固定/变动项，并调整利润方式为“按营收利润率”或“按成本加成”。")
