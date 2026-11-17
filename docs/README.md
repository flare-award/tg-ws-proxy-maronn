<div align="center">

**🇷🇺 Русский • [🇬🇧 English](./EN/README.md)**

</div>

<div align="center">
	<br />
	<p>
		<img width="1729" height="910" alt="tgwsproxy" src="./images/workflow.png" />
	</p>
</div>

##

# TG WS Proxy (форк maronnix)

> [!NOTE]
>
> ### О проекте
>
> Это **неофициальный форк** проекта [Flowseal/tg-ws-proxy](https://github.com/Flowseal/tg-ws-proxy).
>
> - **Автор форка:** [maronnix](https://github.com/maronnix)
> - **Оригинальный репозиторий:** [Flowseal/tg-ws-proxy](https://github.com/Flowseal/tg-ws-proxy)
> - Данный форк был **переработан с использованием ИИ** (правки кода, документации и структуры репозитория).
> - Форк распространяется на условиях оригинальной лицензии **MIT** (см. раздел «Лицензия»).
>
> Все претензии, вопросы и предложения по **этому форку** — к его автору (maronnix).  
> За оригинальный проект отвечает его автор — Flowseal.

# TG WS Proxy

**Локальный MTProto-прокси** для Telegram Desktop, который **ускоряет работу Telegram**, перенаправляя трафик через WebSocket-соединения. Данные передаются в том же зашифрованном виде, а для работы не нужны сторонние серверы.

<picture>
  <source srcset="./images/preview-dark.png" media="(prefers-color-scheme: dark)">
  <img src="./images/preview-white.png">
</picture>

## Навигация

- **🚀 Быстрый старт**
  - **[Windows](./RU/README.windows.md)**
  - **[macOS](./RU/README.macos.md)**
  - **[Linux](./RU/README.linux.md)**
  - **[Docker](./RU/README.docker.md)**
- [Настройка Cloudflare Worker'а (бесплатный аналог CF-прокси)](./RU/CfWorker.md)
- [Настройка Cloudflare-домена (CF-прокси)](./RU/CfProxy.md)
- [Тестовое окружение Telegram (тестовые DC)](./RU/TestDc.md)
- [Fake TLS + upstream в Nginx](./RU/FakeTlsNginx.md)
- [Файлы конфигурации Tray-приложения](./RU/TrayConfig.md)
- [Установка из исходников](./RU/BuildFromSource.md)
- [Руководство для контрибьюторов](./CONTRIBUTING.md)

## Windows: быстрый вход

Перейдите на [страницу релизов](https://github.com/maronnix/tg-ws-proxy/releases) и скачайте:

- `TgWsProxy_windows.exe` (Windows 10+ x64)
- `TgWsProxy_windows_arm64.exe` (Windows 10+ ARM64)
- `TgWsProxy_windows_7_64bit.exe` (Windows 7 x64)
- `TgWsProxy_windows_7_32bit.exe` (Windows 7 x32)

При первом запуске откроется окно с инструкцией по подключению Telegram Desktop. **Приложение сворачивается в системный трей.**

### Меню трея

- **Открыть в Telegram** — автоматически настроить прокси через ссылку `tg://proxy`
- **Скопировать ссылку** — скопировать ссылку для подключения
- **Перезапустить прокси** — перезапуск без выхода из приложения
- **Настройки...** — GUI-редактор конфигурации (версия приложения, опциональная проверка обновлений с GitHub)
- **Открыть логи** — открыть файл логов
- **Выход** — остановить прокси и закрыть приложение

### Настройка Telegram Desktop

**Автоматическая настройка**

Щелкните правой кнопкой мыши по значку в трее и выберите **«Открыть в Telegram»**.

Если не сработало (Telegram не открылся с подключением), выполните шаги ниже:

1. Щелкните правой кнопкой мыши по значку в трее и выберите **«Скопировать ссылку»**
2. Отправьте ссылку в «Избранное» в Telegram и нажмите по ней левой кнопкой мыши
3. Подключитесь

**Ручная настройка**

1. Telegram → **Настройки** → **Продвинутые настройки** → **Тип подключения** → **Прокси**
2. Добавьте прокси:
   - **Тип:** MTProto
   - **Сервер:** `127.0.0.1` (или переопределенный вами)
   - **Порт:** `1443` (или переопределенный вами)
   - **Secret:** из настроек или логов

## Как это работает
Telegram Desktop → MTProto Proxy (127.0.0.1:1443) → WebSocket → Telegram DC

1. Приложение поднимает MTProto прокси на `127.0.0.1:1443`
2. Перехватывает подключения к IP-адресам Telegram
3. Извлекает DC ID из MTProto obfuscation init-пакета
4. Устанавливает WebSocket-соединение (TLS) к соответствующему DC через домены Telegram
5. Если WS недоступен (302 redirect) — автоматически переключается на CfProxy / прямое TCP-соединение

> [!IMPORTANT] 
> ### Не грузит фото/видео?
> **Удалите в настройках прокси в DC → IP всё, кроме `4:149.154.167.220`**  
> **Если это не помогло, полностью очистите это поле**  
> Подобная проблема встречается на аккаунтах без Premium  
> Если это не помогло, настройте собственный домен по инструкции: [CfProxy.md](./RU/CfProxy.md)

## Автоматическая сборка

Проект содержит спецификации PyInstaller ([`packaging/windows.spec`](../packaging/windows.spec), [`packaging/macos.spec`](../packaging/macos.spec), [`packaging/linux.spec`](../packaging/linux.spec)) и GitHub Actions workflow ([`.github/workflows/build.yml`](../.github/workflows/build.yml)) для автоматической сборки.

Минимально поддерживаемые версии ОС для текущих бинарных сборок:

- Windows 10+ x64 для `TgWsProxy_windows.exe`
- Windows 10+ ARM64 для `TgWsProxy_windows_arm64.exe`
- Windows 7 (x64) для `TgWsProxy_windows_7_64bit.exe`
- Windows 7 (x32) для `TgWsProxy_windows_7_32bit.exe`
- Intel macOS 10.15+
- Apple Silicon macOS 11.0+
- Linux x86_64 (требуется AppIndicator для системного трея)

## Благодарности

- Оригинальный проект: [Flowseal/tg-ws-proxy](https://github.com/Flowseal/tg-ws-proxy)
- Автор данного форка: [maronnix](https://github.com/maronnix)
- Форк переработан с использованием ИИ

## Лицензия

Проект распространяется под лицензией **MIT**.  
Оригинальный код и идея принадлежат автору [Flowseal](https://github.com/Flowseal).  
Данный форк является производной работой и распространяется на тех же условиях.

Полный текст лицензии: [MIT License](../LICENSE)
