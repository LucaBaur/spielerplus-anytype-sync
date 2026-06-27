"""
Schritt 4 - Trainingsbeteiligung berechnen und nach Anytype schreiben.

Anytype kann ein Verhaeltnis (Quote) nicht selbst live ausrechnen. Dieses Skript
liest die bereits in Anytype stehenden Trainings (Datum, Anwesend, Abgesagt),
rechnet pro Spielerin die Anwesenheits-Quote der schon stattgefundenen Trainings
und schreibt das Ergebnis zurueck:

  - Property 'Trainingsbeteiligung' (trainingsbeteiligung)  ->  z. B. "50 % (1/2)"
  - optional eine Markdown-Liste der Trainings in den Seitenkoerper der Spielerin

Gedacht zum Anhaengen an den taeglichen SpielerPlus-Sync (erst sync.py, dann
beteiligung.py). Laeuft aber auch eigenstaendig.

Nutzung:
  py beteiligung.py --dry-run     # nur anzeigen, nichts schreiben
  py beteiligung.py               # Quote + Liste schreiben
  py beteiligung.py --no-body     # nur die Quote-Property, kein Seitentext
"""
import argparse
import datetime
import sys

from anytype import Anytype, AnytypeError
from test_login import load_env

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


# ----------------------------------------------------------------- Einstellungen
# Welche Trainings zaehlen in den Nenner?
#   "all_past"       = alle stattgefundenen Trainings mit Datum (Variante B)
#   "responded_only" = nur Trainings, bei denen die Spielerin zu- oder abgesagt
#                      hat, also eingeplant war (Variante A)
COUNT_MODE = "all_past"

# Ein vergangenes Training nur zaehlen, wenn ueberhaupt Anwesenheit erfasst ist
# (mind. eine Person anwesend ODER abgesagt). Verhindert, dass reine Trainings-
# plaene mit Datum aber ohne Rueckmeldungen die Quote verfaelschen.
REQUIRE_ATTENDANCE_DATA = True

BET_HEADING = "## Trainingsbeteiligung"


# --------------------------------------------------------------------- Hilfsmittel
def parse_dt(s: str | None):
    """ISO-String -> aware datetime (naive Zeiten gelten als lokal)."""
    if not s:
        return None
    try:
        dt = datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return dt


def as_id_list(value) -> list[str]:
    """Objects-Property robust zu einer Liste von IDs machen."""
    if not value:
        return []
    if isinstance(value, list):
        return [v if isinstance(v, str) else v.get("id") for v in value]
    return []


def fmt_day(dt: datetime.datetime | None) -> str:
    return dt.astimezone().strftime("%d.%m.%Y") if dt else "ohne Datum"


# ------------------------------------------------------------------- Berechnung
def collect_trainings(at: Anytype, now: datetime.datetime) -> list[dict]:
    """Stattgefundene Trainings einsammeln (Datum in der Vergangenheit)."""
    out = []
    for o in at.search(types=["training"]):
        dt = parse_dt(at.prop_value(o, "datum"))
        if dt is None or dt > now:
            continue  # ohne Datum oder noch nicht stattgefunden -> ignorieren
        anwesend = set(as_id_list(at.prop_value(o, "teilnehmer")))
        abgesagt = set(as_id_list(at.prop_value(o, "abgesagt")))
        if REQUIRE_ATTENDANCE_DATA and not anwesend and not abgesagt:
            continue  # vergangener Plan ohne jede Rueckmeldung
        out.append({
            "id": o["id"],
            "name": o.get("name") or f"Training {fmt_day(dt)}",
            "dt": dt,
            "anwesend": anwesend,
            "abgesagt": abgesagt,
        })
    out.sort(key=lambda t: t["dt"], reverse=True)  # neuestes zuerst
    return out


def quote_for(player_id: str, trainings: list[dict]) -> tuple[int, int]:
    """(anwesend, nenner) fuer eine Spielerin nach COUNT_MODE."""
    att = total = 0
    for t in trainings:
        in_anwesend = player_id in t["anwesend"]
        in_abgesagt = player_id in t["abgesagt"]
        if COUNT_MODE == "responded_only" and not (in_anwesend or in_abgesagt):
            continue
        total += 1
        if in_anwesend:
            att += 1
    return att, total


def quote_text(att: int, total: int) -> str:
    if total == 0:
        return "–"  # noch keine relevanten Trainings
    return f"{round(att / total * 100)} % ({att}/{total})"


def build_body_block(player_id: str, trainings: list[dict],
                     att: int, total: int) -> str:
    """Markdown-Block: Quote + Liste der Trainings mit Status."""
    stand = datetime.date.today().strftime("%d.%m.%Y")
    lines = [BET_HEADING,
             f"Quote: {quote_text(att, total)} · Stand: {stand}",
             "",
             "| Training | Status |",
             "| --- | --- |"]
    for t in trainings:
        if player_id in t["anwesend"]:
            status = "✅ anwesend"
        elif player_id in t["abgesagt"]:
            status = "❌ abgesagt"
        else:
            if COUNT_MODE == "responded_only":
                continue
            status = "– keine Rückmeldung"
        lines.append(f"| {t['name']} ({fmt_day(t['dt'])}) | {status} |")
    return "\n".join(lines)


def strip_old_block(md: str) -> str:
    """Frueheren Beteiligungs-Block entfernen, restlichen Seitentext behalten."""
    lines = (md or "").split("\n")
    h = next((i for i, l in enumerate(lines)
              if l.strip().startswith("#") and "Trainingsbeteiligung" in l), None)
    if h is None:
        return (md or "").strip()
    j = h + 1
    while j < len(lines) and not lines[j].lstrip().startswith("## "):
        j += 1
    return "\n".join(lines[:h] + lines[j:]).strip()


# ------------------------------------------------------------------------- main
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="nichts schreiben")
    ap.add_argument("--no-body", action="store_true",
                    help="nur die Quote-Property, keinen Seitentext schreiben")
    args = ap.parse_args()

    env = load_env()
    at = Anytype(env["Api_key"], env["ANYTYPE_SPACE_ID"],
                 api_base=env.get("ANYTYPE_API_BASE"))
    now = datetime.datetime.now(datetime.timezone.utc)

    trainings = collect_trainings(at, now)
    print(f"Stattgefundene Trainings (zaehlend): {len(trainings)}")
    for t in trainings:
        print(f"  - {t['name']} ({fmt_day(t['dt'])}): "
              f"{len(t['anwesend'])} anwesend, {len(t['abgesagt'])} abgesagt")
    print()

    spieler = at.search(types=["spieler"])
    print(f"Spielerinnen: {len(spieler)}\n")

    for o in spieler:
        pid, name = o["id"], o.get("name", "?")
        att, total = quote_for(pid, trainings)
        text = quote_text(att, total)
        print(f"  {name:<16} {text}")
        if args.dry_run:
            continue

        props = [{"key": "trainingsbeteiligung", "text": text}]
        body = None
        if not args.no_body:
            existing = at.get_object(pid).get("markdown", "")
            block = build_body_block(pid, trainings, att, total)
            rest = strip_old_block(existing)
            body = f"{block}\n\n{rest}" if rest else block
        try:
            at.update_object(pid, props, body=body)  # Name NICHT aendern
        except AnytypeError as ex:
            print(f"     FEHLER bei {name}: {ex}")

    print("\nFertig." + ("  (dry-run, nichts geschrieben)" if args.dry_run else ""))


if __name__ == "__main__":
    main()
