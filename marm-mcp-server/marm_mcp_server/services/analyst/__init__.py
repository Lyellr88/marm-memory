"""A bounded, read-only local analyst over MARM's evidence.

MARM retrieves; the model answers only from what MARM retrieved; code decides
whether the answer is supported. Nothing here writes memory.
"""

from .packet import EvidencePacket, build_packet, merge_packets, render_packet

__all__ = ["EvidencePacket", "build_packet", "merge_packets", "render_packet"]
