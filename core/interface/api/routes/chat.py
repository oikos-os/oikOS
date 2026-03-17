"""Chat endpoints — SSE streaming, history, session transcript."""

from __future__ import annotations

import json

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

router = APIRouter()


class ChatRequest(BaseModel):
    query: str
    force_local: bool = False
    force_cloud: bool = False
    skip_pii_scrub: bool = False
    model: str | None = None
    attached_files: list[dict] | None = None


@router.post("")
def chat(req: ChatRequest):
    from core.cognition.handler import execute_query_stream

    def sse_generator():
        # Prepend attached file content to query
        query = req.query
        if req.attached_files:
            file_context = "\n".join(
                f"[File: {f.get('name', 'unknown')}]\n{f.get('content', '')}"
                for f in req.attached_files
            )
            query = f"{file_context}\n\n{query}"

        for chunk in execute_query_stream(
            query,
            force_local=req.force_local,
            force_cloud=req.force_cloud,
            skip_pii_scrub=req.skip_pii_scrub,
            model_override=req.model,
        ):
            if chunk["done"]:
                resp = chunk["response"]
                rd = resp.routing_decision if resp else None
                payload = {
                    "done": True,
                    "route": resp.route.value if resp and resp.route else None,
                    "model": resp.model_used if resp else None,
                    "confidence": resp.confidence if resp else None,
                    "pii_scrubbed": resp.pii_scrubbed if resp else False,
                    "pipeline": {
                        "pii": rd.pii_detected if rd else False,
                        "adversarial": False,
                        "cosine_gate": rd.cosine_gate_fired if rd else False,
                        "contradiction": bool(resp.contradiction and resp.contradiction.has_contradiction) if resp else False,
                        "coherence": True,
                        "output_filter": True,
                    } if resp else {},
                }
                yield f"data: {json.dumps(payload)}\n\n"
            else:
                yield f"data: {json.dumps({'delta': chunk['delta']})}\n\n"

    return StreamingResponse(sse_generator(), media_type="text/event-stream")


@router.get("/suggestions")
def chat_suggestions(category: str = Query(..., min_length=1)):
    """Stream category-specific suggestions from local LLM based on system context."""
    from core.cognition.inference import get_inference_client
    from core.interface.config import INFERENCE_MODEL

    # Gather live context for grounding
    context_parts = []
    try:
        from core.interface.api.routes.system import get_state
        state = get_state()
        context_parts.append(f"System state: {state.get('fsm_state', 'unknown')}, uptime: {state.get('uptime', 0)}s")
    except Exception:
        pass
    try:
        from core.memory.search import hybrid_search
        recent = hybrid_search(category, limit=3)
        if recent:
            context_parts.append("Related vault entries: " + "; ".join(r.content[:100] for r in recent))
    except Exception:
        pass

    context = "\n".join(context_parts) if context_parts else "No additional context available."

    prompt = (
        f"You are oikOS, a sovereign AI system. The user clicked the \"{category}\" quick-action button.\n"
        f"Current system context:\n{context}\n\n"
        f"Generate exactly 4 short, actionable suggestion prompts the user could send, relevant to the \"{category}\" category.\n"
        f"Each suggestion should be a complete message the user could send as-is.\n"
        f"Output ONLY the 4 suggestions, one per line, no numbering, no bullets, no extra text."
    )

    def sse_generator():
        try:
            client = get_inference_client()
            stream = client.chat(
                model=INFERENCE_MODEL,
                messages=[{"role": "user", "content": prompt}],
                stream=True,
            )
            for chunk in stream:
                delta = (chunk.message.content or "") if chunk.message else ""
                if delta:
                    yield f"data: {json.dumps({'delta': delta})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e), 'done': True})}\n\n"

    return StreamingResponse(sse_generator(), media_type="text/event-stream")


@router.get("/history")
def chat_history(limit: int = Query(20, ge=1, le=100)):
    from core.memory.session import list_recent_sessions

    return list_recent_sessions(limit=limit)


@router.get("/session/{session_id}")
def chat_session(session_id: str):
    from core.memory.session import load_session_transcript

    return load_session_transcript(session_id)
