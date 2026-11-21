# Свой Cloudflare Worker за 5 минут

Это самый надёжный маршрут, когда домены CF-прокси по умолчанию заблокированы
(ситуация с 16.11.2026). Домен и деньги не нужны — хватит бесплатного аккаунта
Cloudflare.

## Шаги

1. Откройте [dash.cloudflare.com](https://dash.cloudflare.com/) и войдите (или
   создайте аккаунт, подтвердите почту).
2. Слева: **Compute (Workers & Pages)** → **Create** → **Start with Hello
   World!** → **Deploy**.
3. Нажмите **Edit code**, удалите всё, что есть в редакторе, и вставьте
   содержимое файла [`worker.js`](./worker.js) целиком:
   - страница файла: https://github.com/flare-award/tg-ws-proxy-maronn/blob/arena/199cb847-tg-ws-proxy-maronn/cloudflare-worker/worker.js
   - «сырой» текст для копирования: https://raw.githubusercontent.com/flare-award/tg-ws-proxy-maronn/arena/199cb847-tg-ws-proxy-maronn/cloudflare-worker/worker.js
4. Нажмите **Deploy** и скопируйте адрес справа — он выглядит так:
   `https://random-symbols-1234.username.workers.dev`
5. В TgWsProxy: **Настройки…** → раздел **Cloudflare Worker** → включите галочку
   «Свой домен» → вставьте этот адрес в поле (без `https://` и без `/`) →
   **Сохранить**. Полностью закройте программу и запустите снова.
6. Проверьте: в логе при старте будет строка `CF worker: enabled (…домен…)`, а
   при работе — `DCx -> CF worker pool hit` или `-> trying CF worker`.

## Если `*.workers.dev` не открывается

Добавьте в [zapret](https://github.com/Flowseal/zapret-discord-youtube/) (или
другое DPI-ПО) домены:

```
cloudflare.com
cloudflare.dev
workers.dev
```

## Зачем это нужно

Worker работает на домене `*.workers.dev`, который не входит в список
заблокированных `*.co.uk` и проксирует WebSocket прямо в дата-центры Telegram.
Прокси использует его **раньше** остальных резервных маршрутов, поэтому Telegram
перестаёт зависеть от заблокированных доменов.
