"""
Client fuer die lokale Anytype-API (http://127.0.0.1:31009/v1).

Die Anytype-Desktop-App muss laufen. API-Key kommt aus der .env (Api_key).
"""
import datetime

import requests

API_BASE = "http://127.0.0.1:31009/v1"
API_VERSION = "2025-05-20"


def iso_to_local_date(s: str) -> str | None:
    """ISO-String -> lokales Kalenderdatum 'YYYY-MM-DD'."""
    if not s:
        return None
    try:
        dt = datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone().date().isoformat()


class AnytypeError(Exception):
    pass


class Anytype:
    def __init__(self, api_key: str, space_id: str, version: str = API_VERSION):
        self.space = space_id
        self.s = requests.Session()
        self.s.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Anytype-Version": version,
            "Content-Type": "application/json",
        })

    def _url(self, path: str) -> str:
        return f"{API_BASE}/spaces/{self.space}{path}"

    # ------------------------------------------------------------- lesen
    def search(self, types=None, query: str = "", limit: int = 100) -> list[dict]:
        """Alle Objekte (optional nach Typ-Key gefiltert) holen, mit Paging."""
        body = {"query": query}
        if types:
            body["types"] = types
        out, offset = [], 0
        while True:
            r = self.s.post(self._url("/search"), json=body,
                            params={"limit": limit, "offset": offset}, timeout=30)
            r.raise_for_status()
            d = r.json()
            out.extend(d.get("data", []))
            if not d.get("pagination", {}).get("has_more"):
                break
            offset += limit
        return out

    @staticmethod
    def prop_value(obj: dict, key: str):
        """Wert einer Eigenschaft aus einem Objekt lesen (text/objects/date)."""
        for p in obj.get("properties", []):
            if p.get("key") == key:
                for fmt in ("text", "number", "date", "objects", "select",
                            "multi_select", "checkbox", "url"):
                    if fmt in p:
                        return p[fmt]
        return None

    def map_by_property(self, type_key: str, prop_key: str) -> dict:
        """{Eigenschaftswert (str) -> object_id} fuer einen Typ."""
        result = {}
        for o in self.search(types=[type_key]):
            val = self.prop_value(o, prop_key)
            if val:
                result[str(val)] = o["id"]
        return result

    def spieler_details(self) -> dict:
        """{spielerplus_id -> {id, name, pos_angriff, pos_abwehr}}."""
        out = {}
        for o in self.search(types=["spieler"]):
            sid = self.prop_value(o, "spielerplus_id")
            if not sid:
                continue
            out[str(sid)] = {
                "id": o["id"],
                "name": o.get("name", ""),
                "pos_angriff": self.prop_value(o, "position_angriff") or "",
                "pos_abwehr": self.prop_value(o, "posotion_abwehr") or "",
            }
        return out

    def get_object(self, object_id: str) -> dict:
        r = self.s.get(self._url(f"/objects/{object_id}"), timeout=30)
        r.raise_for_status()
        return r.json()["object"]

    def training_index(self) -> list[dict]:
        """[{id, event_id, day}] aller Training-Objekte (day = lokales Datum)."""
        items = []
        for o in self.search(types=["training"]):
            eid = self.prop_value(o, "spielerplus_event_id")
            items.append({
                "id": o["id"],
                "name": o.get("name", ""),
                "event_id": str(eid) if eid else None,
                "day": iso_to_local_date(self.prop_value(o, "datum")),
            })
        return items

    # ----------------------------------------------------------- schreiben
    def create_object(self, type_key: str, name: str, properties: list,
                      body: str | None = None) -> dict:
        payload = {"type_key": type_key, "name": name, "properties": properties}
        if body is not None:
            payload["body"] = body
        r = self.s.post(self._url("/objects"), json=payload, timeout=30)
        if r.status_code >= 400:
            raise AnytypeError(f"create {r.status_code}: {r.text[:300]}")
        return r.json()["object"]

    def update_object(self, object_id: str, properties: list,
                      name: str | None = None, body: str | None = None) -> dict:
        payload = {"properties": properties}
        if name is not None:
            payload["name"] = name
        if body is not None:
            payload["markdown"] = body
        r = self.s.patch(self._url(f"/objects/{object_id}"), json=payload, timeout=30)
        if r.status_code >= 400:
            raise AnytypeError(f"update {r.status_code}: {r.text[:300]}")
        return r.json()["object"]
