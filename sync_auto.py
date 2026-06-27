#!/usr/bin/env python3
"""
Headless-Sync: SpielerPlus-Trainings -> Anytype (fuer Cron, ohne GUI).

Laeuft taeglich (z. B. 06:00 Uhr per Cron) und synchronisiert nur die
Trainings, die HEUTE oder MORGEN stattfinden:

  - Training in Anytype noch nicht vorhanden -> neu anlegen
  - Training bereits vorhanden             -> nur Anwesenheitstabelle
                                              einfuegen/aktualisieren

Alle Schritte werden nach ~/logs/anytype_sync.log protokolliert.

Manueller Aufruf zum Testen:
    python3 sync_auto.py
"""
import datetime
import logging
import sys
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path

from anytype import Anytype, AnytypeError
from spielerplus import SpielerPlus, SpielerPlusError
from sync import collect_event, is_laufen, write_event
from test_login import load_env

LOG_DIR = Path.home() / "logs"
LOG_FILE = LOG_DIR / "anytype_sync.log"


def setup_logging() -> logging.Logger:
    """Logger, der nach ~/logs/anytype_sync.log und auf stdout schreibt."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("anytype_sync")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()  # bei wiederholtem Aufruf nicht doppelt loggen

    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")

    # Datei mit Rotation, damit das Log nicht endlos waechst.
    fh = RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=5,
                             encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    return logger


def target_dates() -> set[str]:
    """ISO-Daten (YYYY-MM-DD) fuer heute und morgen, lokale Zeit."""
    today = datetime.date.today()
    tomorrow = today + datetime.timedelta(days=1)
    return {today.isoformat(), tomorrow.isoformat()}


def run(log: logging.Logger) -> int:
    """Fuehrt den Sync aus. Gibt die Anzahl verarbeiteter Trainings zurueck."""
    env = load_env()
    if not env:
        raise RuntimeError(".env nicht gefunden oder leer (Projektordner).")

    wanted = target_dates()
    log.info("Sync-Lauf gestartet. Zieltage (heute/morgen): %s",
             ", ".join(sorted(wanted)))

    # --- SpielerPlus ---
    sp = SpielerPlus(env["SP_EMAIL"], env["SP_PASSWORD"])
    sp.login()
    team_id = env.get("SP_TEAM_ID")
    if not team_id:
        raise RuntimeError("SP_TEAM_ID fehlt in .env.")
    sp.switch_team(int(team_id))
    events = [e for e in sp.list_events() if e["type"] == "training"]
    log.info("SpielerPlus: %d kommende(s) Training(s) gefunden.", len(events))

    # --- Anytype ---
    at = Anytype(env["Api_key"], env["ANYTYPE_SPACE_ID"],
                 api_base=env.get("ANYTYPE_API_BASE"))
    details = at.spieler_details()
    tindex = at.training_index()
    by_event = {t["event_id"]: t["id"] for t in tindex if t["event_id"]}
    by_day = {}
    for t in tindex:
        if t["day"]:
            by_day.setdefault(t["day"], t["id"])  # erstes Training je Tag
    log.info("Anytype: %d Spieler, %d bestehende Trainings.",
             len(details), len(tindex))

    # Tage, an denen es ein regulaeres (Nicht-"Laufen") Training gibt.
    days_with_other = {e["day"] for e in events
                       if e.get("day") and not is_laufen(e)}

    verarbeitet = 0
    for e in events:
        eid = str(e["id"])

        # "Laufen"-Training ignorieren, wenn am selben Tag ein anderes Training ist.
        if is_laufen(e) and e.get("day") in days_with_other:
            log.info("Uebersprungen ('Laufen', anderes Training am selben Tag): "
                     "%s am %s (Event %s)", e.get("title"), e.get("day"), eid)
            continue

        info = collect_event(sp, e, details)
        event_day = info["event_day"]

        # Nur Trainings heute oder morgen.
        if event_day not in wanted:
            log.info("Uebersprungen (nicht heute/morgen): %s am %s (Event %s)",
                     info["name"], event_day or "?", eid)
            continue

        target_id = by_event.get(eid) or by_day.get(event_day)
        log.info("%s (Event %s) | Anwesend: %d | Abgesagt: %d%s",
                 info["name"], eid, info["anwesend"], info["abgesagt"],
                 f" | nicht zuordenbar: {info['unmapped']}"
                 if info["unmapped"] else "")
        try:
            status = write_event(at, target_id, info)
            log.info("   -> %s.", status)
            verarbeitet += 1
        except AnytypeError as ex:
            log.error("   FEHLER beim Schreiben nach Anytype: %s", ex)

    log.info("Sync-Lauf beendet. %d Training(s) verarbeitet.", verarbeitet)
    return verarbeitet


def main() -> int:
    log = setup_logging()
    try:
        run(log)
        return 0
    except (SpielerPlusError, AnytypeError, RuntimeError, KeyError) as e:
        log.error("Sync fehlgeschlagen: %s", e)
        return 1
    except Exception:  # alles andere mit vollem Traceback ins Log
        log.error("Unerwarteter Fehler:\n%s", traceback.format_exc())
        return 1


if __name__ == "__main__":
    sys.exit(main())
