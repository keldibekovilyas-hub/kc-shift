# -*- coding: utf-8 -*-
"""Отчёт за смену по КЦ (Expert Neuro): кто сколько рекламных лидов взял, что с ними стало, звонили ли.
Повторяет Google-таблицу «отчёт за смену по КЦ» (15.10.2026), но собирается автоматически:
Битрикс24 (только чтение) + Binotel (исходящие) + таблица КЦ (Google, по ссылке) + снимки ответственных.

  python build_shift.py [ГГГГ-ММ-ДД] [--out <папка>] [--snapshot]   # день смены (по умолчанию — вчера по Алматы)

Правила (как в таблице заказчика):
  • лид = человек (карточки одного контакта склеены); ТОЛЬКО реклама (attribution.contractor ∈ CONTRS);
  • «Взял за день» = сделали ответственным в день смены: новые лиды дня + вечерние накануне (после 19:00,
    без исходящего накануне) + дожим НБ (карточка переведена в воронку 31 в этот день и сменила ответственного)
    + перекинутые (ответственный отличается между снимками «до дня» и «после смены»);
  • кто к вечернему снимку висел на Администраторе Портала, а утром уже на менеджере — «роздан утром», не в счёт;
  • записал = стадия записи на любой карточке человека; дожим = проигрыш; исход: запись > в работе > дожим > брак;
  • звонки: только исходящие Binotel по последним 10 цифрам после получения лида (−15 мин), ✓ = ANSWER.
Снимки ответственных: data/snapshots/<ISO-время>.json = {deal_id: assigned_by}; --snapshot делает снимок «сейчас».
Выход: <out>/<день>.json и <out>/<день>.html (открытый HTML — дальше encrypt.py закрывает его паролем).
"""
import datetime, glob, html, io, json, os, re, sys, time, urllib.error, urllib.parse, urllib.request
from collections import Counter, defaultdict

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)                                              # vendored modules в репозитории
sys.path.insert(0, os.path.dirname(HERE))                             # локально — модули Сверки
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "Control", "ИИ-панель Битрикс"))
import adjoin, attribution as A                                        # noqa: E402
import kc_sheet                                                        # noqa: E402

ALA = datetime.timezone(datetime.timedelta(hours=5))
NOW = datetime.datetime.now(ALA)
args = [a for a in sys.argv[1:] if not a.startswith("--")]
DAY = args[0] if args else (NOW.date() - datetime.timedelta(days=1)).isoformat()
OUT = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else os.path.join(HERE, "out")
DATA = os.environ.get("KC_SHIFT_DATA") or os.path.join(HERE, "data")
SNAP_DIR = os.path.join(DATA, "snapshots")
os.makedirs(OUT, exist_ok=True); os.makedirs(SNAP_DIR, exist_ok=True)

# ── окружение: вебхук и ключи из переменных (GitHub Actions) или токены/.env (локально)
ENV = dict(os.environ)
envp = os.path.join(os.path.dirname(HERE), "токены", ".env")
if os.path.exists(envp):
    for line in io.open(envp, encoding="utf-8"):
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.strip().split("=", 1); ENV.setdefault(k, v.strip().strip('"'))
WEBHOOK = ENV["BITRIX_WEBHOOK"].rstrip("/") + "/"
KC_URL = ENV.get("KC_SHEET_URL") or kc_sheet.DEFAULT_URL
CATS = (1, 3, 100, 114, 31)
DOJIM = 31
CITY = {1: "Алматы", 3: "Астана", 100: "Шымкент", 114: "Тараз", 31: "Дожим"}
ALLR = "UF_CRM_1788262753"; BRANCH_F = "UF_CRM_AMO_705439"; VZ_F = "UF_CRM_AMO_705563"
DOC_F = {1: "UF_CRM_AMO_705443", 3: "UF_CRM_1662525036130", 100: "UF_CRM_1681701056580", 114: "UF_CRM_1695018910988"}
SEL = ["ID", "TITLE", "DATE_CREATE", "MOVED_TIME", "CATEGORY_ID", "STAGE_ID", "CONTACT_ID", "ASSIGNED_BY_ID", "OPPORTUNITY", "COMMENTS",
       "UTM_SOURCE", "UTM_MEDIUM", "UTM_CAMPAIGN", "UTM_CONTENT", "UTM_TERM", BRANCH_F, VZ_F, ALLR] + list(DOC_F.values())
URL = "https://expertneuro.bitrix24.ru/crm/deal/details/%s/"
NAMES = json.load(io.open(os.path.join(HERE, "bx_users.json"), encoding="utf-8"))
ADMIN = {uid for uid, n in NAMES.items() if "администратор" in n.lower()} | {"1", "0", ""}
D0 = datetime.datetime.fromisoformat(DAY + "T00:00:00+05:00"); D1 = D0 + datetime.timedelta(days=1)
EVE = D0 - datetime.timedelta(hours=5)                               # вечер накануне: с 19:00


def call(method, params):
    data = urllib.parse.urlencode(params, doseq=True).encode()
    for attempt in range(6):
        try:
            with urllib.request.urlopen(urllib.request.Request(WEBHOOK + method + ".json", data=data, method="POST"), timeout=90) as r:
                j = json.loads(r.read().decode())
            if "error" in j and "LIMIT" in str(j.get("error")):
                time.sleep(3 + attempt * 2); continue
            return j
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and attempt < 5:
                time.sleep(3 + attempt * 2); continue
            raise
    return {}


def listall(params):
    out, last = [], 0
    while True:
        r = call("crm.deal.list", params + [("filter[>ID]", last), ("order[ID]", "ASC"), ("start", -1)] + [("select[]", s) for s in SEL])
        page = r.get("result") or []
        out += page
        if len(page) < 50: return out
        last = page[-1]["ID"]; time.sleep(0.2)


def by_ids(ids):
    out = []
    ids = sorted({str(i) for i in ids}, key=int)
    for i in range(0, len(ids), 50):
        r = call("crm.deal.list", [("filter[ID][]", x) for x in ids[i:i + 50]] + [("select[]", s) for s in SEL] + [("start", -1)])
        out += r.get("result") or []
        time.sleep(0.2)
    return out


def alma(iso):
    return datetime.datetime.fromisoformat(iso).astimezone(ALA)


def msk(dt):
    return dt.astimezone(datetime.timezone(datetime.timedelta(hours=3))).strftime("%Y-%m-%dT%H:%M:%S+03:00")


def uname(uid):
    uid = str(uid or "")
    return NAMES.get(uid) or ("id" + uid)


def n10(p):
    dg = re.sub(r"\D", "", str(p or ""))
    if len(dg) >= 11 and dg.startswith("8"): dg = "7" + dg[1:]
    return dg[-10:] if len(dg) >= 10 else ""


def fmt_phone(p):
    d = n10(p)
    return "7 %s %s %s" % (d[:3], d[3:6], d[6:]) if d else ""


# ── снимки ответственных
def snapshot_now():
    """Все сделки входных воронок + дожима за 45 дней → {id: assigned}. Файл = время снимка (Алматы)."""
    since = msk(NOW - datetime.timedelta(days=45)); snap = {}
    for cat in CATS:
        for d in listall([("filter[CATEGORY_ID]", cat), ("filter[>=DATE_CREATE]", since)]):
            snap[d["ID"]] = str(d.get("ASSIGNED_BY_ID") or "")
    p = os.path.join(SNAP_DIR, NOW.strftime("%Y-%m-%dT%H-%M") + ".json")
    json.dump(snap, io.open(p, "w", encoding="utf-8"))
    print("снимок ответственных: %d сделок → %s" % (len(snap), p))
    return p


def load_snaps():
    """(before, after): последний снимок ДО начала дня и первый снимок ПОСЛЕ 20:00 дня смены (или None)."""
    files = sorted(glob.glob(os.path.join(SNAP_DIR, "*.json")))
    before = after = None
    for f in files:
        t = datetime.datetime.strptime(os.path.basename(f)[:16], "%Y-%m-%dT%H-%M").replace(tzinfo=ALA)
        if t <= D0 + datetime.timedelta(hours=8): before = f           # до 08:00 дня смены
        elif t >= D0 + datetime.timedelta(hours=20) and after is None: after = f
    def rd(f):
        if not f: return {}, None
        j = json.load(io.open(f, encoding="utf-8"))
        if isinstance(j, dict) and "deals" in j:                        # формат assign_snapshot.py: {deals: {id: {a: …}}}
            j = {k: str(v.get("a") or "") for k, v in j["deals"].items()}
        b = os.path.basename(f)[:16]
        return j, b[:10] + " " + b[11:13] + ":" + b[14:16]
    return rd(before), rd(after)


if "--snapshot" in sys.argv:
    snapshot_now()
    if len(args) == 0 and "--build" not in sys.argv: sys.exit(0)

(SNAP_B, SNAP_B_T), (SNAP_A, SNAP_A_T) = load_snaps()
print("день смены %s · снимки: до дня %s · после смены %s" % (DAY, SNAP_B_T or "нет", SNAP_A_T or "нет"))

# ── 1. сделки: созданы с 19:00 накануне; переведены в дожим в день; перекинутые по снимкам
deals = {}
for cat in CATS:
    for d in listall([("filter[CATEGORY_ID]", cat), ("filter[>=DATE_CREATE]", msk(EVE))]): deals[d["ID"]] = d
for d in listall([("filter[CATEGORY_ID]", DOJIM), ("filter[>=MOVED_TIME]", msk(D0)), ("filter[<MOVED_TIME]", msk(D1))]): deals[d["ID"]] = d
moved_ids = set()
if SNAP_B and SNAP_A:
    moved_ids = {i for i, a in SNAP_A.items() if i in SNAP_B and SNAP_B[i] != a and a not in ADMIN and i not in deals}
    for d in by_ids(moved_ids): deals[d["ID"]] = d
print("сделок: %d (перекинутых по снимкам %d)" % (len(deals), len(moved_ids)))
# все карточки людей (для исхода нужны и старые карточки того же контакта)
cids = sorted({str(d["CONTACT_ID"]) for d in deals.values() if str(d.get("CONTACT_ID") or "0") != "0"}, key=int)
extra = []
for i in range(0, len(cids), 50):
    r = call("crm.deal.list", [("filter[CONTACT_ID][]", c) for c in cids[i:i + 50]] + [("filter[CATEGORY_ID][]", c) for c in CATS]
             + [("filter[>=DATE_CREATE]", msk(D0 - datetime.timedelta(days=60)))] + [("select[]", s) for s in SEL] + [("start", -1)])
    extra += r.get("result") or []; time.sleep(0.2)
for d in extra: deals.setdefault(d["ID"], d)
# справочники
SN = {}
for cat in CATS:
    for s in call("crm.status.list", [("filter[ENTITY_ID]", "DEAL_STAGE_%d" % cat)]).get("result") or []: SN[s["STATUS_ID"]] = s["NAME"]
FIELDS = call("crm.deal.fields", []).get("result") or {}
enum = lambda code: {str(i["ID"]): i["VALUE"] for i in (FIELDS.get(code, {}).get("items") or [])}
BRANCHES = enum(BRANCH_F); DOCTORS = {c: enum(f) for c, f in DOC_F.items()}
CONTACT = {}
for i in range(0, len(cids), 50):
    r = call("crm.contact.list", [("filter[ID][]", c) for c in cids[i:i + 50]] + [("select[]", s) for s in ("ID", "NAME", "LAST_NAME", "PHONE")] + [("start", -1)])
    for c in r.get("result") or []:
        CONTACT[str(c["ID"])] = {"name": " ".join(x for x in ((c.get("LAST_NAME") or "").strip(), (c.get("NAME") or "").strip()) if x),
                                 "phone": next((p.get("VALUE") for p in (c.get("PHONE") or []) if p.get("VALUE")), "")}
    time.sleep(0.2)

# ── 2. звонки Binotel: день смены и утро следующего дня (до момента сборки)
calls_by_ph = defaultdict(list); incoming = defaultdict(int)
try:
    import binotel_api
    for c in binotel_api.calls(DAY, min(D1.date(), NOW.date()).isoformat()):
        if not c["phone"]: continue
        if c["outgoing"]: calls_by_ph[c["phone"]].append((c["at"], c["answered"], c["employee"]))
        elif c["answered"]: incoming[c["phone"]] += 1
    for v in calls_by_ph.values(): v.sort()
    CALLS_UNTIL = NOW.strftime("%d.%m %H:%M")
    print("Binotel: исходящих %d, номеров %d" % (sum(len(v) for v in calls_by_ph.values()), len(calls_by_ph)))
except Exception as e:
    CALLS_UNTIL = "нет (%s)" % str(e)[:80]; print("Binotel недоступен:", str(e)[:120])

# ── 3. отчёт КЦ
kc_rows = {}; kc_sheets = []
try:
    kc = kc_sheet.load_rows(KC_URL, ttl=600)
    nxt = D1.date().isoformat()
    for r in kc["rows"]:
        if r["day"] in (DAY, nxt) and r["phone"]: kc_rows.setdefault(r["phone"], r)
    kc_sheets = kc["sheets"]; KC_TAKEN = kc["taken"]
    print("отчёт КЦ: строк за %s–%s: %d" % (DAY, nxt, len(kc_rows)))
except Exception as e:
    KC_TAKEN = "нет (%s)" % str(e)[:80]; print("отчёт КЦ недоступен:", str(e)[:120])

# ── 4. люди
byc = defaultdict(list)
for d in deals.values():
    byc[str(d["CONTACT_ID"]) if str(d.get("CONTACT_ID") or "0") != "0" else "d" + d["ID"]].append(d)
out_of = lambda c: adjoin.outcome(c["CATEGORY_ID"], SN.get(c["STAGE_ID"], c["STAGE_ID"]))


def first_owner(d):
    owners = [str(u) for u in (d.get(ALLR) or []) if str(u) not in ("", "0")]
    return owners[0] if owners else str(d.get("ASSIGNED_BY_ID") or "")


people = []; unassigned = []
for cid, cards in byc.items():
    cards.sort(key=lambda c: c["DATE_CREATE"])
    rep = ([c for c in cards if int(c["CATEGORY_ID"]) != DOJIM] or cards)[0]
    x = {k: rep.get(k.upper()) for k in ("title", "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term")}
    if A.contractor(x) not in A.CONTRS: continue                                   # только реклама
    created = alma(rep["DATE_CREATE"])
    cur = str(rep.get("ASSIGNED_BY_ID") or "")
    # карточка дня: та, что «двигалась» в день смены (перевод в дожим) — у неё свой ответственный
    dj = [c for c in cards if int(c["CATEGORY_ID"]) == DOJIM and c.get("MOVED_TIME") and D0 <= alma(c["MOVED_TIME"]) < D1]
    how = None; got_at = None; mgr = None; note = ""
    if dj:
        c = dj[0]; a = str(c.get("ASSIGNED_BY_ID") or ""); fo = first_owner(c)
        if a != fo and a not in ADMIN:
            how, got_at, mgr, note = "дожим", alma(c["MOVED_TIME"]), a, "дожим: НБ от " + uname(fo)
    if how is None and D0 <= created < D1:
        a_after = SNAP_A.get(rep["ID"]) if SNAP_A else None
        if SNAP_A and a_after in ADMIN and cur not in ADMIN:
            ev = [t for t, _, _ in calls_by_ph.get(n10(CONTACT.get(cid, {}).get("phone")), []) if created <= t < D1]
            if ev: how, got_at, mgr, note = "новый", created, cur, "новый (роздан вечером, был звонок)"
            else: how, got_at, mgr, note = "утром", created, cur, "роздан утром %s" % D1.strftime("%d.%m")
        elif cur in ADMIN:
            unassigned.append((rep, cid)); continue
        else:
            how, got_at, mgr, note = "новый", created, cur, "новый"
    if how is None and EVE <= created < D0 and cur not in ADMIN:
        ph = n10(CONTACT.get(cid, {}).get("phone"))
        if not any(created <= t < D0 for t, _, _ in calls_by_ph.get(ph, [])):
            how, got_at, mgr, note = "вечерний", D0 + datetime.timedelta(hours=8), cur, "вечерний накануне, роздан утром"
    if how is None and SNAP_B and SNAP_A and rep["ID"] in moved_ids:
        how, got_at, mgr, note = "перекинут", D0, cur, "перекинут от " + uname(SNAP_B.get(rep["ID"]))
    if how is None and rep["ID"] in moved_ids: pass
    if how is None: continue
    booked = any("запис" in SN.get(c["STAGE_ID"], "").lower() for c in cards)
    best = max(cards, key=lambda c: adjoin.OP[out_of(c)]); o = out_of(best)
    if booked: o = "booked"
    bcat = int(best["CATEGORY_ID"]); ph = n10(CONTACT.get(cid, {}).get("phone"))
    ev = [(t, ans, who) for t, ans, who in calls_by_ph.get(ph, []) if t >= got_at - datetime.timedelta(minutes=15)] if ph else []
    who = Counter((w or "линия").split()[0] for _, _, w in ev)
    k = kc_rows.get(ph) or {}
    br = best.get(BRANCH_F); dc = best.get(DOC_F.get(bcat, "")) if bcat in DOC_F else None
    people.append({
        "mgr": uname(mgr), "mgr_id": mgr, "how": how, "note": note, "count": how != "утром",
        "name": CONTACT.get(cid, {}).get("name") or rep.get("TITLE") or "", "phone": fmt_phone(ph), "ph": ph,
        "branch": BRANCHES.get(str(br), "") if br and str(br) != "0" else "", "stage": SN.get(best["STAGE_ID"], best["STAGE_ID"]),
        "visit": (alma(best[VZ_F]).strftime("%d.%m.%Y %H:%M") if best.get(VZ_F) else ""), "comment": (best.get("COMMENTS") or "").strip()[:120],
        "prepay": best.get("OPPORTUNITY") if best.get("OPPORTUNITY") not in (None, "0.00", "0") else "",
        "calls": [t.strftime("%H:%M" if t.date().isoformat() == DAY else "%d.%m %H:%M") + (" ✓" if ans else "") for t, ans, _ in ev[:4]] + ["—"] * max(0, 4 - len(ev)),
        "n_out": len(ev), "n_ans": sum(1 for _, a, _ in ev if a), "who": ", ".join(("%s×%d" % kv) if kv[1] > 1 else kv[0] for kv in who.most_common()),
        "n_in": incoming.get(ph, 0), "created": created.strftime("%d.%m %H:%M"), "funnel": CITY.get(int(rep["CATEGORY_ID"]), "?") if not dj else "Дожим",
        "doctor": DOCTORS.get(bcat, {}).get(str(dc), "") if dc and str(dc) != "0" else "", "outcome": {"booked": "Записался", "inwork": "В работе", "dojim": "Дожим (НБ)", "trash": "Брак"}[o],
        "booked": booked, "o": o, "no_call": not ev, "in_kc": bool(k), "kc_status": k.get("status", ""), "kc_comment": k.get("comment", ""), "deal": best["ID"],
    })
people.sort(key=lambda p: (p["mgr"], not p["count"], p["created"]))
# нераспределённые
una = []
for rep, cid in unassigned:
    ph = n10(CONTACT.get(cid, {}).get("phone"))
    una.append({"created": alma(rep["DATE_CREATE"]).strftime("%d.%m %H:%M"), "name": CONTACT.get(cid, {}).get("name") or rep.get("TITLE") or "", "phone": fmt_phone(ph),
                "funnel": CITY.get(int(rep["CATEGORY_ID"]), "?"), "stage": SN.get(rep["STAGE_ID"], rep["STAGE_ID"]), "n_out": len(calls_by_ph.get(ph, [])), "deal": rep["ID"]})

# ── 5. сводка по менеджерам
mg = defaultdict(list)
for p in people: mg[p["mgr"]].append(p)
summary = []
for m, L in sorted(mg.items(), key=lambda kv: -sum(1 for p in kv[1] if p["count"])):
    C = [p for p in L if p["count"]]; n = len(C)
    summary.append({"mgr": m, "took": n, "new": sum(p["how"] == "новый" for p in C), "eve": sum(p["how"] == "вечерний" for p in C),
                    "dojim_in": sum(p["how"] == "дожим" for p in C), "moved": sum(p["how"] == "перекинут" for p in C),
                    "booked": sum(p["booked"] for p in C), "conv": round(100.0 * sum(p["booked"] for p in C) / n, 1) if n else 0,
                    "inwork": sum(p["o"] == "inwork" for p in C), "dojim_out": sum(p["o"] == "dojim" for p in C), "trash": sum(p["o"] == "trash" for p in C),
                    "no_call": sum(p["no_call"] for p in C), "reached": sum(p["n_ans"] > 0 for p in C), "n_out": sum(p["n_out"] for p in C),
                    "in_kc": sum(p["in_kc"] for p in C), "morning": sum(not p["count"] for p in L)})
tot = {k: sum(s[k] for s in summary) for k in ("took", "new", "eve", "dojim_in", "moved", "booked", "inwork", "dojim_out", "trash", "no_call", "reached", "n_out", "in_kc", "morning")}
tot["conv"] = round(100.0 * tot["booked"] / tot["took"], 1) if tot["took"] else 0
res = {"day": DAY, "built": NOW.strftime("%Y-%m-%d %H:%M"), "snap_before": SNAP_B_T, "snap_after": SNAP_A_T, "calls_until": CALLS_UNTIL, "kc_taken": KC_TAKEN,
       "summary": summary, "total": tot, "people": people, "unassigned": una}
json.dump(res, io.open(os.path.join(OUT, DAY + ".json"), "w", encoding="utf-8"), ensure_ascii=False)
print("лидов в счёт дня %d · записей %d (%.1f%%) · без звонка %d · нераспределённых %d" % (tot["took"], tot["booked"], tot["conv"], tot["no_call"], len(una)))
for s in summary: print("  %-26s взял %3d (нов %3d веч %2d дож %2d пер %2d) · зап %2d · %4.1f%% · без звонка %2d · исх %3d · КЦ %2d · утром %d" % (
    s["mgr"][:26], s["took"], s["new"], s["eve"], s["dojim_in"], s["moved"], s["booked"], s["conv"], s["no_call"], s["n_out"], s["in_kc"], s["morning"]))

# ── 6. HTML
from render import render                                               # noqa: E402
io.open(os.path.join(OUT, DAY + ".html"), "w", encoding="utf-8").write(render(res))
print("готово:", os.path.join(OUT, DAY + ".html"))
