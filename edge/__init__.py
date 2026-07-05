"""Edge layer — synthetic-emitter simulator + the real detect/classify/report loop.

There is no KrakenSDR in this MVP, so simulate.py stands in for the RF front
end. It models a friendly unit's emitters and produces field-like node reports
(real node->emitter geometry for bearings, explicit measurement noise on the
features) so the backend fusion + classification run on honest inputs.
"""
