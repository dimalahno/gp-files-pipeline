from collections import defaultdict
from datetime import datetime
from typing import Any

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

def ts_to_date(ts_str):
    if not ts_str:
        return ""
    try:
        return datetime.fromtimestamp(int(ts_str) / 1000).strftime("%d.%m.%Y")
    except (ValueError, OSError):
        return ""


def generate_index_document(all_docs: list[Any], skipped_docs: list[Any]) -> str:
    """Генерирует индекс обработанных документов."""
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

        date_str = info.get("court_date", "") or ts_to_date(info["timestamp"])
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

        lines.append(
            f"| {i} | [{md_name}](documents/{md_name}) | {type_name} | {case_short} | {date_str} | {fio} | {articles} | {method} |"
        )

    lines.append("")
    return "\n".join(lines)
