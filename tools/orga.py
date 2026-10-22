#!/usr/bin/env python3
"""Outil de l'espace organisateur 10 Doigts en Cavale.

Le dépôt est public : seules des données CHIFFRÉES y sont publiées (e/<fichier>.json).
La clé de chaque événement n'existe que dans le lien envoyé à l'organisateur
(#<fichier>.<clé>) et dans le Google Sheet privé « ORGA - LIENS ». Ne jamais
écrire une clé ni des données en clair dans ce dépôt.

  python3 tools/orga.py nouveau                       -> affiche un nouvel identifiant de fichier et une nouvelle clé
  python3 tools/orga.py chiffrer <data.json> <fichier> <clé>   -> écrit e/<fichier>.json
  python3 tools/orga.py dechiffrer <fichier> <clé>    -> affiche le JSON en clair (vérification)
"""
import base64, json, os, sys
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
b64 = lambda b: base64.urlsafe_b64encode(b).decode().rstrip("=")
unb64 = lambda s: base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))

def nouveau():
    print(json.dumps({"fichier": b64(os.urandom(12)), "cle": b64(os.urandom(32))}))

def chiffrer(src, fichier, cle):
    data = json.dumps(json.load(open(src, encoding="utf-8")), ensure_ascii=False, separators=(",", ":")).encode()
    iv = os.urandom(12)
    ct = AESGCM(unb64(cle)).encrypt(iv, data, None)
    out = os.path.join(ROOT, "e", fichier + ".json")
    json.dump({"v": 1, "iv": b64(iv), "ct": b64(ct)}, open(out, "w"))
    print("écrit :", os.path.relpath(out, ROOT))

def dechiffrer(fichier, cle):
    box = json.load(open(os.path.join(ROOT, "e", fichier + ".json")))
    print(AESGCM(unb64(cle)).decrypt(unb64(box["iv"]), unb64(box["ct"]), None).decode())

if __name__ == "__main__":
    a = sys.argv[1:]
    {"nouveau": lambda: nouveau(), "chiffrer": lambda: chiffrer(*a[1:4]), "dechiffrer": lambda: dechiffrer(*a[1:3])}[a[0]]()
