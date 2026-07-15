from pathlib import Path

import pandas as pd
import streamlit as st


st.set_page_config(page_title="表示確認", layout="wide")
st.title("表示確認")

png_path = Path("outputs/debug_result_map.png")
exists = png_path.exists()
size = png_path.stat().st_size if exists else 0

st.write(f"exists={exists}")
st.write(f"size={size}")

if exists:
    st.image(str(png_path), use_container_width=True)
else:
    st.error("outputs/debug_result_map.png が見つかりません。")

df = pd.DataFrame(
    {
        "node_id": [1, 2, 3],
        "status": ["initial", "cascade", "normal"],
    }
)
st.dataframe(df, use_container_width=True)
