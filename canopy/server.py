"""Backend web layer — stdlib only (spec sec 6, sec 7).

FastAPI in production; for the hardware-free, install-free MVP we use
http.server so the whole thing runs with a bare Python. The live overlay is
pushed over Server-Sent Events (SSE) instead of a WebSocket — one-directional
push is all the map needs and SSE needs no dependencies. Endpoints:

  GET  /                    the single-page live map + after-action report
  GET  /api/report          after-action report JSON (targetability score)
  GET  /api/sources         nodes
  GET  /api/detections      raw detections (bearings, SAR patches)
  GET  /api/fixes           fused fixes with error ellipses
  GET  /api/signatures      the signature library
  GET  /api/cot             CoT event XML for all fixes (TAK feed)
  GET  /api/stream          SSE live push of new detections/fixes
  POST /api/detections      ingest a live NodeReport (JSON)
"""

from __future__ import annotations

import json
import os
import queue
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

from .models import Detection, GeoFix, Source
from .pipeline import NodeReport, Pipeline
from .store import Store

_FRONTEND = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "frontend")


def _iso(v):
    if isinstance(v, datetime):
        return v.isoformat()
    return v


def _source_json(s: Source) -> dict:
    return {"id": s.id, "label": s.label, "source_int": s.source_int,
            "lat": s.lat, "lon": s.lon, "calibration": s.calibration}


def _detection_json(d: Detection) -> dict:
    return {"id": d.id, "source_int": d.source_int,
            "observed_at": _iso(d.observed_at), "source_id": d.source_id,
            "emitter_type": d.emitter_type, "confidence": d.confidence,
            "geom": d.geom, "features": d.features, "signature_id": d.signature_id}


def _fix_json(f: GeoFix) -> dict:
    return {"id": f.id, "lat": f.lat, "lon": f.lon,
            "err_semimajor_m": f.err_semimajor_m, "err_semiminor_m": f.err_semiminor_m,
            "err_orient_deg": f.err_orient_deg, "cep50_m": f.cep50_m,
            "gdop": f.gdop, "method": f.method, "signature_id": f.signature_id,
            "n_contributors": f.n_contributors, "fixed_at": _iso(f.fixed_at)}


def make_handler(store: Store, pipeline: Pipeline, exercise_id: str):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):  # quiet
            pass

        def _send_json(self, obj, code=200):
            body = json.dumps(obj, default=_iso).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

        def _send_text(self, text, ctype="text/plain", code=200):
            body = text.encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_file(self, path, ctype):
            try:
                with open(path, "rb") as f:
                    body = f.read()
            except FileNotFoundError:
                self._send_text("not found", code=404)
                return
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?")[0]
            if path == "/" or path == "/index.html":
                self._send_file(os.path.join(_FRONTEND, "index.html"), "text/html")
            elif path == "/app.js":
                self._send_file(os.path.join(_FRONTEND, "app.js"), "application/javascript")
            elif path == "/styles.css":
                self._send_file(os.path.join(_FRONTEND, "styles.css"), "text/css")
            elif path == "/api/report":
                self._send_json(pipeline.report(exercise_id))
            elif path == "/api/sources":
                self._send_json([_source_json(s) for s in store.sources.values()])
            elif path == "/api/detections":
                self._send_json([_detection_json(d)
                                 for d in store.detections_for(exercise_id)])
            elif path == "/api/fixes":
                self._send_json([_fix_json(f) for f in store.fixes_for(exercise_id)])
            elif path == "/api/signatures":
                self._send_json([{
                    "id": s.id, "source_int": s.source_int,
                    "emitter_type": s.emitter_type, "times_seen": s.times_seen,
                    "first_seen": _iso(s.first_seen), "last_seen": _iso(s.last_seen),
                    "feature_vector": s.feature_vector,
                } for s in store.signatures.values()])
            elif path == "/api/cot":
                self._send_text("\n".join(pipeline.cot_events(exercise_id)),
                                ctype="application/xml")
            elif path == "/api/stream":
                self._stream()
            else:
                self._send_text("not found", code=404)

        def do_POST(self):
            path = self.path.split("?")[0]
            if path == "/api/detections":
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length)
                try:
                    data = json.loads(raw)
                    rep = NodeReport(
                        node_id=data["node_id"],
                        observed_at=datetime.fromisoformat(data["observed_at"]),
                        center_hz=float(data["center_hz"]),
                        bw_hz=float(data["bw_hz"]),
                        burst_ms=float(data.get("burst_ms", 0.0)),
                        duty=float(data.get("duty", 0.0)),
                        bearing_deg=data.get("bearing_deg"),
                        emitter_type=data["emitter_type"],
                        confidence=float(data.get("confidence", 0.5)),
                        bearing_sigma_deg=data.get("bearing_sigma_deg"),
                        snr_db=data.get("snr_db"),
                    )
                    det = pipeline.ingest(rep, exercise_id)
                    pipeline.fuse(exercise_id)
                    self._send_json({"ok": True, "detection_id": det.id})
                except Exception as e:  # noqa
                    self._send_json({"ok": False, "error": str(e)}, code=400)
            else:
                self._send_text("not found", code=404)

        def _stream(self):
            q: "queue.Queue[tuple]" = queue.Queue()
            unsub = store.subscribe(lambda ev, payload: q.put((ev, payload)))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            try:
                self.wfile.write(b": connected\n\n")
                self.wfile.flush()
                while True:
                    try:
                        ev, payload = q.get(timeout=15)
                        msg = f"event: {ev}\ndata: {json.dumps(payload)}\n\n"
                    except queue.Empty:
                        msg = ": keepalive\n\n"
                    self.wfile.write(msg.encode())
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                unsub()

    return Handler


def serve(store: Store, pipeline: Pipeline, exercise_id: str,
          host: str = "127.0.0.1", port: int = 8787) -> None:
    handler = make_handler(store, pipeline, exercise_id)
    httpd = ThreadingHTTPServer((host, port), handler)
    print(f"CANOPY live UI: http://{host}:{port}  (Ctrl-C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.shutdown()
