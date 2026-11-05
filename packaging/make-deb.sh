#!/bin/sh
# Fabrique ma-voix_<version>_amd64.deb à partir de ma_voix.py
# Les phrases d'origine se préparent avant : python3 ma_voix.py --preparer-sons sons
set -eu
ICI=$(cd "$(dirname "$0")/.." && pwd)
SRC="$ICI/ma_voix.py"
VERSION=$(sed -n 's/^VERSION = "\(.*\)"/\1/p' "$SRC")
PKG=ma-voix
BUILD=$(mktemp -d)
R="$BUILD/${PKG}_${VERSION}_amd64"
trap 'rm -rf "$BUILD"' EXIT
[ -n "$(ls "$ICI/sons" 2>/dev/null)" ] || { echo "dossier sons vide : voir l'en-tête de ce script" >&2; exit 1; }
python3 "$ICI/outils/telecharger_voix.py"

install -d "$R/DEBIAN" "$R/usr/bin" "$R/usr/share/applications" "$R/usr/share/$PKG" "$R/usr/share/doc/$PKG"
sed '1s|^#!.*|#!/usr/bin/python3|' "$SRC" > "$R/usr/bin/$PKG"
chmod 755 "$R/usr/bin/$PKG"
rsync -a --exclude __pycache__ "$ICI/symboles" "$ICI/sons" "$ICI/voix" "$ICI/piper" "$R/usr/share/$PKG/"
find "$R/usr/share/$PKG" -type d -exec chmod 755 {} +
find "$R/usr/share/$PKG" -type f -exec chmod 644 {} +

# Icônes, dessinées par le programme lui-même
python3 -B - "$SRC" "$R/usr/share/icons/hicolor" <<'PY'
import os, sys, importlib.util
spec = importlib.util.spec_from_file_location("ma_voix", sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
for t in (16, 24, 32, 48, 64, 128, 256):
    d = os.path.join(sys.argv[2], f"{t}x{t}", "apps")
    os.makedirs(d, exist_ok=True)
    m.icone(t).save(os.path.join(d, "ma-voix.png"))
PY

cat > "$R/usr/share/applications/$PKG.desktop" <<DESK
[Desktop Entry]
Version=1.0
Type=Application
Name=Ma Voix
GenericName=Parler avec des symboles
Comment=Parler avec des symboles, sans lire ni écrire
Keywords=handicap;communication;symboles;pictogrammes;voix;parole;CAA;
Exec=/usr/bin/$PKG
Icon=$PKG
Terminal=false
StartupWMClass=Ma-voix
Categories=Utility;Accessibility;
DESK

cat > "$R/usr/share/doc/$PKG/copyright" <<'COPY'
Ma Voix
Programme : licence GPL version 3 ou suivante (voir /usr/share/common-licenses/GPL-3).

Pictogrammes (symboles/) : Sergio Palao. Origine : ARASAAC (https://arasaac.org).
Licence : Creative Commons BY-NC-SA 4.0. Propriété : Gouvernement d'Aragon (Espagne).
Usage non commercial uniquement.
Coche, croix et flèche (oui.png, non.png, suivant.png) : dessinées pour ce logiciel.

Piper 1.8.0 (piper/) : licence GPL version 3 ou suivante, avec espeak-ng (GPL 3).
Code source : https://github.com/OHF-voice/piper1-gpl
pathvalidate : licence MIT.

Voix française Siwis (voix/ et sons/) : licence Creative Commons BY 4.0.

ACAT est un logiciel d'Intel. Ma Voix s'inspire de son principe de défilement
mais n'en contient aucun code et n'est ni lié à Intel ni approuvé par Intel.
COPY

TAILLE=$(du -sk "$R/usr" | cut -f1)
# python3-onnxruntime : obligatoire là où il existe. Il manque aux systèmes à Python ancien (Ubuntu 24.04) :
# l'alternative laisse l'installation passer, et seules les phrases ajoutées auront la voix de robot.
cat > "$R/DEBIAN/control" <<CTRL
Package: $PKG
Version: $VERSION
Section: misc
Priority: optional
Architecture: amd64
Installed-Size: $TAILLE
Depends: python3 (>= 3.9), python3-tk, python3-pil, python3-pil.imagetk, espeak-ng, alsa-utils, fonts-dejavu-core, python3-onnxruntime | python3 (<< 3.13)
Recommends: python3-onnxruntime, xdg-user-dirs
Maintainer: Jean-Baptiste Andrivet <146567424+jbandrivet@users.noreply.github.com>
Description: Parler avec des symboles, sans lire ni écrire
 Pour une personne en situation de handicap mental et physique. L'écran ne
 montre que de grands symboles : un choix, une phrase dite à voix haute.
 Se pilote au toucher, en restant sur un symbole, ou avec un ou deux contacts.
CTRL

dpkg-deb --root-owner-group -Zxz --build "$R" "$ICI/${PKG}_${VERSION}_amd64.deb"
ls -la "$ICI/${PKG}_${VERSION}_amd64.deb"
