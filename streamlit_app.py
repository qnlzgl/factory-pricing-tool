import streamlit as st
import pandas as pd

st.set_page_config(page_title="出口产品阶梯定价工具", layout="wide")
st.title("📦 出口产品阶梯定价与报价计算工具")

uploaded_file = st.file_uploader("📂 上传工厂价格表 (Excel)", type=["xlsx"])

if uploaded_file:
    # ======== 读取并清理 ========
    df_raw = pd.read_excel(uploaded_file, header=0)
    df_raw.columns = df_raw.columns.str.strip()
    df_raw = df_raw.dropna(how="all")  # 删除空行
    df_raw = df_raw.fillna("")  # 防止空值出错
    st.success("✅ 文件已上传成功")
    st.write("**文件预览：**")
    st.dataframe(df_raw.head())

    # ======== 识别行/列 ========
    st.sidebar.header("🔧 参数设置")
    row_label_col = st.sidebar.selectbox("请选择行标签列（通常是规格/FITTING）", df_raw.columns)
    model_cols = [c for c in df_raw.columns if c != row_label_col]

    # ======== 展平数据 ========
    df = df_raw.melt(id_vars=[row_label_col], value_vars=model_cols,
                     var_name="型号", value_name="面价")
    df = df[df["面价"].astype(str).str.strip() != ""]
    df["面价"] = pd.to_numeric(df["面价"], errors="coerce")
    df = df.dropna(subset=["面价"])

    # ======== 参数输入 ========
    factory_discount = st.sidebar.number_input("工厂折扣系数（含税价 = 面价 × 系数）", value=0.5, step=0.05)
    freight_cost = st.sidebar.number_input("配仓/货代固定费用（RMB/票）", value=700.0, step=50.0)
    total_qty = st.sidebar.number_input("本票总数量（件）", value=1000, step=100)
    target_profit = st.sidebar.number_input("目标利润率（%）", value=20.0, step=5.0) / 100.0

    st.markdown("## 💰 阶梯定价区间")
    col1, col2, col3 = st.columns(3)
    with col1:
        qty1 = st.number_input("区间1上限（件）", value=100)
        margin1 = st.number_input("区间1加价系数（相对面价）", value=0.8)
    with col2:
        qty2 = st.number_input("区间2上限（件）", value=500)
        margin2 = st.number_input("区间2加价系数（相对面价）", value=0.7)
    with col3:
        qty3 = st.number_input("区间3上限（件）", value=1000)
        margin3 = st.number_input("区间3加价系数（相对面价）", value=0.6)

    # ======== 计算逻辑 ========
    df["含税进价"] = df["面价"] * factory_discount
    df["固定成本分摊"] = freight_cost / total_qty
    df["保本价"] = df["含税进价"] + df["固定成本分摊"]
    df["100件价"] = df["面价"] * margin1
    df["500件价"] = df["面价"] * margin2
    df["1000件价"] = df["面价"] * margin3
    df["目标利润报价"] = df["保本价"] * (1 + target_profit)

    st.markdown("## 📈 定价计算结果")
    st.dataframe(df[[row_label_col, "型号", "面价", "含税进价", "保本价", "100件价", "500件价", "1000件价", "目标利润报价"]])

    # ======== 下载 ========
    csv = df.to_csv(index=False).encode('utf-8-sig')
    st.download_button(
        label="⬇️ 下载报价结果 (CSV)",
        data=csv,
        file_name="报价计算结果.csv",
        mime="text/csv"
    )

    # ======== 订单报价 ========
    st.markdown("## 🧾 客户订单报价模拟")
    st.write("例如：`BC 4-G01 100` 或 `BL Fitting 100`")
    order_data = st.text_area("输入格式：型号 规格 数量（每行一条）", value="BC 4-01 100\nBL 6-01 100")

    if st.button("生成报价单"):
        order_list = []
        for line in order_data.strip().split("\n"):
            parts = line.split()
            if len(parts) >= 3:
                model = parts[0]
                fitting = parts[1]
                qty = int(parts[2])
                row = df[(df["型号"].astype(str) == model) & (df[row_label_col].astype(str) == fitting)]
                if not row.empty:
                    cost = row.iloc[0]["保本价"]
                    quote = row.iloc[0]["目标利润报价"]
                    order_list.append({
                        "型号": model,
                        "规格": fitting,
                        "数量": qty,
                        "保本单价": round(cost, 2),
                        "报价单价": round(quote, 2),
                        "合计报价": round(quote * qty, 2)
                    })
        if order_list:
            order_df = pd.DataFrame(order_list)
            st.dataframe(order_df)
            total = order_df["合计报价"].sum()
            st.markdown(f"### 💵 总报价金额：**{total:.2f} RMB**")
        else:
            st.warning("⚠️ 未匹配到任何型号/规格，请检查输入。")

else:
    st.info("👆 请上传 Excel 文件开始计算。")