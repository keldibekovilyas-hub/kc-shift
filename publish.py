# -*- coding: utf-8 -*-
"""Закрывает отчёты паролем и собирает статический сайт: site/index.html + site/days/<день>.enc + site/days/index.json.
Шифрование AES-256-GCM, ключ из пароля PBKDF2-SHA256 (200 000 итераций); расшифровка в браузере через WebCrypto —
на хостинге лежит только шифротекст, пароль знает руководитель. Пароль — переменная REPORT_PASSWORD.
  python publish.py <папка out с *.html> <папка site>
"""
import base64, io, json, os, sys, hashlib
sys.stdout.reconfigure(encoding="utf-8")
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

OUT, SITE = sys.argv[1], sys.argv[2]
PW = os.environ.get("REPORT_PASSWORD") or ""
if not PW:
    raise SystemExit("REPORT_PASSWORD не задан")
os.makedirs(os.path.join(SITE, "days"), exist_ok=True)
ITER = 200000
days = []
for f in sorted(os.listdir(OUT)):
    if not f.endswith(".html"): continue
    day = f[:-5]; salt = os.urandom(16); nonce = os.urandom(12)
    key = hashlib.pbkdf2_hmac("sha256", PW.encode(), salt, ITER, 32)
    ct = AESGCM(key).encrypt(nonce, io.open(os.path.join(OUT, f), encoding="utf-8").read().encode(), None)
    json.dump({"v": 1, "iter": ITER, "salt": base64.b64encode(salt).decode(), "nonce": base64.b64encode(nonce).decode(), "ct": base64.b64encode(ct).decode()},
              io.open(os.path.join(SITE, "days", day + ".enc"), "w"))
    days.append(day)
# в индекс попадают ВСЕ дни, что лежат в site/days (старые .enc хранятся в репозитории, перешифровывать их не нужно)
days = sorted({f[:-4] for f in os.listdir(os.path.join(SITE, "days")) if f.endswith(".enc")}, reverse=True)
json.dump(days, io.open(os.path.join(SITE, "days", "index.json"), "w"))
INDEX = r"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Смена КЦ</title><style>
:root{--bg:#f6f7fb;--card:#fff;--ink:#1b2430;--mut:#6b7280;--line:#e5e7eb;--blue:#1f4e79}
@media(prefers-color-scheme:dark){:root{--bg:#0f141b;--card:#171e27;--ink:#e6e9ef;--mut:#9aa3b2;--line:#2a3340;--blue:#8ab4e8}}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 -apple-system,Segoe UI,Roboto,Arial,sans-serif}
.box{max-width:460px;margin:12vh auto;background:var(--card);border:1px solid var(--line);border-radius:14px;padding:24px 22px}
h1{font-size:20px;margin:0 0 6px;color:var(--blue)}p{color:var(--mut);margin:4px 0 14px}
input,select,button{font:inherit;padding:10px 12px;border:1px solid var(--line);border-radius:9px;background:var(--bg);color:var(--ink);width:100%;margin:5px 0;box-sizing:border-box}
button{background:var(--blue);color:#fff;border:0;cursor:pointer;font-weight:600}.err{color:#b91c1c;min-height:20px}
#view{display:none}#bar{position:sticky;top:0;background:var(--card);border-bottom:1px solid var(--line);padding:8px 16px;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
#bar select{width:auto;margin:0}#bar b{color:var(--blue)}#frame{width:100%;height:calc(100vh - 54px);border:0}
</style></head><body>
<div class="box" id="gate"><h1>Отчёт за смену КЦ</h1><p>Expert Neuro · только рекламные лиды · обновляется к 08:00</p>
<select id="day"></select><input id="pw" type="password" placeholder="Пароль" autocomplete="current-password"><button id="go">Открыть</button><div class="err" id="err"></div></div>
<div id="view"><div id="bar"><b>Смена КЦ</b><select id="day2"></select><span id="st"></span></div><iframe id="frame"></iframe></div>
<script>
const $=id=>document.getElementById(id);let DAYS=[];
async function key(pw,salt,iter){const b=await crypto.subtle.importKey('raw',new TextEncoder().encode(pw),'PBKDF2',false,['deriveKey']);
return crypto.subtle.deriveKey({name:'PBKDF2',salt,iterations:iter,hash:'SHA-256'},b,{name:'AES-GCM',length:256},false,['decrypt'])}
const b64=s=>Uint8Array.from(atob(s),c=>c.charCodeAt(0));
async function open(day,pw){const r=await fetch('days/'+day+'.enc?'+Date.now());if(!r.ok)throw new Error('нет файла за '+day);const j=await r.json();
const k=await key(pw,b64(j.salt),j.iter);const pt=await crypto.subtle.decrypt({name:'AES-GCM',iv:b64(j.nonce)},k,b64(j.ct));return new TextDecoder().decode(pt)}
function fill(sel){sel.innerHTML=DAYS.map(d=>'<option value="'+d+'">'+d.slice(8)+'.'+d.slice(5,7)+'.'+d.slice(0,4)+'</option>').join('')}
async function show(day){const pw=sessionStorage.getItem('pw')||$('pw').value;try{const html=await open(day,pw);sessionStorage.setItem('pw',pw);
$('gate').style.display='none';$('view').style.display='block';$('frame').srcdoc=html;$('day2').value=day;$('st').textContent='';history.replaceState(null,'','#'+day)}
catch(e){sessionStorage.removeItem('pw');$('err').textContent=e.name==='OperationError'?'Неверный пароль':('Ошибка: '+e.message);$('gate').style.display='block';$('view').style.display='none'}}
(async()=>{DAYS=await (await fetch('days/index.json?'+Date.now())).json();fill($('day'));fill($('day2'));const h=location.hash.slice(1);if(h&&DAYS.includes(h)){$('day').value=h}
$('go').onclick=()=>show($('day').value);$('pw').addEventListener('keydown',e=>{if(e.key==='Enter')show($('day').value)});$('day2').onchange=()=>show($('day2').value);
if(sessionStorage.getItem('pw'))show($('day').value)})();
</script></body></html>"""
io.open(os.path.join(SITE, "index.html"), "w", encoding="utf-8").write(INDEX)
io.open(os.path.join(SITE, ".nojekyll"), "w").write("")
print("сайт: %d дней → %s" % (len(days), SITE))
