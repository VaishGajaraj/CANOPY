"""In-memory signature-library store.

One collection per schema table. The production path swaps this class for a
psycopg-backed repository against db/schema.sql with identical method
signatures — nothing upstream (fusion, scoring, CoT, API) knows the difference.

The invariant the store guards: ``detections`` is one collection for every
modality. ``add_detection`` accepts rf and sar rows through the same door.
"""

from __future__ import annotations

import threading
from datetime import datetime
from typing import Callable, Dict, List, Optional

from .models import (
    Detection,
    Exercise,
    GeoFix,
    Signature,
    Source,
    Watch,
    WatchHit,
)


class Store:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.sources: Dict[str, Source] = {}
        self.exercises: Dict[str, Exercise] = {}
        self.signatures: Dict[str, Signature] = {}
        self.detections: Dict[str, Detection] = {}
        self.fixes: Dict[str, GeoFix] = {}
        self.watches: Dict[str, Watch] = {}
        self.watch_hits: Dict[str, WatchHit] = {}
        # Fan-out for live push (SSE/WebSocket). Callbacks get (event, payload).
        self._subscribers: List[Callable[[str, dict], None]] = []

    # --- subscriptions (live overlay) --------------------------------------
    def subscribe(self, cb: Callable[[str, dict], None]) -> Callable[[], None]:
        with self._lock:
            self._subscribers.append(cb)

        def _unsub() -> None:
            with self._lock:
                if cb in self._subscribers:
                    self._subscribers.remove(cb)

        return _unsub

    def _emit(self, event: str, payload: dict) -> None:
        for cb in list(self._subscribers):
            try:
                cb(event, payload)
            except Exception:
                pass

    # --- sources -----------------------------------------------------------
    def add_source(self, s: Source) -> Source:
        with self._lock:
            self.sources[s.id] = s
        return s

    def get_source(self, sid: str) -> Optional[Source]:
        return self.sources.get(sid)

    # --- exercises ---------------------------------------------------------
    def add_exercise(self, e: Exercise) -> Exercise:
        with self._lock:
            self.exercises[e.id] = e
        return e

    def get_exercise(self, eid: str) -> Optional[Exercise]:
        return self.exercises.get(eid)

    # --- signatures --------------------------------------------------------
    def upsert_signature(self, sig: Signature) -> Signature:
        with self._lock:
            self.signatures[sig.id] = sig
        self._emit("signature", {"id": sig.id})
        return sig

    def find_signature(self, source_int: str, emitter_type: str, channel_hz: float,
                       tol_hz: float) -> Optional[Signature]:
        """Match by modality + emitter type + nearest channel centre."""
        with self._lock:
            best = None
            for sig in self.signatures.values():
                if sig.source_int != source_int or sig.emitter_type != emitter_type:
                    continue
                c = sig.feature_vector.get("center_hz")
                if c is None:
                    best = sig
                    continue
                if abs(c - channel_hz) <= tol_hz:
                    best = sig
            return best

    # --- detections (the sensor-agnostic door) -----------------------------
    def add_detection(self, d: Detection) -> Detection:
        with self._lock:
            self.detections[d.id] = d
        self._emit("detection", {"id": d.id, "source_int": d.source_int,
                                  "emitter_type": d.emitter_type})
        self._check_watches(d)
        return d

    def detections_for(self, exercise_id: str) -> List[Detection]:
        with self._lock:
            rows = [d for d in self.detections.values() if d.exercise_id == exercise_id]
        rows.sort(key=lambda d: d.observed_at)
        return rows

    # --- fixes -------------------------------------------------------------
    def add_fix(self, f: GeoFix) -> GeoFix:
        with self._lock:
            self.fixes[f.id] = f
        self._emit("fix", {"id": f.id})
        return f

    def fixes_for(self, exercise_id: str) -> List[GeoFix]:
        with self._lock:
            return [f for f in self.fixes.values() if f.exercise_id == exercise_id]

    # --- watches (flywheel) ------------------------------------------------
    def add_watch(self, w: Watch) -> Watch:
        with self._lock:
            self.watches[w.id] = w
        return w

    def _check_watches(self, d: Detection) -> None:
        if not d.signature_id:
            return
        for w in list(self.watches.values()):
            if w.active and w.signature_id == d.signature_id:
                hit = WatchHit(watch_id=w.id, detection_id=d.id, fired_at=d.observed_at)
                self.watch_hits[hit.id] = hit
                self._emit("watch_hit", {"watch_id": w.id, "detection_id": d.id})
