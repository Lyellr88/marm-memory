"""A bounded, read-only local analyst over MARM's evidence.

MARM retrieves; the model answers only from what MARM retrieved; code decides
whether the answer is supported. Nothing here writes memory.
"""

from .brief import Brief, analyse, stream_analysis
from .budget import Budget, Run
from .packet import EvidencePacket, build_packet, merge_packets, render_packet
from .verify import Citation, Verification, extract_citations, verify

__all__ = [
    "Brief",
    "Budget",
    "Citation",
    "EvidencePacket",
    "Run",
    "Verification",
    "analyse",
    "build_packet",
    "extract_citations",
    "merge_packets",
    "render_packet",
    "stream_analysis",
    "verify",
]
