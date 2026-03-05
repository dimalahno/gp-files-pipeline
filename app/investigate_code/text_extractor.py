#!/usr/bin/env python3
"""
Файл 1: Извлечение текста из документов (PDF/DOCX/DOC).

Преобразует документы в сырой текст:
- PDF (векторный) → координатная группировка слов (PyMuPDF)
- PDF (сканированный) → OCR через Tesseract (pytesseract)
- DOCX → python-docx
- DOC → LibreOffice → python-docx

На выходе: {имя_файла}_raw.txt

Использование:
    # CLI:
        python text_extractor.py [папка_с_документами]

    # Как модуль:
        from text_extractor import DocumentParser, extract_text, extract_text_for_api
        parser = DocumentParser()
        text, _ = parser.parse_file(pdf_bytes)
"""

import io
import os
import re
import sys
import logging
import subprocess
import tempfile
from typing import Union, BinaryIO, List, Tuple, Optional, Dict, Any
from collections import defaultdict

import fitz  # PyMuPDF
import numpy as np
from PIL import Image
from tqdm import tqdm
from pydantic import BaseModel
from docx import Document
import pytesseract


# ==========================================================================
# Tesseract: автоопределение пути
# ==========================================================================

_TESSERACT_PATHS = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
]

_TESSDATA_CANDIDATES = [
    os.path.expanduser("~/tessdata"),
    r"C:\Program Files\Tesseract-OCR\tessdata",
    r"C:\Program Files (x86)\Tesseract-OCR\tessdata",
]


def _configure_tesseract():
    """Автоопределение пути к tesseract.exe и tessdata."""
    # 1) Путь к исполняемому файлу
    try:
        pytesseract.get_tesseract_version()
        # Уже доступен в PATH
    except pytesseract.TesseractNotFoundError:
        for path in _TESSERACT_PATHS:
            if os.path.isfile(path):
                pytesseract.pytesseract.tesseract_cmd = path
                break

    # 2) Путь к tessdata (нужен rus)
    for td in _TESSDATA_CANDIDATES:
        if os.path.isdir(td) and os.path.isfile(os.path.join(td, "rus.traineddata")):
            os.environ["TESSDATA_PREFIX"] = td
            break


_configure_tesseract()


# ==========================================================================
# LOGGING
# ==========================================================================

class CustomLogger(logging.Logger):
    def __init__(self, name, log_file='extractor.log', level=logging.DEBUG):
        super().__init__(name, level)
        log_format = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

        console_handler = logging.StreamHandler()
        console_handler.setFormatter(log_format)
        console_handler.setLevel(level)

        file_handler = logging.FileHandler(log_file, mode='a')
        file_handler.setFormatter(log_format)
        file_handler.setLevel(level)

        self.addHandler(console_handler)
        self.addHandler(file_handler)


logger = CustomLogger(__name__)


# ==========================================================================
# API MODEL
# ==========================================================================

class parseFileRequest(BaseModel):
    """Pydantic-модель запроса для API парсера."""
    object_content: bytes
    file_name: str


# ==========================================================================
# CONSTANTS
# ==========================================================================

MIN_TEXT_LENGTH = 50


# ==========================================================================
# DOCX / DOC PARSING
# ==========================================================================

def parse_docx_file(file_data: Union[str, bytes]) -> str:
    """Parses a .docx file using python-docx and returns text content."""
    if isinstance(file_data, bytes):
        file_data = io.BytesIO(file_data)

    docx = Document(file_data)
    return "\n".join(para.text for para in docx.paragraphs)


def parse_doc_file(object_content: bytes, filename: str) -> Optional[str]:
    """Converts a .doc file to .docx via LibreOffice and parses it."""
    logger.info(f"Converting {filename} to docx...")
    os.makedirs("./tmp", exist_ok=True)

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".doc") as temp_input_file:
            temp_input_file.write(object_content)
            temp_input_file_path = temp_input_file.name

        converted_file_name = "." + temp_input_file_path.rsplit('.', 1)[0] + ".docx"

        cli_command = [
            "soffice", "--headless", "--convert-to", "docx", "--outdir", "./tmp", temp_input_file_path
        ]

        subprocess.run(cli_command, capture_output=True, timeout=60, check=True)
        parsed_text = parse_docx_file(converted_file_name)

        os.remove(converted_file_name)
        os.remove(temp_input_file_path)
        logger.info(f"{filename} is parsed, OK")
        return parsed_text

    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to convert {filename} to docx. Error: {e.stderr.decode() if e.stderr else 'No error message'}")
        return None
    except Exception as e:
        logger.error(f"Error processing {filename}: {e}")
        return None


# ==========================================================================
# DOCUMENT PARSER CLASS (PDF text extraction)
# ==========================================================================

class DocumentParser:
    """
    Парсер PDF-документов с координатной группировкой, авто-DPI,
    и удалением колонтитулов. OCR через Tesseract (pytesseract).
    """

    def __init__(self):
        self.save_folder = './processed_images'
        os.makedirs(self.save_folder, exist_ok=True)

    def parse_file(self, pdf_data: Union[bytes, BinaryIO, str], detect_table: bool = False) -> Tuple[str, Optional[str]]:
        """
        Parse PDF content from binary data, file-like object, or file path.

        Returns:
            Tuple of (extracted_text, table_contents).
            table_contents is None if detect_table is False.
        """
        if isinstance(pdf_data, str):
            with open(pdf_data, 'rb') as f:
                pdf_data = f.read()

        if hasattr(pdf_data, 'read'):
            pdf_data = pdf_data.read()

        pdf_bytes = bytearray(pdf_data)

        extracted_text = ""
        table_contents = None
        self._is_scanned = False

        try:
            if self._detect_pdf_type(pdf_bytes):
                self._is_scanned = True
                extracted_text = self._extract_text_from_image(pdf_bytes)
            else:
                extracted_text = self._extract_text_from_pdf(pdf_bytes)
        except Exception as e:
            logger.error(f"Error during PDF parsing: {e}")
            extracted_text = ""

        return extracted_text, table_contents

    # --- PDF type detection ---

    def _detect_pdf_type(self, pdf_data: bytearray) -> bool:
        """Detect if PDF is image-based (scanned) or vector-based."""
        pdf_stream = io.BytesIO(pdf_data)
        with fitz.open(stream=pdf_stream, filetype="pdf") as doc:
            if len(doc) == 0:
                return False
            page = doc[0]
            return page.get_text().strip() == "" and len(page.get_images(full=True)) > 0

    def _is_erdr_doc(self, text: str) -> bool:
        """Check if the document is from ERDR system (has QR-code marker)."""
        flattened_text = " ".join(text.split()).lower()
        marker = "qr-код содержит хэш-сумму электронного документа"
        return marker in flattened_text

    # --- Vector PDF extraction (coordinate-based grouping) ---

    def _extract_text_from_pdf(self, pdf_data: bytearray, y_tol: float = 3) -> str:
        """Extract text from vector-based PDF with coordinate grouping and header removal."""
        pdf_stream = io.BytesIO(pdf_data)
        pdf_stream.seek(0)
        all_pages_text = []
        all_words_by_page = []

        # ROI for ERDR documents (clips QR codes, signatures, headers)
        page_roi = (50, 50, 550, 842)
        last_page_roi = (50, 50, 550, 785)

        with fitz.open(stream=pdf_stream, filetype="pdf") as doc:
            if len(doc) == 0:
                return ""

            is_erdr = self._is_erdr_doc(doc[-1].get_text("text"))

            for i, page in enumerate(doc):
                if is_erdr and i == len(doc) - 1:
                    words = page.get_text("words", clip=last_page_roi)
                elif is_erdr and i < len(doc) - 1:
                    words = page.get_text("words", clip=page_roi)
                else:
                    words = page.get_text("words")

                all_words_by_page.append(words)

                if not words:
                    all_pages_text.append("")
                    continue

                # Group words into lines by Y-coordinate
                rows = defaultdict(list)
                for x0, y0, x1, y1, word, *rest in words:
                    key = int(round(y0 / y_tol))
                    rows[key].append((x0, word))

                lines = []
                for row_key in sorted(rows):
                    row_words = sorted(rows[row_key], key=lambda item: item[0])
                    lines.append(" ".join(w for _, w in row_words))

                all_pages_text.append("\n".join(lines))

            # Remove repeating headers/footers (appear at same position on all pages)
            if len(doc) > 1:
                try:
                    repeating = self._find_repeating_words(all_words_by_page)
                    if repeating:
                        cleaned = []
                        for page_words in all_words_by_page:
                            filtered = [
                                (x0, y0, x1, y1, word, *rest)
                                for (x0, y0, x1, y1, word, *rest) in page_words
                                if (round(x0), round(y0), word) not in repeating
                            ]

                            rows = defaultdict(list)
                            for x0, y0, x1, y1, word, *rest in filtered:
                                key = int(round(y0 / y_tol))
                                rows[key].append((x0, word))

                            lines = []
                            for row_key in sorted(rows):
                                rw = rows[row_key]
                                if rw:
                                    rw.sort(key=lambda item: item[0])
                                    lines.append(" ".join(w for _, w in rw))

                            cleaned.append("\n".join(lines))

                        if all(p.strip() for p in cleaned):
                            all_pages_text = cleaned
                except Exception:
                    pass

        return "\n\n".join(all_pages_text)

    def _find_repeating_words(self, all_words_by_page: List) -> set:
        """Find words that appear at the same position on ALL pages (headers/footers)."""
        if not all_words_by_page or len(all_words_by_page) <= 1:
            return set()

        position_word_counts = defaultdict(int)
        for page_words in all_words_by_page:
            seen_on_page = set()
            for x0, y0, x1, y1, word, *_ in page_words:
                pos_word_key = (round(x0), round(y0), word)
                if pos_word_key not in seen_on_page:
                    position_word_counts[pos_word_key] += 1
                    seen_on_page.add(pos_word_key)

        total_pages = len(all_words_by_page)
        return {
            pos_word for pos_word, count in position_word_counts.items()
            if count == total_pages
        }

    # --- Scanned PDF / OCR extraction (Tesseract) ---

    def _get_dpi(self, pdf_data: bytearray) -> int:
        """Auto-detect DPI from PDF image metadata."""
        pdf_stream = io.BytesIO(pdf_data)
        default_dpi = 200

        try:
            with fitz.open(stream=pdf_stream, filetype="pdf") as doc:
                if len(doc) == 0:
                    return default_dpi
                page = doc[0]
                image_list = page.get_images(full=True)
                if not image_list:
                    return default_dpi

                xref = image_list[0][0]
                base_image = doc.extract_image(xref)
                if not base_image:
                    return default_dpi

                img_width = base_image["width"]
                img_height = base_image["height"]
                page_width = page.rect.width
                page_height = page.rect.height
                width_dpi = int(img_width / (page_width / 72))
                height_dpi = int(img_height / (page_height / 72))
                dpi = (width_dpi + height_dpi) // 2

                if dpi < 50 or dpi > 600:
                    return default_dpi
                return dpi

        except Exception as e:
            logger.warning(f"Error determining DPI: {e}")
            return default_dpi

    def _get_ocr_lang(self, pdf_data: bytearray) -> str:
        """Detect OCR language by running Tesseract OSD on first page."""
        try:
            with fitz.open(stream=io.BytesIO(pdf_data), filetype="pdf") as doc:
                if len(doc) == 0:
                    return "rus"
                page = doc[0]
                pix = page.get_pixmap(dpi=150, alpha=False)
                img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                osd = pytesseract.image_to_osd(img, output_type=pytesseract.Output.DICT)
                script = osd.get("script", "").lower()
                if "cyrillic" in script:
                    return "rus+kaz"
                elif "latin" in script:
                    return "eng"
                return "rus+kaz"
        except Exception:
            return "rus+kaz"

    def _extract_text_from_image(self, pdf_data: bytearray) -> str:
        """Extract text from scanned PDF using Tesseract OCR."""
        dpi = self._get_dpi(pdf_data)
        ocr_dpi = min(dpi, 300)
        lang = self._get_ocr_lang(pdf_data)
        logger.info(f"Tesseract OCR: DPI={ocr_dpi}, lang={lang}")
        return self._ocr_with_tesseract(pdf_data, ocr_dpi, lang)

    def _ocr_with_tesseract(self, pdf_data: bytearray, dpi: int, lang: str) -> str:
        """OCR all pages of a scanned PDF using Tesseract."""
        all_text = []
        with fitz.open(stream=io.BytesIO(pdf_data), filetype="pdf") as doc:
            for i, page in enumerate(doc):
                logger.info(f"Tesseract page {i + 1}/{len(doc)}")
                pix = page.get_pixmap(dpi=dpi, alpha=False)
                img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

                try:
                    page_text = pytesseract.image_to_string(
                        img, lang=lang,
                        config="--psm 6"
                    )
                    all_text.append(page_text.strip())
                except Exception as e:
                    logger.warning(f"Tesseract failed on page {i+1}: {e}")
                    all_text.append("")

        return "\n\n".join(all_text)


# ==========================================================================
# UNIFIED EXTRACT FUNCTION
# ==========================================================================

def extract_text(file_path: str) -> Tuple[str, str]:
    """
    Extract text from a file (PDF or DOCX).

    Returns:
        Tuple of (text, method) where method is "text", "ocr", "docx", or "error".
    """
    if file_path.lower().endswith(".docx"):
        try:
            with open(file_path, 'rb') as f:
                text = parse_docx_file(f.read())
            return text, "docx"
        except Exception as e:
            return f"[DOCX ERROR: {e}]", "error"

    # PDF — use DocumentParser with coordinate grouping
    parser = DocumentParser()
    try:
        text, _ = parser.parse_file(file_path)
        # Используем флаг _is_scanned для корректной статистики
        if parser._is_scanned:
            return text or "", "ocr"
        return text or "", "text"
    except Exception as e:
        return f"[PDF ERROR: {e}]", "error"


# ==========================================================================
# API FUNCTION
# ==========================================================================

def extract_text_for_api(file_name: str, file_content: bytes) -> Dict[str, Any]:
    """Extract raw text from file content (for API service).

    Args:
        file_name: Original filename with extension.
        file_content: Raw file bytes.

    Returns:
        Dict with "raw_text" and "method".
    """
    if file_name.lower().endswith(".pdf"):
        parser = DocumentParser()
        text, _ = parser.parse_file(file_content)
        method = "ocr" if parser._is_scanned else "text"
    elif file_name.lower().endswith(".docx"):
        text = parse_docx_file(file_content)
        method = "docx"
    elif file_name.lower().endswith(".doc"):
        text = parse_doc_file(file_content, file_name)
        method = "doc"
    else:
        raise ValueError(f"Unsupported file type: {file_name}")

    return {"raw_text": text or "", "method": method}


# ==========================================================================
# CLI MAIN
# ==========================================================================

def main():
    """Extract text from all PDF/DOCX/DOC files in a folder → *_raw.txt"""
    input_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(input_dir, "raw_texts")
    os.makedirs(output_dir, exist_ok=True)

    all_files = sorted(
        f for f in os.listdir(input_dir)
        if f.lower().endswith((".pdf", ".docx", ".doc"))
    )

    if not all_files:
        print(f"Файлы не найдены в {input_dir}")
        sys.exit(1)

    print(f"Найдено {len(all_files)} файлов")
    print(f"Результаты: {output_dir}")
    print()

    counts = {"text": 0, "ocr": 0, "docx": 0, "doc": 0, "error": 0}

    for i, filename in enumerate(tqdm(all_files, desc="Извлечение текста"), 1):
        file_path = os.path.join(input_dir, filename)

        if filename.lower().endswith(".doc") and not filename.lower().endswith(".docx"):
            try:
                with open(file_path, 'rb') as f:
                    text = parse_doc_file(f.read(), filename)
                method = "doc"
            except Exception as e:
                text = f"[DOC ERROR: {e}]"
                method = "error"
        else:
            text, method = extract_text(file_path)

        counts[method] = counts.get(method, 0) + 1

        base_name = os.path.splitext(filename)[0]
        out_path = os.path.join(output_dir, f"{base_name}_raw.txt")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(text or "")

    print()
    print("=" * 60)
    print(f"Обработано: {len(all_files)} файлов")
    print(f"  Текстовые PDF (PyMuPDF): {counts.get('text', 0)}")
    print(f"  Сканированные PDF (OCR): {counts.get('ocr', 0)}")
    print(f"  DOCX:                    {counts.get('docx', 0)}")
    print(f"  DOC:                     {counts.get('doc', 0)}")
    print(f"  Ошибки:                  {counts.get('error', 0)}")
    print(f"Результаты: {output_dir}")


if __name__ == "__main__":
    main()
