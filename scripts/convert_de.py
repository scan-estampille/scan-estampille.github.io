#!/usr/bin/env python3
"""Convertit l'export CSV de la liste officielle allemande (BLtU, BVL) au format de l'appli
(même format que la liste DGAL) : dept, numAgrement, siret, raisonSociale, adresse, codePostal,
commune, categorie, activites, especes.

Le fichier d'entrée est l'export « CSV » de la Generalliste du site du BVL (point-virgule, Windows-1252).
Une 11e colonne, propre à l'Allemagne, donne les anciens numéros d'agrément (« EV 123, BY 111 ») :
ils figurent encore sur des emballages, et ~1 200 établissements n'ont que ceux-là.
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
    # Sections déduites des établissements de l'export du 16/11/2026 : charcuteries (graisses fondues),
    # boyauderies (estomacs, vessies, boyaux), fabricants de gélatine et de collagène, laiteries
    ("CC", "XII"), ("PP", "XII"),
    ("CC", "XIII"), ("PP", "XIII"),
    ("CC", "XIV"), ("PP", "XIV"),
    ("CC", "XV"), ("PP", "XV"),
    ("CC", "IX"), ("PP", "IX"),
    ("EPC", "X"), ("LEP", "X"), ("PP", "X"),
    ("AH", "VIII"), ("FV", "VIII"), ("ZV", "VIII"), ("FFPP", "VIII"), ("PP", "VIII"), ("WM", "VIII"),
    ("PC", "VII"), ("DC", "VII"),
    ("PP", None),          # vide dans l'export : section inconnue
]
# Codes espèces reconnus par l'appli (cellules du type « B, O, P » ou « wU, wG »)
SPECIES = {"B", "C", "O", "P", "S", "A", "L", "R", "fG", "wU", "wA", "wL", "wG", "F", "SN"}


def clean(t):
    return re.sub(r"\s+", " ", (t or "").replace("\u00a0", " ")).strip()


def decode(raw: bytes) -> str:
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def header_name(cell):
    return clean(cell).strip('"').lstrip("#").strip()


def sniff_delimiter(text):
    """Séparateur de l'export (tabulation, point-virgule ou virgule), deviné sur la ligne d'en-tête."""
    for line in text.splitlines():
        if "bundesland" in line.lower():
            return max(["\t", ";", ",", "|"], key=line.count)
    return "\t"


def find_header(rows):
    for i, row in enumerate(rows):
        if row and header_name(row[0]).lower().startswith("bundesland"):
            return i, [header_name(c) for c in row]
    return None, None


def fail(msg, text):
    # Le début du fichier, tel quel, aide à comprendre ce qui a changé
    preview = "\n".join(repr(l[:300]) for l in text.splitlines()[:3])
    sys.exit(f"{msg}\nDébut du fichier :\n{preview}")


def old_numbers(cell):
    """« EV 123, BY 111, BY 111 » → ['EV 123', 'BY 111'] (sans doublons, dans l'ordre)."""
    out = []
    for o in re.split(r"\s*[,;]\s*|\s+und\s+", cell or ""):
        o = clean(o).upper()
        if o and re.search(r"\d", o) and o not in out:
            out.append(o)
    return out


NEW_NUM = re.compile(r"^(%s)[\s\-]*\d{5}$" % "|".join(sorted(LAENDER)))


def realign(row, width, i_name, i_street, i_town, i_num):
    """Ligne avec un « ; » de trop (dans le nom, l'adresse ou la ville) : on recolle les morceaux
    pour que le numéro retombe dans sa colonne. Les lignes déjà alignées ne changent pas."""
    extra = len(row) - width
    if extra <= 0 or NEW_NUM.match(clean(row[i_num]).upper()):
        return row
    for e in range(1, extra + 1):
        for p in (i_town, i_name, i_street):
            merged = row[:p] + [", ".join(c.strip() for c in row[p:p + e + 1] if c.strip())] + row[p + e + 1:]
            if NEW_NUM.match(clean(merged[i_num]).upper()) and re.match(r"^\d{5}\s", clean(merged[i_town])):
                return merged
    return row


def column(header, test):
    for i, name in enumerate(header):
        if test(name.lower()):
            return i
    return None


def parse(text):
    delim = sniff_delimiter(text)
    rows = list(csv.reader(io.StringIO(text), delimiter=delim))
    h, header = find_header(rows)
    if header is None:
        fail("En-tête « Bundesland » introuvable : le format de l'export a changé.", text)
    print(f"Séparateur : {delim!r}, {len(header)} colonnes, {len(rows) - h - 1} lignes")

    # Code d'activité de chaque colonne : « CS », ou le premier mot de « CS (Kühlhaus) »…
    codes_all = [(re.match(r"^([A-Z]{2,4})\b", n) or [None, None])[1] for n in header]
    expected = [c for c, _ in ACTIVITY_COLUMNS]
    first = next((i for i in range(len(header)) if codes_all[i:i + len(expected)] == expected), None)
    if first is None:
        fail("Colonnes d'activité introuvables ou dans un autre ordre :\n  en-tête "
             f"{header}\n  prévues  {expected}", text)

    i_land = 0
    i_name = column(header, lambda n: n.startswith("name"))
    i_street = column(header, lambda n: "straße" in n or "strasse" in n)
    i_town = column(header, lambda n: n == "ort" or n.endswith(" ort") or n.startswith("plz"))
    i_num = column(header, lambda n: "zulassungsnummer" in n and "alte" not in n and "eier" not in n)
    i_notes = column(header, lambda n: n.startswith("bemerkung"))
    if None in (i_name, i_street, i_town, i_num):
        fail(f"Colonnes de base introuvables dans l'en-tête : {header}", text)

    i_old = column(header, lambda n: n.startswith("alte zulassung"))

    records, seen = [], set()
    for row in rows[h + 1:]:
        row = realign(row, len(header), i_name, i_street, i_town, i_num)
        if len(row) <= i_num:
            continue                      # suite d'une remarque coupée par un retour à la ligne
        get = lambda i: clean(row[i]) if i is not None and i < len(row) else ""
        olds = old_numbers(get(i_old))
        num = get(i_num).upper()
        m = re.match(r"^([A-Z]{2})[\s\-]*(\d{5})$", num)
        if m and m.group(1) in LAENDER:
            num = f"{m.group(1)} {m.group(2)}"
        elif olds:
            num = olds.pop(0)             # établissement qui n'a qu'un ancien numéro
        else:
            continue                      # ligne vide

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
                        "cp": cp, "commune": commune, "acts": acts, "sp": species,
                        "old": [o for o in olds if o != num]})
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
                        q(r["cp"]), q(r["commune"]), "", "; ".join(r["acts"]), "-".join(r["sp"]),
                        q(", ".join(r["old"]))])

    # Le BVL ne date pas son export : on note le jour du téléchargement
    today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    with open(args.meta, "w", encoding="utf-8") as f:
        json.dump({"listDate": today, "count": len(records)}, f)


if __name__ == "__main__":
    main()
