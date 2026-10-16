# -*- coding: utf-8 -*-
"""Единый модуль атрибуции ExpertNeuro (P1-1, инвариант §0.15): подрядчик / город / площадка / исход.
БЕЗ молчаливых свалок: при неизвестном значении возвращаем «не определено» / None, а НЕ самый
частый вариант. Логика перенесена из authoritative.py; импортировать отсюда, не копировать.

Что изменено против прежних копий (и только это — методику §0.16 не трогаем):
  contractor(): `if hu(x): return "i-con"`  ->  `return UNDEF`   (i-con больше не мусоросборник)
  city_of():    хвост `or "Алматы"`          ->  None            (город не определён)
  plat():       хвост `return "Facebook"`    ->  UNDEF           (площадка не определена)
"""
import re

ENTRY = {1, 3, 100, 114}          # входные городские воронки
DOJIM = 31                        # дожим
CONTRS = ["i-con", "SP", "Chill Traffic", "Мухтарбек", "Алишер"]
CITYS = ["Алматы", "Астана", "Шымкент", "Тараз"]
PLATS = ["Facebook", "TikTok", "Google/YT"]
UNDEF = "не определено"           # есть UTM, но атрибуция не распознана
NOAD = "—"                        # нет UTM вообще = не реклама («Не засчитано»)
# приоритет при дедупе по контакту: распознанный подрядчик > не определено > не реклама
CP = {"i-con": 6, "SP": 6, "Chill Traffic": 6, "Мухтарбек": 6, "Алишер": 6, UNDEF: 2, NOAD: 1}
OP = {"booked": 4, "inwork": 3, "dojim": 2, "trash": 1}
BR = {"алмата": "Алматы", "алматы": "Алматы", "астана": "Астана", "шымкент": "Шымкент", "тараз": "Тараз"}


def dom(t):
    m = re.search(r"https?://([^/\s#]+)", t or "")
    return m.group(1).lower() if m else ""


def hu(x):
    return any(x.get(k) for k in ("utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term"))


def contractor(x):
    tl = (x.get("title") or "").lower(); dmn = dom(x.get("title"))
    # expertneuro.asia — домен Алишера (посадка /astana с 08.10.2026), но страница /threads-lead на нём —
    # форма тредс-менеджеров (с 12.10.2026): SOURCE_ID=WEB и адрес в заголовке, а это НЕ реклама.
    sd = (x.get("source_description") or "").lower()
    if "threads" in tl or "тредс" in tl or "threads-lead" in sd: return NOAD
    if "chill" in tl or "expert-neuro.kz" in tl or (x.get("utm_medium") or "").upper() == "CT" or "ct_ala" in (x.get("utm_campaign") or "").lower(): return "Chill Traffic"
    if "мухтарбек" in tl or "mukhtar" in (x.get("utm_campaign") or "").lower(): return "Мухтарбек"
    if (x.get("utm_medium") or "").lower() == "alisher" or "alisher" in (x.get("utm_campaign") or "").lower() or dmn == "expertneuro.asia": return "Алишер"
    # брендовый Google i-con (g_icon, expertneuro1.kz) до 03.09.2026 считался «не рекламой» (NOAD).
    # Решение заказчика 03.09.2026: это реклама i-con — за неё платят из их кабинета, учитывать как i-con.
    if dmn == "expertneuro1.kz": return "i-con"
    if dmn: return "SP"
    if hu(x): return UNDEF        # было "i-con" — мусоросборник убран (P1-1)
    return NOAD


def funnel_city(x):
    c = int(x.get("cat") or 0)
    if c == 1: return "Алматы"
    if c == 3: return "Астана"
    if c == 100: return "Шымкент"
    if c == 114: return "Тараз"
    return BR.get((x.get("branch") or "").strip().lower())


def origin_city(x):   # город из метки/лендинга (origin-first, §0.11) — ловит утёкших в чужую воронку
    s = " ".join([x.get("utm_source") or "", x.get("utm_campaign") or "", x.get("utm_medium") or "",
                  x.get("utm_content") or "", x.get("title") or ""]).lower()
    if "shym" in s or "шымкент" in s: return "Шымкент"
    if "taraz" in s or "_tar" in s or "тараз" in s: return "Тараз"
    if "astana" in s or "_ast" in s or "ast_" in s or "астана" in s: return "Астана"
    if "almaty" in s or "_alm" in s or "alm_" in s or "_ala" in s or "ala_" in s or "алматы" in s: return "Алматы"
    return None


def city_of(x):       # origin приоритетнее воронки; None = город не определён (было `or "Алматы"`)
    return origin_city(x) or funnel_city(x)


AD_CITY_PAT = [("Шымкент", ("шымкент", "shym")), ("Астана", ("астана", "astana", "_ast", "ast_")),
               ("Тараз", ("тараз", "taraz")), ("Алматы", ("алматы", "алмат", "almaty", "_alm", "alm_", "_ala"))]


def ad_city(cab, camp, adset, url):
    """Город СТРОКИ КАБИНЕТА (не лида): сначала ссылка/метка, затем имена кампании/группы, затем кабинет
    (origin-first, §0.11). Общая для всех построителей по кабинетам — второй копии не заводить (§0.15)."""
    for src in (url, camp, adset, cab):
        s = (src or "").lower()
        for city, keys in AD_CITY_PAT:
            if any(k in s for k in keys):
                return city
    return UNDEF


def plat(x):
    src = (x.get("utm_source") or "").lower(); m = (x.get("utm_medium") or "").lower()
    blob = " ".join([src, m, (x.get("utm_campaign") or "").lower(), (x.get("utm_content") or "").lower(), (x.get("utm_term") or "").lower()])
    if "tiktok" in src or "titktok" in src or "amer_tiktok" in src or re.search(r"(^|[ _-])tt([ _-]|$)", src): return "TikTok"
    if "google" in src or "youtube" in src: return "Google/YT"
    if "facebook" in src or "instagram" in src or "meta" in src or src.strip() in ("fb", "ig", "an"): return "Facebook"
    if "{{" in blob: return "Facebook"
    if m == "cpc" or "demand_gen" in blob or "pmax" in blob or "video_pack" in blob: return "Google/YT"
    if m in ("icon_adw", "dan", "amer_tiktok_1", "ct") or "ct_ala" in blob or "без названия" in blob or "tiktok" in blob: return "TikTok"
    if m in ("i-con2", "i-con4", "i-con7", "alisher") or "adk_" in blob or "_adname_" in blob or "grizh" in blob or "wide" in blob or "img_" in blob or "creo" in blob or "vrozsl" in blob: return "Facebook"
    return UNDEF                  # было "Facebook" — молчаливая свалка убрана (P1-1)


def outcome(cat, st):
    cat = int(cat or 0); n = (st or "").lower()
    if cat == DOJIM: return "dojim"
    if cat not in ENTRY: return "booked"
    if any(w in n for w in ["записал", "запись", "финальн", "успешна", "пришёл", "пришел"]): return "booked"
    if any(w in n for w in ["другой город", "не наш", "дубль", "случайно", "некорр", "к друг", "нет денег", "не актуально"]): return "trash"
    return "inwork"
