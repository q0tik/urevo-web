#!/usr/bin/env python3
"""Подключается к дорожке по адресу, снимает карту GATT, подписывается на все
notify/indicate и логирует поток. Расшифровывает стандартную FTMS Treadmill Data
и подсвечивает байтовые поля, которые монотонно растут (кандидаты в шаги/дистанцию/время).

Запуск:  ./.venv/bin/python capture.py <ADDR> [секунды]
"""
import asyncio
import sys
import time
from collections import defaultdict
from bleak import BleakClient

FTMS_TREADMILL_DATA = "00002acd-0000-1000-8000-00805f9b34fb"
FTMS_SERVICE = "00001826-0000-1000-8000-00805f9b34fb"

t0 = time.monotonic()


def ts():
    return f"{time.monotonic() - t0:7.2f}"


def uuid_short(u):
    u = u.lower()
    if u.startswith("0000") and u.endswith("-0000-1000-8000-00805f9b34fb"):
        return "0x" + u[4:8]
    return u


def hexs(data: bytes) -> str:
    return " ".join(f"{b:02x}" for b in data)


def parse_treadmill(data: bytes) -> str:
    try:
        i = 0
        flags = int.from_bytes(data[i:i+2], "little"); i += 2
        out = []
        speed = int.from_bytes(data[i:i+2], "little") / 100; i += 2
        out.append(f"speed={speed:.2f}km/h")
        if flags & 0x0002:
            out.append(f"avgSpd={int.from_bytes(data[i:i+2],'little')/100:.2f}"); i += 2
        if flags & 0x0004:
            d = data[i] | (data[i+1] << 8) | (data[i+2] << 16); i += 3
            out.append(f"dist={d}m")
        if flags & 0x0008:
            out.append(f"incl={int.from_bytes(data[i:i+2],'little',signed=True)/10}%"); i += 2
            out.append(f"ramp={int.from_bytes(data[i:i+2],'little',signed=True)/10}"); i += 2
        if flags & 0x0010: i += 6; out.append("elev±")
        if flags & 0x0020:
            out.append(f"pace={int.from_bytes(data[i:i+2],'little')}"); i += 2
        if flags & 0x0040: i += 2; out.append("avgPace")
        if flags & 0x0080:
            out.append(f"kcal={int.from_bytes(data[i:i+2],'little')}"); i += 2
            i += 2 + 1  # energy per hour + per minute
        if flags & 0x0100:
            out.append(f"hr={data[i]}"); i += 1
        if flags & 0x0200: i += 1
        if flags & 0x0400:
            out.append(f"elapsed={int.from_bytes(data[i:i+2],'little')}s"); i += 2
        if flags & 0x0800:
            out.append(f"remain={int.from_bytes(data[i:i+2],'little')}s"); i += 2
        return f"flags=0x{flags:04x} " + " ".join(out)
    except Exception as e:
        return f"(parse err: {e})"


# Отслеживаем «растущие счётчики»: для каждой характеристики и каждого смещения
# смотрим uint16 (LE) и проверяем, монотонно ли он растёт между уведомлениями.
class Growth:
    def __init__(self):
        self.last = defaultdict(dict)   # uuid -> {offset: value}
        self.grew = defaultdict(set)    # uuid -> set(offset) which increased
        self.samples = defaultdict(int)

    def feed(self, uuid, data: bytes):
        self.samples[uuid] += 1
        for off in range(0, len(data) - 1):
            val = data[off] | (data[off + 1] << 8)
            prev = self.last[uuid].get(off)
            if prev is not None and 0 < val - prev < 500:
                self.grew[uuid].add(off)
            self.last[uuid][off] = val

    def report(self):
        print("\n=== Кандидаты в счётчики (uint16 LE, монотонно растут) ===")
        any_ = False
        for uuid, offs in self.grew.items():
            if offs:
                any_ = True
                print(f"  {uuid_short(uuid)}: смещения байт {sorted(offs)} "
                      f"(из {self.samples[uuid]} уведомлений)")
        if not any_:
            print("  (не нашёл — возможно, мало данных: нужно реально идти во время записи)")


async def main():
    if len(sys.argv) < 2:
        print("Использование: capture.py <ADDR> [секунды]")
        return
    addr = sys.argv[1]
    dur = float(sys.argv[2]) if len(sys.argv) > 2 else 90.0
    growth = Growth()

    print(f"Подключаюсь к {addr} …")
    async with BleakClient(addr) as client:
        print(f"Подключено: {client.is_connected}\n")

        print("=== Карта GATT ===")
        notif_chars = []
        for svc in client.services:
            print(f"service {uuid_short(svc.uuid)}  ({svc.uuid})")
            for c in svc.characteristics:
                props = ",".join(c.properties)
                line = f"  {uuid_short(c.uuid)}  [{props}]"
                if "read" in c.properties:
                    try:
                        v = await client.read_gatt_char(c)
                        txt = "".join(chr(b) if 32 <= b < 127 else "." for b in v)
                        line += f"  = {hexs(v)}  \"{txt}\""
                    except Exception as e:
                        line += f"  (read err: {e})"
                print(line)
                if "notify" in c.properties or "indicate" in c.properties:
                    notif_chars.append(c)

        print(f"\n=== Подписываюсь на {len(notif_chars)} характеристик, запись {dur:.0f} c ===")
        print("*** ИДИ СЕЙЧАС: пройдись, поменяй скорость пультом. ***\n")

        def make_handler(uuid):
            is_tread = uuid.lower() == FTMS_TREADMILL_DATA
            def handler(_char, data: bytearray):
                data = bytes(data)
                growth.feed(uuid, data)
                extra = "  " + parse_treadmill(data) if is_tread else ""
                print(f"{ts()}  NOTIF {uuid_short(uuid):8s} {hexs(data)}{extra}")
            return handler

        for c in notif_chars:
            try:
                await client.start_notify(c, make_handler(c.uuid))
            except Exception as e:
                print(f"  подписка на {uuid_short(c.uuid)} не удалась: {e}")

        await asyncio.sleep(dur)

        for c in notif_chars:
            try:
                await client.stop_notify(c)
            except Exception:
                pass

    growth.report()
    print("\nГотово.")


asyncio.run(main())
