# -*- coding: utf-8 -*-
"""adjoin · сшивка лид↔объявление ПО ОТПЕЧАТКУ МЕТКИ (замена эвристике «самый длинный ключ»).

ПРИНЦИП. Площадка кладёт в ссылку объявления ШАБЛОН: часть значений — литералы, часть — макросы
(`__CAMPAIGN_ID__` у TikTok, `{{ad.name}}` у Facebook, `{campaignid}` у Google). При клике площадка
подставляет макросы, и в CRM приезжает уже РАЗРЕШЁННЫЙ набор utm. Значит для сшивки надо
восстановить, какой набор utm получит лид с каждого объявления («отпечаток»), и сравнивать
НАБОРЫ ЦЕЛИКОМ, а не искать отдельные ключи подстрокой.

Почему это важно. Прежний движок брал ОДИН «самый длинный уникальный ключ» из каждого utm-поля
по отдельности. Если подрядчик скопировал кампанию и utm_campaign совпал у двух кампаний, ключ
объявлялся неуникальным и лид уходил на уровень кабинета — хотя пара (utm_campaign + utm_term)
указывает ровно на одно объявление. На Chill Traffic за 1–31 июля так «терялось» 251 лид из 559.

ГАРАНТИЯ. Не сшивается только то, у чего метки нет или она дословно одинакова у нескольких
объявлений. Оба случая возвращаются с явной причиной, а не молча.

Модуль без побочных эффектов: только чтение файлов, никаких запросов на запись.
"""
import os, re, csv, io, json, html, urllib.parse
from collections import defaultdict

UTM = ("utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term")
WILD = "\x00WILD"          # макрос, значение которого мы не знаем — поле не участвует в сравнении

# Макрос → атрибут объявления, которым площадка его заменит.
MACROS = {
    # ВНИМАНИЕ на TikTok: AID — это ГРУППА объявлений (ad group), CID — САМО объявление (creative).
    # Интуиция «AID = ad id» здесь неверна и стоила 90% сшивки i-con: лид с utm_content=__AID_NAME__
    # приносит имя ГРУППЫ, а мы сравнивали его с именем объявления и получали ноль совпадений.
    "TikTok": {"__campaign_id__": "campaign_id", "__campaign_name__": "campaign_name",
               "__aid__": "adset_id", "__aid_name__": "adset_name",
               "__cid__": "ad_id",
               "__adgroup_id__": "adset_id", "__adgroup_name__": "adset_name", "__adname__": "ad_name"},
    "Facebook": {"{{campaign.id}}": "campaign_id", "{{campaign.name}}": "campaign_name",
                 "{{adset.id}}": "adset_id", "{{adset.name}}": "adset_name",
                 "{{ad.id}}": "ad_id", "{{ad.name}}": "ad_name"},
    "Google": {"{campaignid}": "campaign_id", "{adgroupid}": "adset_id", "{creative}": "ad_id",
               "{campaign}": "campaign_name", "{adgroup}": "adset_name"},
}
MACRO_RE = re.compile(r"(__[a-z0-9_]+__|\{\{[^}]+\}\}|\{[a-z_]+\})", re.I)


def norm(v):
    """Единая нормализация значения метки: url-decode, html-entities, регистр, пробелы.
    В выгрузке кабинета «/» приезжает как %2F, в Битриксе — как «/»; «»» — как &raquo;."""
    s = str(v if v is not None else "")
    if "%" in s:
        try: s = urllib.parse.unquote(s)
        except Exception: pass
    if "&" in s:
        s = html.unescape(s)
    return re.sub(r"\s+", " ", s.strip().lower())


def resolve(value, platform, ent):
    """Значение поля метки после подстановки макросов площадкой. Неизвестный макрос → WILD."""
    v = str(value or "")
    if not v:
        return ""
    table = MACROS.get(platform, {})
    unknown = [False]

    def sub(m):
        key = m.group(0).lower()
        attr = table.get(key)
        if attr and ent.get(attr):
            return str(ent[attr])
        unknown[0] = True
        return m.group(0)

    out = MACRO_RE.sub(sub, v)
    return WILD if unknown[0] else norm(out)


def fingerprint(url, platform, ent, extra=""):
    """Отпечаток объявления: какие utm получит лид, кликнувший по этой ссылке.
    url — конечная ссылка объявления; extra — шаблон отслеживания/суффикс (Google), если есть."""
    q = {}
    for src in (url, extra):
        s = str(src or "")
        if not s:
            continue
        if "utm" in s and "?" not in s:
            s = "http://x/?" + s.lstrip("&?")
        try:
            parsed = urllib.parse.parse_qs(urllib.parse.urlparse(s).query, keep_blank_values=True)
        except Exception:
            continue
        for k, vals in parsed.items():
            if k.lower() in UTM and vals and vals[0]:
                q.setdefault(k.lower(), vals[0])
    fp = {f: resolve(q[f], platform, ent) for f in UTM if f in q}
    # Какие поля привязаны к ИМЕНИ объекта ({{campaign.name}}, __aid_name__, {campaign} …).
    # Facebook запекает такую подстановку в ссылку при создании объявления: переименовали
    # кампанию — лиды продолжают нести старое имя. Сравнивать это поле как улику «против» нельзя,
    # match() учитывает это. Кортеж, а не словарь: отпечатки кладут в set() как tuple(items()).
    table = MACROS.get(platform, {})
    bound = tuple(sorted(f for f in fp if any(table.get(m.lower(), "").endswith("_name")
                                                for m in MACRO_RE.findall(str(q[f])))))
    if bound:
        fp["_bind"] = bound
    return fp


def lead_vector(lead):
    return {f: norm(lead.get(f)) for f in UTM if norm(lead.get(f))}


def match(ads, lead):
    """Кандидаты = объявления, у которых ни одно сопоставимое поле не противоречит метке лида.
    Сопоставимое = у объявления поле известно (не WILD, не пусто) И у лида оно заполнено.
    Побеждает набор с НАИБОЛЬШИМ числом совпавших полей: отпечаток из трёх полей строго
    точнее отпечатка из одного, это не догадка, а более сильное свидетельство.
    Возвращает (список_кандидатов, сколько_полей_совпало)."""
    lv = lead_vector(lead)
    vals = set(lv.values())
    best, best_n, best_score = [], 0, (0, 0)
    for a in ads:
        fp = a["fp"]
        # Железная привязка: площадка подставила в метку РЕАЛЬНЫЙ id объявления ({{ad.id}}, __CID__),
        # и он дословно есть у лида. Сильнее любого отпечатка — id не переименовывают.
        aid = norm(a.get("ad_id"))
        if aid and len(aid) >= 10 and aid in vals:
            score = (99, 0)
            if score > best_score:
                best, best_n, best_score = [a], 3, score
            elif score == best_score:
                best.append(a)
            continue
        if "_names" in fp:
            # Отпечаток по именам (объявление без url_tags — лид-формы и кабинеты без шаблона).
            # Имя КАМПАНИИ обязано найтись среди значений метки — иначе это чужой лид;
            # имена группы и объявления добавляют точности и доводят лид до конкретного креатива.
            nm = fp["_names"]
            if nm.get("campaign") not in vals:
                continue
            hit = 1 + sum(1 for k in ("adset", "ad") if nm.get(k) and nm[k] in vals)
            if hit > best_n:
                best, best_n = [a], hit
            elif hit == best_n:
                best.append(a)
            continue
        hit = 0; bad = False; renamed = 0
        for f, v in fp.items():
            if f.startswith("_") or v == WILD or v == "":
                continue
            if f not in lv:
                continue                      # лид это поле не принёс — не улика ни за, ни против
            if lv[f] == v:
                hit += 1
            elif f in fp.get("_bind", ()):
                # поле подставлено из ИМЕНИ объекта, а имя после клика могли сменить: это не
                # противоречие, а переименование — при условии, что остальное сходится
                renamed += 1
            else:
                bad = True; break
        if bad or hit == 0:
            continue
        score = (hit, -renamed)               # точное совпадение важнее «совпало, если переименовали»
        if score > best_score:
            best, best_n, best_score = [a], hit, score
        elif score == best_score:
            best.append(a)
    if not best and vals:
        # ВЕТО убило всех кандидатов. Запасной путь — по ТЕКУЩИМ ИМЕНАМ объектов: если значения
        # метки лида дословно равны имени кампании (обязательно), группы и объявления, лид кликнул
        # по этому объекту, когда у него был другой шаблон меток. Кейс Amer_ATA3_EN 09.2026: шаблон
        # сменили на ходу (имя кампании переехало из utm_campaign в utm_source), и 79 лидов с
        # «старыми» метками уходили в «не разложено» при живых объявлениях в кабинете.
        nb, nb_n = [], 0
        for a in ads:
            if norm(a.get("campaign")) not in vals:
                continue
            hit = 1 + sum(1 for k in ("adset", "ad") if norm(a.get(k)) and norm(a.get(k)) in vals)
            if hit > nb_n:
                nb, nb_n = [a], hit
            elif hit == nb_n:
                nb.append(a)
        if nb:
            return nb, nb_n
    if not best and lv.get("utm_campaign"):
        # имя кампании совпало по отпечатку, но объявление не определить: уровень КАМПАНИИ,
        # а не «не разложено». Кейс: __CID_NAME__/переименования.
        camp = [a for a in ads if a["fp"].get("utm_campaign") not in (None, "", WILD)
                and a["fp"]["utm_campaign"] == lv["utm_campaign"]]
        if camp:
            return camp, 1
    return best, best_n


def level_of(cands):
    """До какого уровня метка довела лид."""
    if not cands:
        return "нет"
    if len(cands) == 1:
        return "объявление"
    if len({(c["campaign"], c["adset"]) for c in cands}) == 1:
        return "группа"
    if len({c["campaign"] for c in cands}) == 1:
        return "кампания"
    if len({c["cab"] for c in cands}) == 1:
        return "кабинет"
    return "несколько кабинетов"


def why_unmatched(ads, lead):
    """Причина, по которой лид не сшился, — словами, а не пустой клеткой."""
    lv = lead_vector(lead)
    if not lv:
        return "у лида нет ни одной utm-метки"
    if not any(a["fp"] for a in ads):
        return "ни у одного объявления кабинета нет utm в ссылке"
    for f in ("utm_campaign", "utm_term", "utm_content"):
        if f in lv and any(a["fp"].get(f) not in (None, "", WILD) for a in ads):
            same = [a for a in ads if a["fp"].get(f) == lv[f]]
            if same:
                bad = sorted({g for a in same for g, v in a["fp"].items() if v not in (None, "", WILD) and g in lv and lv[g] != v})
                return "ВЕТО: %s=%s совпало у %d объявл., но противоречит %s" % (f, lv[f][:40], len(same), ",".join(bad) or "?")
            return "метка «%s=%s» не встречается ни в одном объявлении периода" % (f, lv[f][:60])
    return "поля метки лида не пересекаются с полями меток объявлений"


# ════════════════════ ЗАГРУЗЧИКИ ВЫГРУЗОК ════════════════════
def _num(x):
    s = str(x if x is not None else "").replace("\xa0", "").replace(" ", "").replace(",", ".")
    try: return float(s)
    except Exception: return 0.0


def _is_total(cell):
    s = str(cell if cell is not None else "").strip().lower()
    return any(w in s for w in ("total", "итого", "всего"))


def _col(hdr, *names):
    low = [str(h or "").replace("\n", " ").strip().lower() for h in hdr]
    for nm in names:
        for i, h in enumerate(low):
            if h == nm.lower(): return i
    for nm in names:
        for i, h in enumerate(low):
            if nm.lower() in h: return i
    return None


def load_tiktok(path, cab=None, contr=None):
    """TikTok Campaign Report на уровне объявлений. Итоговая строка вычитается.

    Кабинет отдаёт то xlsx (кнопка Export), то csv, шапку — то русскую, то английскую;
    сегмент «По дням» (By Day) присутствует не всегда. Всё это читаем здесь, второй разбор
    заводить нельзя: именно расхождение двух реализаций однажды спрятало недельный расход.
    Строкам с сегментом дня проставляем "day"; имя аккаунта из колонки кладём в "cab_col"
    (само "cab" остаётся выведенным из имени файла — на него завязаны отчёты по кабинетам)."""
    if str(path).lower().endswith((".xlsx", ".xlsm")):
        import openpyxl
        wb = openpyxl.load_workbook(path, data_only=True)  # read_only ломает размерность этих файлов
        rows = list(wb[wb.sheetnames[0]].iter_rows(values_only=True))
    else:
        rows = list(csv.reader(io.open(path, encoding="utf-8-sig")))
    hdr = [str(h or "").replace("）", ")") for h in rows[0]]
    c = lambda *n: _col(hdr, *n)
    i_ad, i_ag, i_cm = c("Название рекламы", "Ad name"), c("Название группы объявлений", "Ad group name"), c("Название кампании", "Campaign name")
    # ссылка УРОВНЯ ОБЪЯВЛЕНИЯ: в выгрузке есть ещё «Website URL» уровня группы, обычно пустая;
    # взять её — потерять метку, и лиды не пришьются к объявлению (так было 1–3.09.2026)
    i_url = c("URL-адрес веб-сайта (уровень объявления)", "Website URL (Ad level)", "Website URL")
    # «Spend» обязан стоять раньше «Cost»: точного «Cost» в английской шапке нет, и поиск по
    # подстроке цепляет «Cost per 1,000 people reached» — расход тогда занижается на треть.
    i_sp = c("Расходы", "Spend", "Cost")
    i_im, i_cl = c("Показы", "Impressions"), c("Клики (переход)", "Clicks (destination)")
    i_cv, i_res = c("Конверсии", "Conversions"), c("Результаты", "Results")
    i_cid, i_agid, i_adid = c("Идентификатор кампании"), c("Идентификатор группы объявлений"), c("Идентификатор рекламы")
    i_st = c("Первичный статус", "Primary status")
    i_day = c("По дням", "By Day")
    i_acc = c("Название аккаунта", "Account name")
    cab = cab or ("TikTok · " + re.sub(r"\s+", " ", re.sub(
        r"21449C|Campaign Report|\d{4}-\d\d-\d\d|to|\.xlsx|\(1\)", "", os.path.basename(path)).replace("_", " ")).strip(" -"))
    out, totals = [], 0
    g = lambda r, i: (r[i] if i is not None and i < len(r) else None)
    for r in rows[1:]:
        if not r or not any(r): continue
        if _is_total(g(r, i_ad)) or _is_total(g(r, i_acc)):   # «Total» кладут и в имя рекламы, и в аккаунт
            totals += 1; continue
        ent = {"campaign_id": str(g(r, i_cid) or ""), "adset_id": str(g(r, i_agid) or ""),
               "ad_id": str(g(r, i_adid) or ""), "campaign_name": str(g(r, i_cm) or ""),
               "adset_name": str(g(r, i_ag) or ""), "ad_name": str(g(r, i_ad) or "")}
        url = str(g(r, i_url) or "").strip()
        day = str(g(r, i_day) or "")[:10]
        out.append({"contr": contr, "platform": "TikTok", "cab": cab,
                    "cab_col": str(g(r, i_acc) or ""), "day": day if day[:4].isdigit() else "",
                    "campaign": ent["campaign_name"], "adset": ent["adset_name"], "ad": ent["ad_name"],
                    "campaign_id": ent["campaign_id"], "adset_id": ent["adset_id"], "ad_id": ent["ad_id"],
                    "spend": _num(g(r, i_sp)), "impr": _num(g(r, i_im)), "clicks": _num(g(r, i_cl)),
                    "plat_conv": _num(g(r, i_cv)), "results": _num(g(r, i_res)),
                    "status": str(g(r, i_st) or ""), "url": url if url != "-" else "", "video": "",
                    "fp": fingerprint(url if url != "-" else "", "TikTok", ent)})
    return out, totals


RU_MONTHS = {m: i + 1 for i, m in enumerate(
    ("янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"))}


def _one_day_period(head_txt):
    """Дата из шапки отчёта Google, если период в ней — ровно один день, иначе ''.

    Шапка выглядит как «3 сентября 2026 г. - 3 сентября 2026 г.» (или «01.09.2026 - 01.09.2026»)."""
    t = head_txt.replace(" ", " ").lower()
    ds = re.findall(r"(\d{1,2})\s+([а-я]{3})[а-я]*\s+(\d{4})", t)
    got = ["%s-%02d-%02d" % (y, RU_MONTHS[m], int(d)) for d, m, y in ds if m in RU_MONTHS]
    if not got:
        got = ["%s-%s-%s" % (y, m, d) for d, m, y in re.findall(r"(\d{2})\.(\d{2})\.(\d{4})", t)]
        got += re.findall(r"\d{4}-\d{2}-\d{2}", t)
    return got[0] if got and len(set(got)) == 1 else ""


def load_google(path, cab=None, contr=None):
    """Google Ads / YouTube «Отчёт об объявлениях» (csv/tsv). Шапка не в первой строке.

    Разделитель определяем сами: Google отдаёт то запятые, то ТАБЫ (при выгрузке «в Excel»).
    Прочитать tsv как csv — получить кашу: строки не бьются на колонки, расход выходит $0.00
    и весь отчёт молча оказывается пустым. Кодировка тоже пляшет: utf-8/utf-16/cp1251."""
    raw = None
    for enc in ("utf-8-sig", "utf-16", "cp1251"):
        try:
            raw = io.open(path, encoding=enc, errors="strict").read()
            break
        except Exception:
            raw = None
    if raw is None:
        raw = io.open(path, encoding="utf-8", errors="replace").read()
    head_txt = "\n".join(raw.splitlines()[:6])
    delim = max(("\t", ",", ";"), key=lambda d: head_txt.count(d))
    rows = list(csv.reader(io.StringIO(raw), delimiter=delim))
    hi = next((i for i, r in enumerate(rows[:10]) if any("Конечный URL" in str(x) or "Final URL" in str(x) for x in r)), 2)
    hdr = rows[hi]
    c = lambda *n: _col(hdr, *n)
    i_cm, i_ag, i_ad = c("Кампания", "Campaign"), c("Группа объявлений", "Ad group"), c("Название объявления", "Ad name")
    i_url, i_tt, i_sf = c("Конечный URL", "Final URL"), c("Шаблон отслеживания", "Tracking template"), c("Суффикс конечного URL", "Final URL suffix")
    # «Kлики» — не опечатка здесь: в выгрузке «Отчёт по дням» Google пишет колонку с латинской K,
    # и по-русски «Клики» её не находит — расход есть, а клики молча нули
    i_sp, i_im, i_cl = c("Расходы", "Cost"), c("Показы", "Impr"), c("Взаимодействия", "Клики", "Kлики", "Clicks")
    i_cv = c("Конверсии", "Conversions")
    i_st = c("Статус объявления", "Ad state")
    i_day = c("День", "Day")                   # есть только в выгрузках с сегментом «Время → День»
    # Идентификаторы сущностей — если заказчик добавил их в отчёт. Главный — id объявления:
    # у YouTube-лидов SP он лежит в utm_content дословно (подтверждено 28.09.2026 на 291 лиде Астаны),
    # и match() сшивает по нему «железно», минуя литералы в utm_campaign, по которым SP не сшить.
    i_cid, i_gid, i_aid = c("Идентификатор кампании", "Campaign ID"), c("Идентификатор группы объявлений", "Ad group ID"), c("Идентификатор объявления", "Ad ID")

    def _id(r, i):
        v = str(g(r, i) or "").strip()
        return v if re.fullmatch(r"\d{6,}", v) else ""
    # Ссылка на ролик. Берём колонку «Видео» — в ней ГОТОВЫЙ адрес YouTube.
    # «Идентификатор видео» брать нельзя: там id ассета Google Ads (97804461535),
    # а не 11-символьный id YouTube, и ссылка получилась бы битой.
    i_vid = c("Видео", "Video")
    i_vid_id = c("Идентификатор видео", "Video ID")
    # Выгрузка БЕЗ сегмента «Время → День» даты в строках не содержит — период стоит в шапке
    # («3 сентября 2026 г. - 3 сентября 2026 г.»). Если период — ровно один день, он и есть день
    # каждой строки; если период длиннее, дня у строк нет (размазывать расход по дням нельзя).
    hdr_day = "" if i_day is not None else _one_day_period(head_txt)
    # Сегмент «День» бывает не строками, а СТОЛБЦАМИ: «2026-09-01_Расходы», «2026-09-01_Показы», …
    # (так Google отдаёт, если сегмент положили в столбцы). Тогда колонки «День» нет, а c("Расходы")
    # подстрокой находит первую дату — и весь месяц молча превращается в один день (Астана 1–28.09).
    # Разворачиваем: каждая строка объявления → строка на каждую дату с её метриками.
    pivot = {}
    if i_day is None:
        for j, h in enumerate(hdr):
            m = re.match(r"(\d{4}-\d\d-\d\d)_(.+)$", str(h or "").strip())
            if m:
                pivot.setdefault(m.group(1), {})[m.group(2).strip().lower()] = j
    if pivot:
        i_sp = i_im = i_cl = i_cv = None
    cab = cab or ("Google · " + os.path.basename(path).rsplit(".", 1)[0])
    out, totals = [], 0
    g = lambda r, i: (r[i] if i is not None and i < len(r) else None)

    def _pick(cols, *names):
        for n in names:
            for k, j in cols.items():
                if n.lower() in k:
                    return j
        return None

    for r in rows[hi + 1:]:
        if not r or not any(r): continue
        if _is_total(r[0]):
            totals += 1; continue
        cm = str(g(r, i_cm) or "")
        if not cm: continue
        if pivot:
            for pday, cols in pivot.items():
                sp_v = _num(g(r, _pick(cols, "расход", "cost")))
                im_v = _num(g(r, _pick(cols, "показ", "impr")))
                if not sp_v and not im_v:
                    continue
                ent = {"campaign_name": cm, "adset_name": str(g(r, i_ag) or ""), "ad_name": str(g(r, i_ad) or ""),
                       "campaign_id": _id(r, i_cid), "adset_id": _id(r, i_gid), "ad_id": _id(r, i_aid)}
                url, tt, sf = str(g(r, i_url) or ""), str(g(r, i_tt) or ""), str(g(r, i_sf) or "")
                out.append({"contr": contr, "platform": "Google", "cab": cab,
                            "campaign": cm, "adset": ent["adset_name"], "ad": ent["ad_name"],
                            "campaign_id": ent["campaign_id"], "adset_id": ent["adset_id"], "ad_id": ent["ad_id"],
                            "spend": sp_v, "impr": im_v,
                            "clicks": _num(g(r, _pick(cols, "взаимод", "клик", "kлик", "click"))),
                            "plat_conv": _num(g(r, _pick(cols, "конверс", "conv"))), "results": 0.0,
                            "status": str(g(r, i_st) or ""), "url": url, "video": "", "day": pday,
                            "fp": fingerprint(url, "Google", ent, extra=tt + "&" + sf)})
            continue
        ent = {"campaign_name": cm, "adset_name": str(g(r, i_ag) or ""), "ad_name": str(g(r, i_ad) or ""),
               "campaign_id": _id(r, i_cid), "adset_id": _id(r, i_gid), "ad_id": _id(r, i_aid)}
        url, tt, sf = str(g(r, i_url) or ""), str(g(r, i_tt) or ""), str(g(r, i_sf) or "")
        # «--» у Google означает «пусто»; отдаём только рабочую ссылку, битую не отдаём
        vid = str(g(r, i_vid) or "").strip()
        if vid in ("--", "-", "—"):
            vid = ""
        if not vid.startswith("http"):
            vid_id = str(g(r, i_vid_id) or "").strip()
            vid = ("https://www.youtube.com/watch?v=" + vid_id
                   if re.fullmatch(r"[A-Za-z0-9_-]{11}", vid_id or "") else "")
        day = str(g(r, i_day) or "").strip()[:10] or hdr_day
        out.append({"contr": contr, "platform": "Google", "cab": cab,
                    "campaign": cm, "adset": ent["adset_name"], "ad": ent["ad_name"],
                    "campaign_id": ent["campaign_id"], "adset_id": ent["adset_id"], "ad_id": ent["ad_id"],
                    "spend": _num(g(r, i_sp)), "impr": _num(g(r, i_im)), "clicks": _num(g(r, i_cl)),
                    "plat_conv": _num(g(r, i_cv)), "results": 0.0, "status": str(g(r, i_st) or ""),
                    "url": url, "video": vid,
                    "day": day if re.fullmatch(r"\d{4}-\d\d-\d\d", day) else "",
                    "fp": fingerprint(url, "Google", ent, extra=tt + "&" + sf)})
    return out, totals


# Аудитория группы объектов → значение, которое приезжает в utm_content лида.
# Performance Max не даёт utm на уровень объекта: метка задаётся суффиксом URL кампании и
# различает только аудиторию. Поэтому таблица — по смыслу имени группы, а не по подстроке utm.
PMAX_AUDIENCE = [("родител", "interests_parents"), ("спорт", "interests_sport"),
                 ("офисн", "interests_office_workers"), ("темы поиска", "search_themes_spine"),
                 ("широк", "interests_no")]


def pmax_slug(group_name):
    g = (group_name or "").lower()
    for key, slug in PMAX_AUDIENCE:
        if key in g:
            return slug
    return ""


def load_google_pmax(path, campaign_utm, campaign_name=None, cab=None, contr=None):
    """Google Performance Max, «Отчет о группе объектов» (xlsx).

    У PMax НЕТ объявлений: то, что в интерфейсе зовётся объявлением, — это отдельный объект
    (заголовок, текст, картинка). Самый глубокий осмысленный уровень — ГРУППА ОБЪЕКТОВ,
    она же аудитория. Её и берём как «объявление» отчёта.

    Имени кампании в выгрузке нет — его передаём снаружи (campaign_utm = значение utm_campaign,
    которое кампания подставляет лидам через суффикс конечного URL)."""
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True)
    rows = list(wb[wb.sheetnames[0]].iter_rows(values_only=True))
    hi = next((i for i, r in enumerate(rows[:8])
               if any("группа объектов" in str(c or "").lower() for c in r)), 2)
    hdr = rows[hi]
    c = lambda *n: _col(hdr, *n)
    i_g, i_st = c("Группа объектов"), c("Статус группы объектов")
    i_cl, i_im, i_sp = c("Клики", "Kлики"), c("Показы"), c("Расходы", "Стоимость")
    i_cv = c("Конверсии")
    cab = cab or ("Google PMax · " + os.path.basename(path).rsplit(".", 1)[0])
    campaign_name = campaign_name or os.path.basename(path).rsplit(".", 1)[0]
    out, totals = [], 0
    g = lambda r, i: (r[i] if i is not None and i < len(r) else None)
    for r in rows[hi + 1:]:
        if not r:
            continue
        name = str(g(r, i_g) or "")
        if _is_total(r[0]) or _is_total(name) or not name:
            totals += 1
            continue
        slug = pmax_slug(name)
        out.append({"contr": contr, "platform": "Google", "cab": cab,
                    "campaign": campaign_name, "adset": name.split(" / ")[0].strip(),
                    "ad": "— группа объектов —", "campaign_id": "", "adset_id": "", "ad_id": "",
                    "spend": _num(g(r, i_sp)), "impr": _num(g(r, i_im)), "clicks": _num(g(r, i_cl)),
                    "plat_conv": _num(g(r, i_cv)), "results": 0.0,
                    "status": str(g(r, i_st) or ""), "url": name,
                    "fp": {"utm_campaign": norm(campaign_utm), "utm_content": slug} if slug
                          else {"utm_campaign": norm(campaign_utm)}})
    return out, totals


def is_pmax_report(path):
    """Отчёт о группе объектов? Отличается от обычного отчёта об объявлениях первой строкой."""
    if not path.lower().endswith((".xlsx", ".xls")):
        return False
    try:
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb[wb.sheetnames[0]]
        head = " ".join(str(c or "") for r in list(ws.iter_rows(values_only=True))[:4] for c in r).lower()
        wb.close()
        return "группе объектов" in head or "группа объектов" in head
    except Exception:
        return False


def fb_leadform_fp(ent):
    """Отпечаток для объявления-ЛИД-ФОРМЫ: у неё нет посадочной страницы, значит нет и ссылки,
    в которую можно положить utm. Метку пишет сама интеграция Facebook→Битрикс: в utm_campaign
    уезжает ИМЯ КАМПАНИИ, в utm_content — ИМЯ ОБЪЯВЛЕНИЯ (проверено на июле Мухтарбека:
    `Mukhtarbek_14.07.2026_Sustavy_Lead-form_Almaty_Video_acquisition` / `Mukhtarbek_Creative_1.5 Суставы`).

    Применять ТОЛЬКО когда обычный отпечаток ПУСТ (в ссылке и url_tags нет ни одного utm):
    иначе имена начнут конкурировать с настоящими метками и дадут ложные привязки. Ссылка у
    таких объявлений бывает (кнопка WhatsApp/лид-формы), но utm в ней нет.

    Сходимость на 20–26.07.2026, кабинет «Мухтарбек | EN | Шымкент»: 114 сделок из 114 находят
    и имя кампании, и имя объявления; пара целиком совпадает у 114 из 114."""
    fp = {}
    if ent.get("campaign_name"):
        fp["utm_campaign"] = norm(ent["campaign_name"])
    if ent.get("ad_name"):
        fp["utm_content"] = norm(ent["ad_name"])
    # Раскладка полей у разных интеграций РАЗНАЯ: Мухтарбек шлёт имя кампании в utm_campaign,
    # SP («Султан | EN | Астана») — в utm_medium, а в utm_campaign кладёт имя ГРУППЫ.
    # Поэтому рядом с жёстким отпечатком отдаём набор имён: match() ищет их в ЛЮБОМ utm-поле.
    names = {k: norm(ent[v]) for k, v in (("campaign", "campaign_name"),
                                          ("adset", "adset_name"), ("ad", "ad_name"))
             if ent.get(v)}
    if names.get("campaign"):
        fp["_names"] = names
    return fp


def load_fb_cache(path, contr_of=None):
    """FB ad-level из кэша выгрузки Graph API. url_tags, если он есть в кэше, даёт отпечаток;
    иначе отпечатком служат сами ID сущностей — лиды i-con приносят их в utm напрямую."""
    data = json.load(io.open(path, encoding="utf-8"))
    out = []
    for a in data:
        ent = {"campaign_id": str(a.get("cid") or ""), "adset_id": str(a.get("sid") or ""),
               "ad_id": str(a.get("aid") or ""), "campaign_name": a.get("campaign") or "",
               "adset_name": a.get("adset") or "", "ad_name": a.get("ad") or ""}
        tags = a.get("url_tags") or ""
        fp = fingerprint(tags, "Facebook", ent) if tags else {}
        if not fp:
            # шаблона нет — но лиды FB приносят голые ID сущностей; принимаем их как отпечаток
            fp = {"utm_campaign": norm(ent["campaign_id"]), "utm_term": norm(ent["ad_id"])}
        out.append({"contr": a.get("contr") if contr_of is None else contr_of(a),
                    "platform": "Facebook", "cab": a.get("cab") or "",
                    "campaign": ent["campaign_name"], "adset": ent["adset_name"], "ad": ent["ad_name"],
                    "campaign_id": ent["campaign_id"], "adset_id": ent["adset_id"], "ad_id": ent["ad_id"],
                    "spend": float(a.get("spend") or 0), "impr": float(a.get("impr") or 0),
                    "clicks": float(a.get("clicks") or 0), "plat_conv": float(a.get("pix") or 0),
                    "results": 0.0, "status": "", "url": tags, "fp": fp})
    return out


# ════════════════════ ЛИДЫ ИЗ БИТРИКСА ════════════════════
ENTRY = {1, 3, 100, 114}
DOJIM = 31
OP = {"booked": 4, "inwork": 3, "dojim": 2, "trash": 1}


# Причины брака. Живут здесь, а не в отдельном отчёте: список обязан совпадать со словами,
# по которым outcome() относит лид к браку, — иначе брак будет, а причина уедет в «Прочее».
REASONS = ["Др.город", "Не наш", "Дубль", "Некорр", "Случайно", "Зап.к другим",
           "Нет денег", "Не актуально", "Прочее"]


def reason(stage):
    n = (stage or "").lower()
    if "другой город" in n: return "Др.город"
    if "не наш" in n: return "Не наш"
    if "дубль" in n: return "Дубль"
    if "некорр" in n or "неккор" in n: return "Некорр"
    if "случайно" in n: return "Случайно"
    if "к друг" in n: return "Зап.к другим"
    if "нет денег" in n: return "Нет денег"
    if "не актуально" in n: return "Не актуально"
    return "Прочее"


def outcome(cat, stage):
    cat = int(cat or 0); n = (stage or "").lower()
    if cat == DOJIM: return "dojim"                       # дожим = проигрыш, не запись
    if cat not in ENTRY: return "booked"
    if any(w in n for w in ("записал", "запись", "финальн", "успешна", "пришёл", "пришел")): return "booked"
    if any(w in n for w in ("другой город", "не наш", "дубль", "случайно", "некорр", "к друг",
                            "нет денег", "не актуально")): return "trash"
    return "inwork"


def load_leads(path, keep):
    """Сделки → ЛЮДИ. Группируем по контакту ВСЕ карточки человека, а не только рекламные:
    исход берём по всем (иначе запись, оформленная второй карточкой или в дожиме, теряется),
    а метку — по самой ранней ПОДХОДЯЩЕЙ карточке (именно она привела человека).
    keep(deal) решает, наша ли это карточка; человек наш, если наша хотя бы одна."""
    alld = json.load(io.open(path, encoding="utf-8"))
    byc = defaultdict(list)
    for x in alld:
        byc[x.get("contact") or ("deal:" + str(x.get("id")))].append(x)
    leads, matched_deals = [], []
    for cid, cards in byc.items():
        mine = [c for c in cards if keep(c)]
        if not mine:
            continue
        matched_deals += mine
        rep = min(mine, key=lambda c: c.get("date") or "")
        o = max((outcome(c.get("cat"), c.get("stage")) for c in cards), key=lambda z: OP[z])
        leads.append({"contact": cid, "cards": len(cards), "own_cards": len(mine),
                      "date": rep.get("date") or "",
                      "booked": 1 if o == "booked" else 0, "outcome": o,
                      "utm_source": rep.get("utm_source"), "utm_medium": rep.get("utm_medium"),
                      "utm_campaign": rep.get("utm_campaign"), "utm_content": rep.get("utm_content"),
                      "utm_term": rep.get("utm_term"), "title": rep.get("title") or "",
                      "deal_ids": [c.get("id") for c in cards]})
    return leads, matched_deals


# ════════════════════ СШИВКА ════════════════════
def join(ads, leads, live_only=True):
    """Сшивает лиды с объявлениями.
    Шаг 1 — по объявлениям, крутившимся в периоде (расход или показы > 0). Копии прошлых кампаний
      носят те же метки и создавали бы ничьи там, где живое объявление ровно одно.
    Шаг 2 — если ни одно живое не подошло, пробуем по всем объявлениям кабинета: тогда лид
      пришёл по метке кампании, которая в периоде не крутилась (старая ссылка, отложенная заявка).
      Это не догадка: метка совпала дословно, просто открутки в периоде не было."""
    pool = [a for a in ads if (a["spend"] > 0 or a["impr"] > 0)] if live_only else list(ads)
    res = []
    for L in leads:
        cands, nfields = match(pool, L)
        stale = False
        if not cands and live_only:
            cands, nfields = match(ads, L)
            stale = bool(cands)
        lvl = level_of(cands)
        if stale and lvl != "нет":
            lvl += " (вне периода)"
        res.append({"lead": L, "cands": cands, "level": lvl, "fields": nfields, "stale": stale,
                    "why": why_unmatched(ads, L) if not cands else ""})
    return {"rows": res, "pool": pool, "dropped": len(ads) - len(pool)}
