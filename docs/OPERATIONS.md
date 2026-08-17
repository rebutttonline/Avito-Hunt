# Эксплуатация Avito Hunt

## Сервер

- Host: `193.233.137.65`
- ОС: Ubuntu 24.04
- Каталог приложения: `/opt/avito-hunt`
- Секреты: `/etc/avito-hunt/avito-hunt.env`
- Бэкапы: `/var/backups/avito-hunt`
- Compose project: `avito-hunt`

Приложение не публикует сетевые порты и не конфликтует с Amnezia VPN.

SSH принимает только ключи. Вход по паролю отключён, а `root` разрешён только с ключом. Ключ GitHub Actions ограничен принудительным запуском production deploy-скрипта и не открывает интерактивную оболочку.

## Добавление Telegram-токена

Подключиться администратором:

```bash
ssh root@193.233.137.65
```

Открыть файл секретов:

```bash
nano /etc/avito-hunt/avito-hunt.env
```

Заполнить строку `TELEGRAM_BOT_TOKEN=`, сохранить через `Ctrl+O`, Enter и выйти через `Ctrl+X`. Затем применить конфигурацию:

```bash
/usr/local/sbin/deploy-avito-hunt
```

Токен нельзя коммитить, отправлять в issue или публиковать в логах.

## Состояние и логи

```bash
cd /opt/avito-hunt
docker compose --env-file /etc/avito-hunt/avito-hunt.env ps
docker compose --env-file /etc/avito-hunt/avito-hunt.env logs --tail=100 bot worker
```

## Тестовое уведомление

Команда создаёт внутри базы десять тестовых аналогов и один явно помеченный тестовый вариант ниже рынка. Она использует настоящий production-алгоритм и отправляет сообщение всем активным пользователям:

```bash
cd /opt/avito-hunt
docker compose --env-file /etc/avito-hunt/avito-hunt.env run --rm worker \
  python -m avito_hunt.demo_alert
```

Тестовые ссылки ведут только на главную страницу Avito и не являются реальными объявлениями.

## Ручное развёртывание

```bash
/usr/local/sbin/deploy-avito-hunt
```

Скрипт получает ровно `origin/main`, проверяет Compose-конфигурацию, пересобирает только Avito Hunt и ждёт успешных health checks.

Push в `main` сначала запускает форматирование, линтер и unit-тесты в GitHub Actions. Только после их успеха workflow подключается ограниченным ключом и вызывает deploy-скрипт.

## Резервные копии

Таймер создаёт сжатый дамп PostgreSQL ежедневно около `03:17 UTC` и хранит копии 14 дней.

```bash
systemctl status avito-hunt-backup.timer
systemctl list-timers avito-hunt-backup.timer
/usr/local/sbin/backup-avito-hunt
ls -lh /var/backups/avito-hunt
```

Проверка архива:

```bash
gzip -t /var/backups/avito-hunt/postgres-YYYYMMDDTHHMMSSZ.sql.gz
```

Восстановление следует выполнять только после остановки записи и создания дополнительной резервной копии.

## Откат

Автоматический деплой всегда использует `main`. Для отката нужно вернуть нужный коммит в GitHub через новый revert-коммит и дождаться повторного деплоя. Такой способ сохраняет прозрачную историю изменений.
