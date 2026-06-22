"""
Kleine GUI fuer den SpielerPlus -> Anytype Sync.

Ablauf:
  1. Start -> Trainings der aktuellen Woche werden angezeigt.
  2. Training anklicken -> Auswaehlen.
  3. In Anytype wird geprueft, ob an dem Tag schon ein Training existiert:
       - nein  -> Frage "Neues Training erstellen?"
       - ja    -> Frage "Anwesenheit erstellen/aktualisieren?"

Start:  py gui.py     (oder Doppelklick auf start_gui.pyw)
Die Anytype-Desktop-App muss laufen.
"""
import datetime
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from anytype import Anytype, AnytypeError
from spielerplus import SpielerPlus, SpielerPlusError
from sync import collect_event, write_event
from test_login import load_env


def event_date(ev: dict) -> datetime.date | None:
    """'22.06' (+ aktuelles Jahr) -> date. Jahr wird bei Bedarf korrigiert."""
    try:
        d, m = (int(x) for x in ev["day"].split(".")[:2])
    except (ValueError, KeyError):
        return None
    today = datetime.date.today()
    dt = datetime.date(today.year, m, d)
    if (dt - today).days < -180:      # Jahreswechsel
        dt = datetime.date(today.year + 1, m, d)
    return dt


def this_week_events(events: list) -> list:
    """Trainings der aktuellen Woche (Mo–So). Faellt auf alle zurueck."""
    today = datetime.date.today()
    monday = today - datetime.timedelta(days=today.weekday())
    sunday = monday + datetime.timedelta(days=6)
    week = [e for e in events
            if (d := event_date(e)) and monday <= d <= sunday]
    return week or events


class SyncGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("SpielerPlus → Anytype")
        root.geometry("520x420")

        self.env = load_env()
        self.sp = None
        self.at = None
        self.details = {}
        self.events = []          # parallele Liste zu den Listbox-Eintraegen

        ttk.Label(root, text="Trainings dieser Woche",
                  font=("Segoe UI", 12, "bold")).pack(pady=(12, 4))

        frame = ttk.Frame(root)
        frame.pack(fill="both", expand=True, padx=12)
        self.listbox = tk.Listbox(frame, font=("Segoe UI", 11), height=10)
        self.listbox.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(frame, command=self.listbox.yview)
        sb.pack(side="right", fill="y")
        self.listbox.config(yscrollcommand=sb.set)
        self.listbox.bind("<Double-Button-1>", lambda _e: self.on_select())

        btnrow = ttk.Frame(root)
        btnrow.pack(fill="x", padx=12, pady=8)
        self.select_btn = ttk.Button(btnrow, text="Auswählen",
                                     command=self.on_select, state="disabled")
        self.select_btn.pack(side="left")
        ttk.Button(btnrow, text="Aktualisieren",
                   command=self.load_async).pack(side="left", padx=6)

        self.status = ttk.Label(root, text="Verbinde mit SpielerPlus …",
                                foreground="gray")
        self.status.pack(pady=(0, 10))

        self.load_async()

    # ------------------------------------------------------------- laden
    def set_status(self, text: str, color: str = "gray"):
        self.status.config(text=text, foreground=color)
        self.root.update_idletasks()

    def load_async(self):
        self.select_btn.config(state="disabled")
        self.set_status("Verbinde mit SpielerPlus …")
        threading.Thread(target=self._load, daemon=True).start()

    def _load(self):
        try:
            sp = SpielerPlus(self.env["SP_EMAIL"], self.env["SP_PASSWORD"])
            sp.login()
            team_id = self.env.get("SP_TEAM_ID")
            if not team_id:
                raise RuntimeError("SP_TEAM_ID fehlt in .env "
                                   "(IDs via 'py show_training.py').")
            sp.switch_team(int(team_id))
            events = [e for e in sp.list_events() if e["type"] == "training"]
            at = Anytype(self.env["Api_key"], self.env["ANYTYPE_SPACE_ID"])
            details = at.spieler_details()
        except SpielerPlusError as e:
            self.root.after(0, lambda: self._load_failed(f"SpielerPlus: {e}"))
            return
        except Exception as e:                      # Anytype/Netzwerk
            self.root.after(0, lambda: self._load_failed(str(e)))
            return
        self.sp, self.at, self.details = sp, at, details
        week = this_week_events(events)
        self.root.after(0, lambda: self._fill_list(week))

    def _load_failed(self, msg: str):
        self.set_status("Fehler beim Laden.", "red")
        messagebox.showerror("Verbindung fehlgeschlagen", msg)

    def _fill_list(self, events: list):
        self.events = events
        self.listbox.delete(0, tk.END)
        for e in events:
            self.listbox.insert(tk.END, f"  {e['weekday']} {e['day']}   {e['title']}")
        if events:
            self.listbox.selection_set(0)
            self.select_btn.config(state="normal")
            self.set_status(f"{len(events)} Training(s) gefunden – auswählen.", "black")
        else:
            self.set_status("Keine Trainings gefunden.", "red")

    # ----------------------------------------------------------- auswahl
    def on_select(self):
        sel = self.listbox.curselection()
        if not sel:
            return
        event = self.events[sel[0]]
        self.select_btn.config(state="disabled")
        self.set_status("Lese Teilnahme & prüfe Anytype …")
        threading.Thread(target=self._process, args=(event,), daemon=True).start()

    def _process(self, event: dict):
        try:
            info = collect_event(self.sp, event, self.details)
            tindex = self.at.training_index()
        except Exception as e:
            self.root.after(0, lambda: self._after_action(f"Fehler: {e}", "red"))
            return
        eid = str(event["id"])
        match = next((t for t in tindex
                      if t["event_id"] == eid or t["day"] == info["event_day"]), None)
        self.root.after(0, lambda: self._ask_and_write(info, match))

    def _ask_and_write(self, info: dict, match: dict | None):
        datum_txt = info["datetime_label"] or info["event_day"]
        zusatz = (f"\n\nNicht zuordenbar: {', '.join(info['unmapped'])}"
                  if info["unmapped"] else "")
        info_txt = (f"Anwesend: {info['anwesend']} · Abgesagt: {info['abgesagt']}"
                    f"{zusatz}")

        if match:
            ok = messagebox.askyesno(
                "Training vorhanden",
                f"Am {datum_txt} existiert bereits:\n„{match['name']}“.\n\n"
                f"Anwesenheit erstellen/aktualisieren?\n\n{info_txt}")
            target_id = match["id"]
        else:
            ok = messagebox.askyesno(
                "Kein Training an diesem Tag",
                f"Am {datum_txt} gibt es noch kein Training in Anytype.\n\n"
                f"Neues Training erstellen?\n\n{info_txt}")
            target_id = None

        if not ok:
            self._after_action("Abgebrochen.", "gray")
            return

        self.set_status("Schreibe nach Anytype …")
        threading.Thread(target=self._write, args=(target_id, info),
                         daemon=True).start()

    def _write(self, target_id, info: dict):
        try:
            status = write_event(self.at, target_id, info)
        except AnytypeError as e:
            self.root.after(0, lambda: self._after_action(f"Fehler: {e}", "red"))
            return
        msg = (f"Training {status}: Anwesend {info['anwesend']}, "
               f"Abgesagt {info['abgesagt']}.")
        self.root.after(0, lambda: self._after_action(msg, "green", popup=True))

    def _after_action(self, msg: str, color: str, popup: bool = False):
        self.set_status(msg, color)
        self.select_btn.config(state="normal")
        if popup:
            messagebox.showinfo("Fertig", msg)


def main():
    root = tk.Tk()
    SyncGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
