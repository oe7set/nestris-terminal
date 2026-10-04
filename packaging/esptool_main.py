"""Entry point of the bundled esptool.exe (GPL-2.0-or-later, Espressif).

A separate program on purpose: the terminal only runs it on the command line
to flash the reader (nestris_terminal/updates/service.py), it never imports it.
"""

import esptool

if __name__ == "__main__":
    esptool._main()
