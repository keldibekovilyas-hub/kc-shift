# -*- coding: utf-8 -*-
"""P1-2 · Единая реализация «дня по Алматы». ОДНА функция на весь проект (инвариант §0.15-логика):
panel_server, fetch_* и build_* импортируют отсюда, второй реализации нет.

Битрикс отдаёт DATE_CREATE в Москве (+03:00). КЦ и записи считаем по Алматы (+05:00): день начинается
на 2 часа раньше, поэтому лид 25.07 23:12 МСК = 26.07 01:12 Алматы → это уже 26 июля.

Обрабатывает оба формата:
  • полная ISO со смещением  «2026-07-25T23:12:00+03:00»  (так хранит panel_server.fetch_leads)
  • наивная строка без смещения «2026-07-25T23:12»          (так хранит fetch_attr: DATE_CREATE[:16], МСК)
Наивную строку трактуем как Москву (+03) — иначе astimezone взял бы локальный пояс машины.
"""
import datetime

ALA = datetime.timezone(datetime.timedelta(hours=5))   # Алматы, без DST
MSK = datetime.timezone(datetime.timedelta(hours=3))   # Москва (пояс Битрикса)


def _alma_dh(iso):
    """(date, hour) по Алматы. При ошибке разбора — (None, None)."""
    try:
        dt = datetime.datetime.fromisoformat(str(iso))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=MSK)                 # наивная строка из фетча — это Москва
        dt = dt.astimezone(ALA)
        return dt.date(), dt.hour
    except Exception:
        return None, None


def alma_day(iso):
    """datetime.date по Алматы (или None). Для группировки/фильтра по дню вместо DATE_CREATE[:10]."""
    return _alma_dh(iso)[0]


def alma_day_str(iso):
    """'YYYY-MM-DD' по Алматы (или '' ) — прямая замена rep['date'][:10]."""
    d = alma_day(iso)
    return d.isoformat() if d else ""


def msk_bounds(day_from, day_to):
    """P1-2 · Границы для фильтра Битрикса (МСК) под ЗАПРОШЕННЫЕ АЛМАТИНСКИЕ сутки.

    Алматинский день начинается на 2 часа раньше московского, поэтому окно сдвигается назад:
        20–26 июля по Алматы  →  19.07 22:00 … 26.07 22:00 по Москве.
    Без сдвига фетч не забирал лиды 00:00–02:00 по Алматы (они лежат в предыдущих сутках МСК),
    а build_* потом группировали их по Алматы — день недосчитывался, и сверка «панель против файла»
    давала ложное расхождение.

    day_from/day_to — 'YYYY-MM-DD' (включительно). Возврат — две строки ISO со смещением +03:00
    для filter[>=DATE_CREATE] и filter[<DATE_CREATE].
    """
    d0 = datetime.date.fromisoformat(str(day_from)[:10])
    d1 = datetime.date.fromisoformat(str(day_to)[:10])
    start = datetime.datetime.combine(d0, datetime.time(0), ALA).astimezone(MSK)
    end = datetime.datetime.combine(d1 + datetime.timedelta(days=1), datetime.time(0), ALA).astimezone(MSK)
    fmt = "%Y-%m-%dT%H:%M:%S+03:00"
    return start.strftime(fmt), end.strftime(fmt)
