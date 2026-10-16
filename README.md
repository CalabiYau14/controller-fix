# controller-fix

Macht einen USB-Controller im Android-Modus (`0502:1309`, „Nintendo Co., Ltd.
Android“) unter Linux in Chromium und damit in Amazon Luna nutzbar.

## Problem

Linux erkennt den Controller, aber Chromium kennt seine USB-ID nicht und meldet
ihn Webseiten ohne `standard`-Mapping. Amazon Luna ignoriert solche Controller.

## Lösung

`controller-fix.py` greift den Controller exklusiv ab und gibt alle Eingaben über
ein virtuelles Gerät mit der Kennung eines Xbox-360-Controllers (`045e:028e`)
aus. Diesen erkennt Chromium als Standard-Gamepad.

Voraussetzungen: Python 3 und Schreibrechte auf `/dev/uinput` (bei systemd-logind
meist schon per ACL vorhanden, prüfen mit `getfacl /dev/uinput`). Weitere
Abhängigkeiten gibt es nicht.

## Benutzung

```sh
./controller-fix.py
```

Das Skript läuft, bis es beendet wird. Der Controller kann dabei ab- und wieder
angesteckt werden. Chromium muss nicht neu gestartet werden.

Zum Testen https://hardwaretester.com/gamepad öffnen und eine Taste drücken. Dort
sollte `Microsoft X-Box 360 pad (STANDARD GAMEPAD Vendor: 045e Product: 028e)`
erscheinen.

## Original-Controller verstecken

Ohne weiteres Zutun sieht Chromium den Original-Controller zusätzlich und listet
ihn vor dem Xbox-Pad. Webseiten wie Luna nehmen dann den falschen. Die
udev-Regel `69-controller-fix.rules` blendet ihn aus:

```sh
sudo install -m 644 69-controller-fix.rules /etc/udev/rules.d/
sudo udevadm control --reload
```

Danach den Controller einmal ab- und wieder anstecken.

## Tastenbelegung anpassen

Sind Tasten vertauscht, zeigt

```sh
./controller-fix.py --monitor
```

welchen Code jede Taste und Achse sendet (das Skript darf dabei nicht parallel
laufen, sonst kommen keine Eingaben an). Die Zuordnung steht oben im Skript in
`KEY_MAP` und `ABS_MAP`.

## Autostart (optional)

Als systemd-User-Dienst unter `~/.config/systemd/user/controller-fix.service`:

```ini
[Unit]
Description=Controller als Xbox-360-Pad ausgeben

[Service]
ExecStart=/pfad/zu/controller-fix/controller-fix.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
```

```sh
systemctl --user enable --now controller-fix.service
```
