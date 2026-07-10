"""WebSocket endpoint for Auto-Quant."""

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ....services.auto_quant import pipeline as _pl


def register_websocket_endpoint(router: APIRouter) -> None:
    """Register WebSocket endpoint on the given router."""
    
    @router.websocket("/ws/{run_id}")
    async def pipeline_websocket(websocket: WebSocket, run_id: str) -> None:
        """Real-time event stream for a pipeline run.

        Messages have shape:
            { "stage": int, "status": str, "message": str, "progress": int, "data": {} }

        A null message (or connection close) signals pipeline completion.
        """
        await websocket.accept()

        state = _pl.get_state(run_id)
        if state is None:
            await websocket.send_json({"error": f"Pipeline run '{run_id}' not found."})
            await websocket.close()
            return

        # Send current state snapshot immediately so clients can restore on reconnect
        await websocket.send_json({
            "type": "snapshot",
            "stage": state.current_stage,
            "status": state.status,
            "message": "Connected to pipeline stream.",
            "progress": _pl._state_snapshot(state).get("progress", 0),
            "data": _pl._state_snapshot(state),
        })

        # If pipeline is already finished, just close
        if state.status in ("completed", "failed", "cancelled", "interrupted"):
            await websocket.close()
            return

        q = _pl.get_queue(run_id)
        try:
            while True:
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=30.0)
                except asyncio.TimeoutError:
                    # Send keepalive ping
                    try:
                        await websocket.send_json({"type": "keepalive"})
                    except Exception:
                        break
                    continue

                if msg is None:
                    # Pipeline done — send final snapshot then close
                    final = _pl.get_state(run_id)
                    if final:
                        await websocket.send_json({
                            "type": "final",
                            "stage": final.current_stage,
                            "status": final.status,
                            "message": final.error or "Pipeline finished.",
                            "progress": 100 if final.status == "completed" else -1,
                            "data": _pl._state_snapshot(final),
                        })
                    break

                await websocket.send_json(msg)

        except WebSocketDisconnect:
            pass
        except Exception:
            pass
        finally:
            _pl.release_queue(run_id, q)
