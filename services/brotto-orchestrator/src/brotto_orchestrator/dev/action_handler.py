"""Unified action handler for dev (Pydantic) and extension (dict) modes."""

from __future__ import annotations

from typing import Any


class ActionHandler:
    """Normalize actions from both dev (Pydantic) and extension (dict) modes."""

    @staticmethod
    def to_dict(action: Any) -> dict[str, Any]:
        """Convert action to dict (handles Pydantic models + dicts)."""
        if hasattr(action, 'model_dump'):
            return action.model_dump()
        if isinstance(action, dict):
            return action
        # Fallback
        return {"type": "unknown", "error": f"Unknown action type: {type(action)}"}

    @staticmethod
    def get_type(action: Any) -> str:
        """Get action type from Pydantic or dict."""
        action_dict = ActionHandler.to_dict(action)
        return action_dict.get("type", "unknown")

    @staticmethod
    def get_field(action: Any, field: str, default: Any = None) -> Any:
        """Get field from Pydantic or dict action."""
        action_dict = ActionHandler.to_dict(action)
        return action_dict.get(field, default)
