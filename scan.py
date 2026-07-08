#!/usr/bin/env python3
"""Сканирует BLE-эфир ~10 c и печатает все устройства с именами/сервисами.
Задача — найти дорожку и её адрес (на macOS это CoreBluetooth-UUID)."""
import asyncio
from bleak import BleakScanner


async def main():
    print("Сканирую 10 секунд… (дорожка должна быть включена и НЕ подключена к приложению)\n")
    found = {}

    def cb(device, adv):
        found[device.address] = (device, adv)

    scanner = BleakScanner(detection_callback=cb)
    await scanner.start()
    await asyncio.sleep(10.0)
    await scanner.stop()

    if not found:
        print("Ничего не найдено. Проверь: Bluetooth включён, дорожка включена, "
              "родное приложение закрыто, и терминалу выдан доступ к Bluetooth в "
              "Системных настройках → Конфиденциальность → Bluetooth.")
        return

    # Сортируем по силе сигнала — дорожка рядом, будет вверху.
    items = sorted(found.values(), key=lambda x: -(x[1].rssi or -999))
    print(f"Найдено устройств: {len(items)}\n")
    for device, adv in items:
        name = device.name or adv.local_name or "(без имени)"
        rssi = adv.rssi
        svcs = ", ".join(adv.service_uuids) if adv.service_uuids else "—"
        print(f"  {name:28s}  rssi={rssi:>5}  addr={device.address}")
        print(f"      services: {svcs}")
    print("\nНайди свою дорожку (имя вроде Urevo/SpaceWalk/FS-.., самый сильный rssi) "
          "и скажи мне её addr — подключусь и запишу сигналы.")


asyncio.run(main())
