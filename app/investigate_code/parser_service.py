#!/usr/bin/env python3
"""
Парсер PDF/DOCX файлов уголовного дела.
Ориентирован на формирование справки по делу.

Логика:
1. Извлекает текст (PyMuPDF + Tesseract OCR + DOCX)
2. Классифицирует документы (включая подтипы "other" по содержанию)
3. Фильтрует: оставляет только существенные для справки
4. Извлекает ключевые данные
5. Генерирует Markdown: индекс + отдельные файлы + СВОДНАЯ СПРАВКА
"""

import os
import re
import sys
import fitz  # PyMuPDF
from datetime import datetime
from collections import defaultdict

# --- Настройки ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_DIR = os.path.join(BASE_DIR, "input_files")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
DOCS_DIR = os.path.join(OUTPUT_DIR, "documents")


MIN_TEXT_LENGTH = 50

# ==========================================================================
# ФИЛЬТРАЦИЯ: какие типы включать / исключать
# ==========================================================================

# Типы файлов по имени — пропускаем полностью
SKIP_FILE_TYPES = {"cov_letter", "notification_erdr", "phototable"}

# Подтипы "other" по содержанию — пропускаем
SKIP_OTHER_SUBTYPES = {
    "obligation",        # Обязательство о явке
    "language_statement", # Заявление о языке
    "format_statement",  # Заявление о формате судопроизводства
    "rights_explanation", # Разъяснение прав
    "empty",             # Пустые/битые OCR
    "admin_form",        # Административные формы
    "phototable_embedded", # Фототаблицы внутри "other"
}

# Маппинг типов на русские названия
DOC_TYPE_NAMES = {
    "decree": "Постановление",
    "protocol": "Протокол допроса",
    "report_erdr": "Рапорт ЕРДР",
    "report_kui": "Рапорт КУИ",
    "court_ruling": "Протокол судебного заседания",
    # Подтипы "other" — существенные
    "detention_notice": "Уведомление о задержании",
    "counsel_notice": "Уведомление о защитнике",
    "case_acceptance": "Принятие дела к производству",
    "seizure_decree": "Постановление о выемке",
    "legal_aid_request": "Ходатайство о юр. помощи",
    "other": "Иной документ",
    # Пропускаемые (для отчёта)
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
# ШАБЛОННЫЕ БЛОКИ ДЛЯ УДАЛЕНИЯ
# ==========================================================================
BOILERPLATE_PATTERNS = [
    r"QR-код содержит\s+хэш-сумму электронного документа.*?подписанного ЭЦП",
    r"QR-код содержит\s+данные\s+ЭЦП\s+подписавшего лица.*?подписания документа",
    r"QR-код ЭЦҚ койылған PDF форматтағы электрондық.*?хэш соммасын қамтиды",
    r"QR-код қол қойған тұлғаның ЭЦҚ туралы.*?уақытты қамтиды",
    r"Документ подготовил и подписал:.*?erdr@kgp\.kz",
    r"Құжатты дайындады және қол қойды:.*?erdr@kgp\.kz",
    r"Документ согласован?:.*?erdr@kgp\.kz",
    r"Құжат келісілді:.*?erdr@kgp\.kz",
    r"Документ утвердил:.*?erdr@kgp\.kz",
    r"Документ согласовал:.*?(?=\n\n|\n[А-Я])",
    r"ИС «Единый реестр досудебных расследований»",
    r"«Сотқа дейінгі тергеудің бірыңғай тізілімі» АЖ",
    # Длинные блоки прав потерпевшего
    r"Потерпевший\s+имеет\s+право:.*?(?=Потерпевш(?:ему|ей|ий).*?предупрежден|По\s+существу|Я,\s|показания\s+желаю|$)",
    r"Потерпевший\s+обязан:.*?(?=Потерпевш(?:ему|ей|ий).*?предупрежден|По\s+существу|Я,\s|$)",
    # Блоки прав свидетеля/свидетеля с правом на защиту
    r"Свидетель(?:,\s+имеющий\s+право\s+на\s+защиту,)?\s+имеет\s+право:.*?(?=Свидетель.*?предупрежден|По\s+существу|Права\s+и\s+обязанности|Я,\s|$)",
    r"Свидетель(?:,\s+имеющий\s+право\s+на\s+защиту,)?\s+обязан:.*?(?=По\s+существу|Свидетелю|Права\s+и\s+обязанности|$)",
    # Блоки прав подозреваемого
    r"Подозреваемый\s+вправе:.*?(?=По\s+существу|Подозреваемому|Права\s+(?:и\s+обязанности\s+)?подозреваемого|Я,\s|$)",
    r"Подозреваемый\s+обязан:.*?(?=По\s+существу|Подозреваемому|$)",
    # Блок прав подозреваемого ст.64 УПК — "Права подозреваемого ... мне разъяснены"
    r"Права\s+подозреваемого,?\s*предусмотренные\s+ст\.?\s*\d+\s+(?:Уголовно-\s*процессуального\s+кодекса|УПК)\s+.*?Сущность\s+прав\s+ясна\.?",
    # "Подозреваемый имеет право отказаться от дачи показаний до начала первого допроса"
    r"Подозреваемый\s+имеет\s+право\s+отказаться\s+от\s+дачи\s+показаний.*?(?:первого\s+допроса|показаний)\.?",
    # "Подозреваемый предупрежден о том, что его показания могут быть использованы..."
    r"Подозреваемый\s+предупрежден\s+о\s+том,?\s+что\s+его\s+показания\s+могут\s+быть\s+использованы.*?(?:от\s+этих\s+показаний|показаний)\.\s*",
    # "На вопрос, признает ли подозреваемый себя виновным ... пояснил:"
    r"На\s+вопрос,?\s+признает\s+ли\s+подозреваемый.*?пояснил[:\s]*.*?(?=\n)",
    # "Подозреваемому(ой) предложено дать показания...следующие показания:"
    r"Подозреваемому\(ой\)\s+предложено\s+дать\s+показания.*?следующие\s+показания:\s*",
    # Разъяснение с нумерацией пунктов (1) получить ... 2) ... — обычно 10+ пунктов)
    r"(?:права\s+и\s+обязанности.*?предусмотренные\s+ст\.?\s*(?:65-1|71|64|78)\s+УПК.*?а\s+именно:\s*\n?)(?:\d+\)\s+.+?\n)+.*?(?=Права\s+и\s+обязанности.*?мне\s+разъяснены|Я,\s|$)",
    # Блок прав свидетеля ст.78 УПК — полный текст прав до "мне разъяснены"
    r"Свидетель\s+(?:при\s+допросе\s+)?(?:вправе|имеет\s+право)[:\s].*?(?=Права\s+и\s+обязанности.*?мне\s+разъяснены|Сущность\s+прав\s+ясна|По\s+существу|Я,\s)",
    # Блок "в присутствии своего адвоката. Неявка адвоката..." — ст.78 УПК
    r"в\s+присутствии\s+(?:своего\s+)?адвоката\.?\s*Неявка\s+адвоката.*?(?=Права\s+и\s+обязанности|Сущность\s+прав|$)",
    # "Свидетелю обеспечивается возмещение расходов" (конец блока прав ст.78)
    r"Свидетелю\s+обеспечивается\s+возмещение\s+расходов.*?(?=Права\s+и\s+обязанности|Сущность\s+прав|$)",
    # Блок "Права и обязанности ... мне разъяснены. Сущность прав ясна."
    r"Права\s+и\s+обязанности\s+свидетеля,?\s*предусмотренные\s+ст\.?\s*\d+\s+УПК\s+РК,?\s*мне\s+разъяснены\.?\s*Сущность\s+прав\s+ясна\.?",
    # Подпись "Свидетель:\n ФИО И.О." (повторяющиеся подписи)
    r"(?:Свидетель|Потерпевший|Подозреваемый\(ая\)|Защитник)[:\s]*\n\s*[А-ЯЁ][а-яёА-ЯЁ]+\s+[А-ЯЁ]\.[А-ЯЁ]\.(?:\s*\n)?",
    # Предупреждение об ответственности за ложные показания
    r"Свидетель\s+\S+\s+\S+\s+предупрежден\(а\)\s+об\s+уголовной\s+ответственности.*?(?=Свидетелю\s+разъяснено|По\s+существу|Я,\s)",
    # Разъяснение права отказа от показаний (ст.78)
    r"Свидетелю\s+разъяснено\s+право\s+отказаться\s+от\s+дачи\s+показаний.*?(?:родственников|үй-ішілік)\.?",
    # "Я, ФИО показания желаю давать на ... языке, в помощи переводчика не нуждаюсь"
    r"Я,?\s+\S+\s+\S+\.?\s+показания\s+желаю\s+давать\s+на\s+\S+\s+языке[^.]*не\s+нуждаюсь\.?",
    # "Свидетелю предложено рассказать об отношениях...следующие показания:"
    r"Свидетелю\s+предложено\s+рассказать\s+об\s+отношениях.*?следующие\s+показания:\s*",
    # "С протоколам ознакомлен, заявлении ходатайств не имею"
    r"С\s+протоколам?\s+ознакомлен[^.]*ходатайств\s+не\s+имею\.?",
    # "С целью уточнения и дополнения показаний свидетеля/подозреваемого..."
    r"С\s+целью\s+уточнения\s+и\s+дополнения\s+показаний\s+(?:свидетеля|подозреваемого)\s+(?:ему\(ей\)|ему)\s+заданы\s*\n?\s*следующие\s+вопросы[:\s]*",
    # Подписи "Подозреваемый(ая):\nФИО И.О.\nЗащитник:\nФИО И.О."
    r"Подозреваемый\(ая\)[:\s]*\n\s*[А-ЯЁ][а-яёА-ЯЁ]+\s+[А-ЯЁ]\.[А-ЯЁ]\.\s*\n?\s*(?:Защитник[:\s]*\n\s*[А-ЯЁ][а-яёА-ЯЁ]+\s+[А-ЯЁ]\.[А-ЯЁ]\.\s*)?",
    # ", с участием защитника." — шаблонный фрагмент
    r",?\s+с\s+участием\s+защитника\.?\s*",
    # Блок нумерованных прав подозреваемого/свидетеля "разъяснены права ... а именно: 1)...2)...24)..."
    # Включает все до "Сущность прав ясна" или "Права ... мне разъяснены"
    r"(?:разъяснены\s+права,?\s*предусмотренные\s+ст\.?\s*\d+\s+УПК\s+РК,?\s*а\s+именно:\s*\n?)[\s\S]*?(?=Сущность\s+прав\s+ясна|Права\s+.*?мне\s+разъяснены|На\s+вопрос,?\s+признает|По\s+существу|По\s+поводу\s+подозрения)",
    # Fallback: нумерованные пункты прав без заголовка (пропущенные строки)
    r"\n\d+(?:-\d+)?\)\s+(?:знать|получить|защищать|участвовать|заявлять|представлять|давать|отказаться|приносить|обжаловать|знакомиться|пользоваться|ходатайствовать|иметь|примириться|возражать|безотлагательно|при\s+назначении|в\s+порядке)[^\n]*(?:\n(?!\d+[).]|\n\n|Права|Сущность|По\s+существу|По\s+поводу)[^\n]+)*",
]

# ==========================================================================
# REGEX-ПАТТЕРНЫ
# ==========================================================================
PATTERNS = {
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

RANKS = [
    "полковник", "подполковник", "майор", "капитан", "старший лейтенант",
    "лейтенант", "сержант",
]
POSITIONS = [
    "следователь", "дознаватель", "начальник", "оперуполномоченный",
    "специалист", "судья", "прокурор", "адвокат", "секретарь",
]


# ==========================================================================
# ИЗВЛЕЧЕНИЕ ТЕКСТА
# ==========================================================================

def extract_text_pdf(pdf_path):
    doc = fitz.open(pdf_path)
    text = ""
    for page in doc:
        text += page.get_text()
    if len(text.strip()) >= MIN_TEXT_LENGTH:
        doc.close()
        return text.strip(), "text"
    try:
        import pytesseract
        from PIL import Image
        import io
        ocr_text = ""
        for page_num in range(len(doc)):
            page = doc[page_num]
            mat = fitz.Matrix(2, 2)
            pix = page.get_pixmap(matrix=mat)
            img_data = pix.tobytes("png")
            img = Image.open(io.BytesIO(img_data))
            page_text = pytesseract.image_to_string(img, lang="rus+kaz")
            ocr_text += page_text + "\n"
        doc.close()
        return ocr_text.strip(), "ocr"
    except Exception as e:
        doc.close()
        return f"[OCR ERROR: {e}]", "error"


def extract_text_docx(docx_path):
    try:
        import zipfile
        from xml.etree import ElementTree
        z = zipfile.ZipFile(docx_path)
        doc_xml = z.read("word/document.xml")
        tree = ElementTree.fromstring(doc_xml)
        ns_w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        texts = []
        for p in tree.iter(f"{{{ns_w}}}p"):
            line = ""
            for t in p.iter(f"{{{ns_w}}}t"):
                if t.text:
                    line += t.text
            texts.append(line)
        z.close()
        return "\n".join(texts).strip(), "docx"
    except Exception as e:
        return f"[DOCX ERROR: {e}]", "error"


def extract_text(file_path):
    if file_path.lower().endswith(".docx"):
        return extract_text_docx(file_path)
    return extract_text_pdf(file_path)


# ==========================================================================
# КЛАССИФИКАЦИЯ
# ==========================================================================

def classify_by_filename(filename):
    """Классификация по имени файла."""
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


def classify_other_by_content(text):
    """Классификация документов типа 'other' по содержанию текста."""
    if not text or len(text.strip()) < 30:
        return "empty"

    tl = text.lower()

    # Обязательство о явке
    if "обязательство" in tl and ("о явке" in tl or "являться по вызов" in tl):
        return "obligation"
    if "міндеттеме" in tl:
        return "obligation"

    # Заявление о языке
    if "о языке уголовного судопроизводства" in tl or "тіл туралы" in tl:
        return "language_statement"

    # Заявление о формате
    if ("формат" in tl and "судопроизводства" in tl) or "электронного формата" in tl:
        return "format_statement"

    # Разъяснение прав
    if "разъяснен" in tl and ("прав" in tl and ("подозреваем" in tl or "потерпевш" in tl or "свидетел" in tl)):
        return "rights_explanation"
    if re.search(r"протокол\s*\n?\s*разъяснени[ея]\s+прав", tl):
        return "rights_explanation"

    # Фототаблица (встроенная)
    if "фототаблица" in tl or "фото №" in tl:
        return "phototable_embedded"

    # Уведомление о задержании
    if "задержан" in tl and ("подозреваем" in tl or "уведомлени" in tl or "уведомляю" in tl):
        return "detention_notice"
    if "ұсталғаны" in tl or "ұстау" in tl:
        return "detention_notice"

    # Уведомление о защитнике / адвокате
    if ("защит" in tl or "адвокат" in tl) and ("уведомлени" in tl or "вступ" in tl or "назначен" in tl):
        return "counsel_notice"

    # Ходатайство о юридической помощи
    if "ходатайств" in tl and ("юридическ" in tl or "помощ" in tl or "защит" in tl):
        return "legal_aid_request"

    # Принятие дела к производству
    if "принятии" in tl and ("уголовного дела" in tl or "к своему производству" in tl):
        return "case_acceptance"
    if "өз өндірісіне қабылдау" in tl:
        return "case_acceptance"

    # Постановление о выемке
    if "выемк" in tl or "алу" in tl and "қаулы" in tl:
        return "seizure_decree"

    # Административные формы (очень короткие OCR с заголовками)
    if len(text.strip()) < 100:
        return "admin_form"

    return "other"


def detect_language(text):
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
# ОЧИСТКА И ИЗВЛЕЧЕНИЕ ДАННЫХ
# ==========================================================================

def clean_text(text):
    cleaned = text
    for pattern in BOILERPLATE_PATTERNS:
        cleaned = re.sub(pattern, "", cleaned, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = "\n".join(line.rstrip() for line in cleaned.split("\n"))
    return cleaned.strip()


def _normalize_fio_key(fio):
    """Создаёт нормализованный ключ для сравнения OCR-дублей ФИО."""
    # Заменяем казахские буквы на ближайшие русские для сравнения
    trans = str.maketrans("ӘәҒғҚқҢңӨөҰұҮүҺһІі", "ААГгКкНнООУуУуХхИи")
    key = fio.translate(trans).lower()
    # Удаляем двойные буквы для нечёткого сравнения
    key = re.sub(r"(.)\1+", r"\1", key)
    return key


def _levenshtein(s1, s2):
    """Расстояние Левенштейна для нечёткого сравнения строк."""
    if len(s1) < len(s2):
        return _levenshtein(s2, s1)
    if len(s2) == 0:
        return len(s1)
    prev_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        curr_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = prev_row[j + 1] + 1
            deletions = curr_row[j] + 1
            substitutions = prev_row[j] + (c1 != c2)
            curr_row.append(min(insertions, deletions, substitutions))
        prev_row = curr_row
    return prev_row[-1]


def _fio_similarity(key1, key2):
    """Проверка похожести двух ФИО-ключей с учётом OCR-ошибок и склонений."""
    if key1 == key2:
        return True
    parts1 = key1.split()
    parts2 = key2.split()
    if len(parts1) >= 2 and len(parts2) >= 2:
        fam1, name1 = parts1[0], parts1[1]
        fam2, name2 = parts2[0], parts2[1]
        # Точное совпадение первых 5 букв фамилии + 3 буквы имени (склонения)
        if fam1[:5] == fam2[:5] and name1[:3] == name2[:3]:
            return True
        # Нечёткое: Левенштейн <= 2 для фамилии + <= 1 для имени (OCR-ошибки)
        fam_dist = _levenshtein(fam1[:6], fam2[:6])
        name_dist = _levenshtein(name1[:4], name2[:4])
        if fam_dist <= 2 and name_dist <= 1:
            return True
    return False


def _deduplicate_fio(fio_collection):
    """Дедупликация ФИО с учётом OCR-ошибок.
    fio_collection — set или Counter/dict(fio -> count) для частотного выбора.
    """
    # Если передан set, конвертируем в dict с равными частотами
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

    # Из каждой группы берём самый "чистый" вариант
    result = set()
    for variants in groups:
        # Оценка: частотность + именительный падеж + русский вариант
        def score(v):
            s = 0
            # Частотность — самый частый вариант в документах
            s += fio_counts.get(v, 1) * 20
            parts = v.split()
            # Бонус за именительный падеж (фамилия заканчивается на -ов, -ев, -ин, -ий, -ерь, -ко и т.д.)
            if parts and re.search(r"(?:ов|ин|ев|ий|ер[ьт]|ко|ук|юк|ен)$", parts[0]):
                s += 10
            # Штраф за косвенные падежи (-ова, -ову, -овым, -иной, -ому)
            if parts and re.search(r"(?:ова|ову|овым|овою|ину|иным|иною|ому|ому)$", parts[0]):
                s -= 5
            # Бонус за русские буквы (без казахских)
            if not re.search(r"[ӘәҒғҚқҢңӨөҰұҮүҺһІі]", v):
                s += 5
            # Бонус за длину (более полное ФИО)
            s += len(v) / 100
            return s
        best = max(variants, key=score)
        result.add(best)
    return result


def extract_essential_data(text, doc_type, cleaned_text=None):
    """Извлечение ключевых данных. cleaned_text — текст после удаления boilerplate."""
    data = {}
    ct = cleaned_text or text  # cleaned для показаний/описаний

    fio_matches = re.findall(FIO_PATTERN, text)
    if fio_matches:
        raw_fio = set(" ".join(m) for m in fio_matches)
        # Нормализация OCR-дублей: приводим к единому виду через транслитерацию
        data["fio"] = list(_deduplicate_fio(raw_fio))

    iin = re.findall(PATTERNS["iin"], text)
    if iin:
        data["iin"] = list(set(iin))

    cases = re.findall(PATTERNS["case_numbers"], text)
    if cases:
        data["case_numbers"] = list(set(cases))

    dates = re.findall(PATTERNS["dates_dot"], text)
    for d, m, y in re.findall(PATTERNS["dates_text_ru"], text):
        dates.append(f"{d}.{m}.{y}")
    for y, d, m in re.findall(PATTERNS["dates_text_kk"], text):
        dates.append(f"{d}.{m}.{y}")
    if dates:
        data["dates"] = list(set(dates))

    articles_ru = re.findall(PATTERNS["articles_ru"], text)
    articles_kk = re.findall(PATTERNS["articles_kk"], text)
    articles = []
    for art, part in articles_ru:
        articles.append(f"ст.{art} ч.{part} УК РК")
    for art, part in articles_kk:
        articles.append(f"ст.{art} ч.{part} ҚК РК")
    if articles:
        data["articles_uk"] = list(set(articles))

    phones = re.findall(PATTERNS["phones"], text)
    if phones:
        data["phones"] = list(set(phones))

    amounts = re.findall(PATTERNS["amounts"], text)
    if amounts:
        normalized_amounts = set()
        for a in amounts:
            # Убираем переносы строк и лишние пробелы, нормализуем
            num = re.sub(r"\s+", " ", a.strip())
            # Пробуем получить числовое значение
            try:
                val = int(num.replace(" ", ""))
                if val >= 100:  # отсекаем мусорные маленькие числа
                    normalized_amounts.add(f"{val:,}".replace(",", " ") + " тенге")
            except ValueError:
                pass
        if normalized_amounts:
            data["amounts"] = sorted(normalized_amounts)

    addresses = re.findall(PATTERNS["addresses_ru"], text)
    if addresses:
        data["addresses"] = list(set(addresses))

    # Специфика по типу — используем cleaned text для показаний/описаний
    if doc_type == "protocol":
        data.update(_extract_protocol_data(text, ct))
    elif doc_type == "decree":
        data.update(_extract_decree_data(ct))
    elif doc_type == "court_ruling":
        data.update(_extract_court_ruling_data(text))
    elif doc_type == "detention_notice":
        data.update(_extract_detention_data(text))

    return data


def _extract_protocol_data(raw_text, cleaned_text=None):
    """Извлечение данных протокола. raw_text для анкеты, cleaned_text для показаний."""
    data = {}
    text = raw_text
    ct = cleaned_text or text

    ptype = re.search(r"ПРОТОКОЛ\s*\n\s*допроса\s+(потерпевшего|свидетеля|подозреваемого|обвиняемого)", text, re.IGNORECASE)
    if not ptype:
        # Альтернативный формат
        ptype = re.search(r"допроса\s+(свидетеля,\s+имеющего\s+право\s+на\s+защиту)", text, re.IGNORECASE)
        if ptype:
            data["protocol_subtype"] = "Допрос свидетеля (с правом на защиту)"
    if ptype and "protocol_subtype" not in data:
        data["protocol_subtype"] = f"Допрос {ptype.group(1)}"

    start = re.search(r"Допрос начат:\s*(.+)", text)
    end = re.search(r"Допрос окончен:\s*(.+)", text)
    if start:
        data["interrogation_start"] = start.group(1).strip()
    if end:
        data["interrogation_end"] = end.group(1).strip()

    fields = {
        "Фамилия, имя, отчество": "person_name",
        "Дата рождения": "person_dob",
        "Место рождения": "person_birthplace",
        "Гражданство": "person_citizenship",
        "Место работы или учебы": "person_workplace",
        "Место работы \\(учебы\\)": "person_workplace",
        "Род занятий или должность": "person_occupation",
        "Место жительства": "person_address",
        "Контактные телефоны": "person_phone",
        "Наличие судимости": "person_criminal_record",
    }
    for label, key in fields.items():
        if key in data:
            continue  # уже извлечено
        match = re.search(rf"{label}[:\s]*\n?\s*(.+?)(?:\n|$)", text)
        if match:
            val = match.group(1).strip()
            # Фильтруем мусорные значения
            skip_vals = ("-", "—", "и (или)", "Паспорт или иной документ,",
                         "Паспорт или иной документ", "Место жительства и (или)")
            if val and val not in skip_vals and not val.startswith("Паспорт") and not val.startswith("Место жительства и"):
                data[key] = val

    # --- Извлечение показаний ИЗ ОЧИЩЕННОГО ТЕКСТА (без блоков прав) ---
    testimony_patterns = [
        # "По существу заданных вопросов ... показал(а)/пояснил(а) следующее"
        r"По\s+существу\s+(?:заданных\s+вопросов|дела|известных|могу)[^.]{0,80}?(?:показал[аи]?|пояснил[аи]?|сообщил[аи]?|пояснить)\s*(?:следующее)?[:\s,]*(.+?)(?:(?:На\s+этом\s+допрос|Протокол\s+(?:мною\s+)?прочитан|Допрашиваемый|С\s+моих\s+слов\s+записано|Более\s+(?:мне\s+)?по\s+данному\s+факту|Больше\s+мне))",
        # "По поводу подозрения и всех других обстоятельств ... могу показать следующее:"
        r"По\s+поводу\s+подозрения.*?могу\s+(?:показать|пояснить)\s+следующее[:\s]*(.+?)(?:(?:На\s+этом\s+допрос|Протокол\s+(?:мною\s+)?прочитан|С\s+моих\s+слов\s+записано|Более\s+(?:мне\s+)?по\s+данному\s+факту|Больше\s+мне))",
        # "дал(а) следующие показания:" потом "По существу" (внутри cleaned — без блока прав)
        r"дал[аи]?\s*следующие\s+показания[:\s]*(.+?)(?:(?:На\s+этом\s+допрос|Протокол\s+(?:мною\s+)?прочитан|С\s+моих\s+слов\s+записано))",
        # "могу пояснить следующее"
        r"могу\s+(?:пояснить|показать)\s+следующее[:\s,]*(.+?)(?:(?:На\s+этом\s+допрос|Протокол\s+(?:мною\s+)?прочитан|С\s+моих\s+слов\s+записано|Более\s+(?:мне\s+)?по\s+данному\s+факту|Больше\s+мне))",
        # Fallback: "Показания:" блок
        r"Показания[:\s]+(.+?)(?:(?:На\s+этом\s+допрос|Протокол\s+(?:мною\s+)?прочитан|С\s+моих\s+слов\s+записано))",
    ]
    for pat in testimony_patterns:
        m = re.search(pat, ct, re.DOTALL | re.IGNORECASE)
        if m and len(m.group(1).strip()) > 50:
            testimony = m.group(1).strip()
            # Очистка подписей из текста показаний
            testimony = re.sub(
                r"\n\s*(?:Свидетель|Потерпевший|Подозреваемый\(ая\)|Защитник)[:\s]*\n\s*[А-ЯЁ][а-яёА-ЯЁ]+\s+[А-ЯЁ]\.[А-ЯЁ]\.\s*",
                "\n", testimony
            )
            testimony = re.sub(r"\n\s*С\s+протоколам?\s+ознакомлен[^.]*ходатайств\s+не\s+имею\.?\s*", "\n", testimony)
            # Убираем "С целью уточнения..." и дальнейшие вопросы из testimony (они пойдут в Q&A)
            testimony = re.sub(
                r"\n\s*С\s+целью\s+уточнения\s+и\s+дополнения.*$", "", testimony, flags=re.DOTALL
            )
            testimony = re.sub(r"\n\s*Вопрос:\s.*$", "", testimony, flags=re.DOTALL)
            testimony = testimony.strip()
            if len(testimony) > 50:
                data["testimony"] = testimony
            break

    # Извлечение вопросов-ответов (формат "Вопрос:  скажите... Ответ: ...")
    # Используем строгий формат: "Вопрос:" + пробелы + текст вопроса
    qa_blocks = re.findall(
        r"Вопрос:\s{1,3}(.+?)\nОтвет:\s*(.+?)(?=\nВопрос:\s|\n_{2,}|\nНа\s+этом|\nДопросил|$)",
        ct, re.DOTALL | re.IGNORECASE
    )
    if qa_blocks:
        valid_qa = []
        for q, a in qa_blocks:
            q = q.strip()
            a = a.strip()
            # Убираем подписи из конца ответов
            a = re.sub(r"\n\s*(?:Свидетель|Потерпевший|Подозреваемый\(ая\)|Защитник)(?:,\s+имеющий\s+право\s+на\s+защиту)?[:\s]*\n?\s*[А-ЯЁ][а-яёА-ЯЁ]+\s+[А-ЯЁ]\.[А-ЯЁ]\.\s*(?:\n.*)?$", "", a, flags=re.DOTALL).strip()
            a = re.sub(r"\n\s*С\s+протоколам?\s+ознакомлен.*$", "", a, flags=re.DOTALL).strip()
            # Убираем одиночные "ФИО И.О." в конце ответа
            a = re.sub(r"\n\s*[А-ЯЁ][а-яёА-ЯЁ]+\s+[А-ЯЁ]\.[А-ЯЁ]\.\s*$", "", a).strip()
            # Убираем "С целью уточнения..." в конце
            a = re.sub(r"\n\s*С\s+целью\s+уточнения.*$", "", a, flags=re.DOTALL).strip()
            # Фильтрация: вопрос минимум 15 символов, начинается со "скажите" или "как" или др.
            # и не является мусором (обрезанное слово типа "ы:")
            if len(q) < 15:
                continue
            if len(a) < 3:
                continue
            # Вопрос должен начинаться с осмысленного слова
            if re.match(r'^[а-яёА-ЯЁ]{1,3}[:\s]', q) and not re.match(r'^(?:как|что|кто|где|вы\s)', q, re.IGNORECASE):
                continue
            valid_qa.append((q, a))
        if valid_qa:
            qa_text = "\n".join(f"**В:** {q}\n**О:** {a}" for q, a in valid_qa)
            data["qa_section"] = qa_text

    return data


def _extract_decree_data(text):
    data = {}
    subtype = re.search(
        r"(?:ПОСТАНОВЛЕНИЕ|ҚАУЛЫ)\s*\n\s*(.+?)(?:\n|г\.|Көкшетау)",
        text, re.IGNORECASE
    )
    if subtype:
        data["decree_subtype"] = subtype.group(1).strip()

    # Резолютивная часть: ПОСТАНОВИЛ: ... до конца документа (минус шаблоны)
    resolution = re.search(
        r"(?:ПОСТАНОВИЛ|ҚАУЛЫ ЕТТІМ)[:\s]*(.*?)(?:QR-код|Документ подготовил|Құжатты дайындады|Настоящее постановление|$)",
        text, re.DOTALL | re.IGNORECASE
    )
    if resolution:
        data["resolution"] = resolution.group(1).strip()

    # Описательная часть: УСТАНОВИЛ: ... до "На основании" / "руководствуясь" / "ПОСТАНОВИЛ"
    desc_patterns = [
        r"(?:УСТАНОВИЛ|АНЫҚТАДЫМ)[:\s]*(.*?)(?:На основании|Жоғарыда|руководствуясь|басшылыққа|ПОСТАНОВИЛ|ҚАУЛЫ ЕТТІМ)",
        # Альтернативный: текст между "У С Т А Н О В И Л" (с пробелами) и "ПОСТАНОВИЛ"
        r"У\s*С\s*Т\s*А\s*Н\s*О\s*В\s*И\s*Л[:\s]*(.*?)(?:На основании|руководствуясь|П\s*О\s*С\s*Т\s*А\s*Н\s*О\s*В\s*И\s*Л)",
    ]
    for pat in desc_patterns:
        m = re.search(pat, text, re.DOTALL | re.IGNORECASE)
        if m and len(m.group(1).strip()) > 30:
            data["description"] = m.group(1).strip()
            break

    return data


def _extract_court_ruling_data(text):
    data = {}
    m = re.search(PATTERNS["case_id_court"], text)
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


def _extract_detention_data(text):
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
# ГЕНЕРАЦИЯ MARKDOWN
# ==========================================================================

def generate_markdown(doc_info, cleaned_text, essential_data, extraction_method):
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
        field_labels = {
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
        for key, label in field_labels.items():
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

        for block_key, block_title in [("testimony", "Показания"), ("qa_section", "Вопросы и ответы"), ("resolution", "Резолютивная часть"), ("description", "Описательная часть")]:
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

def _ts_to_date(ts_str):
    if not ts_str:
        return ""
    try:
        return datetime.fromtimestamp(int(ts_str) / 1000).strftime("%d.%m.%Y")
    except (ValueError, OSError):
        return ""


# ==========================================================================
# MAIN
# ==========================================================================

def main():
    os.makedirs(DOCS_DIR, exist_ok=True)

    all_files = sorted(
        f for f in os.listdir(INPUT_DIR)
        if f.lower().endswith(".pdf") or f.lower().endswith(".docx")
    )

    if not all_files:
        print("Файлы не найдены в", INPUT_DIR)
        sys.exit(1)

    print(f"Найдено {len(all_files)} файлов")
    print(f"Результаты: {OUTPUT_DIR}")
    print()

    all_docs = []
    skipped_docs = []
    counts = {"text": 0, "ocr": 0, "docx": 0, "error": 0}

    for i, filename in enumerate(all_files, 1):
        file_path = os.path.join(INPUT_DIR, filename)
        print(f"[{i}/{len(all_files)}] {filename}...", end=" ", flush=True)

        # 1. Классификация по имени
        doc_info = classify_by_filename(filename)

        # Пропуск по типу файла mark_not_converted()
        if doc_info["type"] in SKIP_FILE_TYPES:
            skip_type = doc_info["type"]
            skipped_docs.append({"type": skip_type, "filename": filename})
            print(f"ПРОПУЩЕН ({skip_type})")
            continue

        # 2. Извлечение текста
        raw_text, method = extract_text(file_path)
        counts[method] = counts.get(method, 0) + 1

        # 3. Автоопределение языка
        if not doc_info["lang"] and raw_text and not raw_text.startswith("["):
            doc_info["lang"] = detect_language(raw_text)

        # 4. Доклассификация "other" по содержанию
        if doc_info["type"] == "other":
            subtype = classify_other_by_content(raw_text)
            if subtype != "other":
                doc_info["type"] = subtype

        # Пропуск по подтипу
        if doc_info["type"] in SKIP_OTHER_SUBTYPES:
            skipped_docs.append({"type": doc_info["type"], "filename": filename})
            print(f"ПРОПУЩЕН ({doc_info['type']})")
            continue

        # 5. Очистка + извлечение данных
        cleaned = clean_text(raw_text)
        essential = extract_essential_data(raw_text, doc_info["type"], cleaned)

        # 6. Генерация Markdown
        md_content = generate_markdown(doc_info, cleaned, essential, method)
        md_filename = filename
        for ext in [".pdf", ".docx"]:
            md_filename = md_filename.replace(ext, ".md")
        with open(os.path.join(DOCS_DIR, md_filename), "w", encoding="utf-8") as f:
            f.write(md_content)

        all_docs.append({"info": doc_info, "data": essential, "method": method})

        type_name = DOC_TYPE_NAMES.get(doc_info["type"], doc_info["type"])
        print(f"OK ({method}, {type_name})")

