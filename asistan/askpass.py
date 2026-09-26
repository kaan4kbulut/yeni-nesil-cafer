"""sudo için grafik parola penceresi (SUDO_ASKPASS): güvenlik ajanının onayladığı yönetici komutları için.

sudo bu programı çalıştırır; girilen parolayı yalnızca sudo'ya (standart çıktıya) verir, hiçbir yere kaydetmez.
Vazgeçilirse sıfır olmayan çıkış kodu döner ve sudo komutu çalıştırmaz.
"""

import os
import sys


def main() -> int:
    from PySide6.QtWidgets import QApplication, QInputDialog, QLineEdit

    app = QApplication(sys.argv[:1])
    command = os.environ.get("YA_SUDO_COMMAND", "")[:400]
    text = ("YENİ NESİL CAFER bu işlem için yönetici (sudo) parolanı istiyor:\n\n"
            f"{command}\n\nGüvenlik ajanı bu işlemi onayladı. Parolan kaydedilmez; vazgeçersen işlem yapılmaz.")
    password, ok = QInputDialog.getText(None, "Yönetici parolası", text, QLineEdit.Password)
    del app
    if not ok:
        return 1
    sys.stdout.write(password + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
