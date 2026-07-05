"""NISAR thin slice — multi-INT proof (spec sec 8).

Not a SAR product. One worker computes L-band interferometric coherence change
over a test AOI, flags coherence-loss patches, and writes them into the SAME
detections table as RF, through the SAME CoT path. Proving that a totally
different INT lands in the same library is the whole point.
"""
