"""`python -m asistan <komut>`: komut satırı (asistan/arayuz/komut). Masaüstü `main.py` ile açılır."""

import sys

from .arayuz.komut import ana

sys.exit(ana())
