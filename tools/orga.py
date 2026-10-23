#!/usr/bin/env python3
"""Outil de l'espace organisateur 10 Doigts en Cavale.

Le dépôt est public : seules des données CHIFFRÉES y sont publiées (e/<fichier>.json).
La clé de chaque événement n'existe que dans le lien envoyé à l'organisateur
(#<fichier>.<clé>) et dans le Google Sheet privé « ORGA - LIENS ». Ne jamais
écrire une clé ni des données en clair dans ce dépôt.

  python3 tools/orga.py nouveau                       -> affiche un nouvel identifiant de fichier et une nouvelle clé
  python3 tools/orga.py chiffrer <data.json> <fichier> <clé>   -> écrit e/<fichier>.json
  python3 tools/orga.py dechiffrer <fichier> <clé>    -> affiche le JSON en clair (vérification)
  python3 tools/orga.py appliquer <fichier> <clé> <lignes.json> -> applique les réponses du formulaire, affiche les nouveautés
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

def lire(fichier, cle):
    box = json.load(open(os.path.join(ROOT, "e", fichier + ".json")))
    return json.loads(AESGCM(unb64(cle)).decrypt(unb64(box["iv"]), unb64(box["ct"]), None))

def ecrire(fichier, cle, data):
    iv = os.urandom(12)
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode()
    json.dump({"v": 1, "iv": b64(iv), "ct": b64(AESGCM(unb64(cle)).encrypt(iv, raw, None))}, open(os.path.join(ROOT, "e", fichier + ".json"), "w"))

def date_iso(h):
    """« 22/10/2026 19:50:12 » (heure de Paris) -> ISO UTC."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    try:
        d = datetime.strptime(h.strip(), "%d/%m/%Y %H:%M:%S").replace(tzinfo=ZoneInfo("Europe/Paris"))
        return d.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return h

def appliquer(fichier, cle, lignes_json):
    """Applique les lignes du formulaire (valeurs du Google Sheet, en-tête compris) à l'événement.
    Affiche en JSON les nouveautés appliquées, pour les reporter dans la FDR, le Drive et l'Agenda."""
    import hashlib
    from datetime import datetime, timezone
    data = lire(fichier, cle)
    vus = set(data.get("vus", []))
    data.setdefault("reponses", {}); data.setdefault("questions", {}); data.setdefault("journal", [])
    nouveau = []
    for row in json.load(open(lignes_json))[1:]:
        row = (row + [""] * 5)[:5]
        horo, ev, point, texte, source = [str(x).strip() for x in row]
        if ev != fichier or not point:
            continue
        sig = hashlib.sha256("|".join([horo, point, texte, source]).encode()).hexdigest()[:16]
        if sig in vus:
            continue
        vus.add(sig)
        date = date_iso(horo)
        src = "10DEC" if source.startswith("10DEC") else "orga"
        if point.startswith("question:"):
            data["questions"].setdefault(point[9:], []).append({"texte": texte, "date": date, "source": src})
        else:
            r = {"texte": texte, "date": date, "source": src}
            if src == "10DEC":
                r["statut"] = source.split(":", 1)[1] if ":" in source else "ok"
            data["reponses"][point] = r
        e = {"date": date, "point": point, "texte": texte, "source": src}
        data["journal"].append(e)
        nouveau.append(e)
    data["journal"] = sorted(data["journal"], key=lambda x: x["date"])[-60:]
    data["vus"] = sorted(vus)
    if nouveau:
        data["maj"] = datetime.now(timezone.utc).astimezone().strftime("%d/%m/%Y")
        ecrire(fichier, cle, data)
    print(json.dumps({"evenement": data.get("artiste", "") + " - " + data.get("lieu", ""), "nouveautes": nouveau}, ensure_ascii=False, indent=1))

def manquants(fichier, cle):
    """Liste, sujet par sujet, ce qui n'est pas encore complété (même logique que la page),
    et les adresses mail saisies dans la page pour chaque sujet. Sert aux relances."""
    import re
    d = lire(fichier, cle)
    rep = {k: v for k, v in d.get("reponses", {}).items() if not str(v.get("texte", "")).startswith("✗")}
    mail = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
    def team(pid):
        r = d.get("reponses", {}).get("team-" + pid) or {}
        return r.get("statut") if str(r.get("source", "")).startswith("10DEC") else None
    def fait(pid, statut="todo"):
        r = d.get("reponses", {}).get(pid) or {}
        if str(r.get("source", "")).startswith("10DEC"):
            return r.get("statut", "ok") != "todo"
        return statut in ("ok", "info") or pid in rep
    def contact_fait(cid):
        return d["contacts"].get(cid, {}).get("statut") == "ok" or cid in rep
    def groupe_fait(g):
        return all(contact_fait(r["c"]) for r in d["groups"][g]["roles"])
    def mails(cids):
        out = []
        for c in cids:
            txt = str((rep.get(c) or {}).get("texte", "")) + " " + str(d["contacts"].get(c, {}).get("valeur", ""))
            out += mail.findall(txt)
        return out
    sujets = []
    for t in d["topics"]:
        reste, cids = [], []
        for i, b in enumerate(t.get("besoins", [])):
            if not fait(f'{t["id"]}-b{i}'): reste.append(b["t"] if isinstance(b, dict) else b)
        imp = t.get("important")
        if imp and not t.get("importantTop") and not fait(t["id"] + "-imp"):
            reste.append(imp["t"] if isinstance(imp, dict) else imp)
        for it in t.get("items", []):
            if "contact" in it:
                cids.append(it["contact"])
                if not contact_fait(it["contact"]): reste.append(d["contacts"][it["contact"]]["role"])
            elif not fait(it["id"], it.get("statut", "todo")):
                reste.append(it["titre"])
        if t.get("confirm") and not t.get("besoins") and not fait(t["confirm"]["id"]):
            reste.append("Confirmation : " + t["label"])
        gs = ([t["qui"]] if t.get("qui") else []) + [e[2:] for e in t.get("contactsList", []) if e.startswith("g:")]
        for g in gs:
            cids += [r["c"] for r in d["groups"][g]["roles"]]
            if not groupe_fait(g): reste.append(d["groups"][g]["titre"])
        for e in t.get("contactsList", []):
            if not e.startswith("g:"):
                cids.append(e)
                if not contact_fait(e): reste.append(d["contacts"][e]["role"])
        if reste:
            sujets.append({"id": t["id"], "label": t["label"], "pour": t.get("pour", ""), "echeance": t.get("iso"),
                           "lien": "~" + t["id"], "manque": reste, "mails": sorted(set(mails(cids)))})
    tous = sorted(set(mail.findall(json.dumps(rep, ensure_ascii=False))))
    print(json.dumps({"evenement": d.get("artiste", "") + " · " + d.get("lieu", ""), "date": d.get("iso"),
                      "sujets": sujets, "mails_saisis": tous}, ensure_ascii=False, indent=1))

def dechiffrer(fichier, cle):
    box = json.load(open(os.path.join(ROOT, "e", fichier + ".json")))
    print(AESGCM(unb64(cle)).decrypt(unb64(box["iv"]), unb64(box["ct"]), None).decode())

if __name__ == "__main__":
    a = sys.argv[1:]
    {"nouveau": lambda: nouveau(), "chiffrer": lambda: chiffrer(*a[1:4]), "dechiffrer": lambda: dechiffrer(*a[1:3]),
     "appliquer": lambda: appliquer(*a[1:4]), "manquants": lambda: manquants(*a[1:3])}[a[0]]()
