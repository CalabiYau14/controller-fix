#!/usr/bin/env python3
"""USB-Controller im Android-Modus als Xbox-360-Controller ausgeben.

Chromium kennt den Controller 0502:1309 ("Nintendo Co., Ltd. Android") nicht
und reicht ihn ohne "standard"-Mapping an Webseiten weiter, weshalb Amazon
Luna ihn ignoriert. Dieses Skript greift das Originalgerät exklusiv ab und
spiegelt alle Eingaben auf ein virtuelles Gerät mit der Kennung eines
Xbox-360-Controllers (045e:028e), das Chromium als Standard-Gamepad erkennt.

Benötigt nur Python 3 und Schreibzugriff auf /dev/uinput.
"""

import argparse
import errno
import fcntl
import glob
import os
import signal
import struct
import sys
import time

# Kennung des echten Controllers (siehe lsusb).
CONTROLLER_VENDOR = 0x0502
CONTROLLER_PRODUCT = 0x1309

# linux/input-event-codes.h
EV_SYN, EV_KEY, EV_ABS = 0x00, 0x01, 0x03
SYN_REPORT = 0
BUS_USB = 0x03

BTN_A, BTN_B, BTN_C, BTN_X, BTN_Y, BTN_Z = range(0x130, 0x136)
BTN_TL, BTN_TR, BTN_TL2, BTN_TR2 = range(0x136, 0x13A)
BTN_SELECT, BTN_START, BTN_MODE, BTN_THUMBL, BTN_THUMBR = range(0x13A, 0x13F)

ABS_X, ABS_Y, ABS_Z, ABS_RX, ABS_RY, ABS_RZ = range(0x00, 0x06)
ABS_GAS, ABS_BRAKE = 0x09, 0x0A
ABS_HAT0X, ABS_HAT0Y = 0x10, 0x11

# ioctl-Nummern aus linux/input.h und linux/uinput.h
EVIOCGRAB = 0x40044590
EVIOCGABS = 0x80184540  # + Achsencode
UI_SET_EVBIT = 0x40045564
UI_SET_KEYBIT = 0x40045565
UI_SET_ABSBIT = 0x40045567
UI_DEV_SETUP = 0x405C5503
UI_ABS_SETUP = 0x401C5504
UI_DEV_CREATE = 0x5501
UI_DEV_DESTROY = 0x5502

INPUT_EVENT = struct.Struct("llHHi")  # struct input_event
ABSINFO = struct.Struct("6i")  # value, minimum, maximum, fuzz, flat, resolution

# Das virtuelle Gerät hat dieselben Tasten und Achsen wie ein echter
# Xbox-360-Controller am Kernel-Treiber xpad, damit Chromium dessen Mapping nutzt.
XPAD_NAME = "Microsoft X-Box 360 pad"
XPAD_VENDOR, XPAD_PRODUCT, XPAD_VERSION = 0x045E, 0x028E, 0x0110
XPAD_KEYS = [BTN_A, BTN_B, BTN_X, BTN_Y, BTN_TL, BTN_TR,
             BTN_SELECT, BTN_START, BTN_MODE, BTN_THUMBL, BTN_THUMBR]
STICK = (-32768, 32767, 16, 128)  # minimum, maximum, fuzz, flat
TRIGGER = (0, 255, 0, 0)
HAT = (-1, 1, 0, 0)
XPAD_AXES = {
    ABS_X: STICK, ABS_Y: STICK, ABS_Z: TRIGGER,
    ABS_RX: STICK, ABS_RY: STICK, ABS_RZ: TRIGGER,
    ABS_HAT0X: HAT, ABS_HAT0Y: HAT,
}

# Zuordnung Controller -> virtuelles Xbox-Pad. Falls Tasten vertauscht sind,
# hier anpassen; mit --monitor sieht man, welchen Code eine Taste sendet.
KEY_MAP = {
    BTN_A: BTN_A,  # unten
    BTN_B: BTN_B,  # rechts
    BTN_X: BTN_X,  # links
    BTN_Y: BTN_Y,  # oben
    BTN_TL: BTN_TL,
    BTN_TR: BTN_TR,
    BTN_SELECT: BTN_SELECT,
    BTN_START: BTN_START,
    BTN_MODE: BTN_MODE,
    BTN_THUMBL: BTN_THUMBL,
    BTN_THUMBR: BTN_THUMBR,
}
ABS_MAP = {
    ABS_X: ABS_X,
    ABS_Y: ABS_Y,
    ABS_Z: ABS_RX,  # rechter Stick horizontal
    ABS_RZ: ABS_RY,  # rechter Stick vertikal
    ABS_BRAKE: ABS_Z,  # L2
    ABS_GAS: ABS_RZ,  # R2
    ABS_HAT0X: ABS_HAT0X,
    ABS_HAT0Y: ABS_HAT0Y,
}
# L2/R2 als Tasten; zählen nur, solange der Trigger keine analogen Werte liefert.
TRIGGER_KEY_MAP = {BTN_TL2: ABS_Z, BTN_TR2: ABS_RZ}

CODE_NAMES = {
    (EV_KEY if name.startswith("BTN_") else EV_ABS, code): name
    for name, code in list(globals().items())
    if name.startswith(("BTN_", "ABS_")) and isinstance(code, int)
}


def log(message):
    print(message, file=sys.stderr, flush=True)


class UinputDevice:
    """Virtuelles Eingabegerät über /dev/uinput."""

    def __init__(self, name, vendor, product, version, keys, axes):
        self.fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
        try:
            fcntl.ioctl(self.fd, UI_SET_EVBIT, EV_KEY)
            for code in keys:
                fcntl.ioctl(self.fd, UI_SET_KEYBIT, code)
            fcntl.ioctl(self.fd, UI_SET_EVBIT, EV_ABS)
            for code, (minimum, maximum, fuzz, flat) in axes.items():
                fcntl.ioctl(self.fd, UI_SET_ABSBIT, code)
                fcntl.ioctl(self.fd, UI_ABS_SETUP, struct.pack(
                    "H2x6i", code, 0, minimum, maximum, fuzz, flat, 0))
            fcntl.ioctl(self.fd, UI_DEV_SETUP, struct.pack(
                "4H80sI", BUS_USB, vendor, product, version, name.encode(), 0))
            fcntl.ioctl(self.fd, UI_DEV_CREATE)
        except OSError:
            os.close(self.fd)
            raise

    def emit(self, type_, code, value):
        os.write(self.fd, INPUT_EVENT.pack(0, 0, type_, code, value))

    def close(self):
        fcntl.ioctl(self.fd, UI_DEV_DESTROY)
        os.close(self.fd)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def read_sysfs(path):
    with open(path) as f:
        return f.read().strip()


def find_controller():
    """Gibt das Gamepad-Interface des Controllers zurück, oder None."""
    for sysdir in sorted(glob.glob("/sys/class/input/event*")):
        try:
            vendor = int(read_sysfs(f"{sysdir}/device/id/vendor"), 16)
            product = int(read_sysfs(f"{sysdir}/device/id/product"), 16)
            has_axes = read_sysfs(f"{sysdir}/device/capabilities/abs") != "0"
        except OSError:
            continue
        # Das zweite Interface ("Android Keyboard") hat keine Achsen.
        if (vendor, product) == (CONTROLLER_VENDOR, CONTROLLER_PRODUCT) and has_axes:
            return "/dev/input/" + os.path.basename(sysdir)
    return None


def read_events(fd):
    data = os.read(fd, INPUT_EVENT.size * 64)
    for offset in range(0, len(data), INPUT_EVENT.size):
        _, _, type_, code, value = INPUT_EVENT.unpack_from(data, offset)
        yield type_, code, value


def axis_ranges(fd):
    """Wertebereiche der Achsen aus ABS_MAP, die das Gerät tatsächlich hat."""
    ranges = {}
    for code in ABS_MAP:
        buf = bytearray(ABSINFO.size)
        fcntl.ioctl(fd, EVIOCGABS + code, buf)
        _, minimum, maximum, *_ = ABSINFO.unpack(buf)
        if maximum > minimum:
            ranges[code] = (minimum, maximum)
    return ranges


def scale(value, source, target):
    (smin, smax), (tmin, tmax) = source, target
    value = min(max(value, smin), smax)
    return round(tmin + (value - smin) * (tmax - tmin) / (smax - smin))


def remap(path):
    """Spiegelt den Controller auf ein virtuelles Xbox-Pad, bis er getrennt wird."""
    src = os.open(path, os.O_RDONLY)
    try:
        ranges = axis_ranges(src)
        # Exklusiv abgreifen, damit Chromium vom Original keine Eingaben mehr bekommt.
        fcntl.ioctl(src, EVIOCGRAB, 1)
        with UinputDevice(XPAD_NAME, XPAD_VENDOR, XPAD_PRODUCT, XPAD_VERSION,
                          XPAD_KEYS, XPAD_AXES) as pad:
            log(f"{path} wird als \"{XPAD_NAME}\" ausgegeben.")
            analog_triggers = set()
            while True:
                for type_, code, value in read_events(src):
                    if type_ == EV_SYN and code == SYN_REPORT:
                        pad.emit(EV_SYN, SYN_REPORT, 0)
                    elif type_ == EV_KEY and code in KEY_MAP:
                        pad.emit(EV_KEY, KEY_MAP[code], 1 if value else 0)
                    elif type_ == EV_KEY and code in TRIGGER_KEY_MAP:
                        axis = TRIGGER_KEY_MAP[code]
                        if axis not in analog_triggers:
                            pad.emit(EV_ABS, axis, TRIGGER[1] if value else TRIGGER[0])
                    elif type_ == EV_ABS and code in ranges:
                        axis = ABS_MAP[code]
                        minimum, maximum, *_ = XPAD_AXES[axis]
                        scaled = scale(value, ranges[code], (minimum, maximum))
                        if XPAD_AXES[axis] is TRIGGER and scaled > minimum:
                            analog_triggers.add(axis)
                        pad.emit(EV_ABS, axis, scaled)
    finally:
        os.close(src)


def monitor(path):
    """Zeigt die rohen Eingaben, um KEY_MAP und ABS_MAP anzupassen."""
    src = os.open(path, os.O_RDONLY)
    try:
        log(f"Eingaben von {path} (Strg+C beendet):")
        while True:
            for type_, code, value in read_events(src):
                if type_ in (EV_KEY, EV_ABS):
                    name = CODE_NAMES.get((type_, code), hex(code))
                    print(f"{name:<12} {value}", flush=True)
    finally:
        os.close(src)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--device", help="Eingabegerät des Controllers, z. B. "
                        "/dev/input/event18 (Standard: per USB-ID suchen)")
    parser.add_argument("--monitor", action="store_true",
                        help="nur die rohen Eingaben des Controllers anzeigen")
    args = parser.parse_args()
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    waiting = False
    while True:
        path = args.device or find_controller()
        if path is None or not os.path.exists(path):
            if not waiting:
                log("Warte auf Controller ...")
                waiting = True
            time.sleep(2)
            continue
        waiting = False
        try:
            if args.monitor:
                monitor(path)
            else:
                remap(path)
        except PermissionError as e:
            sys.exit(f"Keine Berechtigung für {e.filename or path}")
        except OSError as e:
            if e.errno == errno.EBUSY:
                sys.exit(f"{path} wird schon von einem anderen Programm abgegriffen.")
            if e.errno != errno.ENODEV:
                raise
            log("Controller getrennt.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
