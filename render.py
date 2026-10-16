# -*- coding: utf-8 -*-
"""HTML отчёта за смену из JSON build_shift.py: сводка по менеджерам, лиды каждого менеджера, нераспределённые, методика.
Один файл без внешних библиотек; таблицы сортируются кликом по шапке, менеджеры сворачиваются."""
import html, json


def esc(v):
    return html.escape("" if v is None else str(v))


CSS = """
:root{--bg:#f6f7fb;--card:#fff;--ink:#1b2430;--mut:#6b7280;--line:#e5e7eb;--blue:#1f4e79;--green:#e2efda;--pink:#fce4e4;--yel:#fff2cc;--grey:#eeeeee}
@media(prefers-color-scheme:dark){:root{--bg:#0f141b;--card:#171e27;--ink:#e6e9ef;--mut:#9aa3b2;--line:#2a3340;--blue:#8ab4e8;--green:#1d3a2a;--pink:#4a2020;--yel:#4a3f12;--grey:#262d38}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 -apple-system,Segoe UI,Roboto,Arial,sans-serif}
.wrap{max-width:1600px;margin:0 auto;padding:16px}h1{font-size:22px;margin:0 0 4px;color:var(--blue)}h2{font-size:17px;margin:22px 0 8px;color:var(--blue)}
.note{color:var(--mut);font-size:12.5px;margin:2px 0}.kpi{display:flex;flex-wrap:wrap;gap:10px;margin:14px 0}
.kpi div{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 14px;min-width:130px}.kpi b{display:block;font-size:22px}.kpi span{color:var(--mut);font-size:12px}
table{border-collapse:collapse;width:100%;background:var(--card);font-size:13px}th,td{border:1px solid var(--line);padding:5px 7px;text-align:left;vertical-align:top}
th{background:var(--blue);color:#fff;position:sticky;top:0;cursor:pointer;white-space:nowrap;font-weight:600}td.n{text-align:right;white-space:nowrap}
tr.tot td{font-weight:700;background:var(--grey)}tr.booked td{background:var(--green)}tr.trash td{background:var(--pink)}tr.morn td{color:var(--mut);background:var(--grey)}
details{background:var(--card);border:1px solid var(--line);border-radius:10px;margin:8px 0;padding:6px 10px}summary{cursor:pointer;font-weight:600;padding:6px 0}
summary small{color:var(--mut);font-weight:400}.tw{overflow-x:auto}a{color:var(--blue)}.tag{font-size:11px;color:var(--mut)}.ok{color:#15803d}.bad{color:#b91c1c}
input.f{width:100%;max-width:420px;padding:8px 10px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--ink);margin:8px 0}
@media(max-width:700px){.wrap{padding:16px 16px}table{font-size:12px}}
"""
JS = """
document.querySelectorAll('th').forEach(th=>th.addEventListener('click',()=>{const t=th.closest('table'),i=[...th.parentNode.children].indexOf(th),tb=t.tBodies[0];
const rows=[...tb.rows].filter(r=>!r.classList.contains('tot'));const num=rows.every(r=>!isNaN(parseFloat((r.cells[i]||{}).innerText))||!(r.cells[i]||{}).innerText.trim());
const dir=th.dataset.d==='a'?'d':'a';th.dataset.d=dir;rows.sort((a,b)=>{let x=(a.cells[i]||{}).innerText||'',y=(b.cells[i]||{}).innerText||'';if(num){x=parseFloat(x)||0;y=parseFloat(y)||0;return dir==='a'?x-y:y-x}return dir==='a'?x.localeCompare(y,'ru'):y.localeCompare(x,'ru')});
rows.forEach(r=>tb.appendChild(r))}));
const f=document.getElementById('flt');if(f){f.addEventListener('input',()=>{const q=f.value.toLowerCase();document.querySelectorAll('table.leads tbody tr').forEach(r=>{r.style.display=r.innerText.toLowerCase().includes(q)?'':'none'})})}
"""


def render(r):
    day = r["day"]; dd = "%s.%s.%s" % (day[8:], day[5:7], day[:4]); t = r["total"]
    H = ["<!doctype html><html lang='ru'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>",
         "<title>Смена КЦ %s</title><style>%s</style></head><body><div class='wrap'>" % (dd, CSS)]
    H.append("<h1>Отчёт за смену КЦ · %s · только рекламные лиды</h1>" % dd)
    H.append("<p class='note'>«Взял за день» = сделали ответственным в этот день: новые лиды дня + вечерние накануне, розданные утром + дожим НБ + перекинутые. Лид = человек. Записал = стадия записи на любой карточке; дожим = проигрыш. Звонки — только исходящие Binotel по номеру после получения лида.</p>")
    H.append("<p class='note'>Собрано %s · снимки ответственных: до дня %s, после смены %s · звонки Binotel до %s · отчёт КЦ скачан %s.</p>"
             % (esc(r["built"]), esc(r["snap_before"] or "нет"), esc(r["snap_after"] or "нет"), esc(r["calls_until"]), esc(r["kc_taken"])))
    H.append("<div class='kpi'>" + "".join("<div><b>%s</b><span>%s</span></div>" % (v, k) for k, v in (
        ("взяли за день", t["took"]), ("записали", t["booked"]), ("конверсия", "%.1f %%" % t["conv"]), ("без исходящего", t["no_call"]),
        ("дозвонились (лидов)", t["reached"]), ("исходящих всего", t["n_out"]), ("внесли в отчёт КЦ", t["in_kc"]), ("нераспределённых", len(r["unassigned"])), ("роздано утром", t["morning"]))) + "</div>")
    # сводка
    cols = [("Менеджер", "mgr"), ("Взял за день", "took"), ("новых", "new"), ("вечерних накануне", "eve"), ("дожим (НБ)", "dojim_in"), ("перекинуто", "moved"), ("Записал", "booked"),
            ("Конверсия", "conv"), ("В работе", "inwork"), ("Дожим (исход)", "dojim_out"), ("Брак", "trash"), ("Без исходящего", "no_call"), ("Дозвонился (лидов)", "reached"),
            ("Исходящих всего", "n_out"), ("Внёс в отчёт КЦ", "in_kc"), ("Роздано утром (не в счёт)", "morning")]
    H.append("<h2>Менеджеры за смену</h2><div class='tw'><table><thead><tr>" + "".join("<th>%s</th>" % c for c, _ in cols) + "</tr></thead><tbody>")
    for s in r["summary"]:
        H.append("<tr>" + "".join("<td%s>%s</td>" % ("" if k == "mgr" else " class='n'", ("%.1f %%" % s[k]) if k == "conv" else esc(s[k])) for _, k in cols) + "</tr>")
    H.append("<tr class='tot'><td>ИТОГО</td>" + "".join("<td class='n'>%s</td>" % (("%.1f %%" % t[k]) if k == "conv" else t[k]) for _, k in cols[1:]) + "</tr></tbody></table></div>")
    # лиды по менеджерам
    H.append("<h2>Лиды по менеджерам</h2><input class='f' id='flt' placeholder='фильтр по любому слову: телефон, статус, фамилия…'>")
    lc = ["№", "ФИО", "Телефон", "Филиал", "Статус", "Дата записи", "Комментарий", "Предоплата", "1-й звонок", "2-й", "3-й", "4-й", "Исх.", "Дозв.", "Кто звонил", "Вх. принято",
          "Как получил", "Создан", "Воронка", "Врач", "Исход", "В отчёте КЦ", "Статус (КЦ)", "Комментарий (КЦ)", "Сделка"]
    by = {}
    for p in r["people"]: by.setdefault(p["mgr"], []).append(p)
    for s in r["summary"]:
        L = by.get(s["mgr"], [])
        H.append("<details><summary>%s <small>· взял %d (новых %d, вечерних %d, дожим %d, перекинуто %d) · записал %d · %.1f %% · без звонка %d · исходящих %d</small></summary><div class='tw'><table class='leads'><thead><tr>"
                 % (esc(s["mgr"]), s["took"], s["new"], s["eve"], s["dojim_in"], s["moved"], s["booked"], s["conv"], s["no_call"], s["n_out"]) + "".join("<th>%s</th>" % c for c in lc) + "</tr></thead><tbody>")
        for i, p in enumerate(L, 1):
            cls = "morn" if not p["count"] else ("booked" if p["booked"] else ("trash" if p["o"] == "trash" else ""))
            vals = [i, p["name"], p["phone"], p["branch"], p["stage"], p["visit"], p["comment"], p["prepay"]] + p["calls"] + [p["n_out"], p["n_ans"], p["who"], p["n_in"], p["note"], p["created"],
                    p["funnel"], p["doctor"], p["outcome"], "да" if p["in_kc"] else "<span class='bad'>НЕТ</span>", p["kc_status"], p["kc_comment"],
                    "<a href='https://expertneuro.bitrix24.ru/crm/deal/details/%s/' target='_blank'>%s</a>" % (p["deal"], p["deal"])]
            H.append("<tr class='%s'>" % cls + "".join("<td%s>%s</td>" % (" class='n'" if isinstance(v, int) else "", v if (isinstance(v, str) and v.startswith("<")) else esc(v)) for v in vals) + "</tr>")
        H.append("</tbody></table></div></details>")
    # нераспределённые
    H.append("<h2>Не распределены <small class='tag'>— рекламные лиды %s, до сих пор на Администраторе Портала</small></h2>" % dd)
    if r["unassigned"]:
        H.append("<div class='tw'><table><thead><tr><th>Создан</th><th>ФИО</th><th>Телефон</th><th>Воронка</th><th>Стадия</th><th>Исходящих по номеру</th><th>Сделка</th></tr></thead><tbody>")
        for u in r["unassigned"]:
            H.append("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td class='n'>%s</td><td><a href='https://expertneuro.bitrix24.ru/crm/deal/details/%s/' target='_blank'>%s</a></td></tr>"
                     % (esc(u["created"]), esc(u["name"]), esc(u["phone"]), esc(u["funnel"]), esc(u["stage"]), u["n_out"], u["deal"], u["deal"]))
        H.append("</tbody></table></div>")
    else:
        H.append("<p class='note'>нет</p>")
    H.append("""<h2>Методика</h2><p class='note'>Источник: Битрикс24 (только чтение) — сделки воронок Алматы, Астана, Шымкент, Тараз, Дожим; Binotel — исходящие звонки; отчёт КЦ — Google-таблица менеджеров.
Лид = человек: карточки одного контакта склеены; статус, филиал, врач, дата записи — с лучшей карточки (запись › в работе › дожим › брак). Только рекламные лиды: подрядчик распознан по метке или посадке; звонки, WhatsApp и повторные без метки исключены.<br>
«Взял за день»: новый — создан в день смены и к вечернему снимку стоит на менеджере; роздан утром — к вечеру висел на Администраторе, а утром уже на менеджере (серые строки, не в счёт; если вечером по номеру был исходящий — считается); вечерний — создан накануне после 19:00 и накануне по нему не звонили; дожим: НБ от … — карточка переведена в воронку дожима в этот день и сменила ответственного; перекинут от … — ответственный отличается между снимками до дня и после смены.<br>
Звонки: только исходящие (callType 1/2) по последним 10 цифрам номера после получения лида (допуск −15 мин); 1–4-й звонок — время по Алматы, ✓ = дозвон (ANSWER; автоответчик от человека Binotel не отличает). SIPUNI в отчёте нет. «Кто звонил» — сотрудник Binotel. «В отчёте КЦ» — телефон нашёлся в таблице КЦ за день смены или следующий.</p>""")
    H.append("</div><script>%s</script></body></html>" % JS)
    return "\n".join(H)


if __name__ == "__main__":
    import io, sys
    r = json.load(io.open(sys.argv[1], encoding="utf-8"))
    io.open(sys.argv[2], "w", encoding="utf-8").write(render(r))
