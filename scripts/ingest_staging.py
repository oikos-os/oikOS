import os
import glob
from docx import Document
from pypdf import PdfReader

STAGING_DIR = "memory/purgatory/import_staging"
OUTPUT_DIR = "memory/purgatory/converted"

def convert_docx(file_path):
    try:
        doc = Document(file_path)
        content = []
        for para in doc.paragraphs:
            content.append(para.text)
        return "\n\n".join(content)
    except Exception as e:
        return f"ERROR: {str(e)}"

def convert_pdf(file_path):
    try:
        reader = PdfReader(file_path)
        content = []
        for page in reader.pages:
            content.append(page.extract_text())
        return "\n\n".join(content)
    except Exception as e:
        return f"ERROR: {str(e)}"

def main():
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    # Walk the directory manually to avoid glob recursion issues
    docx_files = []
    pdf_files = []
    
    for root, dirs, files in os.walk(STAGING_DIR):
        for file in files:
            if file.lower().endswith(".docx") and not file.startswith("~$"):
                docx_files.append(os.path.join(root, file))
            elif file.lower().endswith(".pdf"):
                pdf_files.append(os.path.join(root, file))

    print(f"Found {len(docx_files)} DOCX files and {len(pdf_files)} PDF files.")

    for file_path in docx_files:
        try:
            print(f"Converting: {file_path}")
            text = convert_docx(file_path)
            if not text:
                text = "(Empty or unreadable content)"
                
            base_name = os.path.basename(file_path).replace(".docx", ".md")
            output_path = os.path.join(OUTPUT_DIR, base_name)
            
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(f"# SOURCE: {file_path}\n\n{text}")
        except Exception as e:
            print(f"Failed to process {file_path}: {e}")

    for file_path in pdf_files:
        try:
            print(f"Converting: {file_path}")
            text = convert_pdf(file_path)
            if not text:
                text = "(Empty or unreadable content)"

            base_name = os.path.basename(file_path).replace(".pdf", ".md")
            output_path = os.path.join(OUTPUT_DIR, base_name)
            
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(f"# SOURCE: {file_path}\n\n{text}")
        except Exception as e:
             print(f"Failed to process {file_path}: {e}")

    print("Conversion complete.")

if __name__ == "__main__":
    main()
