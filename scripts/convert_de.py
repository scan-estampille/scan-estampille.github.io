#!/usr/bin/env python3
"""Convertit l'export CSV de la liste officielle allemande (BLtU, BVL) au format de l'appli
(même format que la liste DGAL) : dept, numAgrement, siret, raisonSociale, adresse, codePostal,
commune, categorie, activites, especes.

Le fichier d'entrée est l'export « CSV » de la Generalliste du site du BVL (séparateur : tabulation).
Il est téléchargé par scripts/fetch_de.py.

Usage :
  python scripts/convert_de.py --input generalliste.csv

Données : Bundesamt für Verbraucherschutz und Lebensmittelsicherheit (BVL),
licence « Datenlizenz Deutschland – Namensnennung – Version 2.0 ».
"""
import argparse, csv, datetime, io, json, re, sys

MIN_RECORDS = 10000        # la Generalliste compte ~15 800 établissements : en dessous, fichier suspect
MAX_DROP = 0.20            # refuse une baisse de plus de 20 % par rapport au fichier actuel

LAENDER = {"BB", "BE", "BW", "BY", "HB", "HE", "HH", "MV", "NI", "NW", "RP", "SH", "SL", "SN", "ST", "TH"}

# Colonnes d'activité de la Generalliste, dans l'ordre (à partir de la colonne « CS ») : code de la
# colonne → section de l'annexe III du règlement 853/2004 ; None quand la section n'est pas certaine
# (l'activité est alors affichée sans sa filière). Si le BVL modifie ses colonnes, le script s'arrête.
ACTIVITY_COLUMNS = [
    ("CS", "0"), ("RW", "0"), ("WM", "0"),
    ("SH", "I"), ("CP", "I"),
    ("SH", "II"), ("CP", "II"),
    ("SH", "III"), ("CP", "III"),
    ("GHE", "IV"), ("CP", "IV"),
    ("MM", "V"), ("MP", "V"), ("MSM", "V"),
    ("PP", "VI"),
    ("CC", None), ("PP", None),
    ("CC", None), ("PP", None),
    ("CC", None), ("PP", None),
    ("CC", None), ("PP", None),
    ("CC", "IX"), ("PP", "IX"),
    ("EPC", "X"), ("LEP", "X"), ("PP", "X"),
    ("AH", "VIII"), ("FV", "VIII"), ("ZV", "VIII"), ("FFPP", "VIII"), ("PP", "VIII"), ("WM", "VIII"),
    ("PC", "VII"), ("DC", "VII"),
    ("PP", None),
]
# Codes espèces reconnus par l'appli (cellules du type « B, O, P » ou « wU, wG »)
SPECIES = {"B", "C", "O", "P", "S", "A", "L", "R", "fG", "wU", "wA", "wL", "wG", "F", "SN"}


def clean(t):
    return re.sub(r"\s+", " ", (t or "").replace("\u00a0", " ")).strip()


def decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def find_header(rows):
    for i, row in enumerate(rows):
        if row and clean(row[0]).lstrip("#").strip().lower().startswith("bundesland"):
            return i, [clean(c) for c in row]
    sys.exit("En-tête « Bundesland » introuvable : le format de l'export a changé.")


def parse(text):
    rows = list(csv.reader(io.StringIO(text), delimiter="\t", quoting=csv.QUOTE_NONE))
    h, header = find_header(rows)
    try:
        first = header.index("CS")
    except ValueError:
        sys.exit("Colonne « CS » introuvable : le format de l'export a changé.")
    codes = header[first:first + len(ACTIVITY_COLUMNS)]
    expected = [c for c, _ in ACTIVITY_COLUMNS]
    if codes != expected:
        sys.exit(f"Colonnes d'activité inattendues :\n  lues    {codes}\n  prévues {expected}")
    col = {name: i for i, name in enumerate(header) if name}
    i_land = 0
    i_name = next(i for i, n in enumerate(header) if n.lower().startswith("name"))
    i_street = next(i for i, n in enumerate(header) if n.lower().startswith("straße") or n.lower().startswith("strasse"))
    i_town = next(i for i, n in enumerate(header) if n.lower() == "ort")
    i_num = next(i for i, n in enumerate(header) if n.lower().startswith("neue zulassungsnummer"))
    i_notes = col.get("Bemerkungen")

    records, seen = [], set()
    for row in rows[h + 1:]:
        if len(row) <= i_num:
            continue
        get = lambda i: clean(row[i]) if i is not None and i < len(row) else ""
        num = get(i_num).upper()
        m = re.match(r"^([A-Z]{2})[\s\-]*(\d{5})$", num)
        if not m or m.group(1) not in LAENDER:
            continue                      # ligne vide ou numéro hors format (anciens numéros seuls)
        num = f"{m.group(1)} {m.group(2)}"

        town = get(i_town)
        mt = re.match(r"^(\d{5})\s+(.*)$", town)
        cp, commune = (mt.group(1), mt.group(2)) if mt else ("", town)

        acts, species = [], []
        for k, (code, section) in enumerate(ACTIVITY_COLUMNS):
            cell = get(first + k)
            if not cell:
                continue
            act = f"{section}({code})" if section else code
            if act not in acts:
                acts.append(act)
            for tok in (t.strip() for t in cell.split(",")):
                if tok in SPECIES and tok not in species:
                    species.append(tok)
        if "catering" in get(i_notes).lower() and "RC(CUISCEN)" not in acts:
            acts.append("RC(CUISCEN)")

        name, street = get(i_name), get(i_street)
        key = (num, name.upper(), street.upper())
        if key in seen:
            continue
        seen.add(key)
        records.append({"land": get(i_land), "num": num, "name": name, "street": street,
                        "cp": cp, "commune": commune, "acts": acts, "sp": species})
    return records


def count_lines(path):
    try:
        with open(path, encoding="utf-8") as f:
            return sum(1 for _ in f)
    except FileNotFoundError:
        return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--out", default="ETAB_AGR_DE.txt")
    ap.add_argument("--meta", default="ETAB_AGR_DE.meta.json")
    ap.add_argument("--min", type=int, default=MIN_RECORDS)
    args = ap.parse_args()

    with open(args.input, "rb") as f:
        records = parse(decode(f.read()))
    print(f"{len(records)} établissements")

    old = count_lines(args.out)
    if len(records) < args.min:
        sys.exit(f"Trop peu d'établissements ({len(records)}) : fichier non écrit.")
    if old and len(records) < old * (1 - MAX_DROP):
        sys.exit(f"Baisse suspecte ({old} -> {len(records)}) : fichier non écrit.")

    records.sort(key=lambda r: (r["num"], r["name"]))
    q = lambda s: (s or "").replace('"', "'")
    with open(args.out, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, quoting=csv.QUOTE_ALL, lineterminator="\n")
        for r in records:
            w.writerow([q(r["land"]), q(r["num"]), "", q(r["name"]), q(r["street"]),
                        q(r["cp"]), q(r["commune"]), "", "; ".join(r["acts"]), "-".join(r["sp"])])

    # Le BVL ne date pas son export : on note le jour du téléchargement
    today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    with open(args.meta, "w", encoding="utf-8") as f:
        json.dump({"listDate": today, "count": len(records)}, f)


if __name__ == "__main__":
    main()
