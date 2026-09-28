"""A bounded, read-only local analyst over MARM's evidence.

MARM retrieves; the model answers only from what MARM retrieved; code decides
whether the answer is supported. Nothing here writes memory.
"""

from .brief import Brief, analyse, stream_analysis
from .packet import EvidencePacket, build_packet, render_packet
from .profile import PROFILES, Profile, Run, resolve
from .verify import Citation, Verification, extract_citations, verify

__all__ = [
    "PROFILES",
    "Brief",
    "Citation",
    "EvidencePacket",
    "Profile",
    "Run",
    "Verification",
    "analyse",
    "build_packet",
    "extract_citations",
    "render_packet",
    "resolve",
    "stream_analysis",
    "verify",
]
