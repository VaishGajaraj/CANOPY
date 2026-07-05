"""CANOPY — sensor-agnostic multi-INT signature platform (MVP).

The one defensible asset is the signature library: a detection is
``{when, where, feature_vector, confidence, source_int}`` regardless of
modality. RF bearings and SAR coherence-loss patches are the same row shape,
so a second INT drops into the same library without a schema change.

This package is pure standard library on purpose — the fusion math (the part
the whole thesis rests on) has zero external dependencies and is fully
testable, which is exactly what the kill-criteria in the spec demand.
"""

__version__ = "0.1.0"
