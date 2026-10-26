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
  python3 tools/orga.py equipe <fichier> <clé> <fdr.json>     -> tableau de l'équipe (noms + téléphones) depuis la fiche FDR
  python3 tools/orga.py trajets <fichier> <clé> <fdr.json>    -> heure du run aller (train), hébergement ; alerte si ça change
"""
import base64, json, os, re, sys
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

# Parcours de la vidéo d'annonce LSF (texte → vidéo → montage → publication) : réponses rattachées à l'item « parcours ».
PARCOURS_IDS = ["com-texte", "com-texte-ok", "com-video-ok", "com-montage", "com-montage-fait", "com-quand", "com-heure", "com-collab"]

def parcours_reste(it, rep):
    """Étape en cours du parcours vidéo, si c'est à l'organisateur de la faire (sinon None)."""
    fait = it.get("fait", {})
    etapes = [("texte", "com-texte-ok", "Texte d'annonce à écrire"), ("video", "com-video-ok", None),
              ("montage", "com-montage-fait", "Montage de la vidéo (sous-titres, charte)"), ("publi", None, "Jour et heure de publication de la vidéo")]
    for k, ok, lib in etapes:
        done = fait.get(k) or (ok and ok in rep) or (k == "publi" and "com-quand" in rep and "com-heure" in rep)
        if not done:
            if k == "texte" and "com-texte" in rep: return None
            return lib
    return None

def appliquer(fichier, cle, lignes_json, code=""):
    """Applique les lignes du formulaire (valeurs du Google Sheet, en-tête compris) à l'événement.
    Affiche en JSON les nouveautés appliquées, pour les reporter dans la FDR, le Drive et l'Agenda."""
    import hashlib
    from datetime import datetime, timezone
    data = lire(fichier, cle)
    vus = set(data.get("vus", []))
    data.setdefault("reponses", {}); data.setdefault("questions", {}); data.setdefault("journal", [])
    nouveau = []
    envoi = ""
    # Événements jumeaux (ex. deux artistes le même soir, un espace chacun) : une réponse sur un sujet commun
    # (accueil, horaires, com…) pré-remplit l'autre espace, sauf si celui-ci a déjà sa propre réponse.
    jum = data.get("jumeaux") or {}
    jf = {j["fichier"]: j.get("nom", "") for j in jum.get("fichiers", [])}
    ids = set(jum.get("contacts", []))
    propres = set(jum.get("propres", []))  # blocs d'un sujet commun propres à chaque concert (ex. captation : scènes différentes)
    def collect(x):
        if isinstance(x, dict):
            if x.get("id") in propres: return
            if isinstance(x.get("id"), str): ids.add(x["id"])
            if x.get("type") == "parcours": ids.update(PARCOURS_IDS)
            if x.get("type") == "passes": ids.update(["pass-" + c["k"] for c in x.get("choses", [])] + [x.get("ou", "pass-ou")])
            if x.get("si"): ids.add(x["si"])
            for v in x.values(): collect(v)
        elif isinstance(x, list):
            for v in x: collect(v)
    for t in data.get("topics", []):
        if t.get("id") in jum.get("sujets", []):
            collect(t.get("items", [])); collect(t.get("besoins", []))
            ids.update(f'{t["id"]}-b{i}' for i in range(len(t.get("besoins", [])))); ids.add(t["id"] + "-imp")
            if t.get("confirm"): ids.add(t["confirm"]["id"])
    partage = lambda pt: any(pt == i or pt.startswith(i + "-") for i in ids)
    for row in json.load(open(lignes_json))[1:]:
        row = (row + [""] * 5)[:5]
        horo, ev, point, texte, source = [str(x).strip() for x in row]
        miroir = ""
        if not point:
            continue
        if ev != fichier:
            if ev not in jf or point.startswith("question:") or not partage(point):
                continue
            deja = data["reponses"].get(point)
            if deja and not deja.get("miroir"):
                continue
            miroir = jf[ev] or "l'autre espace"
        sig = hashlib.sha256("|".join([horo, point, texte, source]).encode()).hexdigest()[:16]
        if sig in vus:
            continue
        vus.add(sig)
        date = date_iso(horo)
        # Source : « orga:Prénom – rôle » ou « 10DEC:<statut>:<signature> ».
        # Une réponse « 10DEC » n'est acceptée que si sa signature (code équipe) est valide ; sinon elle compte comme organisateur.
        auteur, statut = "", "ok"
        if source.startswith("10DEC"):
            parts = source.split(":")
            statut = parts[1] if len(parts) > 1 and parts[1] in ("ok", "todo") else "ok"
            attendu = hashlib.sha256((code + "|" + point + "|" + texte).encode()).hexdigest()[:16] if code else None
            if attendu and len(parts) > 2 and parts[2] == attendu:
                src, auteur = "10DEC", "10 Doigts en Cavale"
            else:
                src, auteur = "orga", "réponse « 10DEC » non signée (à vérifier)"
        else:
            src = "orga"
            auteur = source[5:].strip()[:60] if source.startswith("orga:") else ""
        if miroir:
            auteur = (auteur + " · " if auteur else "") + "repris de l'espace " + miroir
        if point == "envoi":  # « lien envoyé » coché dans la page équipe : seulement si signé par l'équipe
            if src == "10DEC" and not miroir:
                data["envoye"] = texte; envoi = texte
            continue
        if point.startswith("question:"):
            data["questions"].setdefault(point[9:], []).append({"texte": texte, "date": date, "source": src, "auteur": auteur})
        else:
            r = {"texte": texte, "date": date, "source": src, "auteur": auteur}
            if src == "10DEC":
                r["statut"] = statut
            if miroir:
                r["miroir"] = miroir
            data["reponses"][point] = r
        e = {"date": date, "point": point, "texte": texte, "source": src, "auteur": auteur}
        data["journal"].append(e)
        nouveau.append(e)
    data["journal"] = sorted(data["journal"], key=lambda x: x["date"])[-60:]
    data["vus"] = sorted(vus)
    if nouveau or envoi:
        data["maj"] = datetime.now(timezone.utc).astimezone().strftime("%d/%m/%Y")
        ecrire(fichier, cle, data)
    print(json.dumps({"evenement": data.get("artiste", "") + " - " + data.get("lieu", ""), "nouveautes": nouveau, "envoi": envoi}, ensure_ascii=False, indent=1))

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
        g = next((it for it in t.get("items", []) if it.get("gate") and it.get("type") == "ouinon"), None)
        if g and str((rep.get(g["id"]) or {}).get("texte", "")) == g.get("non", "Non."):
            continue  # « Non » à la question d'entrée (ex. pas de retransmission) : rien d'autre à demander
        for i, b in enumerate(t.get("besoins", [])):
            if not fait(f'{t["id"]}-b{i}'): reste.append(b["t"] if isinstance(b, dict) else b)
        imp = t.get("important")
        if imp and not t.get("importantTop") and not fait(t["id"] + "-imp"):
            reste.append(imp["t"] if isinstance(imp, dict) else imp)
        for it in t.get("items", []):
            if it.get("dans"):  # rangé dans un autre bloc (ex. dépôt paroles/audio dans le tableau de setlist)
                continue
            if it.get("si") and ((d.get("reponses", {}).get(it["si"]) or {}).get("texte") or ("oui" if it.get("siDef") else "non")) != "oui":
                continue  # bloc masqué par l'équipe (ex. accès voiture : on ne vient pas en voiture)
            if it.get("type") == "tuiles":
                on = str((rep.get(it["id"]) or {}).get("texte", "")).split(" · ")
                manque = [o.get("t", o["texte"]) for o in it.get("options", []) if o["texte"] not in on]
                if manque: reste.append(it.get("titre", "").lstrip("🚪 ").strip() + " : " + ", ".join(manque))
                continue
            if it.get("avec"):
                continue
            if it.get("type") == "passes":
                vals = {c["k"]: (rep.get("pass-" + c["k"]) or {}).get("texte", "") for c in it.get("choses", [])}
                manque = [c["t"] for c in it.get("choses", []) if not vals[c["k"]]]
                if manque: reste.append(it.get("titre", "Pass") + " : " + ", ".join(manque))
                elif "place" in vals.values() and it.get("ou", "pass-ou") not in rep: reste.append(it.get("titre", "Pass") + " sur place : où et auprès de qui")
                continue
            if it.get("type") == "assos":
                garde = [a for a in it.get("liste", []) if (rep.get(it["id"] + "-" + a["k"] + "-rm") or {}).get("texte") != "oui"][:15]  # les 15 premières ; les autres sont en « Voir + »
                lignes = [it["id"] + "-" + a["k"] for a in garde if not a.get("deja")]
                lignes += sorted({k for k in rep if re.match("^" + re.escape(it["id"]) + r"-x[a-z0-9]{4,10}$", k) and not str((rep.get(k) or {}).get("texte", "")).startswith("✗")})
                faits = sum(1 for l in lignes if (rep.get(l + "-env") or {}).get("texte") == "Envoyé")
                if faits < len(lignes): reste.append(f"Prévenir les associations sourdes ({faits}/{len(lignes)})")
                continue
            if it.get("type") == "parcours":
                lib = parcours_reste(it, rep)
                if lib: reste.append(lib)
                continue
            if "contact" in it:
                cids.append(it["contact"])
                if not contact_fait(it["contact"]): reste.append(d["contacts"][it["contact"]]["role"])
            elif it.get("type") == "repas":
                continue
            elif it.get("type") == "fiche":
                g = next((r for r in it["rows"] if r.get("gate")), None)
                if g and str((rep.get(g["id"]) or {}).get("texte", "")) == "Non":
                    continue
                vis = [r for r in it["rows"] if not r.get("on") or str((rep.get(r["on"]) or {}).get("texte", "")) == r.get("si")]
                vides = [r["label"] for r in vis if r.get("type") != "note" and not r.get("opt") and r["id"] not in rep]
                if vides: reste.append(it["titre"] + " : " + ", ".join(vides))
            elif it.get("type") == "hebergement":
                q = (d.get("reponses", {}).get("heb-qui") or {}).get("texte") or (it.get("auto") or {}).get("qui") or it.get("qui", "orga")
                if str((d.get("reponses", {}).get(it["id"] + "-pasbesoin") or {}).get("texte", "")) == "oui" or q == "10dec":
                    continue
                v = lambda k: (rep.get("heb-" + k) or {}).get("texte", "")
                vides = [l for k, l in (("nom", "nom"), ("adr", "adresse"), ("dates", "dates"), ("pdj", "petit-déjeuner")) if not v(k)]
                if not ((v("twin") or "0").isdigit() and int(v("twin") or 0) + int(v("single") or 0) > 0): vides.append("chambres")
                if vides: reste.append(it["titre"] + " : " + ", ".join(vides))
            elif it.get("type") == "grille":  # tableau à colonnes (runs) : case « <ligne>-<colonne> »
                if str((d.get("reponses", {}).get(it["id"] + "-pasbesoin") or {}).get("texte", "")) == "oui":
                    continue  # « Pas besoin, l'équipe est autonome » coché par l'équipe
                ext = [{"id": k, "nom": v["texte"]} for k, v in rep.items() if re.fullmatch(re.escape(it["id"]) + r"-x[a-z0-9]{4,10}", k)]
                vides = [f'{r.get("nom", r["id"])} : {c["l"]}' for r in it["rows"] + ext for c in it["cols"]
                         if not (r.get("cells") or {}).get(c["k"]) and f'{r["id"]}-{c["k"]}' not in rep]
                if vides: reste.append(it["titre"] + " : " + ", ".join(vides))
            elif it.get("type") == "tableau":
                def repas_a(k):
                    for t2 in d["topics"]:
                        for it2 in t2.get("items", []):
                            if it2.get("type") == "repas":
                                for i, r2 in enumerate(it2["rows"]):
                                    o = (rep.get(f'{it2["id"]}-{i}-{k}') or {}).get("texte")
                                    if (o == "oui") if o else r2.get(k): return True
                    return False
                vides = [r["b"] for r in it["rows"] if (not r.get("repas") or repas_a(r["repas"])) and not r.get("a") and r["id"] not in rep]
                if vides: reste.append(it["titre"] + " : " + ", ".join(vides))
            elif not fait(it["id"], it.get("statut", "todo")):
                reste.append(it["titre"])
        if t.get("confirm") and not t.get("besoins") and not fait(t["confirm"]["id"]):
            reste.append("Confirmation : " + t["label"])
        # « ↩ À revoir » envoyé par l'équipe (vu:<bloc> = « revoir|<mot> ») et pas encore repris par l'organisateur
        blocs = [t["id"] + "-prevu"] + [it.get("id", "") for it in t.get("items", [])] + (["grp-" + t["qui"]] if t.get("qui") else [])
        for k in blocs:
            v = d.get("reponses", {}).get("vu:" + k) or {}
            if str(v.get("texte", "")).startswith("revoir|"):
                apres = [r for pid, r in rep.items() if not pid.startswith("vu:") and (pid == k or pid.startswith(k + "-")) and r.get("date", "") > v.get("date", "")]
                if not apres: reste.append("À revoir : " + v["texte"].split("|", 1)[1])
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

def depots(fichier, cle):
    """Liste les points avec une demande de fichiers Dropbox : dossier à surveiller et état (reçu ou non)."""
    d = lire(fichier, cle); out = []
    for t in d.get("topics", []):
        for it in t.get("items", []):
            if it.get("dossier"):
                r = d.get("reponses", {}).get(it["id"]) or {}
                out.append({"point": it["id"], "titre": it.get("titre", ""), "dossier": it["dossier"],
                            "recu": r.get("source") == "10DEC" and r.get("texte", "").startswith("Reçu")})
    print(json.dumps(out, ensure_ascii=False, indent=1))

def recu(fichier, cle, point, noms):
    """Marque un point « Reçu » quand des fichiers sont arrivés dans son dossier Dropbox."""
    from datetime import datetime, timezone
    d = lire(fichier, cle); now = datetime.now(timezone.utc).astimezone()
    texte = "Reçu : " + noms.strip()[:200]
    r = {"texte": texte, "date": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "source": "10DEC", "auteur": "Dépôt Dropbox", "statut": "ok"}
    d.setdefault("reponses", {})[point] = r
    d.setdefault("journal", []).append({k: r[k] for k in ("date", "texte", "source", "auteur")} | {"point": point})
    d["maj"] = now.strftime("%d/%m/%Y"); ecrire(fichier, cle, d)
    print(json.dumps({"point": point, "texte": texte}, ensure_ascii=False))

def accueil(liens_json, fichier, cle, code):
    """Accueil équipe : liste chiffrée de tous les événements du tableau privé des liens.
    Chiffrée avec une clé dérivée du lien (#fichier.clé) ET du code équipe : le lien seul ne suffit pas."""
    import hashlib
    from datetime import datetime, timezone
    evs = []
    for row in json.load(open(liens_json))[1:]:
        row = (list(row) + [""] * 13)[:13]
        nom, date, f, k, lorga, statut, lequipe, fdr, envoye, mail, relances, derniere = [str(x).strip() for x in row[:12]]
        if not (f and k):
            continue
        e = {"nom": nom, "date": date, "fichier": f, "lienOrga": lorga, "lienEquipe": lequipe, "fdr": fdr,
             "statut": statut, "envoye": envoye, "contact": mail, "relances": relances, "derniereRelance": derniere}
        try:
            d = lire(f, k)
            e.update(artiste=d.get("artiste", ""), lieu=d.get("lieu", ""), ville=d.get("ville", ""), iso=d.get("iso", ""),
                     chansigneurs=d.get("chansigneurs", ""), heure=d.get("heure", ""))
            dos = next((it.get("dossier") for t in d.get("topics", []) for it in t.get("items", []) if it.get("dossier")), "")
            if dos:
                e["dropbox"] = "https://www.dropbox.com/home" + "/".join(dos.split("/")[:3]).replace(" ", "%20")
        except Exception as ex:
            e["erreur"] = "Espace illisible : " + type(ex).__name__
        evs.append(e)
    evs.sort(key=lambda e: e.get("iso") or "9999")
    data = {"maj": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "evenements": evs}
    key = hashlib.pbkdf2_hmac("sha256", code.encode(), unb64(cle), 200000, 32)
    iv = os.urandom(12)
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode()
    json.dump({"v": 2, "kdf": "pbkdf2-sha256-200000", "iv": b64(iv), "ct": b64(AESGCM(key).encrypt(iv, raw, None))},
              open(os.path.join(ROOT, "e", fichier + ".json"), "w"))
    print(json.dumps({"evenements": [e["nom"] for e in evs]}, ensure_ascii=False))

def profils(fichier, cle, values_json):
    """Reprend l'onglet « REPAS & TAILLES » de la fiche FDR (régime et tailles saisis par chaque chansigneur dans l'appli FDR)
    dans le tableau des repas et le tableau des tailles (dresscode) de l'espace. N'affiche aucune valeur (données personnelles)."""
    from datetime import datetime, timezone
    d = lire(fichier, cle); rows = json.load(open(values_json)); rows = rows.get("values", rows) if isinstance(rows, dict) else rows
    P = {}
    for r in rows[2:]:
        r = [str(x).strip() for x in (list(r) + [""] * 5)[:5]]
        if r[0] and r[1] != "pas encore répondu": P[r[0].lower()] = {"regime": r[1], "haut": r[2], "bas": r[3], "nom": r[0]}
    def trouve(nom):
        n = nom.strip().lower()
        return P.get(n) or next((v for k, v in P.items() if k.split(" ")[0] == n.split(" ")[0]), None)
    R = d.setdefault("reponses", {}); now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"); n = 0
    def pose(pid, val, qui):
        nonlocal n
        if not val: return
        cur = R.get(pid) or {}
        if cur.get("texte") == val: return
        R[pid] = {"texte": val, "date": now, "source": "10DEC", "statut": "ok", "auteur": "FDR · saisi par " + qui}; n += 1
    for t in d.get("topics", []):
        for it in t.get("items", []):
            if it.get("type") == "repas":
                for i, row in enumerate(it.get("rows", [])):
                    v = trouve(row.get("nom", ""))
                    if v: pose(f'{it["id"]}-{i}-regime', v["regime"], v["nom"])
            for row in it.get("rows", []) if it.get("type") == "fiche" else []:
                if row.get("type") == "tailles":
                    for i, nom in enumerate(row.get("personnes", [])):
                        v = trouve(nom)
                        if v: pose(f'{row["id"]}-{i}-haut', v["haut"], v["nom"]); pose(f'{row["id"]}-{i}-bas', v["bas"], v["nom"])
    if n:
        d["maj"] = datetime.now(timezone.utc).astimezone().strftime("%d/%m/%Y"); ecrire(fichier, cle, d)
    print(json.dumps({"mis_a_jour": n}))

def equipe(fichier, cle, values_json):
    """Tableau « L'équipe de chansigneurs » de l'espace : noms de la ligne « Équipe 10 Doigts » de la fiche FDR,
    téléphones pris dans la partie « 📞 CONTACTS SUR PLACE » de la même fiche (même prénom). N'affiche aucun numéro."""
    import re
    d = lire(fichier, cle); rows = json.load(open(values_json)); rows = rows.get("values", rows) if isinstance(rows, dict) else rows
    rows = [[str(x).strip() for x in (list(r) + [""] * 5)[:5]] for r in rows]
    noms, contacts, zone = [], [], False
    for r in rows:
        if r[0] == "Équipe 10 Doigts": noms = [n for n in re.split(r"\s*(?:,|\bet\b|&|\+)\s*", r[2]) if n]
        if r[0].startswith("📞"): zone = True; continue
        if zone:
            if not any(r): zone = False; continue
            if r[0] != "Nom" and r[3]: contacts.append((r[0], r[3]))
    pre = lambda n: n.strip().split(" ")[0].lower()
    eq = []
    for n in noms:
        c = next((c for c in contacts if pre(c[0]) == pre(n)), None)
        eq.append({"nom": c[0] if c else n, "tel": c[1] if c else ""})
    if eq and eq != d.get("equipe"):
        d["equipe"] = eq; ecrire(fichier, cle, d); print(json.dumps({"mis_a_jour": True, "equipe": [[e["nom"], bool(e["tel"])] for e in eq]}, ensure_ascii=False))
    else:
        print(json.dumps({"mis_a_jour": False, "equipe": [[e["nom"], bool(e["tel"])] for e in eq]}, ensure_ascii=False))

def trajets(fichier, cle, values_json):
    """Depuis la fiche FDR (partie « 🚆 TRAJETS & BILLETS » et « 🛏️ HÉBERGEMENT ») :
    - heure d'arrivée du train le jour du concert -> heure du run aller (et rappel du train retour) ;
    - hébergement de la nuit du concert -> nom et adresse affichés à l'organisateur (jamais les codes d'accès).
    Si un horaire déjà affiché change, une alerte orange apparaît sur la page (« alertes »)."""
    import re
    from datetime import datetime, timezone
    d = lire(fichier, cle); rows = json.load(open(values_json)); rows = rows.get("values", rows) if isinstance(rows, dict) else rows
    rows = [[str(x).strip() for x in (list(r) + [""] * 5)[:5]] for r in rows]
    MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
    ABR = ["jan", "fév", "mar", "avr", "mai", "juin", "juil", "août", "sep", "oct", "nov", "déc"]
    m = re.search(r"(\d{1,2})(?:er)?\s+(" + "|".join(MOIS) + ")", d.get("date", "").lower())
    if not m:
        print(json.dumps({"erreur": "date de l'événement illisible"}, ensure_ascii=False)); return
    jour, mois = int(m.group(1)), MOIS.index(m.group(2)) + 1
    du_jour = re.compile(rf"\b{jour}\s+{ABR[mois - 1]}", re.I)
    nuit_re = re.compile(rf"\b0?{jour}/0?{mois}\b")
    H = re.compile(r"\d{1,2}h\d{0,2}")
    hm = lambda h: (lambda a: int(a[0]) * 60 + int(a[1] or 0))(h.split("h"))
    aller, retour, gare, zone = {}, {}, "", ""
    heb, cur = [], None
    for r in rows:
        if re.match(r"^[^\w\s]+\s+[A-ZÉÈÊÀÂÔÛÇ/&·' ]{4,}", r[0]):  # titre de partie : « 🛏️ HÉBERGEMENT », « 🚆 TRAJETS & BILLETS »…
            zone = r[0][:1]; cur = None; continue
        if not any(r):
            continue
        if zone == "🚆" and r[0] != "Qui":
            hs = H.findall(r[2])
            if len(hs) >= 2 and du_jour.search(r[1]):
                if r[1].lower().startswith("aller"):
                    aller[r[0]] = hs[1]; gare = (r[3].split("·")[0].split("→")[-1]).strip() or gare
                elif r[1].lower().startswith("retour") and r[0] not in retour:
                    retour[r[0]] = hs[0]
        if zone == "🛏":
            if r[0] == "Nom":
                cur = {"nom": r[2]}; heb.append(cur)
            elif cur is not None and r[0].startswith("Adresse"):
                cur["adr"] = r[2]
            elif cur is not None and r[0].startswith("🛏"):
                cur["nuit"] = r[2]
    arr = " / ".join(sorted(set(aller.values()), key=hm))
    dep = " / ".join(sorted(set(retour.values()), key=hm))
    out = {"arrivee": arr, "depart": dep, "hebergement": False, "alertes": []}
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    change = False
    def alerte(bloc, texte):
        d.setdefault("alertes", []).append({"bloc": bloc, "texte": texte, "date": now}); d["alertes"] = d["alertes"][-10:]; out["alertes"].append(texte)
    for t in d.get("topics", []):
        for it in t.get("items", []):
            if it.get("id") == "runs":  # « Qui » : rempli une fois depuis les billets, ensuite l'équipe garde la main
                for r, gens in (("run-aller", aller), ("run-retour", retour)):
                    row = next((x for x in it["rows"] if x["id"] == r), None)
                    if row is not None and gens and not row.setdefault("cells", {}).get("qui"):
                        row["cells"]["qui"] = ", ".join(sorted(gens, key=lambda q: hm((aller if r == "run-aller" else retour)[q]))); change = True
            if it.get("id") == "runs" and arr:
                for r in it["rows"]:
                    if r["id"] == "run-aller":
                        old = r.setdefault("cells", {}).get("heure", "")
                        if old != arr:
                            r["cells"]["heure"] = arr; change = True
                            if old: alerte("runs", f"Le train arrive maintenant à {arr} (avant {old}). Merci de vérifier le run aller.")
            if it.get("id") == "park-runs" and (arr or dep):
                v = it.get("valeur", ""); nv = re.sub(r"(Arrivée en gare de [^à]+à )\S+?(\.)", lambda x: x.group(1) + (arr or x.group(0)[len(x.group(1)):-1]) + ".", v)
                nv = re.sub(r"(Départ de la gare à )\S+?(\.)", lambda x: x.group(1) + (dep or "") + ".", nv) if dep else nv
                if nv != v: it["valeur"] = nv; change = True
            if it.get("type") == "tableau":
                for r in it["rows"]:
                    if r["id"].endswith("train-arr") and arr and r.get("a") != arr: r["a"] = arr; change = True
                    if r["id"].endswith("train-ret") and dep and r.get("a") != dep:
                        if r.get("a"): alerte("runs", f"Le train retour part maintenant à {dep} (avant {r['a']}). Merci de vérifier le run retour.")
                        r["a"] = dep; change = True
            if it.get("type") == "hebergement":
                b = next((x for x in heb if nuit_re.search(x.get("nuit", "")) and "réservé par l'orga" not in x.get("nom", "").lower()), None)
                if b:
                    out["hebergement"] = True
                    a = {"nom": b.get("nom", ""), "adr": b.get("adr", ""), "dates": "Nuit du " + b.get("nuit", "").split(".")[0]}
                    old = it.get("auto") or {}
                    if any(old.get(k) != a[k] for k in a):
                        if old.get("nom") and (old.get("nom") != a["nom"] or old.get("adr") != a["adr"]):
                            alerte("runs", f"L'hébergement a changé : {a['nom']}. Merci de vérifier les runs.")
                        it["auto"] = dict(old, **a); change = True
    if change:
        d["maj"] = datetime.now(timezone.utc).astimezone().strftime("%d/%m/%Y")
        ecrire(fichier, cle, d)
    out["mis_a_jour"] = change
    print(json.dumps(out, ensure_ascii=False))

def points(fichier, cle):
    """Tous les points à remplir d'un événement (id, sujet, libellé, type, choix possibles, réponse actuelle).
    Sert à placer une info reçue par mail sur le bon point."""
    d = lire(fichier, cle); rep = d.get("reponses", {}); out = []
    jum = d.get("jumeaux") or {}; communs = set(jum.get("sujets", [])); propres = set(jum.get("propres", []))
    def add(t, pid, label, typ="", opts=None, item=None):
        r = rep.get(pid) or {}
        out.append({"id": pid, "sujet": t.get("label", t.get("id")), "libelle": label, "type": typ, "choix": opts or [],
                    "reponse": r.get("texte", ""), "commun_aux_2_concerts": t.get("id") in communs and (item or "") not in propres})
    for t in d.get("topics", []):
        for i, b in enumerate(t.get("besoins", [])):
            add(t, f'{t["id"]}-b{i}', b["t"] if isinstance(b, dict) else b, "besoin (« ✓ Prévu » / « Non concerné »)")
        for it in t.get("items", []):
            iid = it.get("id") or it.get("contact")
            if it.get("contact"):
                c = d.get("contacts", {}).get(it["contact"], {}); add(t, it["contact"], "Contact : " + c.get("role", ""), "contact (Nom, téléphone, mail)", item=iid); continue
            typ = it.get("type", "")
            if typ in ("fiche", "tableau"):
                for r in it.get("rows", []):
                    add(t, r["id"], (it.get("titre", "") + " · " + str(r.get("label") or r.get("b") or "")).strip(" ·"), r.get("type", "texte"), r.get("options"), iid)
            elif typ == "grille":
                for r in it.get("rows", []):
                    for c in it.get("cols", []):
                        if isinstance(c, dict) and c.get("k"): add(t, f'{r["id"]}-{c["k"]}', f'{it.get("titre","")} · {r.get("nom","")} · {c.get("l","")}', "case de tableau", item=iid)
            elif typ in ("ouinon", "choix", "texte", "court", "lien", "confirmer", "multi"):
                add(t, it["id"], it.get("titre", ""), typ, [o.get("texte") for o in it.get("options", [])] if typ == "choix" else (["Oui.", "Non."] if typ == "ouinon" else None), iid)
            elif typ == "passes":
                for c in it.get("choses", []): add(t, "pass-" + c["k"], c.get("t", ""), "pass", ["non", "place", "imprimer"], iid)
            elif typ == "hebergement":
                for k, l in (("heb-nom", "Nom de l'hôtel"), ("heb-adr", "Adresse"), ("heb-dates", "Dates"), ("heb-twin", "Chambres twin"), ("heb-single", "Chambres single"), ("heb-pdj", "Petit-déjeuner"), ("heb-conf", "N° de confirmation")):
                    add(t, k, "Hébergement · " + l, "texte", item=iid)
    print(json.dumps(out, ensure_ascii=False, indent=1))

def mail(fichier, cle, infos_json):
    """Infos reçues par mail → réponses de l'espace organisateur, comme si l'organisateur les avait données.
    infos_json : [{"point", "texte", "auteur" (ex. « Leila (par mail le 24/10) »), "date" (ISO du mail), "mail" (id du message)}].
    Jamais d'écrasement : un point qui a déjà une réponse différente est renvoyé dans « conflits » (à signaler, pas à trancher).
    Un mail déjà traité (id dans « mails ») est ignoré."""
    from datetime import datetime, timezone
    d = lire(fichier, cle); rep = d.setdefault("reponses", {}); vus = set(d.get("mails", []))
    ok, conflits, deja = [], [], []
    for x in json.load(open(infos_json, encoding="utf-8")):
        pt, tx = str(x.get("point", "")).strip(), str(x.get("texte", "")).strip()[:500]
        if not pt or not tx: continue
        if x.get("mail") and (x["mail"] + "|" + pt) in vus: deja.append(pt); continue
        cur = rep.get(pt)
        if cur and not str(cur.get("texte", "")).startswith("✗") and not cur.get("miroir"):
            if cur.get("texte", "").strip().lower() != tx.lower(): conflits.append({"point": pt, "dans_l_appli": cur.get("texte", ""), "dans_le_mail": tx})
            else: deja.append(pt)
            continue
        r = {"texte": tx, "date": x.get("date") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "source": "orga", "auteur": str(x.get("auteur", "par mail"))[:80], "mail": True}
        rep[pt] = r
        d.setdefault("journal", []).append({k: r[k] for k in ("date", "texte", "source", "auteur")} | {"point": pt})
        ok.append({"point": pt, "texte": tx, "auteur": r["auteur"]})
        if x.get("mail"): vus.add(x["mail"] + "|" + pt)
    d["mails"] = sorted(vus)[-400:]
    if ok:
        d["journal"] = sorted(d["journal"], key=lambda e: e["date"])[-60:]
        d["maj"] = datetime.now(timezone.utc).astimezone().strftime("%d/%m/%Y")
    if ok or vus: ecrire(fichier, cle, d)
    print(json.dumps({"evenement": d.get("artiste", "") + " - " + d.get("lieu", ""), "ajoutes": ok, "conflits": conflits, "deja": deja}, ensure_ascii=False, indent=1))

JOURS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
JC = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]
# Échéances par sujet, en jours avant le concert (négatif = après).
ECHEANCES = {"public": 42, "setlist": 21, "son": 14, "lumiere": 14, "emplacement": 14, "ecran": 14, "talkback": 14, "contacts": 14,
             "horaires": 14, "accueil": 10, "pass": 10, "presse": 10, "securite": 10, "photos": -15}

def creer(infos_json, code):
    """Nouvel espace organisateur à partir de tools/modele.json et d'un fichier d'infos (voir tools/CREATION.md).
    Écrit le fichier chiffré et affiche {fichier, cle, lien, lien_equipe}."""
    import copy, hashlib
    from datetime import date, timedelta
    I = json.load(open(infos_json, encoding="utf-8"))
    M = json.load(open(os.path.join(ROOT, "tools", "modele.json"), encoding="utf-8"))
    j = date.fromisoformat(I["iso"])
    ch = I.get("chansigneurs", [])
    noms = [c["nom"].split()[0] for c in ch]
    chs = " et ".join([", ".join(noms[:-1]), noms[-1]] if len(noms) > 1 else noms)
    txt = json.dumps(M, ensure_ascii=False).replace("{ARTISTE}", I["artiste"]).replace("{CHANSIGNEURS}", chs or "l'équipe")
    txt = txt.replace("de Les ", "des ").replace("de Le ", "du ")
    d = json.loads(txt)
    ref = I.get("referente") or (ch[0] if ch else {"nom": "", "tel": ""})
    d.update({"id": I.get("id") or f'{I["iso"]}-{I["artiste"]}'.lower().replace(" ", "-"), "artiste": I["artiste"], "lieu": I["lieu"], "ville": I.get("ville", ""),
              "date": f"{JOURS[j.weekday()]} {j.day} {MOIS[j.month - 1]} {j.year}", "iso": I["iso"], "heure": I.get("heure") or "horaire à venir",
              "premiere": I.get("premiere", ""), "premiereChansignee": bool(I.get("premiereChansignee")),
              "referente": {"nom": ref["nom"], "role": "chansigneuse, votre contact", "tel": ref.get("tel", ""), "mail": "10doigtsencavale@gmail.com"},
              "chansigneurs": chs, "equipe": [{"nom": c["nom"], "tel": c.get("tel", "")} for c in ch], "arrivees": I.get("arrivees", []),
              "depotFichiers": "", "envoi": "", "reponses": {}, "questions": {}, "journal": [], "vus": [],
              "adminHash": hashlib.sha256(code.encode()).hexdigest()})
    for cid, v in (I.get("contacts") or {}).items():
        if cid in d["contacts"] and v: d["contacts"][cid].update({"statut": "ok", "valeur": v})
    for t in d["topics"]:
        n = ECHEANCES.get(t["id"], 14); e = j - timedelta(days=n); t["iso"] = e.isoformat()
        t["avant"] = "15 jours après le concert" if n < 0 else f"{JC[e.weekday()]} {e.day}/{e.month}"
        for it in t.get("items", []):
            i = it.get("id")
            if i == "sl" and I.get("setlist"): it["chansons"] = [x if isinstance(x, dict) else {"t": x} for x in I["setlist"]]
            if i == "setlist-dress" and I.get("dress"): it.update({"type": "info", "statut": "ok", "valeur": I["dress"]})
            if i == "park-runs": it["valeur"] = I.get("transport", "")
            if i == "park": it["siDef"] = bool(I.get("voiture"))
            if i == "heb":
                if I.get("heb") is None: it["qui"] = "10dec"
                else: it["auto"] = I["heb"]
            if i == "runs" and I.get("runs"): it["rows"] = I["runs"]
            if i == "acc-repas": it["rows"] = I.get("repas") or [{"nom": x, "date": "", "midi": True, "soir": True, "regime": ""} for x in noms]
            if i == "hor-tab":
                for r in it["rows"]:
                    if (I.get("horaires") or {}).get(r["id"]): r["a"] = I["horaires"][r["id"]]
                for r in I.get("horaires_plus", []): it["rows"].append(r)
            if i == "pub-asso":
                it["liste"] = I.get("assos", [])
                it["msg"] = {"adresse": I.get("adresse", ""), "prog": I.get("prog") or [{"ic": "🎤", "h": I.get("heure", ""), "t": "Concert de " + I["artiste"]}]}
    fichier, cle = b64(os.urandom(12)), b64(os.urandom(32))
    ecrire(fichier, cle, d)
    base = "https://10doigtsencavale-jpg.github.io/ORGA/#" + fichier + "." + cle
    print(json.dumps({"fichier": fichier, "cle": cle, "lien": base, "lien_equipe": base + "!" + code, "date": j.strftime("%d/%m/%Y")}, ensure_ascii=False))

def dechiffrer(fichier, cle):
    box = json.load(open(os.path.join(ROOT, "e", fichier + ".json")))
    print(AESGCM(unb64(cle)).decrypt(unb64(box["iv"]), unb64(box["ct"]), None).decode())

if __name__ == "__main__":
    a = sys.argv[1:]
    {"nouveau": lambda: nouveau(), "chiffrer": lambda: chiffrer(*a[1:4]), "dechiffrer": lambda: dechiffrer(*a[1:3]),
     "appliquer": lambda: appliquer(*a[1:5]), "manquants": lambda: manquants(*a[1:3]),
     "depots": lambda: depots(*a[1:3]), "recu": lambda: recu(*a[1:5]),
     "accueil": lambda: accueil(*a[1:5]),
     "profils": lambda: profils(*a[1:4]), "equipe": lambda: equipe(*a[1:4]), "trajets": lambda: trajets(*a[1:4]), "points": lambda: points(*a[1:3]), "mail": lambda: mail(*a[1:4]), "creer": lambda: creer(*a[1:3])}[a[0]]()
