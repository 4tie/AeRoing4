"""Events router for SSE streaming and recent events polling."""

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from typing import List, Dict, Any
import json
import asyncio

router = APIRouter(prefix="/api/events", tags=["Events"])


@router.get("/recent")
async def get_recent_events(request: Request) -> Dict[str, Any]:
    """Get recent events for polling fallback.
    
    Returns the most recent events from the log broadcaster.
    This is used as a fallback when SSE is not available.
    """
    from datetime import datetime
    import re
    
    # Get the log broadcaster from app state
    broadcaster = request.app.state.log_broadcaster
    
    # Get recent log lines from history
    log_lines = broadcaster.history
    
    # Parse log lines into events
    events = []
    for line in log_lines[-50:]:  # Get last 50 lines
        # Try to extract agent, task, status from log lines
        # Format: [timestamp] [level] [module] message
        match = re.match(r'\[(\d{2}:\d{2}:\d{2})\]\s+\[(\w+)\]\s+\[(\w+)\]\s+(.+)', line)
        if match:
            timestamp_str, level, module, message = match.groups()
            
            # Determine agent based on module
            agent = "System"
            if "AUTO-QUANT" in module:
                agent = "Orchestrator"
            elif "backtest" in module.lower():
                agent = "Scout"
            elif "optimizer" in module.lower():
                agent = "Dev"
            
            # Determine status based on level
            status = "info"
            if level == "ERROR":
                status = "error"
            elif level == "WARNING":
                status = "warning"
            elif level == "INFO":
                status = "success"
            
            # Create timestamp
            try:
                timestamp = datetime.strptime(timestamp_str, "%H:%M:%S").isoformat()
            except:
                timestamp = datetime.now().isoformat()
            
            events.append({
                "agent": agent,
                "task": message[:100],  # Truncate long messages
                "status": status,
                "timestamp": timestamp
            })
    
    # Reverse to show newest first
    events = events[::-1][:20]
    
    return {"events": events}


@router.get("/stream")
async def event_stream():
    """SSE endpoint for real-time event streaming.
    
    This provides a Server-Sent Events stream for real-time updates.
    """
    async def event_generator():
        """Generate SSE events."""
        try:
            while True:
                # In a real implementation, this would pull from the log broadcaster
                # For now, send a heartbeat every 10 seconds
                await asyncio.sleep(10)
                yield f"data: {json.dumps({'type': 'heartbeat', 'timestamp': '2025-06-22T00:00:00Z'})}\n\n"
        except asyncio.CancelledError:
            # Client disconnected
            pass
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )
