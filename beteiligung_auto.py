#!/usr/bin/env python3
"""
Headless-Lauf der Trainingsbeteiligung (fuer Cron, woechentlich sonntags).

Liest die in Anytype stehenden, bereits stattgefundenen Trainings, rechnet pro
Spielerin die Anwesenheits-Quote und schreibt sie zurueck:
  - Property 'trainingsbeteiligung'  ->  z. B. "50 % (1/2)"
  - Markdown-Block (Quote + Trainingsliste) im Seitenkoerper der Spielerin

Die eigentliche Logik liegt in beteiligung.py und wird hier nur mit Logging
orchestriert. Logfile: ~/logs/anytype_beteiligung.log

Manueller Aufruf zum Testen:
    python3 beteiligung_auto.py
"""
import datetime
import logging
import sys
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path

from anytype import Anytype, AnytypeError
from beteiligung import (build_body_block, collect_trainings, quote_for,
                         quote_text, strip_old_block)
from test_login import load_env

LOG_DIR = Path.home() / "logs"
LOG_FILE = LOG_DIR / "anytype_beteiligung.log"


def setup_logging() -> logging.Logger:
    """Logger, der nach ~/logs/anytype_beteiligung.log und auf stdout schreibt."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("anytype_beteiligung")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()  # bei wiederholtem Aufruf nicht doppelt loggen

    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")
    fh = RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=5,
                             encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    return logger


def run(log: logging.Logger) -> int:
    """Berechnet und schreibt die Beteiligung. Gibt Anzahl aktualisierter
    Spielerinnen zurueck."""
    env = load_env()
    if not env:
        raise RuntimeError(".env nicht gefunden oder leer (Projektordner).")

    at = Anytype(env["Api_key"], env["ANYTYPE_SPACE_ID"],
                 api_base=env.get("ANYTYPE_API_BASE"))
    now = datetime.datetime.now(datetime.timezone.utc)

    trainings = collect_trainings(at, now)
    log.info("Beteiligungs-Lauf gestartet. Stattgefundene Trainings (zaehlend): %d",
             len(trainings))

    spieler = at.search(types=["spieler"])
    log.info("Spielerinnen: %d", len(spieler))

    geschrieben = 0
    for o in spieler:
        pid, name = o["id"], o.get("name", "?")
        att, total = quote_for(pid, trainings)
        text = quote_text(att, total)
        props = [{"key": "trainingsbeteiligung", "text": text}]

        existing = at.get_object(pid).get("markdown", "")
        block = build_body_block(pid, trainings, att, total)
        rest = strip_old_block(existing)
        body = f"{block}\n\n{rest}" if rest else block
        try:
            at.update_object(pid, props, body=body)  # Name NICHT aendern
            log.info("%-18s %s", name, text)
            geschrieben += 1
        except AnytypeError as ex:
            log.error("FEHLER bei %s: %s", name, ex)

    log.info("Beteiligungs-Lauf beendet. %d Spielerinnen aktualisiert.", geschrieben)
    return geschrieben


def main() -> int:
    log = setup_logging()
    try:
        run(log)
        return 0
    except (AnytypeError, RuntimeError, KeyError) as e:
        log.error("Beteiligung fehlgeschlagen: %s", e)
        return 1
    except Exception:  # alles andere mit vollem Traceback ins Log
        log.error("Unerwarteter Fehler:\n%s", traceback.format_exc())
        return 1


if __name__ == "__main__":
    sys.exit(main())
