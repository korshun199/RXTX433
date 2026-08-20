# Восстановление HappyModel ES900TX на FCC915

## Проверенное оборудование

- Модуль: HappyModel ES900TX
- MCU: ESP32-D0WDQ6-V3, revision 3.1
- Flash: 4 MB
- USB-UART: CP2102, `/dev/ttyUSB0`
- MAC проверенного экземпляра: `d4:8c:49:b4:9e:0c`

## Причина восстановления

Экспериментальная сборка ExpressLRS 3.3.1 использовала домен
`EU433` (`domain: 5`). Модуль возвращён на штатный диапазон оборудования:
`FCC915` (`domain: 1`).

## Сборка

Правки ExpressLRS сохранены в:

`patches/expresslrs-3.3.1-fcc915.patch`

Применение и сборка:

```sh
cd upstream/ExpressLRS-3.3.1
git apply ../../patches/expresslrs-3.3.1-fcc915.patch
cd src
pio run -e HappyModel_TX_ES900TX_via_UART
```

## Прошивка и проверка

Перед записью был считан полный локальный дамп 4 MB. Дамп намеренно не
публикуется, поскольку содержит индивидуальные настройки устройства.

Прошивка выполнена командой:

```sh
pio run -e HappyModel_TX_ES900TX_via_UART -t upload --upload-port /dev/ttyUSB0
```

После записи отдельно проверены четыре области Flash:

- bootloader: `0x1000`, 17440 байт;
- partition table: `0x8000`, 3072 байта;
- boot_app0: `0xe000`, 8192 байта;
- firmware: `0x10000`, 1482324 байта.

Для каждой области `esptool verify_flash` сообщил `digest matched`.

Проверенный релиз:

`releases/HappyModel_ES900TX/3.3.1_FCC915/firmware.bin`

SHA-256:

`d71e233ca6fdd645376adf98b322bafe7efbf6c1f7538d8f75eb669116e33a21`

Олежка подтвердил нормальную загрузку и работу передатчика после установки
DIP 1 и 2 в `ON`, а DIP 3-6 в `OFF`.
