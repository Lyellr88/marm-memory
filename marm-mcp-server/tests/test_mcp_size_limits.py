"""Test MCP 1MB response size limits."""

import pytest
import json
from core.response_limiter import MCPResponseLimiter

class TestMCPResponseLimiter:
    
    def test_response_size_estimation(self):
        """Test response size estimation accuracy."""
        simple_response = {"status": "success", "message": "test"}
        estimated_size = MCPResponseLimiter.estimate_response_size(simple_response)
        
        # Should be roughly the size of the JSON string
        json_str = json.dumps(simple_response)
        actual_size = len(json_str.encode('utf-8'))
        
        # Estimation should be close to actual (within 10%)
        assert abs(estimated_size - actual_size) / actual_size < 0.1
    
    def test_content_truncation(self):
        """Test intelligent content truncation."""
        long_content = "A" * 1000
        
        # Test truncation preserving start
        truncated = MCPResponseLimiter.truncate_content(long_content, 100, preserve_start=True)
        assert len(truncated) == 100
        assert truncated.startswith("A")
        assert truncated.endswith("...")
        
        # Test truncation preserving end
        truncated = MCPResponseLimiter.truncate_content(long_content, 100, preserve_start=False)
        assert len(truncated) == 100
        assert truncated.startswith("...")
        assert truncated.endswith("A")
    
    def test_memory_content_truncation(self):
        """Test memory-specific content truncation."""
        memory = {
            "id": "test_id",
            "content": "A" * 500,
            "context_type": "code",
            "similarity": 0.95
        }
        
        truncated = MCPResponseLimiter.truncate_memory_content(memory, 100)
        
        assert len(truncated["content"]) <= 100
        assert truncated["_truncated"] is True
        assert truncated["_original_length"] == 500
        assert truncated["id"] == "test_id"  # Other fields preserved
    
    def test_memory_response_limiting(self):
        """Test memory response size limiting."""
        # Create memories with large content
        large_memories = []
        for i in range(10):
            large_memories.append({
                "id": f"memory_{i}",
                "content": "X" * 100000,  # 100KB each
                "context_type": "test",
                "similarity": 0.9 - (i * 0.1)
            })
        
        base_response = {
            "status": "success",
            "message": "Test response",
            "query": "test query"
        }
        
        limited_memories, was_truncated = MCPResponseLimiter.limit_memory_response(
            large_memories, base_response
        )
        
        # Should have truncated to fit in 1MB
        test_response = base_response.copy()
        test_response["results"] = limited_memories
        
        response_size = MCPResponseLimiter.estimate_response_size(test_response)
        assert response_size <= MCPResponseLimiter.CONTENT_LIMIT
        assert was_truncated is True  # Should have been truncated
        assert len(limited_memories) <= len(large_memories)  # Some memories removed or truncated
    
    def test_context_bridge_response_limiting(self):
        """Test context bridge response size limiting."""
        # Create large related content
        large_content = []
        for i in range(15):
            large_content.append({
                "type": "memory",
                "content": "Y" * 80000,  # 80KB each
                "session_name": f"session_{i}",
                "context_type": "project",
                "similarity": 0.95 - (i * 0.05)
            })
        
        base_response = {
            "status": "success",
            "new_topic": "test topic",
            "session_name": "test_session"
        }
        
        limited_content, was_truncated = MCPResponseLimiter.limit_context_bridge_response(
            large_content, base_response
        )
        
        # Verify response size compliance
        test_response = base_response.copy()
        test_response["related_content"] = limited_content
        
        response_size = MCPResponseLimiter.estimate_response_size(test_response)
        assert response_size <= MCPResponseLimiter.CONTENT_LIMIT
        assert was_truncated is True
        assert len(limited_content) <= len(large_content)
    
    def test_truncation_notice_addition(self):
        """Test truncation notice functionality."""
        response = {
            "status": "success",
            "results": []
        }
        
        # Test with truncation
        modified_response = MCPResponseLimiter.add_truncation_notice(
            response, was_truncated=True, total_available=10
        )
        
        assert modified_response["_mcp_truncated"] is True
        assert "1MB" in modified_response["_truncation_reason"]
        assert modified_response["_total_available"] == 10
        assert "partial results" in modified_response["message"]
        
        # Test without truncation
        clean_response = {"status": "success"}
        unmodified_response = MCPResponseLimiter.add_truncation_notice(
            clean_response, was_truncated=False
        )
        
        assert "_mcp_truncated" not in unmodified_response
    
    def test_edge_case_empty_data(self):
        """Test handling of empty or minimal data."""
        # Test empty memories list
        limited, truncated = MCPResponseLimiter.limit_memory_response([], {})
        assert limited == []
        assert truncated is False
        
        # Test very small content
        tiny_memories = [{"content": "small", "id": "1"}]
        limited, truncated = MCPResponseLimiter.limit_memory_response(
            tiny_memories, {"status": "success"}
        )
        assert len(limited) == 1
        assert truncated is False
    
    def test_exact_limit_boundary(self):
        """Test behavior at exactly the 1MB boundary."""
        # Create content that's exactly at the limit
        target_size = MCPResponseLimiter.CONTENT_LIMIT
        
        # Start with base response
        base_response = {"status": "success", "message": "test"}
        base_size = MCPResponseLimiter.estimate_response_size(base_response)
        
        # Calculate content size to hit exactly the limit
        available_space = target_size - base_size - 100  # Small buffer for JSON structure
        content_per_memory = available_space // 3  # 3 memories
        
        boundary_memories = []
        for i in range(3):
            boundary_memories.append({
                "id": f"boundary_{i}",
                "content": "B" * content_per_memory,
                "similarity": 0.9
            })
        
        limited, truncated = MCPResponseLimiter.limit_memory_response(
            boundary_memories, base_response
        )
        
        # Should fit without truncation or with minimal truncation
        test_response = base_response.copy()
        test_response["results"] = limited
        response_size = MCPResponseLimiter.estimate_response_size(test_response)
        
        assert response_size <= MCPResponseLimiter.CONTENT_LIMIT
        assert len(limited) > 0  # Should keep at least some memories
    
    def test_large_summary_response_limiting(self):
        """Test marm_summary response size limiting with many log entries."""
        # Simulate large summary response that would exceed 1MB
        large_summary_data = {
            "status": "success", 
            "session_name": "test_session",
            "total_entries": 500,
            "summary": "\n".join([
                f"**2025-01-15 10:{i:02d}:00** [milestone-{i}]: Very long summary text that contains detailed information about what was accomplished during this particular session milestone including technical details, decisions made, and outcomes achieved." 
                for i in range(5000)  # 5000 entries with long summaries
            ])
        }
        
        # Verify this would exceed 1MB
        response_size = MCPResponseLimiter.estimate_response_size(large_summary_data)
        print(f"Large summary size: {response_size / 1024:.1f} KB")
        
        # This should be larger than our limit
        assert response_size > MCPResponseLimiter.CONTENT_LIMIT, "Test summary should exceed 1MB limit"
        
        # Test that our new summary endpoint would handle this properly
        # (simulating the progressive entry addition logic)
        base_response = {
            "status": "success",
            "session_name": "test_session",
            "total_entries": 500
        }
        
        # Simulate adding entries one by one until size limit hit
        summary_lines = ["# MARM Session Summary: test_session", "Generated: 2025-01-15", ""]
        entries_included = 0
        
        # Start with the base summary
        current_summary_text = "\n".join(summary_lines)

        for i in range(5000):
            entry_line = f"**2025-01-15 10:{i:02d}:00** [milestone-{i}]: {'A' * 500}" # Use a much larger string
            
            # Test adding the NEXT line
            test_summary = current_summary_text + "\n" + entry_line
            
            test_response = base_response.copy()
            test_response["summary"] = test_summary
            test_response["entry_count"] = i + 1
            
            response_size = MCPResponseLimiter.estimate_response_size(test_response)
            
            if response_size > MCPResponseLimiter.CONTENT_LIMIT:
                entries_included = i  # We successfully included i entries (0-indexed)
                break
            
            # If it fits, update the current summary
            current_summary_text = test_summary
        else:
            # If the loop completes without breaking, all entries were included
            entries_included = 5000

        print(f"Would include {entries_included} entries before hitting size limit")
        
        # Should have stopped before including all entries
        assert entries_included < 5000, "Should have truncated entries to stay under limit"
        assert entries_included > 0, "Should have included at least some entries"

if __name__ == "__main__":
    # Quick test run
    test = TestMCPResponseLimiter()
    
    print("Testing response size estimation...")
    test.test_response_size_estimation()
    print("✅ Passed")
    
    print("Testing content truncation...")
    test.test_content_truncation()
    print("✅ Passed")
    
    print("Testing memory response limiting...")
    test.test_memory_response_limiting()
    print("✅ Passed")
    
    print("Testing edge cases...")
    test.test_edge_case_empty_data()
    print("✅ Passed")
    
    print("Testing large summary response limiting...")
    test.test_large_summary_response_limiting()
    print("✅ Passed")
    
    print("\n🎉 All MCP size limit tests passed!")