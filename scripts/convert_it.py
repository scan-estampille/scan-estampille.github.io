#!/usr/bin/env python3
"""Télécharge la liste officielle italienne (Reg. CE 853/2004) et la convertit
au format CSV de la DGAL : dept, numAgrement, siret(=P.IVA), raisonSociale,
adresse, codePostal, commune, categorie, activites, especes.

Usage :
  python scripts/convert_it.py                      # télécharge
  python scripts/convert_it.py --input page.html    # test local, sans réseau
"""
import argparse, csv, json, os, re, sys, time
import requests
ROMAN = {str(i): r for i, r in enumerate(
    ["", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X",
     "XI", "XII", "XIII", "XIV", "XV", "XVI"]) if i}
from bs4 import BeautifulSoup

URL = ("https://www.salute.gov.it/consultazioneStabilimenti/"
       "ConsultazioneStabilimentiServlet?ACTION=gestioneSingolaCategoria&idNormativa=2")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
}
MIN_RECORDS = 500          # en dessous : fichier suspect
MAX_DROP = 0.20            # refuse une baisse de plus de 20 % par rapport au fichier actuel


def download(retries=3):
    s = requests.Session()
    s.headers.update(HEADERS)
    last = None
    for i in range(retries):
        try:
            r = s.get(URL, timeout=(30, 240))   # le serveur met ~30 s à répondre
            r.raise_for_status()
            html = r.content.decode("cp1252", errors="replace")  # page en ISO-8859-1
            if len(html) > 200_000:
                return html
            last = f"réponse trop courte ({len(html)} octets) : anti-robot ou formulaire ?"
        except requests.RequestException as e:
            last = str(e)
        print(f"Essai {i + 1} échoué : {last}", file=sys.stderr)
        time.sleep(5)
    sys.exit(f"Téléchargement impossible : {last}")


def clean(t):
    return re.sub(r"\s+", " ", t or "").strip()


def parse(html):
    soup = BeautifulSoup(html, "html.parser")
    m = re.search(r"Date\)\s*(\d{4}-\d{2}-\d{2}[ \d:]*)", soup.get_text(" "))
    list_date = clean(m.group(1)) if m else None

    merged = {}
    for tr in soup.find_all("tr"):
        # la ligne d'en-tête n'est pas fermée dans le HTML : on ne prend que les td directs
        tds = tr.find_all("td", recursive=False)
        if len(tds) != 10:
            continue
        num, name, vat, _tax, town, cat, act, species, _remarks, _tse = [clean(td.get_text()) for td in tds]
              cat = ROMAN.get(cat, cat)   # 2 -> II ; une valeur inconnue est conservée telle quelle
        num = re.sub(r"^UE\s+", "", num, flags=re.I)        # « UE IT 505 L » -> « IT 505 L »
        if not re.search(r"\d", num):
            continue

        m = re.match(r"^(.*),\s*([^,]+?)\s*\(([A-Z]{2})\)\s*$", town)
        adresse, commune, prov = (m.group(1), m.group(2), m.group(3)) if m else (town, "", "")
              adresse = clean(adresse)    # retire les espaces finaux (« VIA COLLE DI NAVA 24/L »)

        sp = [p.strip() for p in species.split("|")]
        sp = [p for p in sp if p and p != "-"]
        activity = f"{cat}({act})" if cat and act else (act or "")

        key = (num.upper(), name.upper(), adresse.upper())
        rec = merged.setdefault(key, {
            "prov": prov, "num": num, "vat": vat, "name": name,
            "adresse": adresse, "commune": commune, "acts": [], "sp": [],
        })
        if activity and activity not in rec["acts"]:
            rec["acts"].append(activity)
        for p in sp:
            if p not in rec["sp"]:
                rec["sp"].append(p)
    return list_date, list(merged.values())


def count_lines(path):
    try:
        with open(path, encoding="utf-8") as f:
            return sum(1 for _ in f)
    except FileNotFoundError:
        return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input")
    ap.add_argument("--out", default="ETAB_AGR_IT.txt")
    args = ap.parse_args()

    if args.input:
        with open(args.input, "rb") as f:
            html = f.read().decode("cp1252", errors="replace")
    else:
        html = download()

    list_date, records = parse(html)
    print(f"{len(records)} établissements (liste du {list_date})")

    old = count_lines(args.out)
    if len(records) < MIN_RECORDS:
        sys.exit(f"Trop peu d'établissements ({len(records)}) : fichier non écrit.")
    if old and len(records) < old * (1 - MAX_DROP):
        sys.exit(f"Baisse suspecte ({old} -> {len(records)}) : fichier non écrit.")

    records.sort(key=lambda r: (r["num"], r["name"]))
    q = lambda s: (s or "").replace('"', "'")
    with open(args.out, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, quoting=csv.QUOTE_ALL, lineterminator="\n")
        for r in records:
            w.writerow([q(r["prov"]), q(r["num"]), q(r["vat"]), q(r["name"]), q(r["adresse"]),
                        "", q(r["commune"]), "", "; ".join(r["acts"]), "-".join(r["sp"])])

    with open("ETAB_AGR_IT.meta.json", "w", encoding="utf-8") as f:
        json.dump({"listDate": list_date, "count": len(records)}, f)


if __name__ == "__main__":
    main()
