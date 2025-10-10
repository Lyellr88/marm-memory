"""Event-driven automation system for MARM MCP Server."""

import asyncio
import logging
from typing import Dict, List, Callable, Any

class MARMEvents:
    """Built-in automation system with full error isolation"""
    
    def __init__(self):
        self.listeners: Dict[str, List[Callable]] = {}
        self.failed_callbacks: Dict[str, int] = {}  # Track failed callback counts
        self.logger = logging.getLogger(__name__)
    
    def on(self, event_type: str, callback):
        """Register event listener"""
        if event_type not in self.listeners:
            self.listeners[event_type] = []
        self.listeners[event_type].append(callback)
    
    async def emit(self, event_type: str, data: dict):
        """Trigger automatic actions with full error isolation"""
        if event_type not in self.listeners:
            return
        
        callbacks = self.listeners[event_type].copy()  # Snapshot to prevent modification issues
        successful_callbacks = 0
        failed_callbacks = 0
        
        # Execute each callback in complete isolation
        for i, callback in enumerate(callbacks):
            callback_id = f"{event_type}_{id(callback)}"
            
            try:
                # Run callback with timeout protection
                await asyncio.wait_for(callback(data), timeout=30.0)
                successful_callbacks += 1
                
                # Reset failure count on success
                if callback_id in self.failed_callbacks:
                    del self.failed_callbacks[callback_id]
                    
            except asyncio.TimeoutError:
                failed_callbacks += 1
                self._log_callback_error(callback_id, "Callback timed out after 30 seconds", event_type)
                
            except Exception as e:
                failed_callbacks += 1
                self._log_callback_error(callback_id, str(e), event_type)
        
        # Log event completion summary
        if failed_callbacks > 0:
            self.logger.warning(
                f"Event '{event_type}' completed: {successful_callbacks} succeeded, {failed_callbacks} failed"
            )
        else:
            self.logger.debug(f"Event '{event_type}' completed successfully: {successful_callbacks} callbacks")
    
    def _log_callback_error(self, callback_id: str, error_msg: str, event_type: str):
        """Log callback errors with failure tracking"""
        # Track failure count
        self.failed_callbacks[callback_id] = self.failed_callbacks.get(callback_id, 0) + 1
        failure_count = self.failed_callbacks[callback_id]
        
        # Log with increasing severity based on failure count
        if failure_count == 1:
            self.logger.warning(f"Event callback failed for '{event_type}': {error_msg}")
        elif failure_count <= 5:
            self.logger.error(f"Event callback failed {failure_count} times for '{event_type}': {error_msg}")
        else:
            self.logger.critical(f"Event callback consistently failing ({failure_count} times) for '{event_type}': {error_msg}")
            # Could add auto-disable logic here if needed
    
    def get_health_status(self) -> Dict[str, Any]:
        """Get event system health status for monitoring"""
        total_listeners = sum(len(callbacks) for callbacks in self.listeners.values())
        failed_callback_count = len(self.failed_callbacks)
        
        return {
            "total_event_types": len(self.listeners),
            "total_listeners": total_listeners,
            "failed_callbacks": failed_callback_count,
            "health_status": "healthy" if failed_callback_count == 0 else "degraded"
        }

# Global events system
events = MARMEvents()