---
name: belge-rapor
description: Word (docx), PowerPoint (pptx) ya da PDF rapor/sunum oluşturma; tablo, grafik ve Türkçe karakterlerle
---
# Word / PowerPoint / PDF documents (bundled libraries, tested)

Make the charts first (matplotlib → PNG at dpi=150), then put them INTO the document.

Word (python-docx):
```python
from docx import Document
from docx.shared import Cm
doc = Document(); doc.add_heading("Satış Raporu", 0)
doc.add_paragraph("Ocak–Mart dönemi özeti.")
t = doc.add_table(rows=1, cols=2); t.style = "Light Grid Accent 1"
t.rows[0].cells[0].text, t.rows[0].cells[1].text = "Ay", "Toplam"
for ay, v in [("Ocak", 1200), ("Şubat", 900)]:
    r = t.add_row().cells; r[0].text, r[1].text = ay, f"{v:,}"
doc.add_picture("Rapor/aylik.png", width=Cm(15))
doc.save("Rapor/rapor.docx")
```

PowerPoint (python-pptx):
```python
from pptx import Presentation
from pptx.util import Inches
prs = Presentation()
s = prs.slides.add_slide(prs.slide_layouts[5])      # 5 = title only; 1 = title + bullet text
s.shapes.title.text = "Aylık satış"
s.shapes.add_picture("Rapor/aylik.png", Inches(0.7), Inches(1.5), width=Inches(8.6))
prs.save("Rapor/sunum.pptx")
```

PDF (reportlab). The default font has NO Turkish letters (ğ ş ı İ become boxes): register DejaVu, which ships
with matplotlib:
```python
from pathlib import Path
import matplotlib as mpl
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table
pdfmetrics.registerFont(TTFont("DejaVu", str(Path(mpl.get_data_path()) / "fonts/ttf/DejaVuSans.ttf")))
st = getSampleStyleSheet(); st["Title"].fontName = st["Normal"].fontName = "DejaVu"
story = [Paragraph("Satış Raporu", st["Title"]), Paragraph("Özet metni…", st["Normal"]), Spacer(1, 12),
         Image("Rapor/aylik.png", width=440, height=248), Table([["Ay", "Toplam"], ["Ocak", "1.200"]])]
SimpleDocTemplate("Rapor/rapor.pdf", pagesize=A4).build(story)
```

Check at the end: the file exists, reading it back works (`pypdf.PdfReader(p).pages[0].extract_text()`,
`Document(p).paragraphs`), and look at the first page (inspect_output if available) before saying it is done.
