from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any


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
    r"Потерпевший\s+имеет\s+право:.*?(?=Потерпевш(?:ему|ей|ий).*?предупрежден|По\s+существу|Я,\s|показания\s+желаю|$)",
    r"Потерпевший\s+обязан:.*?(?=Потерпевш(?:ему|ей|ий).*?предупрежден|По\s+существу|Я,\s|$)",
    r"Свидетель(?:,\s+имеющий\s+право\s+на\s+защиту,)?\s+имеет\s+право:.*?(?=Свидетель.*?предупрежден|По\s+существу|Права\s+и\s+обязанности|Я,\s|$)",
    r"Свидетель(?:,\s+имеющий\s+право\s+на\s+защиту,)?\s+обязан:.*?(?=По\s+существу|Свидетелю|Права\s+и\s+обязанности|$)",
    r"Подозреваемый\s+вправе:.*?(?=По\s+существу|Подозреваемому|Права\s+(?:и\s+обязанности\s+)?подозреваемого|Я,\s|$)",
    r"Подозреваемый\s+обязан:.*?(?=По\s+существу|Подозреваемому|$)",
    r"Права\s+подозреваемого,?\s*предусмотренные\s+ст\.?\s*\d+\s+(?:Уголовно-\s*процессуального\s+кодекса|УПК)\s+.*?Сущность\s+прав\s+ясна\.?",
    r"Подозреваемый\s+имеет\s+право\s+отказаться\s+от\s+дачи\s+показаний.*?(?:первого\s+допроса|показаний)\.?",
    r"Подозреваемый\s+предупрежден\s+о\s+том,?\s+что\s+его\s+показания\s+могут\s+быть\s+использованы.*?(?:от\s+этих\s+показаний|показаний)\.\s*",
    r"На\s+вопрос,?\s+признает\s+ли\s+подозреваемый.*?пояснил[:\s]*.*?(?=\n)",
    r"Подозреваемому\(ой\)\s+предложено\s+дать\s+показания.*?следующие\s+показания:\s*",
    r"(?:права\s+и\s+обязанности.*?предусмотренные\s+ст\.?\s*(?:65-1|71|64|78)\s+УПК.*?а\s+именно:\s*\n?)(?:\d+\)\s+.+?\n)+.*?(?=Права\s+и\s+обязанности.*?мне\s+разъяснены|Я,\s|$)",
    r"Свидетель\s+(?:при\s+допросе\s+)?(?:вправе|имеет\s+право)[:\s].*?(?=Права\s+и\s+обязанности.*?мне\s+разъяснены|Сущность\s+прав\s+ясна|По\s+существу|Я,\s)",
    r"в\s+присутствии\s+(?:своего\s+)?адвоката\.?\s*Неявка\s+адвоката.*?(?=Права\s+и\s+обязанности|Сущность\s+прав|$)",
    r"Свидетелю\s+обеспечивается\s+возмещение\s+расходов.*?(?=Права\s+и\s+обязанности|Сущность\s+прав|$)",
    r"Права\s+и\s+обязанности\s+свидетеля,?\s*предусмотренные\s+ст\.?\s*\d+\s+УПК\s+РК,?\s*мне\s+разъяснены\.?\s*Сущность\s+прав\s+ясна\.?",
    r"(?:Свидетель|Потерпевший|Подозреваемый\(ая\)|Защитник)[:\s]*\n\s*[А-ЯЁ][а-яёА-ЯЁ]+\s+[А-ЯЁ]\.[А-ЯЁ]\.(?:\s*\n)?",
    r"Свидетель\s+\S+\s+\S+\s+предупрежден\(а\)\s+об\s+уголовной\s+ответственности.*?(?=Свидетелю\s+разъяснено|По\s+существу|Я,\s)",
    r"Свидетелю\s+разъяснено\s+право\s+отказаться\s+от\s+дачи\s+показаний.*?(?:родственников|үй-ішілік)\.?",
    r"Я,?\s+\S+\s+\S+\.?\s+показания\s+желаю\s+давать\s+на\s+\S+\s+языке[^.]*не\s+нуждаюсь\.?",
    r"Свидетелю\s+предложено\s+рассказать\s+об\s+отношениях.*?следующие\s+показания:\s*",
    r"С\s+протоколам?\s+ознакомлен[^.]*ходатайств\s+не\s+имею\.?",
    r"С\s+целью\s+уточнения\s+и\s+дополнения\s+показаний\s+(?:свидетеля|подозреваемого)\s+(?:ему\(ей\)|ему)\s+заданы\s*\n?\s*следующие\s+вопросы[:\s]*",
    r"Подозреваемый\(ая\)[:\s]*\n\s*[А-ЯЁ][а-яёА-ЯЁ]+\s+[А-ЯЁ]\.[А-ЯЁ]\.\s*\n?\s*(?:Защитник[:\s]*\n\s*[А-ЯЁ][а-яёА-ЯЁ]+\s+[А-ЯЁ]\.[А-ЯЁ]\.\s*)?",
    r",?\s+с\s+участием\s+защитника\.?\s*",
    r"(?:разъяснены\s+права,?\s*предусмотренные\s+ст\.?\s*\d+\s+УПК\s+РК,?\s*а\s+именно:\s*\n?)[\s\S]*?(?=Сущность\s+прав\s+ясна|Права\s+.*?мне\s+разъяснены|На\s+вопрос,?\s+признает|По\s+существу|По\s+поводу\s+подозрения)",
    r"\n\d+(?:-\d+)?\)\s+(?:знать|получить|защищать|участвовать|заявлять|представлять|давать|отказаться|приносить|обжаловать|знакомиться|пользоваться|ходатайствовать|иметь|примириться|возражать|безотлагательно|при\s+назначении|в\s+порядке)[^\n]*(?:\n(?!\d+[).]|\n\n|Права|Сущность|По\s+существу|По\s+поводу)[^\n]+)*",
]

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


@dataclass(slots=True)
class TextProcessingResult:
    converted: bool
    skip_type: str | None
    payload: dict[str, Any]


class TextProcessingService:


    def precheck(self, filename: str) -> dict[str, str] | None:
        """# 1. Классификация по имени"""

        doc_info_type = classify_by_filename(filename)

        if doc_info_type["type"] in SKIP_FILE_TYPES:
            skipped = {"type": doc_info_type["type"], "filename": filename}
            return skipped
        return None

    @staticmethod
    def _build_skip_payload(skip_type: str, filename: str) -> dict[str, Any]:
        return {"type": skip_type, "filename": filename}

    def process(self, filename: str, text: str, method: str) -> TextProcessingResult:
        doc_info = classify_by_filename(filename)

        if not doc_info["lang"] and text:
            doc_info["lang"] = detect_language(text)

        if doc_info["type"] == "other":
            subtype = classify_other_by_content(text)
            if subtype != "other":
                doc_info["type"] = subtype

        if doc_info["type"] in SKIP_OTHER_SUBTYPES:
            payload = {"type": doc_info["type"], "filename": filename}
            return TextProcessingResult(converted=False, skip_type=doc_info["type"], payload=payload)

        # Очищаем текст от мусора
        cleaned = clean_text(text)

        essential = extract_essential_data(text, doc_info["type"], cleaned)
        payload = {"info": doc_info, "data": essential, "method": method, "cleaned": cleaned}
        return TextProcessingResult(converted=True, skip_type=None, payload=payload)

    def generate_markdown(self, doc_info: dict[str, Any],
                          cleaned_text: str,
                          essential_data: dict[str, Any],
                          extraction_method: str) -> str:
        lines: list[str] = []
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
                "fio": "ФИО",
                "iin": "ИИН",
                "case_numbers": "Номера дел",
                "dates": "Даты",
                "articles_uk": "Статьи УК РК",
                "phones": "Телефоны",
                "amounts": "Суммы",
                "addresses": "Адреса",
                "protocol_subtype": "Вид протокола",
                "interrogation_start": "Начало допроса",
                "interrogation_end": "Окончание допроса",
                "person_name": "ФИО допрашиваемого",
                "person_dob": "Дата рождения",
                "person_birthplace": "Место рождения",
                "person_citizenship": "Гражданство",
                "person_workplace": "Место работы",
                "person_occupation": "Должность",
                "person_address": "Адрес",
                "person_phone": "Телефон",
                "person_criminal_record": "Судимость",
                "decree_subtype": "Вид постановления",
                "court_case_id": "Номер суд. дела",
                "judge": "Судья",
                "court_subject": "В отношении",
                "court_time_start": "Начало заседания",
                "court_time_end": "Окончание заседания",
                "court_name": "Суд",
                "court_participants": "Участники",
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

            for block_key, block_title in [("testimony", "Показания"), ("qa_section", "Вопросы и ответы"),
                                           ("resolution", "Резолютивная часть"), ("description", "Описательная часть")]:
                if block_key in essential_data:
                    lines.append("")
                    lines.append(f"### {block_title}")
                    lines.append(essential_data[block_key])
            lines.append("")

        lines.append("## Содержание (очищенный текст)")
        lines.append("")
        # В конце очищенный текст
        lines.append(cleaned_text)
        lines.append("")
        return "\n".join(lines)

    def build_converted_markdown(self, doc_info: dict[str, Any],
                                 cleaned_text: str,
                                 essential_data: dict[str, Any],
                                 extraction_method: str) -> str:
        lines: list[str] = []
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
                lines.append(f"- **Дата создания:** {datetime.fromtimestamp(ts).strftime('%d.%m.%Y %H:%M')}")
            except (ValueError, OSError):
                pass

        lines.append(f"- **Извлечение:** {extraction_method}")
        lines.append("")

        if essential_data:
            lines.append("## Извлечённые данные")
            for key, value in essential_data.items():
                if isinstance(value, list):
                    lines.append(f"- **{key}:** {', '.join(str(v) for v in value)}")
                else:
                    lines.append(f"- **{key}:** {value}")
            lines.append("")

        lines.append("## Содержание (очищенный текст)")
        lines.append("")
        lines.append(cleaned_text)
        lines.append("")
        return "\n".join(lines)


def classify_by_filename(filename: str) -> dict[str, str]:
    name_no_ext = filename
    ext = ""

    for file_ext in (".pdf", ".docx", ".doc", ".txt"):
        if filename.lower().endswith(file_ext):
            name_no_ext = filename[:-len(file_ext)]
            ext = file_ext
            break

    parts = name_no_ext.split("_")
    doc_type = "other"

    if filename.upper().startswith("COURT_RULING"):
        doc_type = "court_ruling"
    else:
        for known in ("cov_letter", "report_erdr", "report_kui", "notification_erdr", "phototable", "decree", "protocol"):
            if filename.startswith(known):
                doc_type = known
                break

    lang = parts[-1] if parts and parts[-1] in ("RU", "KK") else ""

    case_number = ""
    timestamp = ""
    numeric_parts = [p for p in parts if re.match(r"^\d{10,}$", p)]

    if len(numeric_parts) >= 2:
        case_number = numeric_parts[0]
        timestamp = numeric_parts[1]
    elif len(numeric_parts) == 1:
        value = numeric_parts[0]
        if len(value) == 15:
            case_number = value
        elif len(value) == 13:
            timestamp = value
        else:
            case_number = value

    court_date = ""
    if doc_type == "court_ruling":
        match = re.search(r"(\d{2}\.\d{2}\.\d{4})", filename)
        if match:
            court_date = match.group(1)

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
    kk_markers = ["қаулы", "бабы", "бөлігі", "тергеуші", "анықтаушы", "құжат", "жылы", "қаңтар", "ақпан", "туралы", "бойынша", "тұлға"]
    ru_markers = ["постановление", "протокол", "следователь", "допрос", "установил", "дознаватель", "потерпевш", "свидетел"]

    tl = text.lower()
    kk = sum(1 for marker in kk_markers if marker in tl)
    ru = sum(1 for marker in ru_markers if marker in tl)

    if kk > ru:
        return "KK"
    if ru > kk:
        return "RU"
    return ""


def clean_text(text: str) -> str:
    """Очещаем текст от ненужно информации используем паттерны BOILERPLATE_PATTERNS"""
    cleaned = text
    for pattern in BOILERPLATE_PATTERNS:
        cleaned = re.sub(pattern, "", cleaned, flags=re.DOTALL | re.IGNORECASE)

    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = "\n".join(line.rstrip() for line in cleaned.split("\n"))
    return cleaned.strip()


def _normalize_fio_key(fio: str) -> str:
    trans = str.maketrans("ӘәҒғҚқҢңӨөҰұҮүҺһІі", "ААГгКкНнООУуУуХхИи")
    key = fio.translate(trans).lower()
    key = re.sub(r"(.)\1+", r"\1", key)
    return key


def _levenshtein(s1: str, s2: str) -> int:
    if len(s1) < len(s2):
        return _levenshtein(s2, s1)
    if len(s2) == 0:
        return len(s1)

    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]


def _fio_similarity(key1: str, key2: str) -> bool:
    if key1 == key2:
        return True

    parts1 = key1.split()
    parts2 = key2.split()

    if len(parts1) >= 2 and len(parts2) >= 2:
        fam1, name1 = parts1[0], parts1[1]
        fam2, name2 = parts2[0], parts2[1]

        if fam1[:5] == fam2[:5] and name1[:3] == name2[:3]:
            return True

        fam_dist = _levenshtein(fam1[:6], fam2[:6])
        name_dist = _levenshtein(name1[:4], name2[:4])
        if fam_dist <= 2 and name_dist <= 1:
            return True

    return False


def _deduplicate_fio(fio_collection: set[str] | dict[str, int] | list[str]) -> set[str]:
    if isinstance(fio_collection, set):
        fio_counts = {fio: 1 for fio in fio_collection}
    elif isinstance(fio_collection, dict):
        fio_counts = fio_collection
    else:
        fio_counts = {fio: 1 for fio in fio_collection}

    fio_list = list(fio_counts.keys())
    keys = [_normalize_fio_key(fio) for fio in fio_list]
    groups: list[list[str]] = []
    used: set[int] = set()

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

    result: set[str] = set()

    for variants in groups:
        def score(value: str) -> float:
            score_value = 0.0
            score_value += fio_counts.get(value, 1) * 20
            parts = value.split()

            if parts and re.search(r"(?:ов|ин|ев|ий|ер[ьт]|ко|ук|юк|ен)$", parts[0]):
                score_value += 10
            if parts and re.search(r"(?:ова|ову|овым|овою|ину|иным|иною|ому|ому)$", parts[0]):
                score_value -= 5
            if not re.search(r"[ӘәҒғҚқҢңӨөҰұҮүҺһІі]", value):
                score_value += 5

            score_value += len(value) / 100
            return score_value

        result.add(max(variants, key=score))

    return result


def extract_essential_data(text: str, doc_type: str, cleaned_text: str | None = None) -> dict[str, Any]:
    """Извлекаем из текста полезную информацию"""
    data: dict[str, Any] = {}
    cleaned = cleaned_text or text

    fio_matches = re.findall(FIO_PATTERN, text)
    if fio_matches:
        raw_fio = {" ".join(match) for match in fio_matches}
        data["fio"] = sorted(_deduplicate_fio(raw_fio))

    iin = re.findall(PATTERNS["iin"], text)
    if iin:
        data["iin"] = sorted(set(iin))

    case_numbers = re.findall(PATTERNS["case_numbers"], text)
    if case_numbers:
        data["case_numbers"] = sorted(set(case_numbers))

    dates = re.findall(PATTERNS["dates_dot"], text)
    for day, month, year in re.findall(PATTERNS["dates_text_ru"], text):
        dates.append(f"{day}.{month}.{year}")
    for year, day, month in re.findall(PATTERNS["dates_text_kk"], text):
        dates.append(f"{day}.{month}.{year}")
    if dates:
        data["dates"] = sorted(set(dates))

    articles: list[str] = []
    for article, part in re.findall(PATTERNS["articles_ru"], text):
        articles.append(f"ст.{article} ч.{part} УК РК")
    for article, part in re.findall(PATTERNS["articles_kk"], text):
        articles.append(f"ст.{article} ч.{part} ҚК РК")
    if articles:
        data["articles_uk"] = sorted(set(articles))

    phones = re.findall(PATTERNS["phones"], text)
    if phones:
        data["phones"] = sorted(set(phones))

    amounts = re.findall(PATTERNS["amounts"], text)
    normalized_amounts: set[str] = set()
    for amount in amounts:
        normalized = re.sub(r"\s+", " ", amount.strip())
        try:
            value = int(normalized.replace(" ", ""))
        except ValueError:
            continue
        if value >= 100:
            normalized_amounts.add(f"{value:,}".replace(",", " ") + " тенге")
    if normalized_amounts:
        data["amounts"] = sorted(normalized_amounts)

    addresses = re.findall(PATTERNS["addresses_ru"], text)
    if addresses:
        data["addresses"] = sorted(set(addresses))

    if doc_type == "protocol":
        data.update(_extract_protocol_data(text, cleaned))
    elif doc_type == "decree":
        data.update(_extract_decree_data(cleaned))
    elif doc_type == "court_ruling":
        data.update(_extract_court_ruling_data(text))
    elif doc_type == "detention_notice":
        data.update(_extract_detention_data(text))

    return data


def _extract_protocol_data(raw_text: str, cleaned_text: str | None = None) -> dict[str, Any]:
    data: dict[str, Any] = {}
    text = raw_text
    cleaned = cleaned_text or text

    protocol_type = re.search(r"ПРОТОКОЛ\s*\n\s*допроса\s+(потерпевшего|свидетеля|подозреваемого|обвиняемого)", text, re.IGNORECASE)
    if not protocol_type:
        protocol_type = re.search(r"допроса\s+(свидетеля,\s+имеющего\s+право\s+на\s+защиту)", text, re.IGNORECASE)
        if protocol_type:
            data["protocol_subtype"] = "Допрос свидетеля (с правом на защиту)"
    if protocol_type and "protocol_subtype" not in data:
        data["protocol_subtype"] = f"Допрос {protocol_type.group(1)}"

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
            continue

        match = re.search(rf"{label}[:\s]*\n?\s*(.+?)(?:\n|$)", text)
        if not match:
            continue

        value = match.group(1).strip()
        skip_values = {"-", "—", "и (или)", "Паспорт или иной документ,", "Паспорт или иной документ", "Место жительства и (или)"}
        if value and value not in skip_values and not value.startswith("Паспорт") and not value.startswith("Место жительства и"):
            data[key] = value

    testimony_patterns = [
        r"По\s+существу\s+(?:заданных\s+вопросов|дела|известных|могу)[^.]{0,80}?(?:показал[аи]?|пояснил[аи]?|сообщил[аи]?|пояснить)\s*(?:следующее)?[:\s,]*(.+?)(?:(?:На\s+этом\s+допрос|Протокол\s+(?:мною\s+)?прочитан|Допрашиваемый|С\s+моих\s+слов\s+записано|Более\s+(?:мне\s+)?по\s+данному\s+факту|Больше\s+мне))",
        r"По\s+поводу\s+подозрения.*?могу\s+(?:показать|пояснить)\s+следующее[:\s]*(.+?)(?:(?:На\s+этом\s+допрос|Протокол\s+(?:мною\s+)?прочитан|С\s+моих\s+слов\s+записано|Более\s+(?:мне\s+)?по\s+данному\s+факту|Больше\s+мне))",
        r"дал[аи]?\s*следующие\s+показания[:\s]*(.+?)(?:(?:На\s+этом\s+допрос|Протокол\s+(?:мною\s+)?прочитан|С\s+моих\s+слов\s+записано))",
        r"могу\s+(?:пояснить|показать)\s+следующее[:\s,]*(.+?)(?:(?:На\s+этом\s+допрос|Протокол\s+(?:мною\s+)?прочитан|С\s+моих\s+слов\s+записано|Более\s+(?:мне\s+)?по\s+данному\s+факту|Больше\s+мне))",
        r"Показания[:\s]+(.+?)(?:(?:На\s+этом\s+допрос|Протокол\s+(?:мною\s+)?прочитан|С\s+моих\s+слов\s+записано))",
    ]

    for pattern in testimony_patterns:
        match = re.search(pattern, cleaned, re.DOTALL | re.IGNORECASE)
        if not match or len(match.group(1).strip()) <= 50:
            continue

        testimony = match.group(1).strip()
        testimony = re.sub(r"\n\s*(?:Свидетель|Потерпевший|Подозреваемый\(ая\)|Защитник)[:\s]*\n\s*[А-ЯЁ][а-яёА-ЯЁ]+\s+[А-ЯЁ]\.[А-ЯЁ]\.\s*", "\n", testimony)
        testimony = re.sub(r"\n\s*С\s+протоколам?\s+ознакомлен[^.]*ходатайств\s+не\s+имею\.?\s*", "\n", testimony)
        testimony = re.sub(r"\n\s*С\s+целью\s+уточнения\s+и\s+дополнения.*$", "", testimony, flags=re.DOTALL)
        testimony = re.sub(r"\n\s*Вопрос:\s.*$", "", testimony, flags=re.DOTALL)
        testimony = testimony.strip()

        if len(testimony) > 50:
            data["testimony"] = testimony
        break

    qa_blocks = re.findall(
        r"Вопрос:\s{1,3}(.+?)\nОтвет:\s*(.+?)(?=\nВопрос:\s|\n_{2,}|\nНа\s+этом|\nДопросил|$)",
        cleaned,
        re.DOTALL | re.IGNORECASE,
    )

    valid_qa: list[tuple[str, str]] = []
    for question, answer in qa_blocks:
        question = question.strip()
        answer = answer.strip()

        answer = re.sub(
            r"\n\s*(?:Свидетель|Потерпевший|Подозреваемый\(ая\)|Защитник)(?:,\s+имеющий\s+право\s+на\s+защиту)?[:\s]*\n?\s*[А-ЯЁ][а-яёА-ЯЁ]+\s+[А-ЯЁ]\.[А-ЯЁ]\.\s*(?:\n.*)?$",
            "",
            answer,
            flags=re.DOTALL,
        ).strip()
        answer = re.sub(r"\n\s*С\s+протоколам?\s+ознакомлен.*$", "", answer, flags=re.DOTALL).strip()
        answer = re.sub(r"\n\s*[А-ЯЁ][а-яёА-ЯЁ]+\s+[А-ЯЁ]\.[А-ЯЁ]\.\s*$", "", answer).strip()
        answer = re.sub(r"\n\s*С\s+целью\s+уточнения.*$", "", answer, flags=re.DOTALL).strip()

        if len(question) < 15 or len(answer) < 3:
            continue
        if re.match(r"^[а-яёА-ЯЁ]{1,3}[:\s]", question) and not re.match(r"^(?:как|что|кто|где|вы\s)", question, re.IGNORECASE):
            continue

        valid_qa.append((question, answer))

    if valid_qa:
        data["qa_section"] = "\n".join(f"**В:** {q}\n**О:** {a}" for q, a in valid_qa)

    return data


def _extract_decree_data(text: str) -> dict[str, Any]:
    data: dict[str, Any] = {}

    subtype = re.search(r"(?:ПОСТАНОВЛЕНИЕ|ҚАУЛЫ)\s*\n\s*(.+?)(?:\n|г\.|Көкшетау)", text, re.IGNORECASE)
    if subtype:
        data["decree_subtype"] = subtype.group(1).strip()

    resolution = re.search(
        r"(?:ПОСТАНОВИЛ|ҚАУЛЫ ЕТТІМ)[:\s]*(.*?)(?:QR-код|Документ подготовил|Құжатты дайындады|Настоящее постановление|$)",
        text,
        re.DOTALL | re.IGNORECASE,
    )
    if resolution:
        data["resolution"] = resolution.group(1).strip()

    description_patterns = [
        r"(?:УСТАНОВИЛ|АНЫҚТАДЫМ)[:\s]*(.*?)(?:На основании|Жоғарыда|руководствуясь|басшылыққа|ПОСТАНОВИЛ|ҚАУЛЫ ЕТТІМ)",
        r"У\s*С\s*Т\s*А\s*Н\s*О\s*В\s*И\s*Л[:\s]*(.*?)(?:На основании|руководствуясь|П\s*О\s*С\s*Т\s*А\s*Н\s*О\s*В\s*И\s*Л)",
    ]

    for pattern in description_patterns:
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if match and len(match.group(1).strip()) > 30:
            data["description"] = match.group(1).strip()
            break

    return data


def _extract_court_ruling_data(text: str) -> dict[str, Any]:
    data: dict[str, Any] = {}

    match = re.search(PATTERNS["case_id_court"], text)
    if match:
        data["court_case_id"] = match.group(1).strip()

    match = re.search(r"председательствующего судьи[:\s]*(.+?)(?:\n|$)", text, re.IGNORECASE)
    if match:
        data["judge"] = match.group(1).strip()

    match = re.search(r"в отношении\s+(.+?)(?:\n|$)", text, re.IGNORECASE)
    if match:
        data["court_subject"] = match.group(1).strip()

    match = re.search(r"Время начала судебного заседания[:\s]*(.+?)(?:\n|$)", text)
    if match:
        data["court_time_start"] = match.group(1).strip()

    match = re.search(r"Время окончания судебного заседания[:\s]*(.+?)(?:\n|$)", text)
    if match:
        data["court_time_end"] = match.group(1).strip()

    match = re.search(r"(?:следственный суд|суд)\s+(?:города\s+)?([А-Яа-яЁёӘәҒғҚқ]+)", text, re.IGNORECASE)
    if match:
        data["court_name"] = match.group(0).strip()

    match = re.search(r"установлена связь.*?с\s+(.*?)(?:\n|$)", text, re.IGNORECASE)
    if match:
        data["court_participants"] = match.group(1).strip()

    return data


def _extract_detention_data(text: str) -> dict[str, Any]:
    data: dict[str, Any] = {}

    match = re.search(r"задержан[аоы]?\s+(\d{1,2}\.\d{2}\.\d{4})\s*(?:г(?:ода)?\.?)?\s*(?:в\s*)?(\d{1,2}[:\s]*\d{2})", text, re.IGNORECASE)
    if match:
        data["detention_date"] = match.group(1)
        data["detention_time"] = match.group(2)

    match = re.search(r"(?:ИВС|ВС|изолятор|содержится)[:\s]*(.+?)(?:\n|$)", text, re.IGNORECASE)
    if match:
        data["detention_location"] = match.group(1).strip()

    return data