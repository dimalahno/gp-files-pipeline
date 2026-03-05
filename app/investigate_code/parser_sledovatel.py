#!/usr/bin/env python3
"""
Объединённый парсер документов уголовного дела.

Лучшее из двух парсеров:
- Извлечение текста: координатная группировка, auto-DPI, обработка поворотов, удаление колонтитулов (A)
- Очистка: 50+ boilerplate-паттернов (B) + OCR-чистка (A)
- Классификация: по имени файла и по содержанию (B)
- Извлечение данных: regex для ФИО, ИИН, дат, статей, сумм, показаний (B)
- Дедупликация ФИО: алгоритмическая с учётом OCR-ошибок (B)

Использование:
    # Как модуль (для API-сервиса):
        from preprocess_merged import DocumentParser, classify_by_filename, extract_essential_data, clean_boilerplate
        parser = DocumentParser()
        raw_text, table_contents = parser.parse_file(pdf_bytes)
        cleaned = clean_boilerplate(raw_text)
        data = extract_essential_data(raw_text, doc_type="protocol", cleaned_text=cleaned)

    # Как CLI (автономный режим):
        python preprocess_merged.py [папка_с_документами]
"""

import io
import os
import re
import sys
import logging
import subprocess
import tempfile
import html as html_module
from typing import Union, BinaryIO, List, Tuple, Optional, Dict, Any
from collections import defaultdict
from datetime import datetime

import fitz  # PyMuPDF
import numpy as np
import cv2
import pytesseract
import pdf2image
from pdf2image import convert_from_bytes
from PIL import Image
from tqdm import tqdm
from pydantic import BaseModel
from docx import Document


# ==========================================================================
# LOGGING
# ==========================================================================

class CustomLogger(logging.Logger):
    def __init__(self, name, log_file='parser.log', level=logging.DEBUG):
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
    """Pydantic-модель запроса для API парсера. Имя в camelCase для обратной совместимости с parse_files_app.py."""
    object_content: bytes
    file_name: str


# ==========================================================================
# CONSTANTS: CLASSIFICATION
# ==========================================================================

MIN_TEXT_LENGTH = 50

SKIP_FILE_TYPES = {"cov_letter", "notification_erdr", "phototable"}

SKIP_OTHER_SUBTYPES = {
    "obligation",
    "language_statement",
    "format_statement",
    "rights_explanation",
    "empty",
    "admin_form",
    "phototable_embedded",
}

DOC_TYPE_NAMES = {
    "decree": "Постановление",
    "protocol": "Протокол допроса",
    "report_erdr": "Рапорт ЕРДР",
    "report_kui": "Рапорт КУИ",
    "court_ruling": "Протокол судебного заседания",
    "detention_notice": "Уведомление о задержании",
    "counsel_notice": "Уведомление о защитнике",
    "case_acceptance": "Принятие дела к производству",
    "seizure_decree": "Постановление о выемке",
    "legal_aid_request": "Ходатайство о юр. помощи",
    "other": "Иной документ",
    "obligation": "Обязательство о явке [ПРОПУЩЕНО]",
    "language_statement": "Заявление о языке [ПРОПУЩЕНО]",
    "format_statement": "Заявление о формате [ПРОПУЩЕНО]",
    "rights_explanation": "Разъяснение прав [ПРОПУЩЕНО]",
    "empty": "Пустой документ [ПРОПУЩЕНО]",
    "admin_form": "Адм. форма [ПРОПУЩЕНО]",
    "phototable_embedded": "Фототаблица [ПРОПУЩЕНО]",
}

LANG_NAMES = {"RU": "Русский", "KK": "Казахский", "": ""}


# ==========================================================================
# CONSTANTS: BOILERPLATE PATTERNS (from B — 50+ regex patterns)
# ==========================================================================

BOILERPLATE_PATTERNS = [
    # QR-коды и ЭЦП
    r"QR-код содержит\s+хэш-сумму электронного документа.*?подписанного ЭЦП",
    r"QR-код содержит\s+данные\s+ЭЦП\s+подписавшего лица.*?подписания документа",
    r"QR-код ЭЦҚ койылған PDF форматтағы электрондық.*?хэш соммасын қамтиды",
    r"QR-код қол қойған тұлғаның ЭЦҚ туралы.*?уақытты қамтиды",
    # Подписи документа
    r"Документ подготовил и подписал:.*?erdr@kgp\.kz",
    r"Құжатты дайындады және қол қойды:.*?erdr@kgp\.kz",
    r"Документ согласован?:.*?erdr@kgp\.kz",
    r"Құжат келісілді:.*?erdr@kgp\.kz",
    r"Документ утвердил:.*?erdr@kgp\.kz",
    r"Документ согласовал:.*?(?=\n\n|\n[А-Я])",
    # ИС ЕРДР
    r"ИС «Единый реестр досудебных расследований»",
    r"«Сотқа дейінгі тергеудің бірыңғай тізілімі» АЖ",
    # Блоки прав потерпевшего
    r"Потерпевший\s+имеет\s+право:.*?(?=Потерпевш(?:ему|ей|ий).*?предупрежден|По\s+существу|Я,\s|показания\s+желаю|$)",
    r"Потерпевший\s+обязан:.*?(?=Потерпевш(?:ему|ей|ий).*?предупрежден|По\s+существу|Я,\s|$)",
    # Блоки прав свидетеля
    r"Свидетель(?:,\s+имеющий\s+право\s+на\s+защиту,)?\s+имеет\s+право:.*?(?=Свидетель.*?предупрежден|По\s+существу|Права\s+и\s+обязанности|Я,\s|$)",
    r"Свидетель(?:,\s+имеющий\s+право\s+на\s+защиту,)?\s+обязан:.*?(?=По\s+существу|Свидетелю|Права\s+и\s+обязанности|$)",
    # Блоки прав подозреваемого
    r"Подозреваемый\s+вправе:.*?(?=По\s+существу|Подозреваемому|Права\s+(?:и\s+обязанности\s+)?подозреваемого|Я,\s|$)",
    r"Подозреваемый\s+обязан:.*?(?=По\s+существу|Подозреваемому|$)",
    # Права подозреваемого ст.64 УПК
    r"Права\s+подозреваемого,?\s*предусмотренные\s+ст\.?\s*\d+\s+(?:Уголовно-\s*процессуального\s+кодекса|УПК)\s+.*?Сущность\s+прав\s+ясна\.?",
    # Отказ от показаний
    r"Подозреваемый\s+имеет\s+право\s+отказаться\s+от\s+дачи\s+показаний.*?(?:первого\s+допроса|показаний)\.?",
    # Предупреждение об использовании показаний
    r"Подозреваемый\s+предупрежден\s+о\s+том,?\s+что\s+его\s+показания\s+могут\s+быть\s+использованы.*?(?:от\s+этих\s+показаний|показаний)\.\s*",
    # Признание вины
    r"На\s+вопрос,?\s+признает\s+ли\s+подозреваемый.*?пояснил[:\s]*.*?(?=\n)",
    # Предложение дать показания
    r"Подозреваемому\(ой\)\s+предложено\s+дать\s+показания.*?следующие\s+показания:\s*",
    # Нумерованные пункты прав
    r"(?:права\s+и\s+обязанности.*?предусмотренные\s+ст\.?\s*(?:65-1|71|64|78)\s+УПК.*?а\s+именно:\s*\n?)(?:\d+\)\s+.+?\n)+.*?(?=Права\s+и\s+обязанности.*?мне\s+разъяснены|Я,\s|$)",
    # Полный текст прав свидетеля
    r"Свидетель\s+(?:при\s+допросе\s+)?(?:вправе|имеет\s+право)[:\s].*?(?=Права\s+и\s+обязанности.*?мне\s+разъяснены|Сущность\s+прав\s+ясна|По\s+существу|Я,\s)",
    # Неявка адвоката
    r"в\s+присутствии\s+(?:своего\s+)?адвоката\.?\s*Неявка\s+адвоката.*?(?=Права\s+и\s+обязанности|Сущность\s+прав|$)",
    # Возмещение расходов свидетелю
    r"Свидетелю\s+обеспечивается\s+возмещение\s+расходов.*?(?=Права\s+и\s+обязанности|Сущность\s+прав|$)",
    # Разъяснение прав свидетелю
    r"Права\s+и\s+обязанности\s+свидетеля,?\s*предусмотренные\s+ст\.?\s*\d+\s+УПК\s+РК,?\s*мне\s+разъяснены\.?\s*Сущность\s+прав\s+ясна\.?",
    # Подписи участников
    r"(?:Свидетель|Потерпевший|Подозреваемый\(ая\)|Защитник)[:\s]*\n\s*[А-ЯЁ][а-яёА-ЯЁ]+\s+[А-ЯЁ]\.[А-ЯЁ]\.(?:\s*\n)?",
    # Предупреждение свидетеля об ответственности
    r"Свидетель\s+\S+\s+\S+\s+предупрежден\(а\)\s+об\s+уголовной\s+ответственности.*?(?=Свидетелю\s+разъяснено|По\s+существу|Я,\s)",
    # Право отказа от показаний свидетеля
    r"Свидетелю\s+разъяснено\s+право\s+отказаться\s+от\s+дачи\s+показаний.*?(?:родственников|үй-ішілік)\.?",
    # Язык показаний
    r"Я,?\s+\S+\s+\S+\.?\s+показания\s+желаю\s+давать\s+на\s+\S+\s+языке[^.]*не\s+нуждаюсь\.?",
    # Предложение рассказать
    r"Свидетелю\s+предложено\s+рассказать\s+об\s+отношениях.*?следующие\s+показания:\s*",
    # Ознакомление с протоколом
    r"С\s+протоколам?\s+ознакомлен[^.]*ходатайств\s+не\s+имею\.?",
    # Уточнение показаний
    r"С\s+целью\s+уточнения\s+и\s+дополнения\s+показаний\s+(?:свидетеля|подозреваемого)\s+(?:ему\(ей\)|ему)\s+заданы\s*\n?\s*следующие\s+вопросы[:\s]*",
    # Подписи подозреваемого и защитника
    r"Подозреваемый\(ая\)[:\s]*\n\s*[А-ЯЁ][а-яёА-ЯЁ]+\s+[А-ЯЁ]\.[А-ЯЁ]\.\s*\n?\s*(?:Защитник[:\s]*\n\s*[А-ЯЁ][а-яёА-ЯЁ]+\s+[А-ЯЁ]\.[А-ЯЁ]\.\s*)?",
    # Участие защитника
    r",?\s+с\s+участием\s+защитника\.?\s*",
    # Развёрнутый блок прав с нумерацией
    r"(?:разъяснены\s+права,?\s*предусмотренные\s+ст\.?\s*\d+\s+УПК\s+РК,?\s*а\s+именно:\s*\n?)[\s\S]*?(?=Сущность\s+прав\s+ясна|Права\s+.*?мне\s+разъяснены|На\s+вопрос,?\s+признает|По\s+существу|По\s+поводу\s+подозрения)",
    # Fallback нумерованных пунктов
    r"\n\d+(?:-\d+)?\)\s+(?:знать|получить|защищать|участвовать|заявлять|представлять|давать|отказаться|приносить|обжаловать|знакомиться|пользоваться|ходатайствовать|иметь|примириться|возражать|безотлагательно|при\s+назначении|в\s+порядке)[^\n]*(?:\n(?!\d+[).]|\n\n|Права|Сущность|По\s+существу|По\s+поводу)[^\n]+)*",
]


# ==========================================================================
# CONSTANTS: REGEX PATTERNS FOR DATA EXTRACTION (from B)
# ==========================================================================

EXTRACTION_PATTERNS = {
    "case_numbers": r"№\s*(\d{12,15})",
    "iin": r"ИИН[:\s]*(\d{12})",
    "dates_dot": r"\b(\d{1,2}\.\d{2}\.\d{4})\b",
    "dates_text_ru": r"(\d{1,2})\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\s+(\d{4})\s+года",
    "dates_text_kk": r"(\d{4})\s+жыл\s+(\d{1,2})\s+(қаңтар|ақпан|наурыз|сәуір|мамыр|маусым|шілде|тамыз|қыркүйек|қазан|қараша|желтоқсан)",
    "articles_ru": r"ст\.?\s*(\d+)\s*ч\.?\s*(\d+)\s*УК\s*РК",
    "articles_kk": r"ҚК-(?:нің|тің)\s+(\d+)-бабы\s+(\d+)-бөлігі",
    "phones": r"(?:\+7|8)[\s\-]?\(?[0-9]{3}\)?[\s\-]?[0-9]{3}[\s\-]?[0-9]{2}[\s\-]?[0-9]{2}",
    "amounts": r"(\d[\d\s]{0,15})\s*(?:тенге|тг\.?|ТЕНГЕ)",
    "addresses_ru": r"г\.?\s*(?:Кокшетау|Астана|Нур-Султан|Алматы|Караганда|Актобе|Шымкент|Костанай|Павлодар|Семей|Тараз|Атырау|Петропавловск|Усть-Каменогорск|Талдыкорган|Актау|Кызылорда|Туркестан)(?:[,\s]+(?:ул\.|улица|пр\.|просп\.|к-сі|көш)\s*[А-ЯЁа-яёӘәҒғҚқҢңӨөҰұҮүҺһІі\d/.]+(?:[,\s]+(?:д\.|дом|кв\.|квартира)\s*[\d/]+)*)*",
    "case_id_court": r"Номер дела:\s*(.+)",
}

FIO_PATTERN = r"(?<!\w)([А-ЯЁӘҒҚҢӨҰҮҺІ][а-яёәғқңөұүһі]+)\s+([А-ЯЁӘҒҚҢӨҰҮҺІ][а-яёәғқңөұүһі]+)\s+([А-ЯЁӘҒҚҢӨҰҮҺІ][а-яёәғқңөұүһі]+(?:вна|вич|ович|евна|евич|ұлы|қызы|кызы|улы))"


# ==========================================================================
# DOCX / DOC PARSING (from A)
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
# DOCUMENT PARSER CLASS (text extraction from A, enhanced)
# ==========================================================================

class DocumentParser:
    """
    Парсер PDF-документов с координатной группировкой, авто-DPI,
    обнаружением повёрнутых страниц и удалением колонтитулов.
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

        try:
            if self._detect_pdf_type(pdf_bytes):
                extracted_text = self._extract_text_from_image(pdf_bytes)
            else:
                extracted_text = self._extract_text_from_pdf(pdf_bytes)

            table_contents = None
            # Table detection is optional; requires model to be loaded
            # if detect_table:
            #     dpi = self._get_dpi(pdf_bytes)
            #     image_pages = convert_from_bytes(pdf_bytes, dpi=dpi)
            #     table_contents = self._get_table_contents(image_pages)

        except Exception as e:
            logger.error(f"Error during PDF parsing: {e}")
            extracted_text = ""
            table_contents = None

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

    # --- Vector PDF extraction (coordinate-based grouping from A) ---

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

    # --- Scanned PDF / OCR extraction (from A) ---

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

    def _page_is_rotated(self, page: fitz.Page) -> bool:
        """Check if a page is rotated using Tesseract OSD."""
        try:
            pix = page.get_pixmap(dpi=72, alpha=False)
            arr = np.frombuffer(pix.samples, dtype=np.uint8)
            img = arr.reshape((pix.h, pix.w, pix.n))
            if pix.n == 4:
                img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

            osd = pytesseract.image_to_osd(gray, config="--psm 0")
            angle = int(next(line for line in osd.splitlines() if line.startswith("Rotate")).split(":")[1])
            return (angle % 360) != 0
        except Exception:
            return False

    def _drop_rotated_pages(self, pdf_bytes) -> bytes:
        """Drop rotated pages from scanned PDF."""
        with fitz.open(stream=io.BytesIO(pdf_bytes), filetype="pdf") as doc:
            keep_mask = [not self._page_is_rotated(page) for page in doc]

            total_pages = len(keep_mask)
            dropped = total_pages - sum(keep_mask)
            logger.info(f"Total pages: {total_pages}, Dropped rotated: {dropped}")

            if all(keep_mask):
                return pdf_bytes

            new_doc = fitz.open()
            for i, keep in enumerate(keep_mask):
                if keep:
                    new_doc.insert_pdf(doc, from_page=i, to_page=i)
                else:
                    logger.info(f"Dropped page {i + 1} (rotated)")

            out = io.BytesIO()
            new_doc.save(out)
            new_doc.close()
            return out.getvalue()

    def _extract_text_from_image(self, pdf_data: bytearray) -> str:
        """Extract text from scanned PDF using OCR with auto-DPI and rotation handling."""
        pdf_data = self._drop_rotated_pages(pdf_data)
        dpi = self._get_dpi(pdf_data)
        logger.info(f"OCR DPI: {dpi}")

        images = pdf2image.convert_from_bytes(pdf_data, dpi=dpi)
        all_text = []

        for i, image in tqdm(enumerate(images), total=len(images), desc="OCR"):
            tqdm.write(f"OCR page {i + 1}/{len(images)}")

            img_np = np.array(image)
            text = pytesseract.image_to_string(
                img_np,
                lang='rus+kaz',
                config='--psm 3 --oem 3'
            )
            all_text.append(text)

        return "\n\n".join(all_text)


# ==========================================================================
# TEXT CLEANING (combined from A + B)
# ==========================================================================

def clean_ocr_artifacts(text: str) -> str:
    """Clean OCR artifacts and formatting issues (from A's _clean_text)."""
    text = html_module.unescape(text)
    # Remove emails
    text = re.sub(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', '', text)
    # Deduplicate repeated phrases
    text = re.sub(r'до\s+18\s+лет[\s,.;]*(?:.*?до\s+18\s+лет){2,}', 'до 18 лет', text, flags=re.DOTALL)
    text = re.sub(r'совершеннолетия[\s,.;]*(?:.*?совершеннолетия){2,}', 'совершеннолетия', text, flags=re.DOTALL)
    text = re.sub(r'(до\s+18\s+лет)(?:[\s,.;]+до\s+18\s+лет)+', r'\1', text)
    text = re.sub(r'(совершеннолетия)(?:[\s,.;]+совершеннолетия)+', r'\1', text)
    # Deduplicate within paragraphs
    paragraphs = []
    for paragraph in text.split('\n\n'):
        do_18_count = len(re.findall(r'до\s+18\s+лет', paragraph))
        if do_18_count > 1:
            paragraph = re.sub(r'до\s+18\s+лет.*', 'до 18 лет', paragraph, flags=re.DOTALL)
        paragraphs.append(paragraph)
    text = '\n\n'.join(paragraphs)
    # Remove repeated word sequences (OCR artifact)
    text = re.sub(r'(\b\w+(?:\s+\w+){0,3}\b)(?:,?\s+\1){3,}', r'\1', text)
    # Fix spacing around №
    text = re.sub(r'№\s+', '№', text)
    # Fix date spacing (e.g. "01 . 01 . 2025" -> "01.01.2025")
    text = re.sub(r'(\d)\s+(\.)(\s*)(\d)', r'\1\2\4', text)
    # Add paragraph breaks after sentence endings before uppercase
    text = re.sub(r'([.!?:;»\)])(\s*)\n([A-ZА-ЯЁ№])', r'\1\2\n\n\3', text)
    # Join broken lines (line ending without punctuation)
    text = re.sub(r'(\S+)\n(?![A-ZА-ЯЁ№\d])', r'\1 ', text)
    # Normalize whitespace
    text = re.sub(r' {2,}', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r' +(?=\n)', '', text)
    text = re.sub(r'\n +', '\n', text)

    return text.strip()


def clean_boilerplate(text: str) -> str:
    """Remove procedural boilerplate blocks using 50+ regex patterns (from B)."""
    cleaned = text
    for pattern in BOILERPLATE_PATTERNS:
        cleaned = re.sub(pattern, "", cleaned, flags=re.DOTALL | re.IGNORECASE)
    # Normalize resulting whitespace
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = "\n".join(line.rstrip() for line in cleaned.split("\n"))
    return cleaned.strip()


def full_clean(text: str) -> str:
    """Full cleaning pipeline: OCR artifacts + boilerplate removal."""
    text = clean_ocr_artifacts(text)
    text = clean_boilerplate(text)
    return text


# ==========================================================================
# CLASSIFICATION (from B)
# ==========================================================================

def classify_by_filename(filename: str) -> Dict[str, str]:
    """Classify document type by filename prefix."""
    name_no_ext = filename
    ext = ""
    for e in [".pdf", ".docx"]:
        if filename.lower().endswith(e):
            name_no_ext = filename[:-len(e)]
            ext = e
            break

    parts = name_no_ext.split("_")

    doc_type = "other"
    if filename.upper().startswith("COURT_RULING"):
        doc_type = "court_ruling"
    else:
        for known in ["cov_letter", "report_erdr", "report_kui",
                       "notification_erdr", "phototable", "decree", "protocol"]:
            if filename.startswith(known):
                doc_type = known
                break

    lang = parts[-1] if parts[-1] in ("RU", "KK") else ""

    case_number = ""
    timestamp = ""
    numeric_parts = [p for p in parts if re.match(r"^\d{10,}$", p)]
    if len(numeric_parts) >= 2:
        case_number = numeric_parts[0]
        timestamp = numeric_parts[1]
    elif len(numeric_parts) == 1:
        p = numeric_parts[0]
        if len(p) == 15:
            case_number = p
        elif len(p) == 13:
            timestamp = p
        else:
            case_number = p

    court_date = ""
    if doc_type == "court_ruling":
        m = re.search(r"(\d{2}\.\d{2}\.\d{4})", filename)
        if m:
            court_date = m.group(1)

    return {
        "type": doc_type,
        "lang": lang,
        "case_number": case_number,
        "timestamp": timestamp,
        "court_date": court_date,
        "filename": filename,
        "ext": ext,
    }


def classify_other_by_content(text: str) -> str:
    """Classify 'other' documents by text content analysis."""
    if not text or len(text.strip()) < 30:
        return "empty"

    tl = text.lower()

    if "обязательство" in tl and ("о явке" in tl or "являться по вызов" in tl):
        return "obligation"
    if "міндеттеме" in tl:
        return "obligation"
    if "о языке уголовного судопроизводства" in tl or "тіл туралы" in tl:
        return "language_statement"
    if ("формат" in tl and "судопроизводства" in tl) or "электронного формата" in tl:
        return "format_statement"
    if "разъяснен" in tl and ("прав" in tl and ("подозреваем" in tl or "потерпевш" in tl or "свидетел" in tl)):
        return "rights_explanation"
    if re.search(r"протокол\s*\n?\s*разъяснени[ея]\s+прав", tl):
        return "rights_explanation"
    if "фототаблица" in tl or "фото №" in tl:
        return "phototable_embedded"
    if "задержан" in tl and ("подозреваем" in tl or "уведомлени" in tl or "уведомляю" in tl):
        return "detention_notice"
    if "ұсталғаны" in tl or "ұстау" in tl:
        return "detention_notice"
    if ("защит" in tl or "адвокат" in tl) and ("уведомлени" in tl or "вступ" in tl or "назначен" in tl):
        return "counsel_notice"
    if "ходатайств" in tl and ("юридическ" in tl or "помощ" in tl or "защит" in tl):
        return "legal_aid_request"
    if "принятии" in tl and ("уголовного дела" in tl or "к своему производству" in tl):
        return "case_acceptance"
    if "өз өндірісіне қабылдау" in tl:
        return "case_acceptance"
    if "выемк" in tl or ("алу" in tl and "қаулы" in tl):
        return "seizure_decree"
    if len(text.strip()) < 100:
        return "admin_form"

    return "other"


def detect_language(text: str) -> str:
    """Detect document language (RU/KK) by keyword markers."""
    kk_markers = ["қаулы", "бабы", "бөлігі", "тергеуші", "анықтаушы", "құжат",
                   "жылы", "қаңтар", "ақпан", "туралы", "бойынша", "тұлға"]
    ru_markers = ["постановление", "протокол", "следователь", "допрос",
                  "установил", "дознаватель", "потерпевш", "свидетел"]
    tl = text.lower()
    kk = sum(1 for m in kk_markers if m in tl)
    ru = sum(1 for m in ru_markers if m in tl)
    if kk > ru:
        return "KK"
    if ru > kk:
        return "RU"
    return ""


# ==========================================================================
# FIO DEDUPLICATION (from B — Levenshtein-based)
# ==========================================================================

def _normalize_fio_key(fio: str) -> str:
    """Create normalized key for FIO comparison (handles OCR and Kazakh letters)."""
    trans = str.maketrans("ӘәҒғҚқҢңӨөҰұҮүҺһІі", "ААГгКкНнООУуУуХхИи")
    key = fio.translate(trans).lower()
    key = re.sub(r"(.)\1+", r"\1", key)
    return key


def _levenshtein(s1: str, s2: str) -> int:
    """Levenshtein distance for fuzzy string comparison."""
    if len(s1) < len(s2):
        return _levenshtein(s2, s1)
    if len(s2) == 0:
        return len(s1)
    prev_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = prev_row[j + 1] + 1
            deletions = curr_row[j] + 1
            substitutions = prev_row[j] + (c1 != c2)
            curr_row.append(min(insertions, deletions, substitutions))
        prev_row = curr_row
    return prev_row[-1]


def _fio_similarity(key1: str, key2: str) -> bool:
    """Check similarity of two FIO keys accounting for OCR errors and declensions."""
    if key1 == key2:
        return True
    parts1 = key1.split()
    parts2 = key2.split()
    if len(parts1) >= 2 and len(parts2) >= 2:
        fam1, name1 = parts1[0], parts1[1]
        fam2, name2 = parts2[0], parts2[1]
        # Exact prefix match (handles declensions)
        if fam1[:5] == fam2[:5] and name1[:3] == name2[:3]:
            return True
        # Fuzzy match (handles OCR errors)
        fam_dist = _levenshtein(fam1[:6], fam2[:6])
        name_dist = _levenshtein(name1[:4], name2[:4])
        if fam_dist <= 2 and name_dist <= 1:
            return True
    return False


def deduplicate_fio(fio_collection) -> set:
    """
    Deduplicate FIO set accounting for OCR errors, declensions, and Kazakh letters.

    Args:
        fio_collection: set of FIO strings, or dict(fio -> count) for frequency-based selection.

    Returns:
        Set of deduplicated FIO strings.
    """
    if isinstance(fio_collection, set):
        fio_counts = {f: 1 for f in fio_collection}
    elif isinstance(fio_collection, dict):
        fio_counts = fio_collection
    else:
        fio_counts = {f: 1 for f in fio_collection}

    fio_list = list(fio_counts.keys())
    keys = [_normalize_fio_key(f) for f in fio_list]
    groups = []
    used = set()

    for i in range(len(fio_list)):
        if i in used:
            continue
        group = [fio_list[i]]
        used.add(i)
        for j in range(i + 1, len(fio_list)):
            if j in used:
                continue
            if _fio_similarity(keys[i], keys[j]):
                group.append(fio_list[j])
                used.add(j)
        groups.append(group)

    result = set()
    for variants in groups:
        def score(v):
            s = fio_counts.get(v, 1) * 20
            parts = v.split()
            if parts and re.search(r"(?:ов|ин|ев|ий|ер[ьт]|ко|ук|юк|ен)$", parts[0]):
                s += 10
            if parts and re.search(r"(?:ова|ову|овым|овою|ину|иным|иною|ому)$", parts[0]):
                s -= 5
            if not re.search(r"[ӘәҒғҚқҢңӨөҰұҮүҺһІі]", v):
                s += 5
            s += len(v) / 100
            return s
        best = max(variants, key=score)
        result.add(best)
    return result


# ==========================================================================
# DATA EXTRACTION (from B)
# ==========================================================================

def extract_essential_data(text: str, doc_type: str, cleaned_text: str = None) -> Dict[str, Any]:
    """
    Extract key data from document text using regex patterns.

    Args:
        text: Raw extracted text.
        doc_type: Document type (e.g. "protocol", "decree").
        cleaned_text: Text after boilerplate removal (for testimony extraction).

    Returns:
        Dict with extracted fields.
    """
    data = {}
    ct = cleaned_text or text

    # FIO
    fio_matches = re.findall(FIO_PATTERN, text)
    if fio_matches:
        raw_fio = set(" ".join(m) for m in fio_matches)
        data["fio"] = list(deduplicate_fio(raw_fio))

    # IIN
    iin = re.findall(EXTRACTION_PATTERNS["iin"], text)
    if iin:
        data["iin"] = list(set(iin))

    # Case numbers
    cases = re.findall(EXTRACTION_PATTERNS["case_numbers"], text)
    if cases:
        data["case_numbers"] = list(set(cases))

    # Dates
    dates = re.findall(EXTRACTION_PATTERNS["dates_dot"], text)
    for d, m, y in re.findall(EXTRACTION_PATTERNS["dates_text_ru"], text):
        dates.append(f"{d}.{m}.{y}")
    for y, d, m in re.findall(EXTRACTION_PATTERNS["dates_text_kk"], text):
        dates.append(f"{d}.{m}.{y}")
    if dates:
        data["dates"] = list(set(dates))

    # Articles UK RK
    articles_ru = re.findall(EXTRACTION_PATTERNS["articles_ru"], text)
    articles_kk = re.findall(EXTRACTION_PATTERNS["articles_kk"], text)
    articles = []
    for art, part in articles_ru:
        articles.append(f"ст.{art} ч.{part} УК РК")
    for art, part in articles_kk:
        articles.append(f"ст.{art} ч.{part} ҚК РК")
    if articles:
        data["articles_uk"] = list(set(articles))

    # Phone numbers
    phones = re.findall(EXTRACTION_PATTERNS["phones"], text)
    if phones:
        data["phones"] = list(set(phones))

    # Amounts
    amounts = re.findall(EXTRACTION_PATTERNS["amounts"], text)
    if amounts:
        normalized_amounts = set()
        for a in amounts:
            num = re.sub(r"\s+", " ", a.strip())
            try:
                val = int(num.replace(" ", ""))
                if val >= 100:
                    normalized_amounts.add(f"{val:,}".replace(",", " ") + " тенге")
            except ValueError:
                pass
        if normalized_amounts:
            data["amounts"] = sorted(normalized_amounts)

    # Addresses
    addresses = re.findall(EXTRACTION_PATTERNS["addresses_ru"], text)
    if addresses:
        data["addresses"] = list(set(addresses))

    # Type-specific extraction (uses cleaned text for testimony)
    if doc_type == "protocol":
        data.update(_extract_protocol_data(text, ct))
    elif doc_type == "decree":
        data.update(_extract_decree_data(ct))
    elif doc_type == "court_ruling":
        data.update(_extract_court_ruling_data(text))
    elif doc_type == "detention_notice":
        data.update(_extract_detention_data(text))

    return data


def _extract_protocol_data(raw_text: str, cleaned_text: str = None) -> Dict:
    """Extract protocol-specific data: subtype, person info, testimony, Q&A."""
    data = {}
    text = raw_text
    ct = cleaned_text or text

    # Protocol subtype
    ptype = re.search(r"ПРОТОКОЛ\s*\n\s*допроса\s+(потерпевшего|свидетеля|подозреваемого|обвиняемого)", text, re.IGNORECASE)
    if not ptype:
        ptype = re.search(r"допроса\s+(свидетеля,\s+имеющего\s+право\s+на\s+защиту)", text, re.IGNORECASE)
        if ptype:
            data["protocol_subtype"] = "Допрос свидетеля (с правом на защиту)"
    if ptype and "protocol_subtype" not in data:
        data["protocol_subtype"] = f"Допрос {ptype.group(1)}"

    # Interrogation time
    start = re.search(r"Допрос начат:\s*(.+)", text)
    end = re.search(r"Допрос окончен:\s*(.+)", text)
    if start:
        data["interrogation_start"] = start.group(1).strip()
    if end:
        data["interrogation_end"] = end.group(1).strip()

    # Person fields from protocol table
    fields = {
        "Фамилия, имя, отчество": "person_name",
        "Дата рождения": "person_dob",
        "Место рождения": "person_birthplace",
        "Гражданство": "person_citizenship",
        "Место работы или учебы": "person_workplace",
        r"Место работы \(учебы\)": "person_workplace",
        "Род занятий или должность": "person_occupation",
        "Место жительства": "person_address",
        "Контактные телефоны": "person_phone",
        "Наличие судимости": "person_criminal_record",
    }
    skip_vals = ("-", "—", "и (или)", "Паспорт или иной документ,",
                 "Паспорт или иной документ", "Место жительства и (или)")
    for label, key in fields.items():
        if key in data:
            continue
        match = re.search(rf"{label}[:\s]*\n?\s*(.+?)(?:\n|$)", text)
        if match:
            val = match.group(1).strip()
            if val and val not in skip_vals and not val.startswith("Паспорт") and not val.startswith("Место жительства и"):
                data[key] = val

    # Testimony extraction (from CLEANED text — without boilerplate rights blocks)
    testimony_patterns = [
        r"По\s+существу\s+(?:заданных\s+вопросов|дела|известных|могу)[^.]{0,80}?(?:показал[аи]?|пояснил[аи]?|сообщил[аи]?|пояснить)\s*(?:следующее)?[:\s,]*(.+?)(?:(?:На\s+этом\s+допрос|Протокол\s+(?:мною\s+)?прочитан|Допрашиваемый|С\s+моих\s+слов\s+записано|Более\s+(?:мне\s+)?по\s+данному\s+факту|Больше\s+мне))",
        r"По\s+поводу\s+подозрения.*?могу\s+(?:показать|пояснить)\s+следующее[:\s]*(.+?)(?:(?:На\s+этом\s+допрос|Протокол\s+(?:мною\s+)?прочитан|С\s+моих\s+слов\s+записано|Более\s+(?:мне\s+)?по\s+данному\s+факту|Больше\s+мне))",
        r"дал[аи]?\s*следующие\s+показания[:\s]*(.+?)(?:(?:На\s+этом\s+допрос|Протокол\s+(?:мною\s+)?прочитан|С\s+моих\s+слов\s+записано))",
        r"могу\s+(?:пояснить|показать)\s+следующее[:\s,]*(.+?)(?:(?:На\s+этом\s+допрос|Протокол\s+(?:мною\s+)?прочитан|С\s+моих\s+слов\s+записано|Более\s+(?:мне\s+)?по\s+данному\s+факту|Больше\s+мне))",
        r"Показания[:\s]+(.+?)(?:(?:На\s+этом\s+допрос|Протокол\s+(?:мною\s+)?прочитан|С\s+моих\s+слов\s+записано))",
    ]
    for pat in testimony_patterns:
        m = re.search(pat, ct, re.DOTALL | re.IGNORECASE)
        if m and len(m.group(1).strip()) > 50:
            testimony = m.group(1).strip()
            # Clean remaining signatures from testimony
            testimony = re.sub(
                r"\n\s*(?:Свидетель|Потерпевший|Подозреваемый\(ая\)|Защитник)[:\s]*\n\s*[А-ЯЁ][а-яёА-ЯЁ]+\s+[А-ЯЁ]\.[А-ЯЁ]\.\s*",
                "\n", testimony
            )
            testimony = re.sub(r"\n\s*С\s+протоколам?\s+ознакомлен[^.]*ходатайств\s+не\s+имею\.?\s*", "\n", testimony)
            testimony = re.sub(r"\n\s*С\s+целью\s+уточнения\s+и\s+дополнения.*$", "", testimony, flags=re.DOTALL)
            testimony = re.sub(r"\n\s*Вопрос:\s.*$", "", testimony, flags=re.DOTALL)
            testimony = testimony.strip()
            if len(testimony) > 50:
                data["testimony"] = testimony
            break

    # Q&A extraction
    qa_blocks = re.findall(
        r"Вопрос:\s{1,3}(.+?)\nОтвет:\s*(.+?)(?=\nВопрос:\s|\n_{2,}|\nНа\s+этом|\nДопросил|$)",
        ct, re.DOTALL | re.IGNORECASE
    )
    if qa_blocks:
        valid_qa = []
        for q, a in qa_blocks:
            q = q.strip()
            a = a.strip()
            # Clean signatures from answers
            a = re.sub(r"\n\s*(?:Свидетель|Потерпевший|Подозреваемый\(ая\)|Защитник)(?:,\s+имеющий\s+право\s+на\s+защиту)?[:\s]*\n?\s*[А-ЯЁ][а-яёА-ЯЁ]+\s+[А-ЯЁ]\.[А-ЯЁ]\.\s*(?:\n.*)?$", "", a, flags=re.DOTALL).strip()
            a = re.sub(r"\n\s*С\s+протоколам?\s+ознакомлен.*$", "", a, flags=re.DOTALL).strip()
            a = re.sub(r"\n\s*[А-ЯЁ][а-яёА-ЯЁ]+\s+[А-ЯЁ]\.[А-ЯЁ]\.\s*$", "", a).strip()
            a = re.sub(r"\n\s*С\s+целью\s+уточнения.*$", "", a, flags=re.DOTALL).strip()
            if len(q) < 15 or len(a) < 3:
                continue
            if re.match(r'^[а-яёА-ЯЁ]{1,3}[:\s]', q) and not re.match(r'^(?:как|что|кто|где|вы\s)', q, re.IGNORECASE):
                continue
            valid_qa.append((q, a))
        if valid_qa:
            qa_text = "\n".join(f"**В:** {q}\n**О:** {a}" for q, a in valid_qa)
            data["qa_section"] = qa_text

    return data


def _extract_decree_data(text: str) -> Dict:
    """Extract decree-specific data: subtype, resolution, description."""
    data = {}

    subtype = re.search(
        r"(?:ПОСТАНОВЛЕНИЕ|ҚАУЛЫ)\s*\n\s*(.+?)(?:\n|г\.|Көкшетау)",
        text, re.IGNORECASE
    )
    if subtype:
        data["decree_subtype"] = subtype.group(1).strip()

    resolution = re.search(
        r"(?:ПОСТАНОВИЛ|ҚАУЛЫ ЕТТІМ)[:\s]*(.*?)(?:QR-код|Документ подготовил|Құжатты дайындады|Настоящее постановление|$)",
        text, re.DOTALL | re.IGNORECASE
    )
    if resolution:
        data["resolution"] = resolution.group(1).strip()

    desc_patterns = [
        r"(?:УСТАНОВИЛ|АНЫҚТАДЫМ)[:\s]*(.*?)(?:На основании|Жоғарыда|руководствуясь|басшылыққа|ПОСТАНОВИЛ|ҚАУЛЫ ЕТТІМ)",
        r"У\s*С\s*Т\s*А\s*Н\s*О\s*В\s*И\s*Л[:\s]*(.*?)(?:На основании|руководствуясь|П\s*О\s*С\s*Т\s*А\s*Н\s*О\s*В\s*И\s*Л)",
    ]
    for pat in desc_patterns:
        m = re.search(pat, text, re.DOTALL | re.IGNORECASE)
        if m and len(m.group(1).strip()) > 30:
            data["description"] = m.group(1).strip()
            break

    return data


def _extract_court_ruling_data(text: str) -> Dict:
    """Extract court ruling data: case ID, judge, subject, times."""
    data = {}
    m = re.search(EXTRACTION_PATTERNS["case_id_court"], text)
    if m:
        data["court_case_id"] = m.group(1).strip()
    m = re.search(r"председательствующего судьи[:\s]*(.+?)(?:\n|$)", text, re.IGNORECASE)
    if m:
        data["judge"] = m.group(1).strip()
    m = re.search(r"в отношении\s+(.+?)(?:\n|$)", text, re.IGNORECASE)
    if m:
        data["court_subject"] = m.group(1).strip()
    m = re.search(r"Время начала судебного заседания[:\s]*(.+?)(?:\n|$)", text)
    if m:
        data["court_time_start"] = m.group(1).strip()
    m = re.search(r"Время окончания судебного заседания[:\s]*(.+?)(?:\n|$)", text)
    if m:
        data["court_time_end"] = m.group(1).strip()
    m = re.search(r"(?:следственный суд|суд)\s+(?:города\s+)?([А-Яа-яЁёӘәҒғҚқ]+)", text, re.IGNORECASE)
    if m:
        data["court_name"] = m.group(0).strip()
    m = re.search(r"установлена связь.*?с\s+(.*?)(?:\n|$)", text, re.IGNORECASE)
    if m:
        data["court_participants"] = m.group(1).strip()
    return data


def _extract_detention_data(text: str) -> Dict:
    """Extract detention notice data: date, time, location."""
    data = {}
    m = re.search(r"задержан[аоы]?\s+(\d{1,2}\.\d{2}\.\d{4})\s*(?:г(?:ода)?\.?)?\s*(?:в\s*)?(\d{1,2}[:\s]*\d{2})", text, re.IGNORECASE)
    if m:
        data["detention_date"] = m.group(1)
        data["detention_time"] = m.group(2)
    m = re.search(r"(?:ИВС|ВС|изолятор|содержится)[:\s]*(.+?)(?:\n|$)", text, re.IGNORECASE)
    if m:
        data["detention_location"] = m.group(1).strip()
    return data


# ==========================================================================
# MARKDOWN GENERATION (from B)
# ==========================================================================

FIELD_LABELS = {
    "fio": "ФИО", "iin": "ИИН", "case_numbers": "Номера дел",
    "dates": "Даты", "articles_uk": "Статьи УК РК",
    "phones": "Телефоны", "amounts": "Суммы", "addresses": "Адреса",
    "protocol_subtype": "Вид протокола",
    "interrogation_start": "Начало допроса",
    "interrogation_end": "Окончание допроса",
    "person_name": "ФИО допрашиваемого",
    "person_dob": "Дата рождения", "person_birthplace": "Место рождения",
    "person_citizenship": "Гражданство",
    "person_workplace": "Место работы", "person_occupation": "Должность",
    "person_address": "Адрес", "person_phone": "Телефон",
    "person_criminal_record": "Судимость",
    "decree_subtype": "Вид постановления",
    "court_case_id": "Номер суд. дела", "judge": "Судья",
    "court_subject": "В отношении",
    "court_time_start": "Начало заседания",
    "court_time_end": "Окончание заседания",
    "court_name": "Суд", "court_participants": "Участники",
    "detention_date": "Дата задержания",
    "detention_time": "Время задержания",
    "detention_location": "Место содержания",
}


def generate_markdown(doc_info: Dict, cleaned_text: str, essential_data: Dict, extraction_method: str) -> str:
    """Generate Markdown document for a single processed file."""
    lines = []
    type_name = DOC_TYPE_NAMES.get(doc_info["type"], doc_info["type"])
    lines.append(f"# {type_name}")
    lines.append("")

    lines.append("## Метаданные")
    lines.append(f"- **Файл:** `{doc_info['filename']}`")
    lines.append(f"- **Тип:** {type_name}")
    if doc_info["lang"]:
        lines.append(f"- **Язык:** {LANG_NAMES.get(doc_info['lang'], doc_info['lang'])}")
    if doc_info["case_number"]:
        lines.append(f"- **Номер дела ЕРДР:** №{doc_info['case_number']}")
    if doc_info.get("court_date"):
        lines.append(f"- **Дата судебного заседания:** {doc_info['court_date']}")
    if doc_info["timestamp"]:
        try:
            ts = int(doc_info["timestamp"]) / 1000
            dt = datetime.fromtimestamp(ts)
            lines.append(f"- **Дата создания:** {dt.strftime('%d.%m.%Y %H:%M')}")
        except (ValueError, OSError):
            pass
    lines.append(f"- **Извлечение:** {extraction_method}")
    lines.append("")

    if essential_data:
        lines.append("## Извлечённые данные")
        for key, label in FIELD_LABELS.items():
            if key in essential_data:
                val = essential_data[key]
                if isinstance(val, list):
                    if len(val) == 1:
                        lines.append(f"- **{label}:** {val[0]}")
                    else:
                        lines.append(f"- **{label}:**")
                        for item in val:
                            lines.append(f"  - {item}")
                else:
                    lines.append(f"- **{label}:** {val}")

        for block_key, block_title in [("testimony", "Показания"), ("qa_section", "Вопросы и ответы"),
                                        ("resolution", "Резолютивная часть"), ("description", "Описательная часть")]:
            if block_key in essential_data:
                lines.append("")
                lines.append(f"### {block_title}")
                lines.append(essential_data[block_key])
        lines.append("")

    lines.append("## Содержание (очищенный текст)")
    lines.append("")
    lines.append(cleaned_text)
    lines.append("")
    return "\n".join(lines)


# ==========================================================================
# CASE SUMMARY (from B)
# ==========================================================================

def _ts_to_date(ts_str: str) -> str:
    if not ts_str:
        return ""
    try:
        return datetime.fromtimestamp(int(ts_str) / 1000).strftime("%d.%m.%Y")
    except (ValueError, OSError):
        return ""


def generate_case_summary(all_docs: List[Dict]) -> str:
    """Generate case summary report from all processed documents."""
    cases = defaultdict(list)
    for doc in all_docs:
        cn = doc["info"]["case_number"] or "без_номера"
        cases[cn].append(doc)

    lines = []
    lines.append("# СПРАВКА ПО ДЕЛУ")
    lines.append("")
    lines.append(f"*Сформировано автоматически: {datetime.now().strftime('%d.%m.%Y %H:%M')}*")
    lines.append("")

    for case_num in sorted(cases.keys()):
        docs = cases[case_num]
        lines.append("---")
        lines.append(f"## Дело №{case_num}")
        lines.append("")

        all_articles = set()
        all_fio = set()
        all_amounts = set()
        all_addresses = set()
        all_phones = set()
        all_iin = set()
        protocols = []
        decrees = []
        detentions = []
        court_rulings = []
        reports = []
        other_useful = []
        fio_counter = defaultdict(int)

        for doc in docs:
            data = doc["data"]
            info = doc["info"]
            dtype = info["type"]

            for a in data.get("articles_uk", []):
                all_articles.add(a)
            for f in data.get("fio", []):
                all_fio.add(f)
                fio_counter[f] += 1
            for am in data.get("amounts", []):
                all_amounts.add(am)
            for ad in data.get("addresses", []):
                all_addresses.add(ad)
            for ph in data.get("phones", []):
                all_phones.add(ph)
            for ii in data.get("iin", []):
                all_iin.add(ii)

            if dtype == "protocol":
                protocols.append(doc)
            elif dtype == "decree":
                decrees.append(doc)
            elif dtype == "detention_notice":
                detentions.append(doc)
            elif dtype == "court_ruling":
                court_rulings.append(doc)
            elif dtype in ("report_erdr", "report_kui"):
                reports.append(doc)
            else:
                other_useful.append(doc)

        # General info
        lines.append("### Общие сведения")
        if all_articles:
            lines.append(f"- **Квалификация:** {', '.join(sorted(all_articles))}")
        if all_fio:
            deduped_fio = deduplicate_fio(fio_counter)
            lines.append("- **Участники:**")
            for f in sorted(deduped_fio):
                lines.append(f"  - {f}")
        if all_iin:
            lines.append(f"- **ИИН:** {', '.join(sorted(all_iin))}")
        if all_amounts:
            lines.append(f"- **Суммы ущерба:** {', '.join(sorted(all_amounts))}")
        if all_addresses:
            clean_addrs = set()
            for addr in all_addresses:
                addr = re.sub(r"\s+", " ", addr.strip())
                if re.search(r"(?:Кокшетау|Астана|Алматы|Караганда|Актобе|Шымкент)", addr, re.IGNORECASE):
                    clean_addrs.add(addr)
            filtered_addrs = set()
            for addr in clean_addrs:
                if "ул." not in addr and "д." not in addr:
                    has_detailed = any(a != addr and addr in a for a in clean_addrs)
                    if not has_detailed:
                        filtered_addrs.add(addr)
                else:
                    filtered_addrs.add(addr)
            if filtered_addrs:
                lines.append("- **Адреса:**")
                for addr in sorted(filtered_addrs):
                    lines.append(f"  - {addr}")
        if all_phones:
            clean_phones = set()
            for ph in all_phones:
                ph_digits = re.sub(r"\D", "", ph)
                if len(ph_digits) == 11 and (ph_digits.startswith("7") or ph_digits.startswith("87")):
                    clean_phones.add(ph)
            if clean_phones:
                lines.append(f"- **Телефоны:** {', '.join(sorted(clean_phones))}")
        lines.append("")

        # Reports
        if reports:
            lines.append("### Первичная информация")
            for doc in sorted(reports, key=lambda d: d["info"]["timestamp"] or ""):
                data = doc["data"]
                info = doc["info"]
                date_str = _ts_to_date(info["timestamp"])
                lines.append(f"**{DOC_TYPE_NAMES.get(info['type'], info['type'])}** ({date_str})")
                if data.get("description"):
                    lines.append(f"> {data['description'][:500]}")
                lines.append("")

        # Protocols
        if protocols:
            lines.append("### Протоколы допросов")
            for doc in sorted(protocols, key=lambda d: d["info"]["timestamp"] or ""):
                data = doc["data"]
                info = doc["info"]
                date_str = _ts_to_date(info["timestamp"])
                subtype = data.get("protocol_subtype", "Протокол")
                person = data.get("person_name", "")
                dob = data.get("person_dob", "")
                if not person and subtype == "Протокол":
                    continue
                person_str = f" — {person}" if person else ""
                dob_str = f" ({dob})" if dob else ""
                lines.append(f"**{subtype}**{person_str}{dob_str} [{date_str}]")
                if data.get("person_workplace"):
                    occ = data.get("person_occupation", "")
                    if occ and occ not in ("Место жительства и (или)",):
                        lines.append(f"- Работа: {data['person_workplace']}, {occ}")
                    else:
                        lines.append(f"- Работа: {data['person_workplace']}")
                if data.get("person_address"):
                    lines.append(f"- Адрес: {data['person_address']}")
                if data.get("person_criminal_record"):
                    lines.append(f"- Судимость: {data['person_criminal_record']}")
                if data.get("testimony"):
                    lines.append("- **Показания:**")
                    lines.append(f"> {data['testimony']}")
                if data.get("qa_section"):
                    lines.append("- **Вопросы и ответы:**")
                    lines.append(data["qa_section"])
                lines.append("")

        # Decrees
        if decrees:
            lines.append("### Ключевые постановления")
            for doc in sorted(decrees, key=lambda d: d["info"]["timestamp"] or ""):
                data = doc["data"]
                info = doc["info"]
                date_str = _ts_to_date(info["timestamp"])
                subtype = data.get("decree_subtype", "")
                if not subtype and not data.get("resolution"):
                    continue
                title = subtype if subtype else "Постановление"
                lines.append(f"**{title}** [{date_str}]")
                if data.get("description"):
                    lines.append("*Обстоятельства:*")
                    lines.append(f"> {data['description']}")
                    lines.append("")
                if data.get("resolution"):
                    lines.append("*Решение:*")
                    lines.append(f"> {data['resolution']}")
                lines.append("")

        # Detentions
        if detentions:
            lines.append("### Задержание")
            seen_detentions = set()
            for doc in detentions:
                data = doc["data"]
                fio_list = data.get("fio", [])
                fio_dedup = list(deduplicate_fio(set(fio_list))) if fio_list else []
                person = fio_dedup[0] if fio_dedup else "?"
                det_key = (data.get('detention_date', ''), person)
                if det_key in seen_detentions:
                    continue
                seen_detentions.add(det_key)
                date_str = data.get('detention_date', '?')
                time_str = data.get('detention_time', '?')
                loc = data.get("detention_location", "")
                if loc and not re.search(r"(?:УП|ИВС|изолятор|Кокшетау|полиц)", loc, re.IGNORECASE):
                    loc = ""
                lines.append(f"- **{person}**: {date_str}, {time_str}" + (f" — {loc}" if loc else ""))
            lines.append("")

        # Court rulings
        if court_rulings:
            lines.append("### Судебное заседание")
            for doc in court_rulings:
                data = doc["data"]
                info = doc["info"]
                lines.append(f"- Дата: {info.get('court_date', '?')}")
                if data.get("court_name"):
                    lines.append(f"- Суд: {data['court_name']}")
                if data.get("judge"):
                    lines.append(f"- Судья: {data['judge']}")
                if data.get("court_subject"):
                    lines.append(f"- В отношении: {data['court_subject']}")
                if data.get("court_case_id"):
                    lines.append(f"- Номер дела: {data['court_case_id']}")
                if data.get("court_participants"):
                    lines.append(f"- Участники: {data['court_participants']}")
            lines.append("")

        lines.append("")

    return "\n".join(lines)


def generate_index(all_docs: List[Dict], skipped_docs: List[Dict]) -> str:
    """Generate index of all processed documents."""
    lines = []
    lines.append("# Индекс обработанных документов")
    lines.append("")

    type_counts = defaultdict(int)
    for doc in all_docs:
        type_counts[DOC_TYPE_NAMES.get(doc["info"]["type"], doc["info"]["type"])] += 1

    skip_counts = defaultdict(int)
    for doc in skipped_docs:
        skip_counts[DOC_TYPE_NAMES.get(doc["type"], doc["type"])] += 1

    lines.append(f"**Включено в справку:** {len(all_docs)} документов")
    lines.append("")
    for t, c in sorted(type_counts.items(), key=lambda x: -x[1]):
        lines.append(f"- {t}: {c}")
    lines.append("")

    lines.append(f"**Пропущено (не существенно):** {len(skipped_docs)} документов")
    lines.append("")
    for t, c in sorted(skip_counts.items(), key=lambda x: -x[1]):
        lines.append(f"- {t}: {c}")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("| № | Файл | Тип | Дело | Дата | ФИО | Статья | Метод |")
    lines.append("|---|------|-----|------|------|-----|--------|-------|")

    for i, doc in enumerate(all_docs, 1):
        info = doc["info"]
        data = doc["data"]
        method = doc["method"]
        type_name = DOC_TYPE_NAMES.get(info["type"], info["type"])

        date_str = info.get("court_date", "") or _ts_to_date(info["timestamp"])
        case_short = ("..." + info["case_number"][-5:]) if info["case_number"] else ""

        fio = ""
        if isinstance(data.get("fio"), list) and data["fio"]:
            fio = data["fio"][0]
        elif data.get("person_name"):
            fio = data["person_name"]
        elif data.get("court_subject"):
            fio = data["court_subject"]
        if len(fio) > 30:
            fio = fio[:27] + "..."

        articles = ", ".join(data.get("articles_uk", []))

        md_name = info["filename"]
        for ext in [".pdf", ".docx"]:
            md_name = md_name.replace(ext, ".md")

        lines.append(f"| {i} | [{md_name}](documents/{md_name}) | {type_name} | {case_short} | {date_str} | {fio} | {articles} | {method} |")

    lines.append("")
    return "\n".join(lines)


# ==========================================================================
# UNIFIED EXTRACT FUNCTION (for API integration)
# ==========================================================================

def extract_text(file_path: str) -> Tuple[str, str]:
    """
    Extract text from a file (PDF or DOCX).
    Uses DocumentParser for PDF (coordinate-based extraction from A).

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
        if text and len(text.strip()) >= MIN_TEXT_LENGTH:
            return text, "text"
        else:
            return text or "", "ocr"  # parse_file handles OCR fallback internally
    except Exception as e:
        return f"[PDF ERROR: {e}]", "error"


def parse_file_for_api(file_name: str, decoded_object_content: bytes) -> Dict:
    """
    Parse a single file for the API service.
    Combines A's extraction quality with B's cleaning.

    Returns:
        Dict with "parsed_data" (cleaned text), "table_contents", "raw_data" (extracted structured data).
    """
    table_contents = None

    if file_name.endswith(".pdf"):
        parser = DocumentParser()
        extracted_text, table_contents = parser.parse_file(decoded_object_content)
    elif file_name.endswith(".docx"):
        extracted_text = parse_docx_file(decoded_object_content)
    elif file_name.endswith(".doc"):
        extracted_text = parse_doc_file(decoded_object_content, file_name)
    else:
        raise ValueError(f"Unsupported file type: {file_name}")

    # Apply full cleaning pipeline
    cleaned_text = full_clean(extracted_text) if extracted_text else ""

    return {
        "parsed_data": cleaned_text,
        "raw_text": extracted_text,
        "table_contents": table_contents,
    }


# ==========================================================================
# CLI MAIN (from B — standalone mode)
# ==========================================================================

def main():
    """CLI entry point for batch processing documents."""
    base_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(base_dir, "output")
    docs_dir = os.path.join(output_dir, "documents")

    os.makedirs(docs_dir, exist_ok=True)

    all_files = sorted(
        f for f in os.listdir(base_dir)
        if f.lower().endswith(".pdf") or f.lower().endswith(".docx")
    )

    if not all_files:
        print(f"��айлы не найдены в {base_dir}")
        sys.exit(1)

    print(f"Найдено {len(all_files)} файлов")
    print(f"Результаты: {output_dir}")
    print()

    all_docs = []
    skipped_docs = []
    counts = {"text": 0, "ocr": 0, "docx": 0, "error": 0}

    parser = DocumentParser()

    for i, filename in enumerate(all_files, 1):
        file_path = os.path.join(base_dir, filename)
        print(f"[{i}/{len(all_files)}] {filename}...", end=" ", flush=True)

        # 1. Classification by filename
        doc_info = classify_by_filename(filename)

        if doc_info["type"] in SKIP_FILE_TYPES:
            skipped_docs.append({"type": doc_info["type"], "filename": filename})
            print(f"ПРОПУЩЕН ({doc_info['type']})")
            continue

        # 2. Text extraction (using A's DocumentParser for PDFs)
        if filename.lower().endswith(".docx"):
            try:
                with open(file_path, 'rb') as f:
                    raw_text = parse_docx_file(f.read())
                method = "docx"
            except Exception as e:
                raw_text = f"[DOCX ERROR: {e}]"
                method = "error"
        else:
            try:
                raw_text, _ = parser.parse_file(file_path)
                method = "text" if raw_text and len(raw_text.strip()) >= MIN_TEXT_LENGTH else "ocr"
            except Exception as e:
                raw_text = f"[PDF ERROR: {e}]"
                method = "error"

        counts[method] = counts.get(method, 0) + 1

        # 3. Language detection
        if not doc_info["lang"] and raw_text and not raw_text.startswith("["):
            doc_info["lang"] = detect_language(raw_text)

        # 4. Sub-classification for "other" by content
        if doc_info["type"] == "other":
            subtype = classify_other_by_content(raw_text)
            if subtype != "other":
                doc_info["type"] = subtype

        if doc_info["type"] in SKIP_OTHER_SUBTYPES:
            skipped_docs.append({"type": doc_info["type"], "filename": filename})
            print(f"ПРОПУЩЕН ({doc_info['type']})")
            continue

        # 5. Full cleaning + data extraction
        cleaned = full_clean(raw_text)
        essential = extract_essential_data(raw_text, doc_info["type"], cleaned)

        # 6. Markdown output
        md_content = generate_markdown(doc_info, cleaned, essential, method)
        md_filename = filename
        for ext in [".pdf", ".docx"]:
            md_filename = md_filename.replace(ext, ".md")
        with open(os.path.join(docs_dir, md_filename), "w", encoding="utf-8") as f:
            f.write(md_content)

        all_docs.append({"info": doc_info, "data": essential, "method": method})

        type_name = DOC_TYPE_NAMES.get(doc_info["type"], doc_info["type"])
        print(f"OK ({method}, {type_name})")

    # 7. Index
    index_content = generate_index(all_docs, skipped_docs)
    with open(os.path.join(output_dir, "index.md"), "w", encoding="utf-8") as f:
        f.write(index_content)

    # 8. Case summary
    summary = generate_case_summary(all_docs)
    summary_path = os.path.join(output_dir, "СПРАВКА.md")
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(summary)

    print()
    print("=" * 60)
    print(f"Включено в справку: {len(all_docs)} документов")
    print(f"  Текстовые (PyMuPDF): {counts.get('text', 0)}")
    print(f"  OCR (Tesseract):     {counts.get('ocr', 0)}")
    print(f"  DOCX:                {counts.get('docx', 0)}")
    print(f"  Ошибки:              {counts.get('error', 0)}")
    print(f"Пропущено:             {len(skipped_docs)}")
    print(f"Справка:    {summary_path}")
    print(f"Индекс:     {os.path.join(output_dir, 'index.md')}")


if __name__ == "__main__":
    main()
