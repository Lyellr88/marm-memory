"""Response size limiting utilities for MCP compliance."""

import json
import sys
from typing import Dict, List, Any, Tuple

class MCPResponseLimiter:
    """Ensures MCP responses stay under 1MB limit."""
    
    # MCP response size limit (1MB = 1,048,576 bytes)
    MAX_RESPONSE_SIZE = 1048576
    
    # Safe buffer to account for JSON overhead and metadata
    SAFE_BUFFER = 48576  # ~47KB buffer
    CONTENT_LIMIT = MAX_RESPONSE_SIZE - SAFE_BUFFER  # ~1000KB for actual content
    
    @staticmethod
    def estimate_response_size(response_data: Dict[Any, Any]) -> int:
        """Estimate JSON response size in bytes."""
        try:
            json_str = json.dumps(response_data, ensure_ascii=False)
            return len(json_str.encode('utf-8'))
        except Exception as e:
            # Fallback estimation if JSON serialization fails
            print(f"Warning: JSON serialization failed ({e}), using inaccurate fallback for size estimation")
            return sys.getsizeof(str(response_data))
    
    @staticmethod
    def truncate_content(content: str, max_chars: int, preserve_start: bool = True) -> str:
        """Intelligently truncate content while preserving meaning."""
        if len(content) <= max_chars:
            return content
        
        if preserve_start:
            # Keep beginning, add ellipsis
            return content[:max_chars-3] + "..."
        else:
            # Keep end, add ellipsis at start
            return "..." + content[-(max_chars-3):]
    
    @staticmethod
    def truncate_memory_content(memory: Dict[str, Any], max_content_chars: int, 
                              preserve_start: bool = True) -> Dict[str, Any]:
        """Truncate a single memory's content field."""
        truncated = memory.copy()
        if 'content' in truncated:
            original_length = len(truncated['content'])
            
            # Choose truncation strategy based on content type
            # Error logs might benefit from preserving the end (final error message)
            content_type = memory.get('context_type', 'general')
            if content_type in ['error', 'debug', 'log'] and preserve_start is True:
                # For error content, preserve end by default unless explicitly requested otherwise
                preserve_start = False
            
            truncated['content'] = MCPResponseLimiter.truncate_content(
                truncated['content'], max_content_chars, preserve_start
            )
            
            # Add truncation indicator
            if original_length > max_content_chars:
                truncated['_truncated'] = True
                truncated['_original_length'] = original_length
                truncated['_truncation_strategy'] = 'start' if preserve_start else 'end'
        
        return truncated
    
    @classmethod
    def limit_memory_response(cls, memories: List[Dict[str, Any]], 
                            response_metadata: Dict[str, Any],
                            preserve_start: bool = True) -> Tuple[List[Dict[str, Any]], bool]:
        """
        Limit memory list response to stay under MCP size limits.
        Returns (limited_memories, was_truncated)
        """
        if not memories:
            return memories, False
        
        # Estimate base response size without content
        base_response = response_metadata.copy()
        base_response['results'] = []
        base_size = cls.estimate_response_size(base_response)
        
        # Calculate available space for memory content
        available_space = cls.CONTENT_LIMIT - base_size
        
        # If base response is already too big, return minimal response
        if available_space <= 0:
            return [], True
        
        # Try to fit memories, truncating content as needed
        limited_memories = []
        current_size = base_size
        was_truncated = False
        
        # Calculate rough max content per memory
        estimated_content_per_memory = available_space // len(memories)
        # Reserve space for JSON overhead (field names, quotes, commas, etc.)
        max_content_per_memory = max(100, estimated_content_per_memory - 200)
        
        for memory in memories:
            # Truncate this memory's content with smart strategy selection
            truncated_memory = cls.truncate_memory_content(
                memory, max_content_per_memory, preserve_start
            )
            
            # Test if adding this memory exceeds limit
            test_memories = limited_memories + [truncated_memory]
            test_response = response_metadata.copy()
            test_response['results'] = test_memories
            test_size = cls.estimate_response_size(test_response)
            
            if test_size > cls.CONTENT_LIMIT:
                # Can't fit this memory, stop here
                was_truncated = True
                break
            
            # Memory fits, add it
            limited_memories.append(truncated_memory)
            current_size = test_size
            
            # Check if we truncated content
            if '_truncated' in truncated_memory:
                was_truncated = True
        
        return limited_memories, was_truncated
    
    @classmethod
    def limit_context_bridge_response(cls, related_content: List[Dict[str, Any]], 
                                    response_metadata: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], bool]:
        """Limit context bridge response with multiple content types."""
        if not related_content:
            return related_content, False
        
        # Similar to memory response but handles mixed content types
        base_response = response_metadata.copy()
        base_response['related_content'] = []
        base_size = cls.estimate_response_size(base_response)
        
        available_space = cls.CONTENT_LIMIT - base_size
        if available_space <= 0:
            return [], True
        
        limited_content = []
        was_truncated = False
        max_content_per_item = max(150, (available_space // len(related_content)) - 300)
        
        for item in related_content:
            # Truncate content field in context items
            truncated_item = item.copy()
            if 'content' in truncated_item:
                original_length = len(truncated_item['content'])
                truncated_item['content'] = cls.truncate_content(
                    truncated_item['content'], max_content_per_item
                )
                if original_length > max_content_per_item:
                    truncated_item['_truncated'] = True
                    was_truncated = True
            
            # Test size
            test_content = limited_content + [truncated_item]
            test_response = response_metadata.copy()
            test_response['related_content'] = test_content
            test_size = cls.estimate_response_size(test_response)
            
            if test_size > cls.CONTENT_LIMIT:
                was_truncated = True
                break
            
            limited_content.append(truncated_item)
        
        return limited_content, was_truncated
    
    @classmethod
    def add_truncation_notice(cls, response: Dict[str, Any], was_truncated: bool, 
                            total_available: int = None) -> Dict[str, Any]:
        """Add truncation notice to response if content was limited."""
        if was_truncated:
            response['_mcp_truncated'] = True
            response['_truncation_reason'] = "Response limited to 1MB for MCP compliance"
            
            if total_available:
                response['_total_available'] = total_available
                response['message'] = response.get('message', '') + f" (showing partial results due to size limit, {total_available} total available)"
        
        return response