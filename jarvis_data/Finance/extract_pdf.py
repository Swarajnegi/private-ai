import fitz
import sys

doc = fitz.open(r"E:\J.A.R.V.I.S\jarvis_data\Finance\gemini_research.pdf")
text = ""
for page in doc:
    text += page.get_text()

# Write to a text file
with open(r"E:\J.A.R.V.I.S\jarvis_data\Finance\gemini_research_extracted.txt", "w", encoding="utf-8") as f:
    f.write(text)

print(f"Extracted {len(text)} chars to gemini_research_extracted.txt")
