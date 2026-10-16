# Отчёт за смену КЦ · Expert Neuro

Автоматическая панель: к 08:00 по Алматы у руководителя готов отчёт по вчерашней смене — кто сколько рекламных
лидов взял, что с ними стало, звонили ли (Битрикс24 + Binotel + таблица КЦ). Повторяет Google-таблицу
«отчёт за смену по КЦ» от 15.10.2026, но собирается сама.

## Как устроено
- `build_shift.py <день>` — забирает данные, считает, пишет `out/<день>.json` и `out/<день>.html`.
  `--snapshot` делает снимок ответственных (`data/snapshots/<время>.json`, только id сделки → id ответственного).
- `render.py` — HTML из JSON. `publish.py` — шифрует HTML паролем (AES-256-GCM) и собирает `site/`.
- `.github/workflows/shift.yml` — расписание: 21:45 Алматы снимок «после смены» + черновик, 07:40 Алматы снимок
  «до дня» + итоговый отчёт за вчера + публикация на GitHub Pages.
- Общие модули (`adjoin.py`, `attribution.py`, `binotel_api.py`, `kc_sheet.py`, `bx_users.json`) — копии из Сверки,
  обновлять `sync_modules.ps1`.

## Секреты репозитория (Settings → Secrets and variables → Actions)
| Секрет | Что |
|---|---|
| `BITRIX_WEBHOOK` | входящий вебхук Битрикс24 (только чтение) |
| `BINOTEL_API_KEY`, `BINOTEL_API_SECRET` | ключи Binotel |
| `KC_SHEET_URL` | ссылка на таблицу КЦ вида `https://docs.google.com/spreadsheets/d/<id>/export?format=xlsx` |
| `REPORT_LOGIN`, `REPORT_PASSWORD` | логин и пароль, которыми открывается сайт (ключ шифрования строится из пары) |

## Включить Pages
Settings → Pages → Source: **GitHub Actions**. Адрес: `https://<логин>.github.io/<репозиторий>/`.
Сайт показывает только шифротекст; без пароля данных на нём нет.

## Запуск руками
Actions → «Отчёт за смену КЦ» → Run workflow → день (пусто = вчера).
