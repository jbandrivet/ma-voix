#!/usr/bin/env python3
"""Télécharge les pictogrammes ARASAAC choisis et dessine ceux qui sont faits maison.

Chaque numéro a été choisi à l'œil : pas de texte dans l'image, rien d'effrayant.
Pictogrammes : Sergio Palao, ARASAAC, CC BY-NC-SA 4.0, propriété du Gouvernement d'Aragon.
"""
import os
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from PIL import Image, ImageDraw

ICI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOSSIER = os.path.join(ICI, "symboles")

ARASAAC = {
    "alarme": 6214, "maison": 2317,
    # dossiers de l'accueil
    "mal": 2367, "manger": 2349, "emotions": 7251, "toilettes": 2430, "jouer": 35717, "famille": 2392,
    # mal
    "mal_tete": 28753, "mal_ventre": 28765, "mal_dents": 28757, "mal_gorge": 28761,
    "mal_dos": 28785, "mal_oreilles": 28777, "mal_jambe": 28769, "mal_pied": 35809,
    # manger et boire
    "faim": 36655, "soif": 2248, "jus": 11461, "cafe": 2296, "fruit": 28339, "gateau": 10234,
    "fini": 28429, "bon": 2418,
    # émotions
    "content": 31923, "triste": 31939, "colere": 2374, "peur": 31896, "fatigue": 31925,
    "ennui": 28705, "aime": 38891, "aime_pas": 38890,
    # besoins
    "douche": 2370, "dormir": 2369, "froid": 2401, "chaud": 31845, "position": 6248,
    "medicament": 30119, "tranquille": 38932,
    # activités
    "musique": 32131, "tele": 2782, "sortir": 31839, "lire": 31680, "des": 3089,
    "ordinateur": 7214, "dessiner": 8088, "telephone": 2585,
    # personnes
    "maman": 2458, "papa": 31146, "frere": 2423, "soeur": 2422, "ami": 11178,
    "infirmiere": 31390, "medecin": 2467, "calin": 4550,
}


def telecharger(paire):
    nom, num = paire
    chemin = os.path.join(DOSSIER, nom + ".png")
    if os.path.exists(chemin):
        return
    url = f"https://static.arasaac.org/pictograms/{num}/{num}_500.png"
    req = urllib.request.Request(url, headers={"User-Agent": "ma-voix"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read()
    with open(chemin, "wb") as f:
        f.write(data)


def dessiner(nom, trace):
    t = 2000
    im = Image.new("RGBA", (t, t), (0, 0, 0, 0))
    trace(ImageDraw.Draw(im), t)
    im.resize((500, 500), Image.LANCZOS).save(os.path.join(DOSSIER, nom + ".png"))


def oui(d, t):
    pts = [(0.14 * t, 0.54 * t), (0.40 * t, 0.80 * t), (0.86 * t, 0.22 * t)]
    d.line(pts, fill=(20, 60, 10, 255), width=int(0.20 * t), joint="curve")
    d.line(pts, fill=(78, 154, 6, 255), width=int(0.15 * t), joint="curve")


def non(d, t):
    a, b = 0.16 * t, 0.84 * t
    for largeur, couleur in ((0.20, (90, 10, 10, 255)), (0.15, (204, 0, 0, 255))):
        d.line([(a, a), (b, b)], fill=couleur, width=int(largeur * t))
        d.line([(a, b), (b, a)], fill=couleur, width=int(largeur * t))


def suivant(d, t):
    fleche = [(0.10, 0.38), (0.52, 0.38), (0.52, 0.16), (0.92, 0.50), (0.52, 0.84), (0.52, 0.62), (0.10, 0.62)]
    d.polygon([(x * t, y * t) for x, y in fleche], fill=(233, 120, 30, 255), outline=(90, 50, 20, 255),
              width=int(0.02 * t))


if __name__ == "__main__":
    os.makedirs(DOSSIER, exist_ok=True)
    with ThreadPoolExecutor(8) as ex:
        list(ex.map(telecharger, ARASAAC.items()))
    dessiner("oui", oui)
    dessiner("non", non)
    dessiner("suivant", suivant)
    print(len(os.listdir(DOSSIER)), "symboles dans", DOSSIER)
