"""
Schritt 3b – Sync: SpielerPlus-Trainings -> Anytype.

Pro Training wird in Anytype ein 'Training'-Objekt angelegt/aktualisiert:
  - Datum            (aus SpielerPlus)
  - Anwesend         (zugesagte Spielerinnen, verknuepft)
  - Abgesagt         (abgesagte Spielerinnen, verknuepft)
  - SpielerPlus-Event-ID  (zur Wiedererkennung)

Nutzung:
  py sync.py --dry-run        # nur anzeigen, nichts schreiben
  py sync.py                  # wirklich nach Anytype schreiben
  py sync.py --limit 3        # nur die naechsten 3 Trainings
"""
import argparse
import datetime
import re
import sys

from anytype import Anytype, AnytypeError
from spielerplus import SpielerPlus, SpielerPlusError
from test_login import load_env

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def parse_datetime(s: str) -> str | None:
    """'22.06.26 - 19:45 Uhr' -> ISO mit lokaler Zeitzone, z. B.
    '2026-06-22T19:45:00+02:00'. So zeigt Anytype Datum/Uhrzeit korrekt an."""
    m = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{2,4}).*?(\d{1,2}):(\d{2})", s)
    if not m:
        return None
    d, mo, y, h, mi = (int(x) for x in m.groups())
    if y < 100:
        y += 2000
    # Naive Zeit als lokale Zeit interpretieren und Offset anhaengen.
    local = datetime.datetime(y, mo, d, h, mi).astimezone()
    return local.isoformat()


def is_laufen(event: dict) -> bool:
    """True, wenn das SpielerPlus-Training den Titel 'Laufen' traegt."""
    return "laufen" in (event.get("title") or "").lower()


# Freitext-Position (aus Anytype) -> Handball-Kategorie. Reihenfolge wichtig.
def position_category(pos: str) -> str:
    p = (pos or "").lower()
    if "tor" in p:
        return "Torhüter"
    if "außen" in p or "aussen" in p:
        return "Außen"
    if any(k in p for k in ("mitte", "halb", "rückraum", "ruckraum", "allrounder")):
        return "Rückraum"
    if "kreis" in p:
        return "Kreis"
    return "Sonstige"


# Anzeige-Reihenfolge der Positionsgruppen
POS_ORDER = ["Torhüter", "Rückraum", "Außen", "Kreis", "Sonstige"]


TABLE_HEADING = "## Zusagen nach Position"
SUMMARY_PREFIX = "Zugesagt gesamt:"


def build_position_table(zusagen: list, details: dict) -> str:
    """Kurz-Zusammenfassung + Markdown-Tabelle, nach Position gruppiert."""
    groups: dict[str, list[str]] = {k: [] for k in POS_ORDER}
    for p in zusagen:
        d = details.get(str(p["user_id"]))
        if not d:
            continue  # z. B. Trainer/Kassenwart, nicht in Anytype
        cat = position_category(d["pos_angriff"])
        groups[cat].append(p["name"])

    total = sum(len(v) for v in groups.values())
    torhueter = len(groups["Torhüter"])
    feldspieler = total - torhueter
    summary = (f"{SUMMARY_PREFIX} {total} · Torhüter: {torhueter} · "
               f"Feldspieler: {feldspieler}")

    lines = [TABLE_HEADING, summary, "",
             "| Position | Spielerinnen |", "| --- | --- |"]
    for cat in POS_ORDER:
        if groups[cat]:
            lines.append(f"| {cat} | {', '.join(groups[cat])} |")
    return "\n".join(lines)


def strip_old_table(md: str) -> str:
    """Entfernt einen zuvor eingefuegten Sync-Block (Ueberschrift +
    Zusammenfassung + Tabellenzeilen + Leerzeilen), laesst den Rest stehen."""
    lines = (md or "").split("\n")
    h = next((i for i, l in enumerate(lines)
              if l.strip().startswith("#") and "Zusagen nach Position" in l), None)
    if h is None:
        return (md or "").strip()
    j = h + 1
    while j < len(lines):
        s = lines[j].strip()
        if s == "" or s.startswith("|") or s.startswith(SUMMARY_PREFIX):
            j += 1
        else:
            break
    return "\n".join(lines[:h] + lines[j:]).strip()


def merge_body(table_md: str, existing_md: str) -> str:
    """Tabelle nach oben, vorhandener Inhalt (ohne alte Tabelle) darunter."""
    rest = strip_old_table(existing_md)
    return table_md + "\n\n" + rest if rest else table_md


def to_obj_ids(leute: list, details: dict):
    """SpielerPlus-Teilnehmer -> Anytype-Objekt-IDs (+ nicht zuordenbare Namen)."""
    ids, fehlend = [], []
    for p in leute:
        d = details.get(str(p["user_id"]))
        (ids.append(d["id"]) if d else fehlend.append(p["name"]))
    return ids, fehlend


def collect_event(sp, event: dict, details: dict, exclude=frozenset()) -> dict:
    """Teilnahme eines Trainings holen und alles fuer Anytype vorbereiten."""
    part = sp.get_participation("training", event["id"])
    zug = [p for p in part["groups"]["zugesagt"]
           if str(p["user_id"]) not in exclude]
    nachtraeglich_ab = [p for p in part["groups"]["zugesagt"]
                        if str(p["user_id"]) in exclude]
    abg = part["groups"]["abgesagt"] + nachtraeglich_ab
    anwesend_ids, fz = to_obj_ids(zug, details)
    abgesagt_ids, fa = to_obj_ids(abg, details)
    datum = (parse_datetime(part["datetime"])
             or parse_datetime(f"{event['day']}.{datetime.date.today().year} - 00:00"))
    eid = str(event["id"])
    return {
        "datum": datum,
        "event_day": (datum or "")[:10],
        "datetime_label": part.get("datetime", ""),
        "name": f"Training {part['datetime'].split(' - ')[0]}".strip(),
        "table": build_position_table(zug, details),
        "anwesend": len(anwesend_ids),
        "abgesagt": len(abgesagt_ids),
        "unmapped": fz + fa,
        "props": [
            {"key": "datum", "date": datum},
            {"key": "teilnehmer", "objects": anwesend_ids},
            {"key": "abgesagt", "objects": abgesagt_ids},
            {"key": "spielerplus_event_id", "text": eid},
        ],
    }


def write_event(at, target_id, info: dict) -> str:
    """Training anlegen oder aktualisieren. Gibt 'angelegt'/'aktualisiert' zurueck."""
    if target_id:
        existing = at.get_object(target_id).get("markdown", "")
        body = merge_body(info["table"], existing)
        at.update_object(target_id, info["props"], body=body)  # Name NICHT aendern
        return "aktualisiert"
    at.create_object("training", info["name"], info["props"], body=info["table"])
    return "angelegt"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="nichts schreiben")
    ap.add_argument("--limit", type=int, default=None, help="max. Anzahl Trainings")
    ap.add_argument("--exclude", default="",
                    help="SpielerPlus-User-IDs (komma-getrennt), die fuer diesen "
                         "Lauf als abgesagt gelten (z. B. kurzfristige Absage)")
    args = ap.parse_args()
    exclude = {x.strip() for x in args.exclude.split(",") if x.strip()}

    env = load_env()

    # --- SpielerPlus ---
    sp = SpielerPlus(env["SP_EMAIL"], env["SP_PASSWORD"])
    try:
        sp.login()
    except SpielerPlusError as e:
        print(f"FEHLER Login SpielerPlus: {e}")
        return
    team_id = env.get("SP_TEAM_ID")
    if not team_id:
        print("FEHLER: SP_TEAM_ID fehlt in .env. "
              "Mit 'py show_training.py' findest du die IDs deiner Teams.")
        return
    sp.switch_team(int(team_id))
    events = [e for e in sp.list_events() if e["type"] == "training"]
    # Tage, an denen es ein regulaeres (Nicht-"Laufen") Training gibt. Aus der
    # vollen Liste (vor --limit), damit die Regel unabhaengig vom Limit greift.
    days_with_other = {e["day"] for e in events
                       if e.get("day") and not is_laufen(e)}
    if args.limit:
        events = events[: args.limit]
    print(f"SpielerPlus: {len(events)} Training(s) gefunden.\n")

    # --- Anytype ---
    at = Anytype(env["Api_key"], env["ANYTYPE_SPACE_ID"],
                 api_base=env.get("ANYTYPE_API_BASE"))
    details = at.spieler_details()                       # uid -> {id,name,pos}
    spieler_map = {uid: d["id"] for uid, d in details.items()}
    tindex = at.training_index()
    by_event = {t["event_id"]: t["id"] for t in tindex if t["event_id"]}
    by_day = {}
    for t in tindex:
        if t["day"]:
            by_day.setdefault(t["day"], t["id"])  # erstes Training je Tag
    print(f"Anytype: {len(spieler_map)} Spieler, {len(tindex)} bestehende Trainings.\n")

    for e in events:
        eid = str(e["id"])

        # "Laufen" ignorieren, wenn am selben Tag ein anderes Training ist.
        if is_laufen(e) and e.get("day") in days_with_other:
            print(f"== {e.get('title')}  (Event {eid})")
            print("   uebersprungen ('Laufen', anderes Training am selben Tag)")
            continue

        info = collect_event(sp, e, details, exclude)
        print(f"== {info['name']}  (Event {eid})")
        print(f"   Anwesend: {info['anwesend']} | Abgesagt: {info['abgesagt']}"
              + (f" | nicht zuordenbar: {info['unmapped']}" if info["unmapped"] else ""))

        target_id = by_event.get(eid) or by_day.get(info["event_day"])
        if args.dry_run:
            print(f"   (dry-run, wuerde {'aktualisieren' if target_id else 'neu anlegen'})")
            continue
        try:
            status = write_event(at, target_id, info)
            print(f"   -> {status}.")
        except AnytypeError as ex:
            print(f"   FEHLER: {ex}")

    print("\nFertig.")


if __name__ == "__main__":
    main()
