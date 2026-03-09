import re
from collections import defaultdict
from datetime import datetime


def _normalize_fio_key(fio):
    """Создаёт нормализованный ключ для сравнения OCR-дублей ФИО."""
    trans = str.maketrans("ӘәҒғҚқҢңӨөҰұҮүҺһІі", "ААГгКкНнООУуУуХхИи")
    key = fio.translate(trans).lower()
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
        if fam1[:5] == fam2[:5] and name1[:3] == name2[:3]:
            return True
        fam_dist = _levenshtein(fam1[:6], fam2[:6])
        name_dist = _levenshtein(name1[:4], name2[:4])
        if fam_dist <= 2 and name_dist <= 1:
            return True
    return False


def _deduplicate_fio(fio_collection):
    """Дедупликация ФИО с учётом OCR-ошибок."""
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
            s = 0
            s += fio_counts.get(v, 1) * 20
            parts = v.split()
            if parts and re.search(r"(?:ов|ин|ев|ий|ер[ьт]|ко|ук|юк|ен)$", parts[0]):
                s += 10
            if parts and re.search(r"(?:ова|ову|овым|овою|ину|иным|иною|ому|ому)$", parts[0]):
                s -= 5
            if not re.search(r"[ӘәҒғҚқҢңӨөҰұҮүҺһІі]", v):
                s += 5
            s += len(v) / 100
            return s

        best = max(variants, key=score)
        result.add(best)
    return result


def _ts_to_date(ts_str):
    if not ts_str:
        return ""
    try:
        return datetime.fromtimestamp(int(ts_str) / 1000).strftime("%d.%m.%Y")
    except (ValueError, OSError):
        return ""


def generate_case_summary(all_docs, doc_type_names):
    """Генерирует сводную справку по делу из обработанных документов."""
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

        lines.append("### Общие сведения")
        if all_articles:
            lines.append(f"- **Квалификация:** {', '.join(sorted(all_articles))}")
        if all_fio:
            deduped_fio = _deduplicate_fio(fio_counter)
            lines.append("- **Участники:**")
            for f in sorted(deduped_fio):
                lines.append(f"  - {f}")
        if all_iin:
            lines.append(f"- **ИИН:** {', '.join(sorted(all_iin))}")
        if all_amounts:
            lines.append(
                f"- **Суммы ущерба:** {', '.join(sorted(all_amounts, key=lambda x: int(x.replace(' ', '').replace('тенге', '').strip()) if x.replace(' ', '').replace('тенге', '').strip().isdigit() else 0))}"
            )
        if all_addresses:
            clean_addrs = set()
            for addr in all_addresses:
                addr = addr.strip()
                if not re.search(r"(?:Кокшетау|Астана|Алматы|Караганда)", addr, re.IGNORECASE):
                    continue
                addr = re.sub(r"\s+", " ", addr)
                addr = re.sub(r"г\s*\.?\s*(?=Кокшетау|Астана|Алматы|Караганда)", "г.", addr)
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

        if reports:
            lines.append("### Первичная информация")
            for doc in sorted(reports, key=lambda d: d["info"]["timestamp"] or ""):
                data = doc["data"]
                info = doc["info"]
                date_str = _ts_to_date(info["timestamp"])
                lines.append(f"**{doc_type_names.get(info['type'], info['type'])}** ({date_str})")
                if data.get("description"):
                    lines.append(f"> {data['description'][:500]}")
                lines.append("")

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

        if detentions:
            lines.append("### Задержание")
            seen_detentions = set()
            for doc in detentions:
                data = doc["data"]
                det_key = (data.get("detention_date", ""), data.get("detention_time", ""))
                fio_list = data.get("fio", [])
                fio_dedup = list(_deduplicate_fio(set(fio_list))) if fio_list else []
                person = fio_dedup[0] if fio_dedup else "?"

                entry_key = (det_key[0], person)
                if entry_key in seen_detentions:
                    continue
                seen_detentions.add(entry_key)

                date_str = data.get("detention_date", "?")
                time_str = data.get("detention_time", "?")
                loc = data.get("detention_location", "")
                if loc and not re.search(r"(?:УП|ИВС|изолятор|Кокшетау|полиц)", loc, re.IGNORECASE):
                    loc = ""

                lines.append(f"- **{person}**: {date_str}, {time_str}" + (f" — {loc}" if loc else ""))
            lines.append("")

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
