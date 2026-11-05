#!/usr/bin/env python3
"""Ma Voix : parler avec des symboles.

Pour une personne qui ne peut ni parler ni écrire. Par défaut, l'écran ne montre aucun mot :
seulement de grands symboles (l'aidant peut faire écrire les phrases dessous). Un choix = une phrase dite à voix haute.
Se pilote au toucher, en restant sur un symbole, ou avec un ou deux contacts
(le cadre orange défile, comme dans ACAT d'Intel).

Les réglages de l'aidant s'ouvrent avec Ctrl+Maj+A, ou en restant appuyé
5 secondes en haut à droite de l'écran.
"""
import array
import atexit
import ctypes
import fcntl
import hashlib
import importlib.util
import json
import math
import os
import queue
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import wave
from ctypes import POINTER, byref, c_double, c_char_p, c_int, c_ubyte, c_uint, c_ulong, c_void_p
from functools import lru_cache
from io import BytesIO

VERSION = "1.5"
NOM_PAQUET = "ma-voix"

DEPOT = "jbandrivet/ma-voix"
URL_DERNIERE = f"https://api.github.com/repos/{DEPOT}/releases/latest"
PAGE_VERSIONS = f"https://github.com/{DEPOT}/releases/latest"
CHEMIN_PROGRAMME = f"/usr/bin/{NOM_PAQUET}"

ICI = os.path.dirname(os.path.abspath(__file__))


# À côté du script pendant le développement, sinon là où le paquet l'a installé
BASE = ICI if os.path.isdir(os.path.join(ICI, "symboles")) else os.path.join("/usr/share", NOM_PAQUET)
SYMBOLES = os.path.join(BASE, "symboles")
SONS = os.path.join(BASE, "sons")
MODELE = os.path.join(BASE, "voix", "fr_FR-siwis-medium.onnx")
PIPER = os.path.join(BASE, "piper")

_xdg = os.environ.get
CONF = os.path.join(_xdg("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), NOM_PAQUET)
DONNEES = os.path.join(_xdg("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), NOM_PAQUET)
CACHE = os.path.join(_xdg("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), NOM_PAQUET)
IMAGES_PERSO = os.path.join(DONNEES, "images")
F_REGLAGES = os.path.join(CONF, "reglages.json")
F_TABLEAU = os.path.join(CONF, "tableau.json")
F_AUTOSTART = os.path.join(_xdg("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"),
                           "autostart", NOM_PAQUET + ".desktop")

# Couleurs du thème Human d'Ubuntu 8.04
BG = "#EFEBE7"
BORD = "#A69C91"
FG = "#1A1A1A"
SEL = "#E5822E"
ORANGE = "#F06A00"          # cadre du défilement : doit se voir de loin
BRUN_HAUT = "#7A5A42"
BRUN_BAS = "#43301F"

TEINTES = {
    None: ("#FFFFFF", "#E6DFD6"),
    "dossier": ("#FFF9EE", "#EBD3A9"),
    "vert": ("#F4FCE8", "#BFE39A"),
    "rouge": ("#FFF0EC", "#F3B3A6"),
    "alarme": ("#FFE3D6", "#F49B7E"),
}

MODES = (
    ("direct", "En touchant ou en cliquant sur le symbole"),
    ("attente", "En restant sur le symbole, sans cliquer (souris à la tête, regard)"),
    ("un", "Avec un seul contact : le cadre défile tout seul"),
    ("deux", "Avec deux contacts : un pour avancer, un pour choisir"),
)
GRILLES = ((2, 2, "4 symboles"), (3, 2, "6 symboles"), (3, 3, "9 symboles"), (4, 3, "12 symboles"))
VOIX = (
    ("siwis", "Voix de femme naturelle (Siwis)"),
    ("robot", "Voix de robot, façon ACAT (eSpeak Klatt)"),
)
MODIFICATEURS = {"Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R", "Meta_L", "Meta_R",
                 "Super_L", "Super_R", "ISO_Level3_Shift", "Caps_Lock", "Num_Lock"}

NOMS_TOUCHES = {"space": "Espace", "Return": "Entrée", "Tab": "Tabulation", "BackSpace": "Retour arrière",
                "Escape": "Échap", "Up": "Haut", "Down": "Bas", "Left": "Gauche", "Right": "Droite"}

REGLAGES = {
    "mode": "direct", "vitesse": 2.5, "balayage": "case", "scan_voix": False,
    "attente": 1.5, "anti_rebond": 0.4, "touche_a": "space", "touche_b": "Return",
    "colonnes": 3, "lignes": 3, "ecrire": False, "affichage": 2.0, "retour_accueil": True, "plein_ecran": True,
    "voix": "siwis", "genre": "m", "lenteur": 1.3, "volume": 100, "premier_lancement": True,
}
TOURS_AVANT_ACCUEIL = 3     # tours de défilement sans choix avant de revenir à l'accueil
DUREE_COIN = 5000           # ms d'appui en haut à droite pour ouvrir les réglages
DELAI_ARRET = 2000          # ms avant de pouvoir couper l'alarme : des appuis répétés dans la panique
                            # ne doivent pas couper l'appel à l'aide


# ---------------------------------------------------------------- données

def S(image, texte, texte_f=None, **autres):
    d = {"image": image + ".png", "texte": texte}
    if texte_f:
        d["texte_f"] = texte_f
    d.update(autres)
    return d


def tableau_defaut():
    def page(nom, *items):
        return {"nom": nom, "items": list(items)}
    return {
        "accueil": page(
            "Accueil",
            S("oui", "Oui", couleur="vert"),
            S("non", "Non", couleur="rouge"),
            S("alarme", "J'ai besoin d'aide !", couleur="alarme", alarme=True),
            S("mal", "J'ai mal", page="mal"),
            S("manger", "Manger et boire", page="manger"),
            S("emotions", "Comment je me sens", page="emotions"),
            S("toilettes", "Mes besoins", page="besoins"),
            S("jouer", "Ce que je veux faire", page="activites"),
            S("famille", "Les personnes", page="personnes")),
        "mal": page(
            "J'ai mal",
            S("mal_tete", "J'ai mal à la tête"), S("mal_ventre", "J'ai mal au ventre"),
            S("mal_dents", "J'ai mal aux dents"), S("mal_gorge", "J'ai mal à la gorge"),
            S("mal_dos", "J'ai mal au dos"), S("mal_oreilles", "J'ai mal aux oreilles"),
            S("mal_jambe", "J'ai mal à la jambe"), S("mal_pied", "J'ai mal au pied")),
        "manger": page(
            "Manger et boire",
            S("faim", "J'ai faim"), S("soif", "J'ai soif"),
            S("jus", "Je veux du jus de fruit"), S("cafe", "Je veux un café"),
            S("fruit", "Je veux un fruit"), S("gateau", "Je veux un gâteau"),
            S("bon", "C'est bon !"), S("fini", "J'ai fini")),
        "emotions": page(
            "Comment je me sens",
            S("content", "Je suis content", "Je suis contente"), S("triste", "Je suis triste"),
            S("colere", "Je suis en colère"), S("peur", "J'ai peur"),
            S("fatigue", "Je suis fatigué", "Je suis fatiguée"), S("ennui", "Je m'ennuie"),
            S("aime", "J'aime ça"), S("aime_pas", "Je n'aime pas ça")),
        "besoins": page(
            "Mes besoins",
            S("toilettes", "Je dois aller aux toilettes"), S("douche", "Je veux me laver"),
            S("dormir", "Je veux dormir"), S("froid", "J'ai froid"), S("chaud", "J'ai chaud"),
            S("position", "Je veux changer de position"), S("medicament", "Je veux mes médicaments"),
            S("tranquille", "Je veux être tranquille")),
        "activites": page(
            "Ce que je veux faire",
            S("musique", "Je veux écouter de la musique"), S("tele", "Je veux regarder la télé"),
            S("sortir", "Je veux sortir"), S("lire", "Je veux une histoire"),
            S("des", "Je veux jouer"), S("ordinateur", "Je veux aller sur l'ordinateur"),
            S("dessiner", "Je veux dessiner"), S("telephone", "Je veux téléphoner")),
        "personnes": page(
            "Les personnes",
            S("maman", "Je veux voir maman"), S("papa", "Je veux voir papa"),
            S("frere", "Je veux voir mon frère"), S("soeur", "Je veux voir ma sœur"),
            S("ami", "Je veux voir mon ami"), S("infirmiere", "Je veux voir l'infirmière"),
            S("medecin", "Je veux voir le médecin"), S("calin", "Je veux un câlin")),
    }


RETOUR = {"image": "maison.png", "texte": "Retour", "special": "retour"}
SUITE = {"image": "suivant.png", "texte": "Suite", "special": "suite"}


def ecrire_json(chemin, donnees):
    """Écrit d'un coup : une coupure de courant ne doit pas abîmer le tableau."""
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    tmp = chemin + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(donnees, f, ensure_ascii=False, indent=1)
    os.replace(tmp, chemin)


def lire_json(chemin):
    try:
        with open(chemin, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        try:
            os.replace(chemin, chemin + ".abime")
        except OSError:
            pass
        return None


def charger_reglages():
    r = dict(REGLAGES)
    r.update(lire_json(F_REGLAGES) or {})
    return r


def charger_tableau():
    t = lire_json(F_TABLEAU)
    return t if isinstance(t, dict) and "accueil" in t else tableau_defaut()


def phrase(item, r):
    return item.get("texte_f") or item["texte"] if r["genre"] == "f" else item["texte"]


def toutes_les_phrases(tableau, genres=None):
    vues = [RETOUR["texte"], SUITE["texte"]]
    for p in tableau.values():
        for it in p["items"]:
            for t in ([it["texte"], it.get("texte_f")] if genres is None else
                      [phrase(it, {"genre": genres})]):
                if t and t not in vues:
                    vues.append(t)
    return vues


# ---------------------------------------------------------------- voix

def cle_son(voix, lenteur, texte):
    return hashlib.sha1(f"{voix}|{lenteur:.2f}|{texte}".encode()).hexdigest()[:20] + ".wav"


def piper_disponible():
    return (os.path.exists(MODELE) and os.path.isdir(os.path.join(PIPER, "piper"))
            and importlib.util.find_spec("onnxruntime") is not None)


def fabriquer_piper(texte, lenteur, sortie):
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(
        [PIPER] + [p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep) if p]))
    subprocess.run([sys.executable, "-m", "piper", "-m", MODELE, "--length-scale", f"{lenteur:.2f}",
                    "--sentence-silence", "0.5", "-f", sortie],
                   input=texte.encode(), env=env, check=True, timeout=60,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def fabriquer_espeak(moteur, texte, lenteur, sortie):
    with open(sortie, "wb") as f:
        subprocess.run([moteur, "-v", "fr+klatt", "-s", str(int(175 / lenteur)), "-p", "40",
                        "--stdin", "--stdout"],
                       input=texte.encode(), stdout=f, stderr=subprocess.DEVNULL, check=True, timeout=30)


def regler_volume(source, gain, sortie):
    with wave.open(source, "rb") as w:
        params, brut = w.getparams(), w.readframes(w.getnframes())
    if params.sampwidth != 2:
        shutil.copyfile(source, sortie)
        return
    a = array.array("h", brut)
    for i, v in enumerate(a):
        a[i] = max(-32768, min(32767, int(v * gain)))
    with wave.open(sortie, "wb") as w:
        w.setparams(params)
        w.writeframes(a.tobytes())


def fabriquer_alarme(sortie):
    """Deux notes qui s'alternent : s'entend depuis la pièce d'à côté."""
    taux = 22050
    with wave.open(sortie, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(taux)
        donnees = bytearray()
        for note in (880, 660, 880, 660):
            for i in range(int(taux * 0.25)):
                env = min(1.0, i / 300, (int(taux * 0.25) - i) / 300)
                donnees += struct.pack("<h", int(20000 * env * math.sin(2 * math.pi * note * i / taux)))
        w.writeframes(bytes(donnees))


class Voix:
    def __init__(self, reglages):
        self.r = reglages
        self.gen = 0
        self.proc = None
        self.verrou = threading.Lock()
        self.occupe = False
        self.temp = tempfile.mkdtemp(prefix="ma-voix-")
        atexit.register(shutil.rmtree, self.temp, ignore_errors=True)
        os.makedirs(CACHE, exist_ok=True)
        self.espeak = shutil.which("espeak-ng") or shutil.which("espeak")
        self.piper = piper_disponible()
        self.lecteurs = [c for c in (["pw-play"], ["paplay"], ["aplay", "-q"]) if shutil.which(c[0])]
        self.alarme = os.path.join(self.temp, "alarme.wav")
        fabriquer_alarme(self.alarme)

    def diagnostic(self):
        """Ce qui manque, en clair, pour l'aidant. Vide si tout va bien."""
        if not self.lecteurs:
            return "Aucun lecteur de son trouvé : installez alsa-utils."
        if not self.espeak and not self.piper:
            return "Aucune voix trouvée : installez espeak-ng."
        if self.r["voix"] == "siwis" and not self.piper:
            return ("La voix naturelle ne peut pas fabriquer de nouvelles phrases sur ce PC "
                    "(python3-onnxruntime manque) : les phrases ajoutées auront la voix de robot.")
        return ""

    def son(self, texte):
        """Rend le fichier WAV de la phrase, en le fabriquant s'il n'existe pas encore."""
        voix, lenteur = self.r["voix"], float(self.r["lenteur"])
        if voix == "siwis" and not self.piper:
            fourni = os.path.join(SONS, cle_son(voix, lenteur, texte))
            if os.path.exists(fourni):
                return fourni
            voix = "robot"
        nom = cle_son(voix, lenteur, texte)
        for dossier in (SONS, CACHE):
            chemin = os.path.join(dossier, nom)
            if os.path.exists(chemin):
                return chemin
        chemin = os.path.join(CACHE, nom)
        tmp = chemin + f".{threading.get_ident()}.tmp"
        try:
            if voix == "siwis":
                fabriquer_piper(texte, lenteur, tmp)
            elif self.espeak:
                fabriquer_espeak(self.espeak, texte, lenteur, tmp)
            else:
                return None
            os.replace(tmp, chemin)
        except (OSError, subprocess.SubprocessError) as e:
            print("voix :", e, file=sys.stderr)
            if os.path.exists(tmp):
                os.remove(tmp)
            if voix == "siwis" and self.espeak:
                fabriquer_espeak(self.espeak, texte, lenteur, tmp)
                os.replace(tmp, chemin)
            else:
                return None
        return chemin

    def dire(self, texte, doux=False, alarme=False):
        self.stop()
        g = self.gen
        self.occupe = True
        threading.Thread(target=self._parler, args=(g, texte, doux, alarme), daemon=True).start()

    def stop(self):
        with self.verrou:
            self.gen += 1
            if self.proc and self.proc.poll() is None:
                self.proc.terminate()
        self.occupe = False

    def _parler(self, g, texte, doux, alarme):
        try:
            f = self.son(texte)
            if f:
                gain = self.r["volume"] / 100 * (0.35 if doux else 1)
                if abs(gain - 1) > 0.01:
                    sortie = os.path.join(self.temp, f"{g}.wav")
                    regler_volume(f, gain, sortie)
                    f = sortie
            if alarme:
                # Sonne jusqu'à ce qu'on l'arrête : sinon l'appel se perd si personne n'est là
                while self._jouer(self.alarme, g) and (not f or self._jouer(f, g)):
                    time.sleep(0.8)
            elif f:
                self._jouer(f, g)
        finally:
            if g == self.gen:
                self.occupe = False

    def _jouer(self, fichier, g):
        for cmd in self.lecteurs:
            with self.verrou:
                if g != self.gen:
                    return False
                self.proc = subprocess.Popen(cmd + [fichier], stdout=subprocess.DEVNULL,
                                             stderr=subprocess.DEVNULL)
                p = self.proc
            if p.wait() == 0:
                return True
            if g != self.gen:
                return False
        return False

    def preparer(self, phrases):
        """Fabrique en tâche de fond ce qui manque : le premier choix sera immédiat."""
        def travail():
            for t in phrases:
                self.son(t)
        threading.Thread(target=travail, daemon=True).start()


def preparer_sons(dossier):
    """Pour le paquet : enregistre à l'avance toutes les phrases d'origine."""
    os.makedirs(dossier, exist_ok=True)
    phrases = toutes_les_phrases(tableau_defaut())
    for t in phrases:
        fabriquer_piper(t, REGLAGES["lenteur"], os.path.join(dossier, cle_son("siwis", REGLAGES["lenteur"], t)))
    print(len(phrases), "phrases enregistrées dans", dossier)


# ---------------------------------------------------------------- dessin

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps, ImageTk  # noqa: E402


def rgb(c):
    return tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))


def degrade(w, h, haut, bas):
    masque = Image.linear_gradient("L").resize((w, h))
    return Image.composite(Image.new("RGB", (w, h), rgb(bas)), Image.new("RGB", (w, h), rgb(haut)), masque)


@lru_cache(maxsize=48)
def forme(w, h, rayon, onglet):
    """Masque du bouton, arrondi ; un dossier porte un onglet en haut à gauche."""
    k = 3 if w * h < 700_000 else 1     # un grand masque en 3x prend une seconde sur une vieille tablette
    m = Image.new("L", (w * k, h * k), 0)
    d = ImageDraw.Draw(m)
    if onglet:
        o = max(10, h // 11)
        d.rounded_rectangle((0, o * k, w * k - 1, h * k - 1), rayon * k, fill=255)
        d.rounded_rectangle((0, 0, int(w * 0.42) * k, (o + rayon * 2) * k), rayon * k, fill=255)
    else:
        d.rounded_rectangle((0, 0, w * k - 1, h * k - 1), rayon * k, fill=255)
    return m.resize((w, h), Image.LANCZOS) if k > 1 else m


@lru_cache(maxsize=160)
def picto(chemin, w, h):
    try:
        with Image.open(chemin) as im:
            im = ImageOps.exif_transpose(im).convert("RGBA")
        return ImageOps.contain(im, (w, h), Image.LANCZOS)
    except (OSError, ValueError):
        vide = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ImageDraw.Draw(vide).rounded_rectangle((w // 4, h // 4, w * 3 // 4, h * 3 // 4), 12, outline=BORD, width=4)
        return vide


def chemin_image(nom):
    return nom if os.path.isabs(nom) else os.path.join(SYMBOLES, nom)


@lru_cache(maxsize=32)
def police(taille):
    try:
        return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", taille)
    except OSError:
        return ImageFont.load_default()


def couper_texte(texte, largeur, f):
    lignes, ligne = [], ""
    for mot in texte.split():
        essai = f"{ligne} {mot}".strip()
        if ligne and f.getlength(essai) > largeur:
            lignes.append(ligne)
            ligne = mot
        else:
            ligne = essai
    return lignes + [ligne]


def ajuster_texte(texte, largeur, grand):
    """La plus grande police qui tient sur deux lignes."""
    taille = grand
    while True:
        f = police(taille)
        lignes = couper_texte(texte, largeur, f)
        if taille <= 12 or (len(lignes) <= 2 and all(f.getlength(x) <= largeur for x in lignes)):
            return f, taille, lignes
        taille -= 2


def rendu_case(item, w, h, actif=False, texte=None):
    """Bouton brillant façon Clearlooks avec son symbole, et sa phrase écrite si on la veut."""
    dossier = bool(item.get("page"))
    teinte = item.get("couleur") or ("dossier" if dossier else None)
    if item.get("alarme"):
        teinte = "alarme"
    ombre = 4
    bw, bh = w - ombre, h - ombre
    rayon = max(10, min(bw, bh) // 16)
    bord = max(10, min(bw, bh) // 18) if actif else 2
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))

    m = forme(bw, bh, rayon, dossier)
    fond_ombre = Image.new("L", (w, h), 0)
    fond_ombre.paste(m, (ombre, ombre))
    if w * h < 700_000:
        fond_ombre = fond_ombre.filter(ImageFilter.GaussianBlur(3))
    fond_ombre = fond_ombre.point(lambda v: v * 3 // 8)
    im.paste((60, 45, 30, 255), (0, 0), fond_ombre)

    im.paste(rgb(ORANGE) if actif else rgb(BORD) if not dossier else (168, 120, 60), (0, 0), m)
    interieur = Image.new("L", (bw, bh), 0)
    interieur.paste(forme(bw - 2 * bord, bh - 2 * bord, max(3, rayon - bord), dossier), (bord, bord))
    if actif:
        haut, bas = "#FFF4E0", "#FFD9A8"
    else:
        haut, bas = TEINTES[teinte]
    im.paste(degrade(bw, bh, haut, bas), (0, 0), interieur)
    brillance = Image.new("L", (bw, bh), 0)
    ImageDraw.Draw(brillance).rectangle((0, 0, bw, int(bh * 0.42)), fill=70)
    im.paste((255, 255, 255), (0, 0), ImageChops.multiply(brillance, interieur))

    marge = max(10, min(bw, bh) // 18) + max(8, min(bw, bh) // 20)   # le symbole ne bouge pas sous le cadre
    haut_img = marge + (max(10, bh // 11) if dossier else 0)
    bas_img = marge
    if texte:
        f, taille, lignes = ajuster_texte(texte, bw - 2 * (bord + 10), max(14, min(64, bh // 7)))
        pas = int(taille * 1.2)
        bas_img = bord + 8 + pas * len(lignes) + 6
    p = picto(chemin_image(item["image"]), bw - 2 * marge, bh - bas_img - haut_img)
    x = (bw - p.width) // 2
    y = haut_img + (bh - bas_img - haut_img - p.height) // 2
    im.alpha_composite(p, (x, y))
    if texte:
        d = ImageDraw.Draw(im)
        for i, ligne in enumerate(lignes):
            d.text(((bw - f.getlength(ligne)) / 2, bh - bord - 8 - pas * (len(lignes) - i)), ligne,
                   font=f, fill=rgb(FG))
    return im


def bandeau(w, h):
    im = degrade(w, h, BRUN_HAUT, BRUN_BAS)
    ImageDraw.Draw(im).rectangle((0, h - 4, w, h), fill=rgb(SEL))
    return im


def icone(t):
    """Une bulle de parole orange avec un sourire."""
    k = 4
    s = t * k
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    boite = (s * .06, s * .08, s * .94, s * .74)
    queue_b = [(s * .24, s * .66), (s * .20, s * .95), (s * .50, s * .70)]
    d.rounded_rectangle(boite, s * .20, fill=(120, 72, 30, 255))
    d.polygon(queue_b, fill=(120, 72, 30, 255))
    b2 = (s * .10, s * .12, s * .90, s * .70)
    d.rounded_rectangle(b2, s * .17, fill=(240, 130, 40, 255))
    d.polygon([(s * .27, s * .64), (s * .235, s * .87), (s * .47, s * .68)], fill=(240, 130, 40, 255))
    for cx in (.36, .64):
        d.ellipse((s * (cx - .05), s * .26, s * (cx + .05), s * .36), fill=(255, 255, 255, 255))
    d.arc((s * .30, s * .26, s * .70, s * .60), 25, 155, fill=(255, 255, 255, 255), width=max(k, int(s * .045)))
    return im.resize((t, t), Image.LANCZOS)


# ---------------------------------------------------------------- interface

import tkinter as tk  # noqa: E402
from tkinter import messagebox, ttk  # noqa: E402


# ---------------------------------------------------------------- toucher

# Sous Wayland, GNOME écoute les touchers sur le cadre des fenêtres X11. Un programme Tk ne
# reçoit donc que les déplacements du doigt, jamais l'appui. On demande les touchers avec
# XInput 2 sur la fenêtre de Tk, devant le cadre, et on les transforme en clics pour Tk.
# Si quelque chose manque, on ne fait rien : la souris et le reste marchent comme avant.

XI_TOUCH_BEGIN, XI_TOUCH_UPDATE, XI_TOUCH_END = 18, 19, 20
XI_ALL_MASTER_DEVICES = 1
DOIGT_PERDU = 8.0       # s : plus long que l'appui de 5 s qui ouvre les réglages
GENERIC_EVENT = 35
BOUTON1 = 0x100


class XIEventMask(ctypes.Structure):
    _fields_ = [("deviceid", c_int), ("mask_len", c_int), ("mask", POINTER(c_ubyte))]


class XGenericEventCookie(ctypes.Structure):
    _fields_ = [("type", c_int), ("serial", c_ulong), ("send_event", c_int), ("display", c_void_p),
                ("extension", c_int), ("evtype", c_int), ("cookie", c_uint), ("data", c_void_p)]


class XEvent(ctypes.Union):
    _fields_ = [("type", c_int), ("xcookie", XGenericEventCookie), ("pad", ctypes.c_long * 24)]


class XIDeviceEvent(ctypes.Structure):
    _fields_ = [("type", c_int), ("serial", c_ulong), ("send_event", c_int), ("display", c_void_p),
                ("extension", c_int), ("evtype", c_int), ("time", c_ulong), ("deviceid", c_int),
                ("sourceid", c_int), ("detail", c_int), ("root", c_ulong), ("event", c_ulong),
                ("child", c_ulong), ("root_x", c_double), ("root_y", c_double),
                ("event_x", c_double), ("event_y", c_double), ("flags", c_int)]


class Tactile:
    def __init__(self, root):
        self.root = root
        self.doigt = None       # le premier doigt posé ; les autres sont ignorés
        self.depuis = 0.0
        self.cible = None
        self.actif = False
        try:
            self._brancher()
        except (OSError, AttributeError, TypeError, tk.TclError) as e:
            print("tactile :", e, file=sys.stderr)

    def _brancher(self):
        x = ctypes.CDLL("libX11.so.6")
        xi = ctypes.CDLL("libXi.so.6")
        x.XOpenDisplay.restype = c_void_p
        x.XOpenDisplay.argtypes = [c_char_p]
        x.XQueryExtension.argtypes = [c_void_p, c_char_p, POINTER(c_int), POINTER(c_int), POINTER(c_int)]
        x.XSync.argtypes = [c_void_p, c_int]
        x.XPending.argtypes = [c_void_p]
        x.XNextEvent.argtypes = [c_void_p, POINTER(XEvent)]
        x.XGetEventData.argtypes = [c_void_p, POINTER(XGenericEventCookie)]
        x.XFreeEventData.argtypes = [c_void_p, POINTER(XGenericEventCookie)]
        x.XConnectionNumber.argtypes = [c_void_p]
        xi.XIQueryVersion.argtypes = [c_void_p, POINTER(c_int), POINTER(c_int)]
        xi.XISelectEvents.argtypes = [c_void_p, c_ulong, POINTER(XIEventMask), c_int]
        self.x = x
        d = self.d = x.XOpenDisplay(None)
        if not d:
            raise OSError("pas d'affichage X")
        op, ev, er = c_int(), c_int(), c_int()
        if not x.XQueryExtension(d, b"XInputExtension", byref(op), byref(ev), byref(er)):
            raise OSError("pas de XInput")
        self.opcode = op.value
        maj, mi = c_int(2), c_int(2)
        if xi.XIQueryVersion(d, byref(maj), byref(mi)) != 0 or (maj.value, mi.value) < (2, 2):
            raise OSError("XInput trop ancien")

        self.xi = xi
        self.fenetres = set()
        self.root.update_idletasks()
        self.abonner(self.root)
        if not self.fenetres:
            raise OSError("abonnement refusé")
        self.actif = True
        # Les fenêtres de dialogue s'abonnent en s'ouvrant
        self.root.bind_class("Toplevel", "<Map>", lambda e: self.abonner(e.widget.winfo_toplevel()), add="+")
        self.root.tk.createfilehandler(x.XConnectionNumber(d), tk.READABLE, self._lire)
        self._lire()

    def abonner(self, fenetre):
        """S'abonne sur la fenêtre de Tk elle-même : devant le cadre, que GNOME écoute déjà."""
        fid = fenetre.winfo_id()
        if fid in self.fenetres:
            return
        x, d = self.x, self.d
        # Une erreur X tuerait le programme : on l'attrape le temps de s'abonner
        erreurs = []
        rappel = ctypes.CFUNCTYPE(c_int, c_void_p, c_void_p)(lambda _d, _e: erreurs.append(1) or 0)
        x.XSetErrorHandler.restype = c_void_p
        x.XSetErrorHandler.argtypes = [c_void_p]
        ancien = x.XSetErrorHandler(ctypes.cast(rappel, c_void_p))
        octets = (c_ubyte * 3)()
        for t in (XI_TOUCH_BEGIN, XI_TOUCH_UPDATE, XI_TOUCH_END):
            octets[t >> 3] |= 1 << (t & 7)
        masque = XIEventMask(XI_ALL_MASTER_DEVICES, 3, ctypes.cast(octets, POINTER(c_ubyte)))
        self.xi.XISelectEvents(d, fid, byref(masque), 1)
        x.XSync(d, 0)
        x.XSetErrorHandler(ancien)
        if not erreurs:
            self.fenetres.add(fid)

    def _lire(self, *_):
        x, d = self.x, self.d
        while x.XPending(d):
            e = XEvent()
            x.XNextEvent(d, byref(e))
            c = e.xcookie
            if c.type == GENERIC_EVENT and c.extension == self.opcode and x.XGetEventData(d, byref(c)):
                t = ctypes.cast(c.data, POINTER(XIDeviceEvent)).contents
                self._toucher(c.evtype, t.detail, int(t.root_x), int(t.root_y))
                x.XFreeEventData(d, byref(c))

    def _toucher(self, quoi, doigt, rx, ry):
        maintenant = time.monotonic()
        if quoi == XI_TOUCH_BEGIN and self.doigt is not None and maintenant - self.depuis > DOIGT_PERDU:
            self.doigt = self.cible = None      # sa fin s'est perdue : il ne doit pas tout bloquer
        if doigt == self.doigt:
            self.depuis = maintenant
        if quoi == XI_TOUCH_BEGIN and self.doigt is None:
            w = self.root.winfo_containing(rx, ry)
            if w is None:
                return
            self.doigt, self.cible, self.depuis = doigt, w, maintenant
            self._envoyer("<Motion>", rx, ry, 0)
            self._envoyer("<ButtonPress-1>", rx, ry, 0)
        elif doigt == self.doigt and quoi == XI_TOUCH_UPDATE:
            self._envoyer("<Motion>", rx, ry, BOUTON1)
        elif doigt == self.doigt and quoi == XI_TOUCH_END:
            self._envoyer("<ButtonRelease-1>", rx, ry, BOUTON1)
            self.doigt = self.cible = None

    def _envoyer(self, sequence, rx, ry, etat):
        w = self.cible
        try:
            w.event_generate(sequence, x=rx - w.winfo_rootx(), y=ry - w.winfo_rooty(),
                             rootx=rx, rooty=ry, state=etat)
        except tk.TclError:             # le widget a disparu entre-temps
            self.doigt = self.cible = None


def style_human(root):
    st = ttk.Style(root)
    st.theme_use("clam")
    st.configure(".", background=BG, foreground=FG, bordercolor=BORD, darkcolor="#D6CFC6", lightcolor="#FFFFFF",
                 troughcolor="#D9D2C9", selectbackground=SEL, selectforeground="#FFFFFF",
                 fieldbackground="#FFFFFF", focuscolor=SEL, insertcolor=FG, arrowcolor="#3C3C3C",
                 font=("DejaVu Sans", 10))
    st.map(".", background=[("disabled", BG), ("active", "#F6F3F0")], foreground=[("disabled", "#9A938B")])
    st.configure("TButton", padding=(10, 5), relief="raised")
    st.map("TButton", background=[("pressed", "#D9D1C7"), ("active", "#F9F7F4")],
           bordercolor=[("focus", "#B88A5C")])
    st.configure("TNotebook", background=BG, tabmargins=(6, 6, 6, 0), bordercolor=BORD)
    st.configure("TNotebook.Tab", padding=(14, 6), background="#DDD6CD", bordercolor=BORD)
    st.map("TNotebook.Tab", background=[("selected", BG), ("active", "#ECE7E1")],
           expand=[("selected", (1, 2, 1, 0))])
    st.configure("Treeview", rowheight=26, background="#FFFFFF", fieldbackground="#FFFFFF", bordercolor=BORD)
    st.map("Treeview", background=[("selected", SEL)], foreground=[("selected", "#FFFFFF")])
    st.configure("Symboles.Treeview", rowheight=54)
    st.configure("TEntry", padding=(4, 3))
    st.configure("TLabelframe", background=BG, bordercolor=BORD)
    st.configure("TLabelframe.Label", background=BG, font=("DejaVu Sans", 10, "bold"))
    st.configure("Note.TLabel", foreground="#6B5D4D")
    st.configure("Alerte.TLabel", foreground="#A40000")
    st.configure("Maj.TButton", background=SEL, foreground="#FFFFFF", bordercolor="#B85F15")
    st.map("Maj.TButton", background=[("pressed", "#B85F15"), ("active", "#F09A50")],
           foreground=[("active", "#FFFFFF")])


class Appli:
    def __init__(self):
        self.r = charger_reglages()
        self.t = charger_tableau()
        self.voix = Voix(self.r)
        self.root = tk.Tk(className=NOM_PAQUET)
        self.root.title("Ma Voix")
        self.root.geometry("1100x760")
        self.root.configure(bg=BG)
        self._ico = ImageTk.PhotoImage(icone(64))
        self.root.iconphoto(True, self._ico)
        style_human(self.root)
        self.root.update_idletasks()
        self.tactile = Tactile(self.root)
        self.canvas = tk.Canvas(self.root, bg=BG, highlightthickness=0, cursor="hand2")
        self.canvas.pack(fill="both", expand=True)

        self.page, self.tranche, self.image_page = "accueil", 0, None
        self.cases, self.ids, self.photos = [], {}, {}
        self.marques = []
        self.confirmation = False
        self.panneau = None
        self.apprendre = None
        self.dernier_contact = 0.0
        self.touches = {}
        self.job_scan = self.job_taille = self.job_coin = self.job_att = self.job_fin = None
        self.groupes, self.gi, self.tours, self.sous_groupe = [], 0, 0, False
        self.att_i, self.att_t0 = None, 0.0
        self.arret = None           # rectangle de la maison qui coupe l'alarme, quand elle est là
        self.job_arret = self.job_arret_att = None

        self.canvas.bind("<Configure>", self._sur_taille)
        self.canvas.bind("<ButtonPress>", self._appui)
        self.canvas.bind("<ButtonRelease>", self._relache)
        self.canvas.bind("<Motion>", self._mouvement)
        self.canvas.bind("<Leave>", lambda e: self._attente_zero())
        self.root.bind("<KeyPress>", self._touche)
        self.root.bind("<KeyRelease>", self._touche_relachee)
        self.root.protocol("WM_DELETE_WINDOW", self.ouvrir_reglages)

        self.plein_ecran(self.r["plein_ecran"])
        self.voix.preparer(toutes_les_phrases(self.t, self.r["genre"]))
        if self.r["premier_lancement"]:
            self.root.after(200, self.ouvrir_reglages)
        else:
            self.root.after(100, self.afficher, "accueil")

    def dessin(self, it, w, h, actif=False):
        return rendu_case(it, w, h, actif, phrase(it, self.r) if self.r["ecrire"] else None)

    def plein_ecran(self, oui):
        self.root.attributes("-fullscreen", bool(oui))

    def sauver(self):
        ecrire_json(F_REGLAGES, self.r)

    def sauver_tableau(self):
        ecrire_json(F_TABLEAU, self.t)

    # ---- affichage d'une page

    def preparer_cases(self):
        c, l = self.r["colonnes"], self.r["lignes"]
        n = c * l
        items = self.t.get(self.page, self.t["accueil"])["items"]
        accueil = self.page == "accueil"
        place = n if accueil else n - 1
        cases = [None] * n
        if len(items) <= place:
            self.tranche = 0
            cases[:len(items)] = items
        else:
            place -= 1
            debut = self.tranche * place
            if debut >= len(items):
                self.tranche, debut = 0, 0
            morceau = items[debut:debut + place]
            cases[:len(morceau)] = morceau
            cases[n - (1 if accueil else 2)] = SUITE
        if not accueil:
            cases[n - 1] = RETOUR
        self.cases = cases

    def geometrie(self):
        W, H = self.canvas.winfo_width(), self.canvas.winfo_height()
        bh = max(44, int(H * 0.08))
        m = max(8, int(min(W, H) * 0.015))
        c, l = self.r["colonnes"], self.r["lignes"]
        return W, H, bh, m, (W - m * (c + 1)) // c, (H - bh - m * (l + 1)) // l

    def rectangle_case(self, i):
        _W, _H, bh, m, cw, ch = self.geometrie()
        c = self.r["colonnes"]
        return m + (i % c) * (cw + m), bh + m + (i // c) * (ch + m), cw, ch

    def case_en(self, x, y):
        for i, it in enumerate(self.cases):
            if it is not None:
                cx, cy, cw, ch = self.rectangle_case(i)
                if cx <= x < cx + cw and cy <= y < cy + ch:
                    return i
        return None

    def dessiner_bandeau(self, image=None):
        W, _H, bh, *_ = self.geometrie()
        self.photos["bandeau"] = ImageTk.PhotoImage(bandeau(W, bh))
        self.canvas.create_image(0, 0, anchor="nw", image=self.photos["bandeau"])
        if image:
            t = bh - 12
            pastille = Image.new("RGBA", (t, t), (255, 255, 255, 0))
            pastille.paste((255, 255, 255, 255), (0, 0), forme(t, t, 8, False))
            p = picto(chemin_image(image), t - 8, t - 8)
            pastille.alpha_composite(p, ((t - p.width) // 2, (t - p.height) // 2))
            self.photos["pastille"] = ImageTk.PhotoImage(pastille)
            self.canvas.create_image(10, 4, anchor="nw", image=self.photos["pastille"])

    def afficher(self, page=None, tranche=0, image=None):
        if self.panneau is not None:
            return
        self._annuler_scan()
        self._attente_zero()
        self._oublier_arret()
        if page is not None:
            self.page, self.tranche = page, tranche
            self.image_page = image
        self.confirmation = False
        self.preparer_cases()
        self.canvas.delete("all")
        self.ids, self.photos, self.marques = {}, {}, []
        self.dessiner_bandeau(self.image_page)
        for i, it in enumerate(self.cases):
            if it is None:
                continue
            x, y, cw, ch = self.rectangle_case(i)
            self.photos[i, False] = ImageTk.PhotoImage(self.dessin(it, cw, ch))
            self.ids[i] = self.canvas.create_image(x, y, anchor="nw", image=self.photos[i, False])
        self.demarrer_scan()

    def _sur_taille(self, _e):
        if self.job_taille:
            self.root.after_cancel(self.job_taille)
        self.job_taille = self.root.after(150, self._retracer)

    def _retracer(self):
        self.job_taille = None
        if not self.confirmation:
            self.afficher()

    def marquer(self, indices):
        for i in self.marques:
            if i in self.ids:
                self.canvas.itemconfigure(self.ids[i], image=self.photos[i, False])
        self.marques = list(indices)
        for i in self.marques:
            if (i, True) not in self.photos:
                _x, _y, cw, ch = self.rectangle_case(i)
                self.photos[i, True] = ImageTk.PhotoImage(self.dessin(self.cases[i], cw, ch, actif=True))
            self.canvas.itemconfigure(self.ids[i], image=self.photos[i, True])

    # ---- choix

    def activer(self, i):
        it = self.cases[i]
        spec = it.get("special")
        if spec == "retour":
            self.afficher("accueil")
        elif spec == "suite":
            self.afficher(self.page, self.tranche + 1, self.image_page)
        elif it.get("page") in self.t:
            self.afficher(it["page"], 0, it["image"])
        else:
            self.montrer(it)

    def montrer(self, it):
        """Le symbole choisi en très grand pendant qu'il est dit : l'autre personne le voit aussi."""
        self._annuler_scan()
        self._attente_zero()
        self.confirmation = True
        self.voix.dire(phrase(it, self.r), alarme=bool(it.get("alarme")))   # avant de dessiner : la voix d'abord
        W, H, bh, m, *_ = self.geometrie()
        self.canvas.delete("all")
        self.ids, self.marques = {}, []
        self.dessiner_bandeau()
        cw, ch = W - 2 * m, H - bh - 2 * m
        if it.get("alarme"):
            # place gardée dès le début : le symbole ne bouge pas quand la maison arrive
            cw -= self.rectangle_arret()[2] + m
            self.job_arret = self.root.after(DELAI_ARRET, self._montrer_arret)
        rendu = dict(it)
        rendu.pop("page", None)
        self.photos["grand"] = ImageTk.PhotoImage(self.dessin(rendu, cw, ch))
        self.canvas.create_image(m, bh + m, anchor="nw", image=self.photos["grand"])
        if not it.get("alarme"):        # l'alarme reste à l'écran jusqu'à l'appui sur la maison
            self.limite_voix = time.monotonic() + 30
            self.root.after(100, self._attendre_voix)

    def rectangle_arret(self):
        W, H, bh, m, *_ = self.geometrie()
        w, h = W // 4, (H - bh) // 3 - m
        return W - m - w, H - m - h, w, h

    def _montrer_arret(self):
        self.job_arret = None
        x, y, w, h = self.arret = self.rectangle_arret()
        self.photos["arret"] = ImageTk.PhotoImage(self.dessin(dict(RETOUR, texte="Arrêter"), w, h, actif=True))
        self.canvas.create_image(x, y, anchor="nw", image=self.photos["arret"])

    def dans_arret(self, x, y):
        ax, ay, aw, ah = self.arret
        return ax <= x < ax + aw and ay <= y < ay + ah

    def _oublier_arret(self):
        for job in (self.job_arret, self.job_arret_att):
            if job:
                self.root.after_cancel(job)
        self.job_arret = self.job_arret_att = self.arret = None

    def arreter(self):
        """Coupe l'alarme et revient à l'accueil."""
        self.voix.stop()
        if self.job_fin:
            self.root.after_cancel(self.job_fin)
            self.job_fin = None
        self.dernier_contact = time.monotonic()     # ce même appui ne choisit rien à l'accueil
        self.afficher("accueil")

    def _attendre_voix(self):
        if self.panneau is not None or not self.confirmation:
            return
        if self.voix.occupe and time.monotonic() < self.limite_voix:
            self.root.after(100, self._attendre_voix)
        else:
            self.job_fin = self.root.after(int(self.r["affichage"] * 1000), self._fin_confirmation)

    def _fin_confirmation(self):
        self.job_fin = None
        self.confirmation = False
        if self.r["retour_accueil"]:
            self.afficher("accueil")
        else:
            self.afficher()

    # ---- défilement

    def _annuler_scan(self):
        if self.job_scan:
            self.root.after_cancel(self.job_scan)
            self.job_scan = None

    def groupes_depart(self):
        pleines = [i for i, it in enumerate(self.cases) if it is not None]
        if self.r["balayage"] == "ligne":
            c = self.r["colonnes"]
            lignes = {}
            for i in pleines:
                lignes.setdefault(i // c, []).append(i)
            return [lignes[k] for k in sorted(lignes)]
        return [[i] for i in pleines]

    def demarrer_scan(self):
        if self.r["mode"] not in ("un", "deux"):
            return
        self.groupes = self.groupes_depart()
        self.gi, self.tours, self.sous_groupe = 0, 0, False
        self._montrer_groupe(premier=True)

    def _montrer_groupe(self, premier=False):
        g = self.groupes[self.gi]
        self.marquer(g)
        if self.r["scan_voix"] and len(g) == 1:
            self.voix.dire(phrase(self.cases[g[0]], self.r), doux=True)
        if self.r["mode"] == "un":
            # plus de temps sur la première case : le temps de voir que la page a changé
            d = self.r["vitesse"] * (1.5 if premier else 1)
            self.job_scan = self.root.after(int(d * 1000), self.avancer)

    def avancer(self):
        self._annuler_scan()
        self.gi += 1
        if self.gi >= len(self.groupes):
            self.gi = 0
            self.tours += 1
            if self.sous_groupe and self.tours >= 2:
                self.demarrer_scan()
                return
            if self.page != "accueil" and self.tours >= TOURS_AVANT_ACCUEIL and self.r["mode"] == "un":
                self.afficher("accueil")
                return
        self._montrer_groupe()

    def choisir(self):
        self._annuler_scan()
        g = self.groupes[self.gi]
        if len(g) > 1:
            self.groupes, self.gi, self.tours, self.sous_groupe = [[i] for i in g], 0, 0, True
            self._montrer_groupe(premier=True)
        else:
            self.activer(g[0])

    # ---- contacts, souris, clavier

    def contact(self, quoi):
        """quoi : 'A' pour le premier contact, 'B' pour le second, None pour tout le reste."""
        if self.panneau is None and self.arret and self.r["mode"] in ("un", "deux") and quoi:
            self.arreter()
            return
        if self.panneau is not None or self.confirmation:
            return
        maintenant = time.monotonic()
        if maintenant - self.dernier_contact < self.r["anti_rebond"]:
            return
        mode = self.r["mode"]
        if mode == "un":
            self.dernier_contact = maintenant
            self.choisir()
        elif mode == "deux" and quoi:
            self.dernier_contact = maintenant
            self.avancer() if quoi == "A" else self.choisir()

    def _dans_le_coin(self, x, y):
        W, _H, bh, *_ = self.geometrie()
        return x > W - 110 and y < bh

    def _appui(self, e):
        if self._dans_le_coin(e.x, e.y):
            self.job_coin = self.root.after(DUREE_COIN, self.ouvrir_reglages)
            return
        if self.r["mode"] in ("un", "deux"):
            self.contact("B" if e.num == 3 else "A")
            return
        if self.arret and e.num == 1 and self.dans_arret(e.x, e.y):
            self.arreter()
            return
        if self.confirmation or e.num != 1:
            return
        maintenant = time.monotonic()
        i = self.case_en(e.x, e.y)
        if i is not None and maintenant - self.dernier_contact >= self.r["anti_rebond"]:
            self.dernier_contact = maintenant
            self.activer(i)

    def _relache(self, _e):
        if self.job_coin:
            self.root.after_cancel(self.job_coin)
            self.job_coin = None

    def _touche(self, e):
        k = e.keysym
        if e.state & 0x4 and k.lower() == "a":
            self.ouvrir_reglages()
            return
        if k in MODIFICATEURS:
            return
        if k in self.touches:           # touche maintenue : répétition automatique, on ignore
            if self.touches[k]:
                self.root.after_cancel(self.touches[k])
                self.touches[k] = None
            return
        self.touches[k] = None
        if self.apprendre:
            self.apprendre(k)
            return
        if self.r["mode"] == "un":
            self.contact("A")
        else:
            self.contact("A" if k == self.r["touche_a"] else "B" if k == self.r["touche_b"] else None)

    def _touche_relachee(self, e):
        k = e.keysym
        if k in self.touches:
            self.touches[k] = self.root.after(40, self.touches.pop, k, None)

    # ---- choisir sans cliquer

    def _mouvement(self, e):
        if self.r["mode"] == "attente" and self.arret and self.panneau is None:
            dedans = self.dans_arret(e.x, e.y)
            if dedans and not self.job_arret_att:
                self.job_arret_att = self.root.after(int(self.r["attente"] * 1000), self.arreter)
            elif not dedans and self.job_arret_att:
                self.root.after_cancel(self.job_arret_att)
                self.job_arret_att = None
            return
        if self.r["mode"] != "attente" or self.confirmation or self.panneau is not None:
            return
        i = self.case_en(e.x, e.y)
        if i == self.att_i:
            return
        self._attente_zero()
        if i is not None:
            self.att_i, self.att_t0 = i, time.monotonic()
            self.marquer([i])
            self.job_att = self.root.after(50, self._attente_tic)

    def _attente_zero(self):
        if self.job_att:
            self.root.after_cancel(self.job_att)
            self.job_att = None
        self.att_i = None
        self.canvas.delete("attente")
        if self.marques and self.r["mode"] == "attente":
            self.marquer([])

    def _attente_tic(self):
        self.job_att = None
        i = self.att_i
        if i is None:
            return
        part = (time.monotonic() - self.att_t0) / max(0.2, self.r["attente"])
        if part >= 1:
            self._attente_zero()
            self.activer(i)
            return
        x, y, cw, ch = self.rectangle_case(i)
        self.canvas.delete("attente")
        self.canvas.create_rectangle(x + 16, y + ch - 30, x + 16 + (cw - 36) * part, y + ch - 16,
                                     fill=ORANGE, outline="", tags="attente")
        self.job_att = self.root.after(50, self._attente_tic)

    # ---- réglages de l'aidant

    def ouvrir_reglages(self):
        if self.panneau is not None:
            return
        self._relache(None)
        self._annuler_scan()
        self._attente_zero()
        self._oublier_arret()
        self.voix.stop()
        if self.job_fin:
            self.root.after_cancel(self.job_fin)
            self.job_fin = None
        self.confirmation = False
        self.plein_ecran(False)
        self.canvas.pack_forget()
        self.panneau = Reglages(self.root, self)
        self.panneau.pack(fill="both", expand=True)

    def fermer_reglages(self):
        self.apprendre = None
        self.panneau.destroy()
        self.panneau = None
        self.r["premier_lancement"] = False
        self.sauver()
        self.sauver_tableau()
        self.voix.preparer(toutes_les_phrases(self.t, self.r["genre"]))
        self.canvas.pack(fill="both", expand=True)
        self.plein_ecran(self.r["plein_ecran"])
        self.root.focus_force()
        self.root.update_idletasks()
        self.afficher("accueil")

    def quitter(self):
        self.voix.stop()
        self.root.destroy()

    def relancer(self):
        """Repart sur la nouvelle version. Le verrou se libère tout seul avec l'ancien programme."""
        self.quitter()
        shutil.rmtree(self.voix.temp, ignore_errors=True)
        os.execv(CHEMIN_PROGRAMME, [CHEMIN_PROGRAMME])


class Reglages(ttk.Frame):
    """Réglages pour l'aidant : le seul endroit avec des mots, sauf si l'aidant les demande aussi à l'écran."""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app, self.r = app, app.r
        haut = tk.Label(self, text="  Ma Voix : réglages pour l'aidant", anchor="w", fg="white",
                        bg=BRUN_BAS, font=("DejaVu Sans", 13, "bold"), pady=8)
        haut.pack(fill="x")
        tk.Frame(self, bg=SEL, height=3).pack(fill="x")
        ttk.Label(self, style="Note.TLabel", padding=(12, 8, 12, 0),
                  text="Pour revenir ici : Ctrl+Maj+A, ou rester appuyé 5 secondes en haut à droite de l'écran."
                  ).pack(fill="x")
        d = app.voix.diagnostic()
        if d:
            ttk.Label(self, text=d, style="Alerte.TLabel", padding=(12, 4, 12, 0)).pack(fill="x")

        bas = ttk.Frame(self, padding=10)
        bas.pack(side="bottom", fill="x")
        ttk.Button(bas, text="Quitter le logiciel", command=app.quitter).pack(side="left")
        ttk.Button(bas, text="Revenir aux symboles", command=app.fermer_reglages).pack(side="right")
        self.maj = None
        self.q_maj = queue.Queue()
        self.b_maj = ttk.Button(bas, text="Chercher une mise à jour", command=self.clic_maj)
        self.b_maj.pack(side="left", padx=(16, 8))
        self.l_maj = ttk.Label(bas, text=f"Version {VERSION}", style="Note.TLabel")
        self.l_maj.pack(side="left")
        self.verifier_maj(discret=True)

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=10, pady=(6, 0))
        nb.add(self.onglet_acces(nb), text="Comment choisir")
        nb.add(self.onglet_ecran(nb), text="Écran")
        nb.add(self.onglet_voix(nb), text="Voix")
        nb.add(Editeur(nb, app), text="Symboles")
        nb.add(self.onglet_apropos(nb), text="À propos")

    def verifier_maj(self, discret=False):
        self.b_maj.state(["disabled"])
        if not discret:
            self.l_maj.configure(text="Vérification…")

        def travail():
            try:
                self.q_maj.put(("fait", chercher_maj()))
            except (OSError, ValueError, KeyError):
                self.q_maj.put(("erreur", None))
        threading.Thread(target=travail, daemon=True).start()
        self.after(150, self._lire_maj, discret)

    def _lire_maj(self, discret):
        if self.app.panneau is not self:
            return
        try:
            quoi, info = self.q_maj.get_nowait()
        except queue.Empty:
            self.after(150, self._lire_maj, discret)
            return
        self.b_maj.state(["!disabled"])
        self.maj = info
        if info:
            self.b_maj.configure(text="Mettre à jour", style="Maj.TButton")
            self.l_maj.configure(text=f"Version {info['version']} disponible (vous avez la {VERSION})")
        else:
            self.b_maj.configure(text="Chercher une mise à jour", style="TButton")
            if quoi == "erreur":
                self.l_maj.configure(text=f"Version {VERSION}" if discret else "Pas d'accès à internet")
            else:
                self.l_maj.configure(text=f"Version {VERSION} : à jour")

    def clic_maj(self):
        if not self.maj:
            self.verifier_maj()
        elif installation_possible():
            FenetreMaj(self)
        else:
            messagebox.showinfo(
                "Mise à jour", "Ce système ne peut pas installer tout seul la mise à jour.\n"
                "La page de téléchargement va s'ouvrir.", parent=self)
            subprocess.Popen(["xdg-open", PAGE_VERSIONS], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def changer(self, cle, valeur):
        self.r[cle] = valeur
        self.app.sauver()

    def curseur(self, parent, texte, cle, mini, maxi, unite="s", pas=0.1):
        ligne = ttk.Frame(parent)
        ligne.pack(fill="x", pady=3)
        ttk.Label(ligne, text=texte, width=44).pack(side="left")
        val = ttk.Label(ligne, width=8, anchor="e")
        val.pack(side="right")

        def bouger(v):
            v = round(float(v) / pas) * pas
            v = int(v) if pas >= 1 else round(v, 2)
            val.configure(text=f"{v} {unite}".replace(".", ","))
            self.r[cle] = v

        s = ttk.Scale(ligne, from_=mini, to=maxi, value=self.r[cle], command=bouger)
        s.pack(side="left", fill="x", expand=True, padx=8)
        s.bind("<ButtonRelease-1>", lambda e: self.app.sauver())
        bouger(self.r[cle])
        return s

    def case_a_cocher(self, parent, texte, cle, apres=None):
        v = tk.BooleanVar(value=self.r[cle])

        def fait():
            self.changer(cle, v.get())
            if apres:
                apres()
        ttk.Checkbutton(parent, text=texte, variable=v, command=fait).pack(anchor="w", pady=2)

    def onglet_acces(self, nb):
        f = ttk.Frame(nb, padding=12)
        a = ttk.LabelFrame(f, text="La personne choisit", padding=8)
        a.pack(fill="x")
        v = tk.StringVar(value=self.r["mode"])
        for cle, texte in MODES:
            ttk.Radiobutton(a, text=texte, value=cle, variable=v,
                            command=lambda: self.changer("mode", v.get())).pack(anchor="w", pady=1)

        b = ttk.LabelFrame(f, text="Temps", padding=8)
        b.pack(fill="x", pady=(8, 0))
        self.curseur(b, "Temps du cadre sur chaque symbole", "vitesse", 0.5, 8)
        self.curseur(b, "Temps à rester sur un symbole sans cliquer", "attente", 0.5, 5)
        self.curseur(b, "Ignorer un nouvel appui pendant", "anti_rebond", 0, 3)
        self.curseur(b, "Laisser le symbole choisi en grand encore", "affichage", 0.5, 10)

        c = ttk.LabelFrame(f, text="Défilement et contacts", padding=8)
        c.pack(fill="x", pady=(8, 0))
        w = tk.StringVar(value=self.r["balayage"])
        l1 = ttk.Frame(c)
        l1.pack(anchor="w")
        for cle, texte in (("case", "Symbole par symbole (le plus simple)"), ("ligne", "Ligne, puis symbole (plus rapide)")):
            ttk.Radiobutton(l1, text=texte, value=cle, variable=w,
                            command=lambda: self.changer("balayage", w.get())).pack(side="left", padx=(0, 16))
        self.case_a_cocher(c, "Dire chaque symbole tout bas pendant le défilement", "scan_voix")
        l2 = ttk.Frame(c)
        l2.pack(anchor="w", pady=(4, 0))
        for cle, nom in (("touche_a", "Contact pour avancer"), ("touche_b", "Contact pour choisir")):
            ttk.Label(l2, text=nom + " :").pack(side="left")
            b2 = ttk.Button(l2, text=NOMS_TOUCHES.get(self.r[cle], self.r[cle]), width=14)
            b2.configure(command=lambda c_=cle, b_=b2: self.apprendre(c_, b_))
            b2.pack(side="left", padx=(6, 18))
        ttk.Label(c, style="Note.TLabel",
                  text="Avec deux contacts, le clic gauche avance et le clic droit choisit. "
                       "Avec un seul contact, n'importe quelle touche ou clic convient.").pack(anchor="w", pady=(4, 0))

        return f

    def onglet_ecran(self, nb):
        d = ttk.Frame(nb, padding=12)
        l3 = ttk.Frame(d)
        l3.pack(anchor="w")
        ttk.Label(l3, text="Nombre de symboles par écran :").pack(side="left", padx=(0, 8))
        g = tk.StringVar(value=f"{self.r['colonnes']}x{self.r['lignes']}")

        def grille():
            c_, l_ = g.get().split("x")
            self.r["colonnes"], self.r["lignes"] = int(c_), int(l_)
            self.app.sauver()
        for co, li, nom in GRILLES:
            ttk.Radiobutton(l3, text=nom, value=f"{co}x{li}", variable=g, command=grille).pack(side="left", padx=(0, 10))
        self.case_a_cocher(d, "Écrire la phrase sous chaque symbole", "ecrire")
        self.case_a_cocher(d, "Revenir à l'accueil après chaque phrase", "retour_accueil")
        self.case_a_cocher(d, "Plein écran", "plein_ecran")
        v2 = tk.BooleanVar(value=os.path.exists(F_AUTOSTART))
        ttk.Checkbutton(d, text="Lancer au démarrage de l'ordinateur", variable=v2,
                        command=lambda: self.demarrage(v2.get())).pack(anchor="w", pady=2)
        return d

    def apprendre(self, cle, bouton):
        bouton.configure(text="Appuyez…")

        def recu(k):
            self.app.apprendre = None
            self.changer(cle, k)
            bouton.configure(text=NOMS_TOUCHES.get(k, k))
        self.app.apprendre = recu

    def demarrage(self, oui):
        if oui:
            os.makedirs(os.path.dirname(F_AUTOSTART), exist_ok=True)
            with open(F_AUTOSTART, "w", encoding="utf-8") as f:
                f.write("[Desktop Entry]\nType=Application\nName=Ma Voix\n"
                        f"Exec={NOM_PAQUET}\nIcon={NOM_PAQUET}\nTerminal=false\n")
        elif os.path.exists(F_AUTOSTART):
            os.remove(F_AUTOSTART)

    def onglet_voix(self, nb):
        f = ttk.Frame(nb, padding=12)
        a = ttk.LabelFrame(f, text="Voix", padding=8)
        a.pack(fill="x")
        v = tk.StringVar(value=self.r["voix"])
        for cle, texte in VOIX:
            ttk.Radiobutton(a, text=texte, value=cle, variable=v,
                            command=lambda: self.changer("voix", v.get())).pack(anchor="w", pady=1)
        b = ttk.LabelFrame(f, text="Réglage", padding=8)
        b.pack(fill="x", pady=(8, 0))
        self.curseur(b, "Lenteur (1 = normal, 2 = très lent)", "lenteur", 1, 2, unite="×", pas=0.05)
        self.curseur(b, "Volume", "volume", 20, 200, unite="%", pas=5)
        ttk.Label(b, style="Note.TLabel",
                  text="Après un changement de lenteur, les phrases sont refaites : "
                       "la première fois, chacune met une seconde de plus.").pack(anchor="w")
        c = ttk.LabelFrame(f, text="La personne parle au", padding=8)
        c.pack(fill="x", pady=(8, 0))
        g = tk.StringVar(value=self.r["genre"])
        for cle, texte in (("m", "Masculin (je suis content)"), ("f", "Féminin (je suis contente)")):
            ttk.Radiobutton(c, text=texte, value=cle, variable=g,
                            command=lambda: self.changer("genre", g.get())).pack(anchor="w")
        d = ttk.LabelFrame(f, text="Essayer", padding=8)
        d.pack(fill="x", pady=(8, 0))
        e = ttk.Entry(d)
        e.insert(0, "Je veux voir maman")
        e.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ttk.Button(d, text="Écouter", command=lambda: self.app.voix.dire(e.get())).pack(side="left")
        return f

    def onglet_apropos(self, nb):
        f = ttk.Frame(nb, padding=16)
        t = tk.Text(f, wrap="word", bg=BG, relief="flat", font=("DejaVu Sans", 10), height=18, highlightthickness=0)
        t.pack(fill="both", expand=True)
        t.insert("1.0", f"""Ma Voix {VERSION}

Parler avec des symboles, sans lire ni écrire.

Pictogrammes : Sergio Palao. Origine : ARASAAC (https://arasaac.org). Licence : Creative Commons BY-NC-SA. Propriété : Gouvernement d'Aragon (Espagne). Usage non commercial uniquement.

Voix naturelle : Piper avec la voix française Siwis (licence CC BY 4.0).
Voix de robot : eSpeak NG, synthèse de Klatt.

Le fonctionnement par défilement à un seul contact s'inspire d'ACAT, le logiciel libre d'Intel pour Stephen Hawking. Ce logiciel n'est ni lié à Intel ni approuvé par Intel.

Ce logiciel aide à communiquer. Il ne remplace pas une sonnette d'appel ni une surveillance médicale.
""")
        t.configure(state="disabled")
        return f


class Editeur(ttk.Frame):
    """Changer les symboles et les phrases."""

    def __init__(self, parent, app):
        super().__init__(parent, padding=10)
        self.app, self.t = app, app.t
        self.vignettes = {}
        self.page = "accueil"
        self.courant = None     # le symbole dont le champ de texte montre la phrase

        g = ttk.Frame(self)
        g.pack(side="left", fill="y")
        ttk.Label(g, text="Écrans").pack(anchor="w")
        self.pages = ttk.Treeview(g, show="tree", selectmode="browse", height=12)
        self.pages.column("#0", width=200)
        self.pages.pack(fill="y", expand=True)
        self.pages.bind("<<TreeviewSelect>>", self._page_choisie)
        ttk.Button(g, text="Remettre tout d'origine", command=self.remettre).pack(fill="x", pady=(6, 0))

        m = ttk.Frame(self)
        m.pack(side="left", fill="both", expand=True, padx=10)
        ttk.Label(m, text="Symboles de cet écran").pack(anchor="w")
        cadre = ttk.Frame(m)
        cadre.pack(fill="both", expand=True)
        self.liste = ttk.Treeview(cadre, show="tree", selectmode="browse", style="Symboles.Treeview")
        sb = ttk.Scrollbar(cadre, orient="vertical", command=self.liste.yview)
        self.liste.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.liste.pack(side="left", fill="both", expand=True)
        self.liste.bind("<<TreeviewSelect>>", self._symbole_choisi)

        d = ttk.Frame(self, width=270)
        d.pack(side="left", fill="y")
        self.apercu = ttk.Label(d, anchor="center")
        self.apercu.pack(pady=(0, 6))
        ttk.Label(d, text="Phrase dite à voix haute :").pack(anchor="w")
        self.v_texte = tk.StringVar()
        e = ttk.Entry(d, textvariable=self.v_texte, width=32)
        e.pack(fill="x")
        e.bind("<FocusOut>", lambda _e: self.enregistrer_texte())
        e.bind("<Return>", lambda _e: self.enregistrer_texte())
        for texte, cmd in (("Écouter", self.ecouter),
                           ("Mettre une photo ou une image…", self.image_fichier),
                           ("Chercher un symbole sur internet…", self.image_internet),
                           ("Monter", lambda: self.deplacer(-1)), ("Descendre", lambda: self.deplacer(1)),
                           ("Ajouter un symbole", self.ajouter),
                           ("Ajouter un écran", lambda: self.ajouter(dossier=True)),
                           ("Supprimer", self.supprimer)):
            ttk.Button(d, text=texte, command=cmd).pack(fill="x", pady=(5, 0))
        self.remplir_pages()

    def remplir_pages(self):
        self.pages.delete(*self.pages.get_children())
        for cle, p in self.t.items():
            self.pages.insert("", "end", iid=cle, text=p["nom"])
        if self.page not in self.t:
            self.page = "accueil"
        self.pages.selection_set(self.page)
        self.remplir_liste()

    def remplir_liste(self, garder=None):
        self.enregistrer_texte()
        self.courant = None
        self.liste.delete(*self.liste.get_children())
        self.vignettes = {}
        for i, it in enumerate(self.t[self.page]["items"]):
            v = Image.new("RGBA", (48, 48), (0, 0, 0, 0))
            p = picto(chemin_image(it["image"]), 46, 46)
            v.alpha_composite(p, ((48 - p.width) // 2, (48 - p.height) // 2))
            self.vignettes[i] = ImageTk.PhotoImage(v)
            self.liste.insert("", "end", iid=str(i), text=self.nom_ligne(it), image=self.vignettes[i])
        if garder is not None and self.liste.exists(str(garder)):
            self.liste.selection_set(str(garder))
            self.liste.see(str(garder))
            self._symbole_choisi(None)      # tout de suite, sans attendre l'événement
        else:
            self.courant = None
            self.v_texte.set("")
            self.apercu.configure(image="")

    def nom_ligne(self, it):
        return "  " + phrase(it, self.app.r) + ("  ▸ écran" if it.get("page") else "")

    def _page_choisie(self, _e):
        s = self.pages.selection()
        if s and s[0] != self.page:
            self.enregistrer_texte()
            self.page = s[0]
            self.remplir_liste()

    def rang(self):
        s = self.liste.selection()
        return int(s[0]) if s else None

    def item(self):
        i = self.rang()
        return None if i is None else self.t[self.page]["items"][i]

    def _symbole_choisi(self, _e):
        it = self.item()
        if it is self.courant:
            return
        self.enregistrer_texte()
        self.courant = it
        if it:
            self.v_texte.set(phrase(it, self.app.r))
            im = Image.new("RGBA", (160, 160), (255, 255, 255, 255))
            p = picto(chemin_image(it["image"]), 150, 150)
            im.alpha_composite(p, ((160 - p.width) // 2, (160 - p.height) // 2))
            self._apercu = ImageTk.PhotoImage(im)
            self.apercu.configure(image=self._apercu)

    def enregistrer_texte(self):
        # Toujours le symbole affiché dans le champ, pas celui qu'on vient de cliquer
        it = self.courant
        v = self.v_texte.get().strip()
        if not it or not v or v == phrase(it, self.app.r):
            return
        it["texte_f" if self.app.r["genre"] == "f" and "texte_f" in it else "texte"] = v
        if it.get("page"):
            self.t[it["page"]]["nom"] = v
            self.remplir_pages_sans_bouger()
        self.app.sauver_tableau()
        for i, x in enumerate(self.t[self.page]["items"]):
            if x is it:
                self.liste.item(str(i), text=self.nom_ligne(it))

    def remplir_pages_sans_bouger(self):
        for cle, p in self.t.items():
            self.pages.item(cle, text=p["nom"])

    def ecouter(self):
        self.enregistrer_texte()
        it = self.item()
        if it:
            self.app.voix.dire(phrase(it, self.app.r))

    def poser_image(self, chemin):
        it = self.item()
        if it and chemin:
            it["image"] = chemin
            self.app.sauver_tableau()
            self.remplir_liste(self.rang())

    def image_fichier(self):
        if self.item() is None:
            return self.demander_choix()
        d = ChoixImage(self)
        self.wait_window(d)
        if d.resultat:
            try:
                self.poser_image(importer_image(d.resultat))
            except (OSError, ValueError) as e:
                messagebox.showerror("Image", f"Cette image ne peut pas être lue.\n{e}", parent=self)

    def image_internet(self):
        if self.item() is None:
            return self.demander_choix()
        d = RechercheSymbole(self)
        self.wait_window(d)
        self.poser_image(d.resultat)

    def demander_choix(self):
        messagebox.showinfo("Symboles", "Choisissez d'abord un symbole dans la liste.", parent=self)

    def deplacer(self, sens):
        i = self.rang()
        items = self.t[self.page]["items"]
        if i is None or not 0 <= i + sens < len(items):
            return
        items[i], items[i + sens] = items[i + sens], items[i]
        self.app.sauver_tableau()
        self.remplir_liste(i + sens)

    def ajouter(self, dossier=False):
        items = self.t[self.page]["items"]
        it = {"image": "suivant.png", "texte": "Nouvel écran" if dossier else "Nouvelle phrase"}
        if dossier:
            n = 1
            while f"ecran{n}" in self.t:
                n += 1
            cle = f"ecran{n}"
            self.t[cle] = {"nom": it["texte"], "items": []}
            it["page"] = cle
            self.pages.insert("", "end", iid=cle, text=it["texte"])
        items.append(it)
        self.app.sauver_tableau()
        self.remplir_liste(len(items) - 1)

    def supprimer(self):
        i = self.rang()
        it = self.item()
        if it is None:
            return
        q = "Supprimer ce symbole ?"
        if it.get("page"):
            q = "Supprimer ce symbole et tout l'écran qu'il ouvre ?"
        if not messagebox.askyesno("Supprimer", q, parent=self):
            return
        del self.t[self.page]["items"][i]
        if it.get("page"):
            self.oublier_page(it["page"])
        self.app.sauver_tableau()
        self.remplir_pages()

    def oublier_page(self, cle):
        p = self.t.pop(cle, None)
        if p:
            for it in p["items"]:
                if it.get("page"):
                    self.oublier_page(it["page"])

    def remettre(self):
        if messagebox.askyesno("Remettre d'origine",
                               "Remettre tous les symboles et toutes les phrases d'origine ?\n"
                               "Vos photos et vos phrases seront perdues.", parent=self):
            self.t.clear()
            self.t.update(tableau_defaut())
            self.app.sauver_tableau()
            self.page = "accueil"
            self.remplir_pages()


def importer_image(chemin):
    """Copie l'image chez nous : elle reste là même si la clé USB est retirée."""
    os.makedirs(IMAGES_PERSO, exist_ok=True)
    with Image.open(chemin) as im:
        im = ImageOps.exif_transpose(im).convert("RGBA")
    im.thumbnail((900, 900), Image.LANCZOS)
    tampon = BytesIO()
    im.save(tampon, "PNG")
    nom = hashlib.sha1(tampon.getvalue()).hexdigest()[:16] + ".png"
    sortie = os.path.join(IMAGES_PERSO, nom)
    with open(sortie, "wb") as f:
        f.write(tampon.getvalue())
    return sortie


def lire_url(url):
    req = urllib.request.Request(url, headers={"User-Agent": "ma-voix"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read()


def numero(version):
    return tuple(int(x) for x in re.findall(r"\d+", version))


def chercher_maj():
    """Rend ce qu'il faut pour installer une version plus récente, ou None si on est à jour."""
    d = json.loads(lire_url(URL_DERNIERE))
    version = d["tag_name"].lstrip("v")
    if numero(version) <= numero(VERSION):
        return None
    for a in d.get("assets", []):
        if re.fullmatch(r"ma-voix(_[\d.]+)?_amd64\.deb", a["name"]):
            return {"version": version, "nom": a["name"], "url": a["browser_download_url"],
                    "empreinte": (a.get("digest") or "").replace("sha256:", "")}
    return None


def installation_possible():
    return (os.path.realpath(sys.argv[0]) == CHEMIN_PROGRAMME
            and all(os.path.exists(c) for c in ("/usr/bin/pkexec", "/usr/bin/apt-get")))


def telecharger(info, dossier, avancement):
    """Télécharge le paquet et vérifie qu'il est bien celui annoncé par GitHub."""
    chemin = os.path.join(dossier, info["nom"])
    req = urllib.request.Request(info["url"], headers={"User-Agent": "ma-voix"})
    h = hashlib.sha256()
    with urllib.request.urlopen(req, timeout=30) as r, open(chemin, "wb") as f:
        total, recu = int(r.headers.get("Content-Length") or 0), 0
        while True:
            bloc = r.read(1 << 18)
            if not bloc:
                break
            f.write(bloc)
            h.update(bloc)
            recu += len(bloc)
            if total:
                avancement(100 * recu / total)
    if info["empreinte"] and h.hexdigest() != info["empreinte"]:
        os.remove(chemin)
        raise ValueError("fichier abîmé")
    os.chmod(chemin, 0o644)         # apt le lit avec son propre utilisateur
    return chemin


class FenetreMaj(tk.Toplevel):
    """Télécharge et installe, puis relance le logiciel."""

    def __init__(self, reglages):
        super().__init__(reglages)
        self.app = reglages.app
        self.title("Mise à jour de Ma Voix")
        self.configure(bg=BG)
        self.geometry("440x130")
        self.resizable(False, False)
        self.transient(reglages.winfo_toplevel())
        self.protocol("WM_DELETE_WINDOW", lambda: None)     # on ne coupe pas une installation
        self.q = queue.Queue()
        c = ttk.Frame(self, padding=16)
        c.pack(fill="both", expand=True)
        self.texte = ttk.Label(c, text="Vérification…")
        self.texte.pack(anchor="w")
        self.barre = ttk.Progressbar(c, maximum=100)
        self.barre.pack(fill="x", pady=(10, 0))
        self.fermer = ttk.Button(c, text="Fermer", command=self.destroy)
        threading.Thread(target=self._travail, daemon=True).start()
        self.after(100, self._lire)

    def _travail(self):
        dossier = tempfile.mkdtemp(prefix="ma-voix-maj-")
        os.chmod(dossier, 0o755)
        try:
            info = chercher_maj()           # on revérifie : la version a pu changer entre-temps
            if not info:
                self.q.put(("fin", "Ma Voix est déjà à jour."))
                return
            self.q.put(("texte", f"Téléchargement de la version {info['version']}…"))
            deb = telecharger(info, dossier, lambda p: self.q.put(("avance", p)))
            self.q.put(("texte", "Installation : entrez le mot de passe administrateur…"))
            self.q.put(("attente", None))
            rc = subprocess.run(["/usr/bin/pkexec", "/usr/bin/apt-get", "install", "-y", deb],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode
            if rc == 0:
                self.q.put(("relance", None))
            elif rc in (126, 127):
                self.q.put(("fin", "Mise à jour annulée : mot de passe non donné."))
            else:
                self.q.put(("fin", "L'installation a échoué. Le logiciel reste dans sa version actuelle."))
        except ValueError:
            self.q.put(("fin", "Le fichier reçu est abîmé. Rien n'a été installé."))
        except (OSError, KeyError):
            self.q.put(("fin", "Pas d'accès à internet. Rien n'a été installé."))
        finally:
            shutil.rmtree(dossier, ignore_errors=True)

    def _lire(self):
        try:
            while True:
                quoi, v = self.q.get_nowait()
                if quoi == "texte":
                    self.texte.configure(text=v)
                elif quoi == "avance":
                    self.barre.configure(value=v)
                elif quoi == "attente":
                    self.barre.configure(mode="indeterminate")
                    self.barre.start(40)
                elif quoi == "relance":
                    self.texte.configure(text="Installé. Le logiciel redémarre…")
                    self.after(1200, self.app.relancer)
                    return
                else:
                    self.barre.stop()
                    self.barre.pack_forget()
                    self.texte.configure(text=v, wraplength=400)
                    self.fermer.pack(side="bottom", anchor="e", pady=(10, 0))
                    self.protocol("WM_DELETE_WINDOW", self.destroy)
                    return
        except queue.Empty:
            pass
        self.after(100, self._lire)


class ChoixImage(tk.Toplevel):
    """Choisir une image, à la façon du sélecteur de GNOME 2, avec aperçu."""
    EXT = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp")

    def __init__(self, parent):
        super().__init__(parent)
        self.title("Choisir une photo ou une image")
        self.configure(bg=BG)
        self.geometry("820x520")
        self.transient(parent.winfo_toplevel())
        self.resultat = None
        self.dossier = os.path.expanduser("~")

        g = ttk.Frame(self, padding=8)
        g.pack(side="left", fill="y")
        self.places = ttk.Treeview(g, show="tree", selectmode="browse")
        self.places.column("#0", width=170)
        self.places.pack(fill="y", expand=True)
        for nom, chemin in self.lieux():
            self.places.insert("", "end", text=nom, values=(chemin,))
        self.places.bind("<<TreeviewSelect>>", self._lieu)

        d = ttk.Frame(self, padding=(0, 8, 8, 8))
        d.pack(side="left", fill="both", expand=True)
        self.chemin = ttk.Label(d, style="Note.TLabel")
        self.chemin.pack(fill="x")
        bas = ttk.Frame(d)
        bas.pack(side="bottom", fill="x", pady=(6, 0))
        ttk.Button(bas, text="Choisir", command=self.valider).pack(side="right")
        ttk.Button(bas, text="Annuler", command=self.destroy).pack(side="right", padx=6)
        ttk.Button(bas, text="Dossier parent", command=lambda: self.aller(os.path.dirname(self.dossier))).pack(side="left")
        milieu = ttk.Frame(d)
        milieu.pack(fill="both", expand=True)
        self.apercu = ttk.Label(milieu, anchor="center", width=26)
        self.apercu.pack(side="right", fill="y", padx=(8, 0))
        self.liste = ttk.Treeview(milieu, show="tree", selectmode="browse")
        sb = ttk.Scrollbar(milieu, orient="vertical", command=self.liste.yview)
        self.liste.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.liste.pack(side="left", fill="both", expand=True)
        self.liste.bind("<<TreeviewSelect>>", self._selection)
        self.liste.bind("<Double-1>", lambda _e: self.valider())
        self.aller(self.dossier)

    @staticmethod
    def lieux():
        out = [("Dossier personnel", os.path.expanduser("~"))]
        for nom, cle in (("Bureau", "DESKTOP"), ("Images", "PICTURES"), ("Téléchargements", "DOWNLOAD")):
            try:
                c = subprocess.run(["xdg-user-dir", cle], capture_output=True, text=True).stdout.strip()
            except OSError:
                c = ""
            if c and os.path.isdir(c):
                out.append((nom, c))
        u = os.environ.get("USER", "")
        for base in (f"/run/media/{u}", f"/media/{u}"):
            if os.path.isdir(base):
                out += [(n, os.path.join(base, n)) for n in sorted(os.listdir(base))]
        return out

    def _lieu(self, _e):
        s = self.places.selection()
        if s:
            self.aller(self.places.item(s[0], "values")[0])

    def aller(self, dossier):
        try:
            noms = sorted(os.listdir(dossier), key=str.lower)
        except OSError:
            return
        self.dossier = dossier
        self.chemin.configure(text=dossier)
        self.liste.delete(*self.liste.get_children())
        noms = [n for n in noms if not n.startswith(".")]
        for n in noms:
            if os.path.isdir(os.path.join(dossier, n)):
                self.liste.insert("", "end", iid="d" + n, text="▸ " + n)
        for n in noms:
            if n.lower().endswith(self.EXT):
                self.liste.insert("", "end", iid="f" + n, text=n)

    def _selection(self, _e):
        s = self.liste.selection()
        if s and s[0][0] == "f":
            p = picto(os.path.join(self.dossier, s[0][1:]), 200, 200)
            self._ap = ImageTk.PhotoImage(p)
            self.apercu.configure(image=self._ap)

    def valider(self):
        s = self.liste.selection()
        if not s:
            return
        chemin = os.path.join(self.dossier, s[0][1:])
        if s[0][0] == "d":
            self.aller(chemin)
        else:
            self.resultat = chemin
            self.destroy()


class RechercheSymbole(tk.Toplevel):
    """Chercher dans les pictogrammes ARASAAC (il faut internet)."""

    def __init__(self, parent):
        super().__init__(parent)
        self.title("Chercher un symbole")
        self.configure(bg=BG)
        self.geometry("760x560")
        self.transient(parent.winfo_toplevel())
        self.resultat = None
        self.q = queue.Queue()
        self.n_recherche = 0
        self.images = []

        h = ttk.Frame(self, padding=10)
        h.pack(fill="x")
        self.e = ttk.Entry(h)
        self.e.pack(side="left", fill="x", expand=True)
        self.e.bind("<Return>", lambda _e: self.chercher())
        self.e.focus_set()
        ttk.Button(h, text="Chercher", command=self.chercher).pack(side="left", padx=(8, 0))
        self.etat = ttk.Label(self, style="Note.TLabel", padding=(10, 0),
                              text="Tapez un mot. Pictogrammes ARASAAC, usage non commercial.")
        self.etat.pack(fill="x")
        cadre = ttk.Frame(self, padding=10)
        cadre.pack(fill="both", expand=True)
        self.c = tk.Canvas(cadre, bg="#FFFFFF", highlightthickness=1, highlightbackground=BORD)
        sb = ttk.Scrollbar(cadre, orient="vertical", command=self.c.yview)
        self.c.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.c.pack(side="left", fill="both", expand=True)
        self.grille = tk.Frame(self.c, bg="#FFFFFF")
        self.c.create_window(0, 0, anchor="nw", window=self.grille)
        self.grille.bind("<Configure>", lambda _e: self.c.configure(scrollregion=self.c.bbox("all")))
        self.after(100, self._lire)

    def chercher(self):
        mot = self.e.get().strip()
        if not mot:
            return
        self.n_recherche += 1
        for w in self.grille.winfo_children():
            w.destroy()
        self.images = []
        self.etat.configure(text="Recherche en cours…")
        threading.Thread(target=self._travail, args=(self.n_recherche, mot), daemon=True).start()

    def _travail(self, n, mot):
        try:
            data = lire_url("https://api.arasaac.org/v1/pictograms/fr/search/" + urllib.parse.quote(mot))
            trouves = [x["_id"] for x in json.loads(data) if not x.get("sex") and not x.get("violence")][:24]
        except urllib.error.HTTPError:
            trouves = []
        except (OSError, ValueError):
            self.q.put((n, "erreur", None))
            return
        self.q.put((n, "total", len(trouves)))
        for i in trouves:
            try:
                self.q.put((n, i, lire_url(f"https://static.arasaac.org/pictograms/{i}/{i}_300.png")))
            except OSError:
                pass

    def _lire(self):
        try:
            while True:
                n, quoi, valeur = self.q.get_nowait()
                if n != self.n_recherche:
                    continue
                if quoi == "erreur":
                    self.etat.configure(text="Pas d'accès à internet.")
                elif quoi == "total":
                    self.etat.configure(text=f"{valeur} symbole(s). Cliquez sur celui qui convient."
                                        if valeur else "Aucun symbole pour ce mot.")
                else:
                    self.ajouter(quoi, valeur)
        except queue.Empty:
            pass
        self.after(100, self._lire)

    def ajouter(self, num, octets):
        im = Image.open(BytesIO(octets)).convert("RGBA")
        im.thumbnail((130, 130), Image.LANCZOS)
        ph = ImageTk.PhotoImage(im)
        self.images.append(ph)
        k = len(self.images) - 1
        tk.Button(self.grille, image=ph, bg="#FFFFFF", relief="flat", activebackground="#FBE6D3",
                  command=lambda: self.prendre(num, octets)).grid(row=k // 5, column=k % 5, padx=2, pady=2)

    def prendre(self, num, octets):
        os.makedirs(IMAGES_PERSO, exist_ok=True)
        try:
            octets = lire_url(f"https://static.arasaac.org/pictograms/{num}/{num}_500.png")
        except OSError:
            pass                        # on garde la version plus petite déjà reçue
        chemin = os.path.join(IMAGES_PERSO, f"arasaac_{num}.png")
        with open(chemin, "wb") as f:
            f.write(octets)
        self.resultat = chemin
        self.destroy()


def main():
    if "--version" in sys.argv:
        print("Ma Voix", VERSION)
        return
    if "--preparer-sons" in sys.argv:
        preparer_sons(sys.argv[sys.argv.index("--preparer-sons") + 1])
        return
    os.makedirs(CONF, exist_ok=True)
    verrou = open(os.path.join(CONF, "verrou"), "w")
    try:
        fcntl.flock(verrou, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("Ma Voix est déjà ouvert.", file=sys.stderr)
        return
    Appli().root.mainloop()


if __name__ == "__main__":
    main()
