# Node Desk 4.0

Тёмный настольный клиент для SSH-серверов и Tailscale. Поддержка Debian/Linux и macOS.

## Возможности

- Несколько SSH-серверов с названием, описанием, IP, портом и username.
- Список с поиском, карточки редактирования и кнопка подключения справа.
- Открытие отдельной SSH-сессии в системном терминале: Terminal на Mac, установленный терминал на Linux.
- Пароли в macOS Keychain или Linux Secret Service, отдельно для каждой записи.
- Tailscale: сохранение IP exit node, статус и единая кнопка подключения/отключения.
- Два отдельных GitHub Release для каждой версии: Debian и macOS.

## Debian

```sh
sudo apt install ./node-desk_4.0.0_all.deb
```

Запуск: **Node Desk** в меню или `node-desk`. Старое имя команды `tailscale-exit-ui` также работает.
Пакет заменяет прежний `tailscale-exit-ui`; серверы, пароли и настройки сохраняются.
Tailscale устанавливается отдельно. Для управления им без sudo один раз выполните:

```sh
sudo tailscale set --operator="$USER"
```

Это разрешает вашему пользователю управлять Tailscale, включая остальные настройки.

## macOS

Для готовых сборок требуется macOS 15+. Выберите DMG для процессора:

- `node-desk_4.0.0_macos_arm64.dmg` — Apple Silicon.
- `node-desk_4.0.0_macos_x86_64.dmg` — Intel.

Откройте DMG и перетащите **Node Desk.app** в **Applications**.
Python и зависимости входят в приложение. SSH уже есть в macOS; Tailscale устанавливается отдельно.
Первый запуск может запросить доступ к Keychain и разрешение управления Terminal — оно используется только для открытия SSH-консоли.

Автоматические сборки имеют ad-hoc подпись и не проходят Apple notarization. macOS может заблокировать первый запуск; разрешение открывается в **System Settings → Privacy & Security**. Для обычного распространения с Developer ID нужна подпись своим сертификатом и notarization. Настройка notarization в текущий workflow не входит.

Tailscale ищется в PATH, `/Applications/Tailscale.app`, пользовательском `~/Applications` и стандартных каталогах Homebrew. Для встроенного CLI задаётся `TAILSCALE_BE_CLI=1`. Откройте Tailscale и авторизуйтесь до использования вкладки VPN. Linux-команда назначения оператора для macOS GUI не требуется приложению.

## Использование

«+ Добавить сервер» открывает форму. Название, IP и пользователь обязательны, порт по умолчанию 22. Описание — произвольное. «Сохранить» возвращает к списку.
Кнопка «Подключиться» справа запускает SSH в отдельном терминале. Нажатие на карточку или «Открыть →» открывает редактирование. Сервер и его пароль можно удалить после подтверждения.

Пустое поле пароля при редактировании сохраняет прежний пароль. После сохранения оно очищается, а подпись сообщает о сохранённом пароле. Для удаления есть отдельная кнопка. Изменение названия и описания не теряет пароль. Даже записи с одинаковыми параметрами подключения имеют собственные пароли.

Пароли не записываются в JSON и не передаются через argv или переменные окружения. OpenSSH использует отдельный askpass helper. Если системное хранилище недоступно, приложение показывает ошибку. Сохранение в незашифрованный файл не предусмотрено. Ключи SSH и OTP/2FA обрабатывает OpenSSH. Первый неизвестный ключ сервера нужно подтвердить; проверка host key остаётся включённой.

Статус SSH виден в терминале. После ошибки он остаётся открытым до Enter. Закрытие приложения не завершает уже открытые SSH-сессии.

Во вкладке Tailscale «Сохранить» запоминает IP без подключения. Корректный IP также сохраняется при закрытии. Статус обновляется каждые 3 секунды. «Подключён» означает, что Tailscale работает, exit node выбран и сообщает Online; отдельной проверки доступа к интернету нет. Отключение убирает только exit node. Закрытие окна не отключает VPN.

Данные настроек:

- Debian: `~/.config/tailscale-exit-ui/` (учитывается `XDG_CONFIG_HOME` для совместимости).
- macOS: `~/Library/Application Support/Node Desk/`.

Пароли остаются в системном хранилище конкретного компьютера и не переносятся вместе с JSON.

## Запуск исходников

Debian:

```sh
sudo apt install python3 python3-tk python3-keyring python3-secretstorage openssh-client xterm
python3 node-desk.py
```

На минимальном рабочем столе для паролей понадобится служба Secret Service, например `gnome-keyring` с `dbus-user-session` и повторным входом в графический сеанс.

macOS с Homebrew:

```sh
brew install python@3.13 python-tk@3.13
"$(brew --prefix python@3.13)/bin/python3.13" -m venv .venv
.venv/bin/python -m pip install -r requirements-macos.txt
.venv/bin/python node-desk.py
```

Исходники `node-desk.py`, `ssh_client.py`, `ssh_helper.py` и `platform_support.py` должны находиться рядом. Helper для запуска из исходников создаётся автоматически с правильным интерпретатором. Он содержит только пути к программам.

## Тесты и сборка

```sh
python3 -m unittest discover -p 'test_*.py' -v
python3 scripts/build_deb.py
```

Debian-пакет будет в `dist/`. Сборка не требует sudo; нужен `dpkg-deb`.
Сборка macOS выполняется на Mac и использует архитектуру текущего Python:

```sh
.venv/bin/python scripts/build_macos.py
```

Скрипт собирает `Node Desk.app` и отдельный console helper через PyInstaller, проверяет подпись, запускает helper и проверку интерфейса на временных данных, затем создаёт DMG в `dist/`. С реальными серверами smoke test не соединяется, Keychain не читает. `MACOS_SIGN_IDENTITY` задаёт необязательную identity для codesign; по умолчанию `-` (ad-hoc). После подписи для распространения с Developer ID потребуется отдельно настроить notarization.

## Два релиза на GitHub

Workflow: `.github/workflows/release.yml`.

1. Версия задаётся в `VERSION`.
2. Commit и push изменений в свой репозиторий.
3. Push базового тега, совпадающего с версией:

```sh
git add .
git commit -m "Add macOS support and dual-platform releases"
git push origin HEAD
git tag v4.0.0
git push origin v4.0.0
```

GitHub Actions собирает Debian-пакет, macOS arm64 и macOS x86_64 на соответствующих runner. Перед публикацией выполняются тесты и smoke test интерфейса. Успешные сборки создают два отдельных релиза на одном исходном commit:

- `v4.0.0-debian` — `.deb`.
- `v4.0.0-macos` — два `.dmg`, для Apple Silicon и Intel.

Для GitHub Release используется стандартный `GITHUB_TOKEN` с `contents: write` только у задач публикации. Личный токен не нужен. Политика организации должна разрешать запись в Releases. Ошибка одной платформы не публикует её релиз и не мешает успешному релизу другой.

Workflow можно сначала запустить вручную через **Actions → Build Debian and macOS releases → Run workflow**. При ручном запуске с ветки он только соберёт артефакты, без публикации Releases. Бинарные файлы не нужно коммитить в Git.

## Проверено в текущей среде

Локальные тесты платформенных адаптеров и сборка `.deb` выполняются на Linux. macOS-приложение, Keychain, Terminal и GUI должны пройти проверку на macOS runner после отправки workflow на GitHub. До успешного запуска CI готового проверенного DMG нет.

Документация: [Tailscale CLI](https://tailscale.com/docs/reference/tailscale-cli?tab=macos), [PyInstaller](https://pyinstaller.org/en/stable/usage.html), [Homebrew Python/Tk](https://formulae.brew.sh/formula/python-tk@3.13).
