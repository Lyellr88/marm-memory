"""Utility helper functions for MARM MCP Server."""

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any

def format_log_entry(date: str, topic: str, summary: str) -> str:
    """Format a log entry in the standard MARM format"""
    return f"{date}-{topic}-{summary}"

def parse_log_entry(entry: str) -> Optional[Dict[str, str]]:
    """Parse a log entry string into its components"""
    pattern = r'^(\d{4}-\d{2}-\d{2})-(.*?)-(.*?)$'
    match = re.match(pattern, entry)
    
    if match:
        return {
            "date": match.group(1),
            "topic": match.group(2).strip(),
            "summary": match.group(3).strip()
        }
    
    return None

def get_current_timestamp() -> str:
    """Get current timestamp in ISO format"""
    return datetime.now(timezone.utc).isoformat()

def truncate_text(text: str, max_length: int = 100) -> str:
    """Truncate text to specified length with ellipsis"""
    if len(text) <= max_length:
        return text
    return text[:max_length-3] + "..."

def sanitize_filename(filename: str) -> str:
    """Sanitize filename by removing invalid characters"""
    # Remove invalid characters for filenames
    sanitized = re.sub(r'[<>:"/\\|?*\x00-\x1F]', '_', filename)
    # Remove leading/trailing whitespace and dots
    sanitized = sanitized.strip('. ')
    return sanitized or "unnamed_file"

def calculate_similarity_score(text1: str, text2: str) -> float:
    """Calculate simple similarity score between two texts (0.0 to 1.0)"""
    if not text1 or not text2:
        return 0.0
    
    # Simple word overlap calculation
    words1 = set(text1.lower().split())
    words2 = set(text2.lower().split())
    
    intersection = words1.intersection(words2)
    union = words1.union(words2)
    
    if len(union) == 0:
        return 0.0
    
    return len(intersection) / len(union)

def format_context_preview(context: str, max_lines: int = 3) -> str:
    """Format a context preview with limited lines"""
    lines = context.strip().split('\n')
    if len(lines) <= max_lines:
        return context
    
    preview = '\n'.join(lines[:max_lines])
    return preview + f"\n... ({len(lines) - max_lines} more lines)"

async def read_protocol_file():
    """Read the PROTOCOL.md file and return its content"""
    try:
        protocol_path = Path(__file__).parent.parent / "marm-docs" / "PROTOCOL.md"
        if protocol_path.exists():
            with open(protocol_path, 'r', encoding='utf-8') as f:
                return f.read()
        else:
            return "⚠️ PROTOCOL.md file not found. Please ensure documentation is properly loaded."
    except Exception as e:
        return f"❌ Error reading PROTOCOL.md: {str(e)}"