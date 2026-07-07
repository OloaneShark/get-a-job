
from pathlib import Path
from pypdf import PdfReader
from docx import Document


def extract_resume_text(file_path):
    suffix = Path(file_path).suffix.lower()
    
    if suffix == ".pdf":
        return extract_pdf_text(file_path)
    
    if suffix == ".docx":
        return extract_docx_text(file_path)
    
    if suffix == ".txt":
        return extract_txt_text(file_path)
    
    return ""
    
    
def extract_pdf_text(file_path):
    reader = PdfReader(file_path)
    text = []
    
    for page in reader.pages:
        page_text = page.extract_text()
        if page_text:
            text.append(page_text)
            
    return "\n\n".join(text).strip()


def extract_docx_text(file_path):
    document = Document(file_path)
    text = []
    
    for paragraph in document.paragraphs:
        if paragraph.text.strip():
            text.append(paragraph.text.strip())
            
    return "\n".join(text).strip()


def extract_txt_text(file_path):
    with open(file_path, "r", encoding="utf-8", errors="ignore") as file:
        return file.read().strip()
    
