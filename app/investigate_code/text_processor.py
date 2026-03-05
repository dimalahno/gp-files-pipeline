#!/usr/bin/env python3
"""
Файл 2: Обработка сырого текста документов уголовного дела.

Принимает *_raw.txt (сырой текст) и выполняет:
1. Классификацию (по имени файла → по содержимому)
2. Определение типа → генерацию осмысленного имени файла
3. Очистку (OCR-артефакты + boilerplate)
4. Извлечение данных (ФИО, даты, статьи, показания)
5. Дедупликацию ФИО

На выходе: {тип_документа}_{ФИО/дата}_cleaned.txt

Использование:
    # CLI:
        python text_processor.py [папка_с_raw_текстами]

    # Как модуль:
        from text_processor import (
            classify_by_filename, classify_other_by_content,
            full_clean, extract_essential_data, generate_content_filename,
            process_raw_text_for_api,
        )
"""

import os
import re
import sys
import logging
import html as html_module
from typing import List, Tuple, Optional, Dict, Any
from collections import defaultdict
from datetime import datetime


# ==========================================================================
# LOGGING
# ==========================================================================

logger = logging.getLogger(__name__)


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
    # --- Основные типы ---
    "interrogation_suspect": "Допрос подозреваемого",
    "interrogation_victim": "Допрос потерпевшего",
    "interrogation_victim_additional": "Доп. допрос потерпевшего",
    "interrogation_witness": "Допрос свидетеля",
    "interrogation_witness_defense": "Допрос свидетеля с правом на защиту",
    "indictment": "Обвинительный акт",
    "expertise": "Заключение эксперта",
    "expertise_appointment": "Назначение экспертизы",
    "inspection_protocol": "Протокол осмотра предметов/документов",
    "crime_scene_protocol": "Протокол ОМП",
    "decree": "Постановление",
    "decree_measure_restraint": "Постановление о мере пресечения",
    "decree_defense_provision": "Постановление об обеспечении защитника",
    "decree_electronic_format": "Постановление о ведении в эл. формате",
    "decree_term_extension": "Продление срока расследования",
    "decree_recognize_suspect": "Признание подозреваемым",
    "decree_recognize_victim": "Признание потерпевшим",
    "report_erdr": "Рапорт ЕРДР",
    "report_kui": "Рапорт КУИ",
    "court_ruling": "Протокол судебного заседания",
    "witness_list": "Список лиц к вызову",
    "detention_notice": "Уведомление о задержании",
    "counsel_notice": "Уведомление о защитнике",
    "case_acceptance": "Принятие дела к производству",
    "seizure_decree": "Постановление о выемке",
    "legal_aid_request": "Ходатайство о юр. помощи",
    "protocol": "Протокол допроса",
    # --- Новые типы (из Инструкции) ---
    "interrogation_suspect_additional": "Доп. допрос подозреваемого",
    "interrogation_witness_additional": "Доп. допрос свидетеля",
    "qualification_decree": "Постановление о квалификации деяния",
    "criminal_record": "Сведения о судимости",
    "property_info": "Сведения об имуществе",
    "audit_act": "Акт проверки",
    "revision_act": "Акт ревизии",
    "specialist_conclusion": "Заключение специалиста",
    "evidence_attachment": "Постановление о приобщении вещдоков",
    "confrontation_protocol": "Протокол очной ставки",
    "identification_protocol": "Протокол предъявления для опознания",
    "verification_protocol": "Протокол проверки показаний на месте",
    "experiment_protocol": "Протокол следственного эксперимента",
    "seizure_protocol": "Протокол выемки",
    "search_decree": "Постановление о производстве обыска",
    "search_protocol": "Протокол обыска",
    "covert_actions_protocol": "Протокол осмотра результатов НСД",
    "investigation_assignment": "Постановление о поручении расследования",
    "familiarization_protocol": "Протокол ознакомления с материалами",
    "recognizance": "Подписка о невыезде",
    "legal_claim": "Исковое заявление",
    "investigation_start_notice": "Уведомление о начале расследования",
    "victim_statement": "Заявление потерпевшего",
    "police_db_record": "Справка из БД (полицейская)",
    "special_registry": "Выписка из спецучётов",
    "conclusion": "Заключение эксперта",
    "other": "Иной документ",
    # --- Пропускаемые ---
    "obligation": "Обязательство о явке [ПРОПУЩЕНО]",
    "language_statement": "Заявление о языке [ПРОПУЩЕНО]",
    "format_statement": "Заявление о формате [ПРОПУЩЕНО]",
    "rights_explanation": "Разъяснение прав [ПРОПУЩЕНО]",
    "empty": "Пустой документ [ПРОПУЩЕНО]",
    "admin_form": "Адм. форма [ПРОПУЩЕНО]",
    "phototable_embedded": "Фототаблица [ПРОПУЩЕНО]",
    "cov_letter": "Сопроводительное письмо [ПРОПУЩЕНО]",
    "notification_erdr": "Уведомление ЕРДР [ПРОПУЩЕНО]",
    "phototable": "Фототаблица [ПРОПУЩЕНО]",
}

LANG_NAMES = {"RU": "Русский", "KK": "Казахский", "": ""}

# Метаданные блоков: block (раздел ОА/КД), needed_for_kd, needed_for_oa
DOC_BLOCK_META = {
    # --- Подозреваемый ---
    "interrogation_suspect":            {"block": "suspect",   "kd": True,  "oa": True},
    "interrogation_suspect_additional":  {"block": "suspect",   "kd": True,  "oa": True},
    "decree_recognize_suspect":          {"block": "suspect",   "kd": True,  "oa": True},
    "decree_measure_restraint":          {"block": "suspect",   "kd": True,  "oa": True},
    "criminal_record":                   {"block": "suspect",   "kd": True,  "oa": True},
    "property_info":                     {"block": "suspect",   "kd": False, "oa": True},
    # --- Потерпевший ---
    "interrogation_victim":              {"block": "victim",    "kd": True,  "oa": True},
    "interrogation_victim_additional":   {"block": "victim",    "kd": True,  "oa": True},
    "decree_recognize_victim":           {"block": "victim",    "kd": True,  "oa": True},
    # --- Свидетели ---
    "interrogation_witness":             {"block": "witness",   "kd": True,  "oa": True},
    "interrogation_witness_additional":  {"block": "witness",   "kd": True,  "oa": True},
    "interrogation_witness_defense":     {"block": "witness",   "kd": True,  "oa": True},
    "confrontation_protocol":            {"block": "witness",   "kd": True,  "oa": True},
    "identification_protocol":           {"block": "witness",   "kd": True,  "oa": True},
    "verification_protocol":             {"block": "witness",   "kd": True,  "oa": True},
    # --- Экспертизы ---
    "expertise_appointment":             {"block": "expertise", "kd": True,  "oa": True},
    "expertise":                         {"block": "expertise", "kd": True,  "oa": True},
    "specialist_conclusion":             {"block": "expertise", "kd": True,  "oa": True},
    "audit_act":                         {"block": "expertise", "kd": False, "oa": True},
    "revision_act":                      {"block": "expertise", "kd": False, "oa": True},
    # --- Иные процессуальные ---
    "crime_scene_protocol":              {"block": "other_procedural", "kd": True,  "oa": True},
    "inspection_protocol":               {"block": "other_procedural", "kd": True,  "oa": True},
    "experiment_protocol":               {"block": "other_procedural", "kd": True,  "oa": True},
    "seizure_protocol":                  {"block": "other_procedural", "kd": True,  "oa": True},
    "seizure_decree":                    {"block": "other_procedural", "kd": True,  "oa": True},
    "search_decree":                     {"block": "other_procedural", "kd": True,  "oa": True},
    "search_protocol":                   {"block": "other_procedural", "kd": True,  "oa": True},
    "evidence_attachment":               {"block": "other_procedural", "kd": True,  "oa": True},
    "covert_actions_protocol":           {"block": "other_procedural", "kd": True,  "oa": True},
    "report_erdr":                       {"block": "other_procedural", "kd": True,  "oa": True},
    "qualification_decree":              {"block": "other_procedural", "kd": True,  "oa": True},
    # --- Общие ---
    "indictment":                        {"block": "indictment", "kd": False, "oa": True},
    "witness_list":                      {"block": "other_procedural", "kd": False, "oa": True},
    "decree_defense_provision":          {"block": "other_procedural", "kd": True,  "oa": True},
    "decree_electronic_format":          {"block": "other_procedural", "kd": True,  "oa": False},
    "decree_term_extension":             {"block": "other_procedural", "kd": True,  "oa": False},
    "case_acceptance":                   {"block": "other_procedural", "kd": True,  "oa": False},
    "detention_notice":                  {"block": "suspect",          "kd": True,  "oa": False},
    "counsel_notice":                    {"block": "suspect",          "kd": True,  "oa": False},
}


# ==========================================================================
# CONSTANTS: BOILERPLATE PATTERNS
# ==========================================================================

# Общие паттерны — применяются ко ВСЕМ документам
_BP_GENERAL = [
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
]

# Паттерны для допросов — применяются только к interrogation_* типам
_BP_INTERROGATION = [
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

# Типы документов, к которым применяются паттерны допросов
_INTERROGATION_TYPES = {
    "interrogation_suspect", "interrogation_victim", "interrogation_victim_additional",
    "interrogation_witness", "interrogation_witness_defense", "protocol",
    "interrogation_suspect_additional", "interrogation_witness_additional",
    "confrontation_protocol", "verification_protocol",
}

# Обратная совместимость
BOILERPLATE_PATTERNS = _BP_GENERAL + _BP_INTERROGATION


# ==========================================================================
# CONSTANTS: REGEX PATTERNS FOR DATA EXTRACTION
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
    "addresses_ru": r"г\.?\s*(?:Кокшетау|Астана|Нур-Султан|Алматы|Караганда|Актобе|Шымкент|Костанай|Павлодар|Семей|Тараз|Атырау|Петропавловск|Усть-Каменогорск|Талдыкорган|Актау|Кызылорда|Туркестан|Уральск|Экибастуз|Темиртау|Рудный|Жезказган|Балхаш|Сатпаев|Степногорск|Сарань|Аксу|Щучинск|Лисаковск|Риддер|Текели|Жанаозен|Байконур|Арыс|Каратау|Сергеевка|Аягоз)(?:[,\s]+(?:ул\.|улица|пр\.|просп\.|мкр\.|микрорайон|к-сі|көш(?:есі)?|көшесі|Төреқұлов|район)\s*[А-ЯЁа-яёӘәҒғҚқҢңӨөҰұҮүҺһІі\w\d/.\-]+(?:[,\s]+(?:д\.|дом|үй|кв\.|квартира|корп\.|корпус|пом\.|кв)\s*[№\d/\-]+)*)*",
    "case_id_court": r"Номер дела:\s*(.+)",
}

FIO_PATTERN = r"(?<!\w)([А-ЯЁӘҒҚҢӨҰҮҺІ][а-яёәғқңөұүһі]+)\s+([А-ЯЁӘҒҚҢӨҰҮҺІ][а-яёәғқңөұүһі]+)\s+([А-ЯЁӘҒҚҢӨҰҮҺІ][а-яёәғқңөұүһі]+(?:вна|вич|ович|евна|евич|ұлы|қызы|кызы|улы))"


# ==========================================================================
# CLASSIFICATION: FILENAME PATTERNS
# ==========================================================================

# Паттерны для человекочитаемых имён файлов (порядок важен — специфичные перед общими)
_HUMAN_FILENAME_PATTERNS = [
    # Допросы (доп. допросы — специфичные перед общими)
    # \w* после "допрос" чтобы матчить "допроса", "допросов" и т.д.
    # \.? после "доп" чтобы матчить "доп." и "доп "
    (r"доп(?:олнительн\w*)?\.?\s*допрос\w*\s+(?:потерпевш|оптерпевш)", "interrogation_victim_additional"),
    (r"доп(?:олнительн\w*)?\.?\s*допрос\w*\s+подозреваем", "interrogation_suspect_additional"),
    (r"доп(?:олнительн\w*)?\.?\s*допрос\w*\s+свидетел", "interrogation_witness_additional"),
    (r"допрос\w*\s+подозреваем", "interrogation_suspect"),
    (r"допрос\w*\s+потерпевш", "interrogation_victim"),
    (r"допрос\w*\s+свидетел\w*[,.]?\s*имеющ\w*\s+право\s+на\s+защ", "interrogation_witness_defense"),
    (r"допрос\w*\s+свидетел", "interrogation_witness"),
    # Экспертизы / заключения
    (r"назначени\w*\s+(?:судебно[- ]?медицинск|смэ|экспертиз)", "expertise_appointment"),
    (r"заключени\w*\s+(?:смэ|судебно[- ]?медицинск|эксперт)", "expertise"),
    (r"заключени\w*\s+специалист", "specialist_conclusion"),
    # Обвинительный акт
    (r"обвинительн\w*\s+акт", "indictment"),
    # Постановления (специфичные)
    (r"о?\s*признани\w*\s+(?:лица\s+)?(?:в\s+качестве\s+)?подозреваем", "decree_recognize_suspect"),
    (r"о?\s*признани\w*\s+(?:лица\s+)?потерпевш", "decree_recognize_victim"),
    (r"о?\s*применени\w*\s+мер\w*\s+пресечен", "decree_measure_restraint"),
    (r"об?\s*обеспечени\w*\s+(?:участия\s+)?защитник", "decree_defense_provision"),
    (r"о?\s*ведени\w*\s+(?:уголовного\s+)?(?:судопроизводства\s+)?в\s+эл(?:ектронн)?\w*\s+формат", "decree_electronic_format"),
    (r"продлен\w*\s+срок", "decree_term_extension"),
    (r"о?\s*назначени\w*\s+(?:смэ|судебно[- ]?медицинск|экспертиз)", "expertise_appointment"),
    (r"квалификаци\w*\s+деян", "qualification_decree"),
    (r"квал\b", "qualification_decree"),
    (r"приобщени\w*\s+(?:вещественн|вещдок|к\s+(?:уголовному\s+)?делу)", "evidence_attachment"),
    (r"о?\s*производств\w*\s+обыск", "search_decree"),
    (r"о?\s*поручени\w*\s+(?:производств|досудебн|расследован)", "investigation_assignment"),
    # Протоколы (специфичные перед общими)
    (r"(?:протокол\s+)?(?:осмотра?\s+)?мест\w*\s+происшестви|протокол\s+омп", "crime_scene_protocol"),
    (r"протокол\s+очн\w*\s+ставк", "confrontation_protocol"),
    (r"протокол\s+(?:предъявлени\w*\s+(?:для\s+)?)?опознан", "identification_protocol"),
    (r"протокол\s+проверк\w*\s+показаний", "verification_protocol"),
    (r"протокол\s+следственн\w*\s+эксперимент", "experiment_protocol"),
    (r"протокол\s+(?:о\s+производстве\s+)?выемк", "seizure_protocol"),
    (r"протокол\s+(?:о\s+производстве\s+)?обыск", "search_protocol"),
    (r"протокол\s+осмотра\s+результат\w*\s+(?:нсд|негласн)", "covert_actions_protocol"),
    (r"протокол\s+ознакомлени", "familiarization_protocol"),
    (r"ознакомлени\w*\s+с\s+материал", "familiarization_protocol"),
    (r"протокол\s+осмотра", "inspection_protocol"),
    # Рапорты
    (r"рапорт\s*(?:о\s+)?регистрац\w*\s*(?:в\s+)?ердр", "report_erdr"),
    (r"рапорт", "report_erdr"),
    # Сведения
    (r"сведени\w*\s+(?:о\s+)?судимост", "criminal_record"),
    (r"сведени\w*\s+(?:об?\s+)?имуществ", "property_info"),
    # Акты (ревизия перед проверкой — специфичные перед общими)
    (r"акт\s+ревизи", "revision_act"),
    (r"акт\s+проверк", "audit_act"),
    # Прочее
    (r"список\s+лиц\s*,?\s*подлежащ", "witness_list"),
    (r"подписк\w*\s+о\s+невыезд", "recognizance"),
    (r"исков\w*\s+заявлени", "legal_claim"),
    (r"фототаблиц", "phototable"),
    # Общие постановления (в конце, чтобы специфичные перебивали)
    (r"постановлени", "decree"),
]


# ==========================================================================
# CLASSIFICATION FUNCTIONS
# ==========================================================================

def classify_by_filename(filename: str) -> Dict[str, str]:
    """Classify document type by filename prefix (system names and human-readable)."""
    name_no_ext = filename
    ext = ""
    for e in [".pdf", ".docx", ".doc", "_raw.txt"]:
        if filename.lower().endswith(e):
            name_no_ext = filename[:-len(e)]
            ext = e
            break

    parts = name_no_ext.split("_")

    # 1) Системные префиксы (decree_..., protocol_..., cov_letter_...)
    doc_type = "other"
    if filename.upper().startswith("COURT_RULING"):
        doc_type = "court_ruling"
    else:
        for known in ["cov_letter", "report_erdr", "report_kui",
                       "notification_erdr", "phototable", "conclusion",
                       "decree", "protocol"]:
            if filename.startswith(known):
                doc_type = known
                break

    # 2) Человекочитаемые имена файлов (если системный префикс не сработал)
    if doc_type == "other":
        fn_lower = name_no_ext.lower()
        for pattern, dtype in _HUMAN_FILENAME_PATTERNS:
            if re.search(pattern, fn_lower):
                doc_type = dtype
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
    """Classify 'other' documents by text content analysis.

    Использует два контекста поиска:
    - header (первые 1500 символов) — для определения типа по заголовку
    - tl (весь текст) — для fallback-проверок
    """
    if not text or len(text.strip()) < 30:
        return "empty"

    tl = text.lower()
    # Заголовок документа — первые 1500 символов (для определения типа)
    header = tl[:1500]

    # --- Пропускаемые (мелкие формальные документы) ---
    if "обязательство" in tl and ("о явке" in tl or "являться по вызов" in tl):
        return "obligation"
    if "міндеттеме" in tl:
        return "obligation"
    if "о языке уголовного судопроизводства" in tl or "тіл туралы" in tl:
        return "language_statement"
    if re.search(r"протокол\s*\n?\s*разъяснени[ея]\s+прав", tl):
        return "rights_explanation"
    if ("фототаблица" in tl or "ф о т о т а б л и ц а" in tl) and "к протоколу" in tl:
        return "phototable_embedded"

    # --- Допросы (доп. допросы перед основными) ---
    if re.search(r"протокол\s+дополнительного\s+допроса\s+потерпевш", header):
        return "interrogation_victim_additional"
    if re.search(r"протокол\s+дополнительного\s+допроса\s+подозреваем", header):
        return "interrogation_suspect_additional"
    if re.search(r"протокол\s+дополнительного\s+допроса\s+свидетел", header):
        return "interrogation_witness_additional"
    if re.search(r"протокол\s+допроса\s+подозреваем", header) or \
       ("в качестве подозреваемого" in header and "допрос" in header):
        return "interrogation_suspect"
    if re.search(r"протокол\s+допроса\s+потерпевш", header) or \
       ("в качестве потерпевшего" in header and "допрос" in header):
        return "interrogation_victim"
    if re.search(r"протокол\s+допроса\s+свидетел\w*[,.]?\s+имеющ\w*\s+право\s+на\s+защ", header) or \
       ("в качестве свидетеля, имеющего право на защиту" in header):
        return "interrogation_witness_defense"
    if re.search(r"протокол\s+допроса\s+свидетел", header) or \
       ("в качестве свидетеля" in header and "допрос" in header):
        return "interrogation_witness"

    # --- Обвинительный акт ---
    if "обвинительный акт" in header or "составил обвинительный акт" in tl:
        return "indictment"

    # --- Постановления (специфичные — ПЕРЕД экспертизами, т.к. постановления
    #     часто содержат слова "заключение эксперта" в разделе о правах) ---
    if re.search(r"(?:постановление|қаулы)\s*.*квалификаци\w*\s+деян", header) or \
       ("квалифицировать" in header and "деяни" in header):
        return "qualification_decree"
    if re.search(r"постановление\s+о\s+признании\s+(?:лица\s+)?(?:в\s+качестве\s+)?подозреваем", header) or \
       ("усматриваются признаки состава" in header and "подозреваем" in header):
        return "decree_recognize_suspect"
    if re.search(r"постановление\s+о\s+признании\s+(?:лица\s+)?потерпевш", header) or \
       ("признать" in header and "потерпевшим" in header and "постановил" in tl):
        return "decree_recognize_victim"
    if re.search(r"постановление\s+о\s+применении\s+мер\w*\s+пресечен", header):
        return "decree_measure_restraint"
    if re.search(r"постановление\s+(?:об?\s+)?обеспечении\s+(?:участия\s+)?защитник", header):
        return "decree_defense_provision"
    if re.search(r"(?:ведении|вести)\s+(?:уголовного\s+)?(?:судопроизводства\s+)?в\s+электронн", header):
        return "decree_electronic_format"
    if re.search(r"продлени\w*\s+срок\w*\s+(?:досудебного\s+)?расследован", header) or \
       ("продлеваю" in header and "срок" in header):
        return "decree_term_extension"
    if re.search(r"постановление\s*.*приобщени\w*\s+(?:вещественн|к\s+(?:уголовному\s+)?делу)", header) or \
       ("приобщить" in tl and ("вещественн" in tl or "к делу" in tl) and "постановил" in tl):
        return "evidence_attachment"
    if re.search(r"постановление\s*.*(?:о\s+)?производств\w*\s+обыск", header) or \
       ("обыск" in header and "постановил" in tl and "произвести" in tl):
        return "search_decree"
    if re.search(r"постановлени\w*\s+о\s+поручени\w*\s+(?:производств|досудебн|расследован)", header):
        return "investigation_assignment"
    if re.search(r"постановлени\w*\s+о\s+принятии", header) and \
       ("уголовного дела" in header or "к своему производству" in header):
        return "case_acceptance"

    # --- Экспертизы (ищем ТОЛЬКО в заголовке, чтобы не ловить
    #     "заключения эксперта" в тексте прав подозреваемого) ---
    if re.search(r"назначени\w*\s+(?:судебно[- ]?медицинской\s+)?эксперт", header) or \
       ("на разрешение эксперта" in header and "вопрос" in header):
        return "expertise_appointment"
    if re.search(r"заключени\w*\s+(?:судебно[- ]?медицинск|эксперт)", header) or \
       ("выводы" in header and "эксперт" in header):
        return "expertise"

    # --- Протоколы (специфичные перед общими) ---
    if re.search(r"протокол\s+осмотра\s+мест\w*\s+происшестви", header) or \
       "получив сообщение о совершенном уголовном правонарушении" in header:
        return "crime_scene_protocol"
    if re.search(r"протокол\s+очной\s+ставки", header) or \
       ("очная ставка" in header and "между" in header):
        return "confrontation_protocol"
    if re.search(r"протокол\s+(?:предъявления\s+(?:для\s+)?)?опознани[ея]", header) or \
       ("предъявлен для опознания" in header):
        return "identification_protocol"
    if re.search(r"протокол\s+проверки\s+показаний\s+на\s+месте", header) or \
       ("проверка показаний" in header and "на месте" in header):
        return "verification_protocol"
    if re.search(r"протокол\s+следственного\s+эксперимент", header) or \
       ("следственный эксперимент" in header):
        return "experiment_protocol"
    if re.search(r"протокол\s+(?:о\s+производстве\s+)?выемк", header) or \
       ("произвел выемку" in tl or "произведена выемка" in tl):
        return "seizure_protocol"
    if re.search(r"протокол\s+(?:о\s+производстве\s+)?обыск", header) or \
       ("произвел обыск" in tl or "произведен обыск" in tl):
        return "search_protocol"
    if re.search(r"протокол\s+осмотра\s+результат\w*\s+(?:негласн|нсд)", header) or \
       ("негласные следственные действия" in tl and "осмотр" in tl):
        return "covert_actions_protocol"
    if re.search(r"протокол\s+ознакомлени", header) or \
       ("ознакомлен" in header and "материал" in header):
        return "familiarization_protocol"
    if re.search(r"протокол\s+осмотра\s+(?:предметов|документов|вещей)", header) or \
       "произвел осмотр предметов" in tl:
        return "inspection_protocol"

    # --- Заключения специалиста ---
    if re.search(r"заключени\w*\s+специалист", header) or \
       ("специалист" in header and "заключение" in header and "исследование" in header):
        return "specialist_conclusion"

    # --- Сведения ---
    if ("судимост" in tl or "не судим" in tl) and ("сведения" in tl or "справка" in tl):
        return "criminal_record"
    if ("имуществ" in tl or "собственност" in tl) and ("сведения" in tl or "справка" in tl):
        return "property_info"

    # --- Акты ---
    if "акт" in header and ("ревизи" in tl or "проверки" in tl) and \
       ("установлено" in tl or "выявлено" in tl or "обнаружено" in tl):
        if "ревизи" in tl:
            return "revision_act"
        return "audit_act"

    # --- Список лиц ---
    if "список" in header and ("лиц" in header or "подлежащ" in header) and \
       ("вызову" in tl or "судебное заседание" in tl or "сторона" in tl):
        return "witness_list"

    # --- Рапорты ---
    if ("рапорт" in header or "баянат" in header) and \
       ("ердр" in tl or "зарегистрирован" in tl or "обнаружен" in tl):
        return "report_erdr"

    # --- Прочие уведомления ---
    if "задержан" in tl and ("подозреваем" in tl or "уведомлени" in tl or "уведомляю" in tl):
        return "detention_notice"
    if "ұсталғаны" in tl or "ұстау" in tl:
        return "detention_notice"
    if ("защит" in header or "адвокат" in header) and \
       ("уведомлени" in header or "вступ" in header or "назначен" in header):
        return "counsel_notice"
    if "ходатайств" in header and ("юридическ" in tl or "помощ" in tl or "защит" in tl):
        return "legal_aid_request"
    if "принятии" in header and ("уголовного дела" in header or "к своему производству" in header):
        return "case_acceptance"
    if "өз өндірісіне қабылдау" in header:
        return "case_acceptance"
    if "выемк" in header or ("алу" in header and "қаулы" in header):
        return "seizure_decree"

    # --- Новые типы ---
    if re.search(r"подписк\w*\s+о\s+невыезд", header):
        return "recognizance"
    if re.search(r"исков\w*\s+заявлени", header):
        return "legal_claim"
    if re.search(r"уведомлени\w*\s+о\s+начале\s+(?:досудебного\s+)?расследован", header):
        return "investigation_start_notice"
    if re.search(r"справк\w*\s+на\s+осужденн", header):
        return "criminal_record"
    if re.search(r"заявлени\w*\s+(?:потерпевш|от\s+потерпевш)", header) or \
       (re.search(r"начальнику\s+уп", header) and "прошу" in header):
        return "victim_statement"
    if "специальные учёты" in tl or "специальные учеты" in tl or \
       "алфавитным учетным карточкам" in tl:
        return "special_registry"
    if "регистр недвижимости" in tl:
        return "police_db_record"
    if re.search(r"(?:статус|фамилия|имя|отчество|дата рождения).{0,5}(?:статус|фамилия|имя|отчество|дата рождения)", header):
        return "police_db_record"

    # --- Общие типы (fallback) ---
    if ("формат" in tl and "судопроизводства" in tl) or "электронного формата" in tl:
        return "format_statement"
    if "фототаблица" in tl or "фото №" in tl:
        return "phototable_embedded"
    if re.search(r"постановлени[ея]?\b", header) and "постановил" in tl:
        return "decree"

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
# TEXT CLEANING
# ==========================================================================

def clean_ocr_artifacts(text: str) -> str:
    """Clean OCR artifacts and formatting issues."""
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


def clean_boilerplate(text: str, doc_type: str = "other") -> str:
    """Remove procedural boilerplate blocks."""
    patterns = list(_BP_GENERAL)
    if doc_type in _INTERROGATION_TYPES:
        patterns.extend(_BP_INTERROGATION)

    cleaned = text
    for pattern in patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.DOTALL | re.IGNORECASE)
    # Normalize resulting whitespace
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = "\n".join(line.rstrip() for line in cleaned.split("\n"))
    return cleaned.strip()


def full_clean(text: str, doc_type: str = "other") -> str:
    """Full cleaning pipeline: OCR artifacts + boilerplate removal."""
    text = clean_ocr_artifacts(text)
    text = clean_boilerplate(text, doc_type=doc_type)
    return text


# ==========================================================================
# FIO DEDUPLICATION (Levenshtein-based)
# ==========================================================================

def _normalize_fio_key(fio: str) -> str:
    """Create normalized key for FIO comparison."""
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
        if fam1[:5] == fam2[:5] and name1[:3] == name2[:3]:
            return True
        fam_dist = _levenshtein(fam1[:6], fam2[:6])
        name_dist = _levenshtein(name1[:4], name2[:4])
        if fam_dist <= 2 and name_dist <= 1:
            return True
    return False


def deduplicate_fio(fio_collection) -> set:
    """Deduplicate FIO set accounting for OCR errors, declensions, and Kazakh letters."""
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
# DATE NORMALIZATION
# ==========================================================================

_MONTHS_RU = {
    "января": "01", "февраля": "02", "марта": "03", "апреля": "04",
    "мая": "05", "июня": "06", "июля": "07", "августа": "08",
    "сентября": "09", "октября": "10", "ноября": "11", "декабря": "12",
}

_MONTHS_KK = {
    "қаңтар": "01", "ақпан": "02", "наурыз": "03", "сәуір": "04",
    "мамыр": "05", "маусым": "06", "шілде": "07", "тамыз": "08",
    "қыркүйек": "09", "қазан": "10", "қараша": "11", "желтоқсан": "12",
}


def _normalize_date_ru(day: str, month_name: str, year: str) -> str:
    m = _MONTHS_RU.get(month_name.lower())
    if not m:
        return ""
    return f"{int(day):02d}.{m}.{year}"


def _normalize_date_kk(day: str, month_name: str, year: str) -> str:
    m = _MONTHS_KK.get(month_name.lower())
    if not m:
        return ""
    return f"{int(day):02d}.{m}.{year}"


def _extract_document_date(text: str) -> str:
    """Extract the main document date (first occurrence in header area)."""
    header = text[:500]

    m = re.search(EXTRACTION_PATTERNS["dates_text_ru"], header)
    if m:
        return _normalize_date_ru(m.group(1), m.group(2), m.group(3))

    m = re.search(EXTRACTION_PATTERNS["dates_text_kk"], header)
    if m:
        return _normalize_date_kk(m.group(2), m.group(3), m.group(1))

    m = re.search(EXTRACTION_PATTERNS["dates_dot"], header)
    if m:
        return m.group(1)

    return ""


# ==========================================================================
# DATA EXTRACTION
# ==========================================================================

def extract_essential_data(text: str, doc_type: str, cleaned_text: str = None) -> Dict[str, Any]:
    """Extract key data from document text using regex patterns."""
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
    dates_raw = set(re.findall(EXTRACTION_PATTERNS["dates_dot"], text))
    for d, month_name, y in re.findall(EXTRACTION_PATTERNS["dates_text_ru"], text):
        normalized = _normalize_date_ru(d, month_name, y)
        if normalized:
            dates_raw.add(normalized)
    for y, d, month_name in re.findall(EXTRACTION_PATTERNS["dates_text_kk"], text):
        normalized = _normalize_date_kk(d, month_name, y)
        if normalized:
            dates_raw.add(normalized)
    if dates_raw:
        data["dates"] = sorted(dates_raw)

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

    # Document date
    doc_date = _extract_document_date(text)
    if doc_date:
        data["document_date"] = doc_date

    # Language detection
    lang = detect_language(text)
    if lang:
        data["lang"] = lang

    # Block metadata
    block_meta = DOC_BLOCK_META.get(doc_type)
    if block_meta:
        data["block"] = block_meta["block"]
        data["needed_for_kd"] = block_meta["kd"]
        data["needed_for_oa"] = block_meta["oa"]

    # Type-specific extraction
    if doc_type in _INTERROGATION_TYPES:
        data.update(_extract_protocol_data(text, ct))
    elif doc_type == "protocol":
        data.update(_extract_protocol_data(text, ct))
    elif doc_type in ("decree", "decree_measure_restraint", "decree_defense_provision",
                       "decree_electronic_format", "decree_term_extension",
                       "decree_recognize_suspect", "decree_recognize_victim",
                       "qualification_decree", "evidence_attachment",
                       "search_decree", "seizure_decree"):
        data.update(_extract_decree_data(ct))
    elif doc_type == "court_ruling":
        data.update(_extract_court_ruling_data(text))
    elif doc_type == "detention_notice":
        data.update(_extract_detention_data(text))
    elif doc_type in ("seizure_protocol", "search_protocol", "experiment_protocol",
                       "identification_protocol", "covert_actions_protocol"):
        data.update(_extract_protocol_data(text, ct))

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

    # Testimony extraction (from CLEANED text)
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
    """Extract court ruling data."""
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
    """Extract detention notice data."""
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
# CONTENT-BASED FILENAME GENERATION
# ==========================================================================

def generate_content_filename(doc_type: str, essential_data: Dict) -> str:
    """Generate meaningful filename based on document type and extracted data.

    Examples:
        interrogation_suspect + {person_name: "Терехин Данил Сергеевич"} → "Допрос_подозреваемого_Терехин_Д.С."
        expertise + {document_date: "14.03.2025"} → "Заключение_эксперта_14.03.2025"
        decree + {} → "Постановление"
    """
    base = DOC_TYPE_NAMES.get(doc_type, "Иной документ")

    # Add person name if available (abbreviated: Фамилия И.О.)
    person = essential_data.get("person_name", "")
    if not person and essential_data.get("fio"):
        fio_full = essential_data["fio"][0]
        parts = fio_full.split()
        if len(parts) >= 2:
            person = f"{parts[0]} {parts[1][0]}."
            if len(parts) >= 3:
                person += f"{parts[2][0]}."

    # Or add document date
    date = essential_data.get("document_date", "")

    # Build name
    name = base
    if person:
        name += f"_{person}"
    elif date:
        name += f"_{date}"

    # Sanitize for filesystem
    name = re.sub(r'[<>:"/\\|?*]', '', name)
    name = re.sub(r'\s+', '_', name)
    name = re.sub(r'_+', '_', name)
    name = name.strip('_')

    return name


# ==========================================================================
# MARKDOWN GENERATION
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


def generate_markdown(doc_info: Dict, cleaned_text: str, essential_data: Dict) -> str:
    """Generate Markdown document for a single processed file."""
    lines = []
    type_name = DOC_TYPE_NAMES.get(doc_info["type"], doc_info["type"])
    lines.append(f"# {type_name}")
    lines.append("")

    lines.append("## Метаданные")
    lines.append(f"- **Файл:** `{doc_info['filename']}`")
    lines.append(f"- **Тип:** {type_name}")
    if doc_info.get("lang"):
        lines.append(f"- **Язык:** {LANG_NAMES.get(doc_info['lang'], doc_info['lang'])}")
    if doc_info.get("case_number"):
        lines.append(f"- **Номер дела ЕРДР:** №{doc_info['case_number']}")
    if doc_info.get("court_date"):
        lines.append(f"- **Дата судебного заседания:** {doc_info['court_date']}")
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
# API FUNCTION
# ==========================================================================

def process_raw_text_for_api(file_name: str, raw_text: str) -> Dict[str, Any]:
    """Process raw text: classification + cleaning + extraction.

    Args:
        file_name: Original filename (for filename-based classification).
        raw_text: Raw extracted text.

    Returns:
        Dict with cleaned_text, doc_type, content_filename, essential_data, lang.
    """
    doc_info = classify_by_filename(file_name)
    if doc_info["type"] == "other" and raw_text:
        doc_info["type"] = classify_other_by_content(raw_text)

    if not doc_info["lang"]:
        doc_info["lang"] = detect_language(raw_text)

    cleaned = full_clean(raw_text, doc_type=doc_info["type"])
    essential = extract_essential_data(raw_text, doc_info["type"], cleaned)
    content_name = generate_content_filename(doc_info["type"], essential)

    return {
        "cleaned_text": cleaned,
        "doc_type": doc_info["type"],
        "doc_type_name": DOC_TYPE_NAMES.get(doc_info["type"], doc_info["type"]),
        "content_filename": content_name,
        "essential_data": essential,
        "lang": doc_info.get("lang", ""),
        "doc_info": doc_info,
    }


# ==========================================================================
# CLI MAIN
# ==========================================================================

def main():
    """Process *_raw.txt files → *_cleaned.txt with content-based naming."""
    input_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(input_dir, "cleaned_texts")
    os.makedirs(output_dir, exist_ok=True)

    raw_files = sorted(
        f for f in os.listdir(input_dir)
        if f.endswith("_raw.txt")
    )

    if not raw_files:
        print(f"Файлы *_raw.txt не найдены в {input_dir}")
        sys.exit(1)

    print(f"Найдено {len(raw_files)} файлов *_raw.txt")
    print(f"Результаты: {output_dir}")
    print()

    all_docs = []
    skipped_docs = []
    name_counter = defaultdict(int)

    for filename in raw_files:
        with open(os.path.join(input_dir, filename), "r", encoding="utf-8") as f:
            raw_text = f.read()

        # Restore original filename (remove _raw.txt suffix)
        original_name = filename.replace("_raw.txt", "")

        # 1. Classification by filename
        doc_info = classify_by_filename(original_name + ".pdf")

        # Skip by file type
        if doc_info["type"] in SKIP_FILE_TYPES:
            skipped_docs.append({"type": doc_info["type"], "filename": filename})
            print(f"  {filename} → ПРОПУЩЕН ({doc_info['type']})")
            continue

        # 2. Classification by content (if type not determined)
        if doc_info["type"] == "other":
            doc_info["type"] = classify_other_by_content(raw_text)

        if doc_info["type"] in SKIP_OTHER_SUBTYPES:
            skipped_docs.append({"type": doc_info["type"], "filename": filename})
            print(f"  {filename} → ПРОПУЩЕН ({doc_info['type']})")
            continue

        # 3. Language detection
        if not doc_info["lang"]:
            doc_info["lang"] = detect_language(raw_text)

        # 4. Cleaning
        cleaned = full_clean(raw_text, doc_type=doc_info["type"])

        # 5. Data extraction
        essential = extract_essential_data(raw_text, doc_info["type"], cleaned)

        # 6. Generate content-based filename
        content_name = generate_content_filename(doc_info["type"], essential)

        # Handle duplicate names
        name_counter[content_name] += 1
        if name_counter[content_name] > 1:
            content_name += f"_{name_counter[content_name]}"

        # 7. Save cleaned text
        out_path = os.path.join(output_dir, f"{content_name}_cleaned.txt")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(cleaned)

        type_name = DOC_TYPE_NAMES.get(doc_info["type"], doc_info["type"])
        print(f"  {filename} → {content_name}_cleaned.txt ({type_name})")

        all_docs.append({"info": doc_info, "data": essential})

    print()
    print("=" * 60)
    print(f"Обработано: {len(all_docs)} документов")
    print(f"Пропущено:  {len(skipped_docs)}")
    print(f"Результаты: {output_dir}")


if __name__ == "__main__":
    main()
