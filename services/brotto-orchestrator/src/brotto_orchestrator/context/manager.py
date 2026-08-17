"""Context manager: token budgeting, history compression, memory management.

Implements right-sized context per Decision D4.
"""

from __future__ import annotations

import re
from typing import Any


class ContextManager:
    """Manages LLM context size, token budgets, history compression."""

    # Rough token estimates (1 token ≈ 4 chars for English text)
    TOKEN_BUDGET_TOTAL = 4000  # 4k context for agent turn
    TOKEN_BUDGET_SYSTEM = 1000  # System prompt + rules
    TOKEN_BUDGET_OBSERVATION = 1000  # Current observation
    TOKEN_BUDGET_HISTORY = 1500  # History of past actions
    TOKEN_BUDGET_MEMORY = 500  # Extracted data/memory

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """Rough token estimate using character count.

        1 token ≈ 4 characters for English text (conservative).
        """
        return max(1, len(text) // 4)

    @staticmethod
    def compress_history(
        history: list[dict[str, Any]],
        max_tokens: int | None = None,
    ) -> list[dict[str, Any]]:
        """Compress history by keeping recent steps, summarizing old ones.

        Strategy:
        1. Keep last 5 steps in full detail
        2. For older steps, keep only type + result
        3. Drop steps if still over budget

        Args:
            history: List of (action, result) tuples
            max_tokens: Max tokens allocated for history (default: TOKEN_BUDGET_HISTORY)

        Returns:
            Compressed history
        """
        if not history:
            return []

        if max_tokens is None:
            max_tokens = ContextManager.TOKEN_BUDGET_HISTORY

        # Keep last 5 steps in full
        recent_steps = history[-5:] if len(history) > 5 else history
        old_steps = history[:-5] if len(history) > 5 else []

        # Compress old steps to just type + result
        compressed_old = [
            {
                "step": s.get("step"),
                "type": s.get("type"),
                "result": s.get("result", {}).get("ok", False),
            }
            for s in old_steps
        ]

        # Check token budget
        combined = compressed_old + recent_steps
        combined_text = _format_history(combined)
        token_count = ContextManager.estimate_tokens(combined_text)

        if token_count <= max_tokens:
            return combined

        # If still over budget, keep only last 3 steps
        return history[-3:] if len(history) >= 3 else history

    @staticmethod
    def format_context(
        observation: dict[str, Any],
        history: list[dict[str, Any]],
        memory: dict[str, Any],
        goal: str,
    ) -> str:
        """Format complete context for agent.

        Per Decision D4: Structured observation with targets, history, memory.

        Returns:
            Formatted context string ready for agent input
        """
        from .builder import build_context

        # Build base context using existing builder
        context = build_context(
            observation=observation,
            history=history,
            memory=memory,
            goal=goal,
        )

        # Estimate tokens
        tokens_used = ContextManager.estimate_tokens(context)
        budget_remaining = ContextManager.TOKEN_BUDGET_TOTAL - tokens_used

        # Add context size notice if near limit
        if budget_remaining < 500:
            context += f"\n\n⚠️ Context budget low ({tokens_used}/{ContextManager.TOKEN_BUDGET_TOTAL} tokens). Be concise."

        return context


def _format_history(history: list[dict[str, Any]]) -> str:
    """Format history for token counting."""
    if not history:
        return ""

    lines = ["HISTORY:"]
    for h in history:
        step_str = f"step {h.get('step', '?')} {h.get('type', '?')} -> "
        if isinstance(h.get("result"), dict):
            result_str = "ok" if h["result"].get("ok") else h["result"].get("error", "failed")
        else:
            result_str = str(h.get("result", "?"))
        lines.append(f"  {step_str}{result_str}")

    return "\n".join(lines)
