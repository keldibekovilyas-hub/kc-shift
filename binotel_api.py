# -*- coding: utf-8 -*-
"""Binotel: звонки за период. Одна точка для новых отчётов (раньше запрос жил копиями в пяти скриптах).

Только чтение: stats/list-of-calls-for-period. Ключи — BINOTEL_API_KEY / BINOTEL_API_SECRET из
токены/.env, в коде их нет. API отдаёт не больше суток за запрос, поэтому идём по дням.

Время звонка — unixtime; отдаём aware-datetime по Алматы (+05:00). Время Битрикса — Москва (+03:00):
сравнивать их можно только как aware-datetime, иначе всё поедет на 2 часа.

    from binotel_api import calls, norm_phone
    for c in calls("2026-09-01", "2026-09-14"):
        c["phone"], c["at"], c["outgoing"], c["answered"], c["employee"], c["billsec"]
"""
import os, io, re, json, time, datetime, urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
ALA = datetime.timezone(datetime.timedelta(hours=5))
_ENV = {}
for _p in (os.path.join(ROOT, "токены", ".env"), os.path.join(ROOT, "Control", "токены", ".env")):
    if os.path.exists(_p):
        for _line in io.open(_p, encoding="utf-8"):
            if "=" in _line and not _line.strip().startswith("#"):
                _k, _v = _line.strip().split("=", 1)
                _ENV.setdefault(_k.strip(), _v.strip().strip('"'))
KEY, SEC = (os.environ.get("BINOTEL_API_KEY") or _ENV.get("BINOTEL_API_KEY")), (os.environ.get("BINOTEL_API_SECRET") or _ENV.get("BINOTEL_API_SECRET"))


def norm_phone(p):
    """Телефон → последние 10 цифр (8XXX… и +7XXX… дают одно и то же). Пусто, если цифр меньше 10."""
    d = re.sub(r"\D", "", str(p or ""))
    return d[-10:] if len(d) >= 10 else ""


def _day(day):
    t0 = int(datetime.datetime.fromisoformat(day + "T00:00:00+05:00").timestamp())
    payload = {"key": KEY, "secret": SEC, "startTime": str(t0), "stopTime": str(t0 + 86399)}
    req = urllib.request.Request("https://api.binotel.com/api/4.0/stats/list-of-calls-for-period.json",
                                 data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    last = None
    for a in range(5):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                j = json.loads(r.read().decode())
            if j.get("status") != "error":
                return j.get("callDetails") or {}
            last = j.get("message")
        except Exception as e:
            last = repr(e)
        time.sleep(3 * (a + 1))
    # молча вернуть пустой день нельзя: «звонков не было» и «Binotel не ответил» — разные вещи
    raise RuntimeError("Binotel не отдал звонки за %s: %s" % (day, last))


def calls(day_from, day_to):
    """Все звонки с 00:00 day_from до 23:59 day_to по Алматы."""
    if not (KEY and SEC):
        raise RuntimeError("нет BINOTEL_API_KEY / BINOTEL_API_SECRET в токены/.env")
    out = []
    d, end = datetime.date.fromisoformat(day_from), datetime.date.fromisoformat(day_to)
    while d <= end:
        for cid, c in _day(d.isoformat()).items():
            emp = c.get("employeeData") or {}
            out.append({"id": c.get("generalCallID", cid),
                        "phone": norm_phone(c.get("externalNumber")),
                        "at": datetime.datetime.fromtimestamp(int(c.get("startTime") or 0), ALA),
                        # callType: 0 — входящий, 1 — исходящий, 2 — исходящий с внутреннего
                        "outgoing": str(c.get("callType")) in ("1", "2"),
                        "answered": c.get("disposition") == "ANSWER",
                        "disposition": c.get("disposition") or "",
                        "employee": (emp.get("name") or "") if isinstance(emp, dict) else "",
                        "billsec": int(c.get("billsec") or 0), "waitsec": int(c.get("waitsec") or 0)})
        d += datetime.timedelta(days=1)
        time.sleep(0.3)
    return out


def record_url(call_id):
    """Ссылка на mp3 разговора (stats/call-record). Живёт недолго — качать сразу.
    Пусто, если записи нет: неотвеченный звонок или запись не велась."""
    payload = {"key": KEY, "secret": SEC, "generalCallID": str(call_id)}
    req = urllib.request.Request("https://api.binotel.com/api/4.0/stats/call-record.json",
                                 data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    for a in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                j = json.loads(r.read().decode())
            return j.get("url") or ""
        except Exception:
            time.sleep(2 * (a + 1))
    return ""


def download_record(call_id, path):
    """Скачивает запись разговора в path. True — если файл получен и не пустой."""
    url = record_url(call_id)
    if not url:
        return False
    for a in range(4):
        try:
            urllib.request.urlretrieve(url, path)
            return os.path.getsize(path) > 1024
        except Exception:
            time.sleep(2 * (a + 1))
    return False
