---
name: veri-analizi
description: Excel/CSV verisini okuma, özetleme, gruplama, grafik çizme ve sonucu grafikli Excel olarak kaydetme
---
# Data analysis with pandas + matplotlib (bundled, tested)

First look at the real data (read_file on a CSV, or print `df.head()`, `df.dtypes` in run_python): column names and
formats in your code must be the real ones. Numbers you report must come from code you ran.

```python
import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path

out = Path("Rapor"); out.mkdir(exist_ok=True)
df = pd.read_excel("satis.xlsx")                     # CSV: pd.read_csv("x.csv", sep=None, engine="python")
df["tarih"] = pd.to_datetime(df["tarih"], dayfirst=True, errors="coerce")   # Turkish dates are day first
print(df.shape); print(df.dtypes); print(df.head())

aylik = df.groupby(df["tarih"].dt.to_period("M"))["tutar"].sum()
ozet = df.pivot_table(index="urun", values="tutar", aggfunc=["sum", "mean", "count"])

fig, ax = plt.subplots(figsize=(8, 4.5), dpi=150)
aylik.plot(kind="bar", ax=ax, color="#3b82f6")
ax.set_title("Aylık satış"); ax.set_xlabel(""); ax.set_ylabel("TL")
fig.tight_layout(); fig.savefig(out / "aylik.png"); plt.close(fig)

with pd.ExcelWriter(out / "analiz.xlsx", engine="openpyxl") as w:   # several sheets
    aylik.to_frame("toplam").to_excel(w, sheet_name="Aylık")
    ozet.to_excel(w, sheet_name="Ürün özeti")

from openpyxl import load_workbook                    # chart INSIDE the Excel file (when asked)
from openpyxl.drawing.image import Image as XLImage
wb = load_workbook(out / "analiz.xlsx"); ws = wb.create_sheet("Grafik")
ws.add_image(XLImage(str(out / "aylik.png")), "A1"); wb.save(out / "analiz.xlsx")
```

Pitfalls: money written as "1.234,56" → `pd.to_numeric(s.str.replace(".", "").str.replace(",", "."))`; never
call plt.show(); a chart "in the Excel/Word file" means embedded (above), not a separate PNG. Trends / forecast:
statsmodels (`from statsmodels.tsa.holtwinters import ExponentialSmoothing`); anomalies: scikit-learn
`IsolationForest`. Install them with install_python_package if missing. Finish by checking the files you promised
exist and, for charts, look at them (inspect_output if available).
