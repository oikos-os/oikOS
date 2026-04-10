from __future__ import annotations

from core.interface.config import (
    CONTEXT_ENGINE_HOT_WINDOW,
    CONTEXT_ENGINE_TOKEN_MULTIPLIER,
    CONTEXT_ENGINE_WARM_CEILING,
)


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return int(len(text.split()) * CONTEXT_ENGINE_TOKEN_MULTIPLIER)


class ContextEngine:
    def __init__(self, hot_window: int | None = None, warm_ceiling: int | None = None):
        self.hot_window = hot_window if hot_window is not None else CONTEXT_ENGINE_HOT_WINDOW
        self.warm_ceiling = warm_ceiling if warm_ceiling is not None else CONTEXT_ENGINE_WARM_CEILING

    def mask_observations(self, conversation_history: list[dict], window_size: int | None = None) -> list[dict]:
        hot = window_size if window_size is not None else self.hot_window
        tool_indices = [
            i for i, turn in enumerate(conversation_history) if turn.get("role") == "tool"
        ]
        if not tool_indices:
            return list(conversation_history)

        # Rank from end: last tool = rank 1
        ranks = {}
        for rank, idx in enumerate(reversed(tool_indices), 1):
            ranks[idx] = rank

        result = []
        tool_counter = 0
        for i, turn in enumerate(conversation_history):
            if i not in ranks:
                result.append(dict(turn))
                continue

            tool_counter += 1
            rank = ranks[i]
            tc = turn["tool_call"]

            if rank <= hot:
                result.append(dict(turn))
            elif rank <= self.warm_ceiling:
                n_tokens = estimate_tokens(turn["content"])
                placeholder = f"[masked — {n_tokens} tokens removed. Call: {tc['name']}({tc['args_summary']})]"
                result.append({"role": "tool", "content": placeholder, "tool_call": tc})
            else:
                placeholder = f"[Turn {tool_counter}: {tc['name']} call — details masked]"
                result.append({"role": "tool", "content": placeholder, "tool_call": tc})

        return result
