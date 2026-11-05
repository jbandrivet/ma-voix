#!/usr/bin/env python3
"""Télécharge la voix Siwis (63 Mo, trop lourde pour le dépôt) et vérifie qu'elle est intacte."""
import hashlib
import os
import urllib.request

ICI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHEMIN = os.path.join(ICI, "voix", "fr_FR-siwis-medium.onnx")
URL = ("https://huggingface.co/rhasspy/piper-voices/resolve/main/"
       "fr/fr_FR/siwis/medium/fr_FR-siwis-medium.onnx")
SHA256 = "641d1ab097da2b81128c076810edb052b385decc8be3381814802a64a73baf99"


def empreinte(chemin):
    h = hashlib.sha256()
    with open(chemin, "rb") as f:
        for bloc in iter(lambda: f.read(1 << 20), b""):
            h.update(bloc)
    return h.hexdigest()


if __name__ == "__main__":
    if not (os.path.exists(CHEMIN) and empreinte(CHEMIN) == SHA256):
        urllib.request.urlretrieve(URL, CHEMIN + ".tmp")
        if empreinte(CHEMIN + ".tmp") != SHA256:
            os.remove(CHEMIN + ".tmp")
            raise SystemExit("La voix téléchargée n'est pas la bonne : arrêt.")
        os.replace(CHEMIN + ".tmp", CHEMIN)
    print("Voix prête :", CHEMIN)
