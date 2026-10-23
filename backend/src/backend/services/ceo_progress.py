"""Live progress for one chat turn: the one place a specialist's stage names can reach the CEO's turn without either importing the other.

The CEO sets `STAGE_SINK` for the duration of a turn; a specialist (today the CFO query planner) calls it with a stage name such as PLANNING. It carries only a name,
never a figure, so it can not change what an answer says (docs/specs/ceo-expense-tracker-chat.md and the CEO hub's progress events).
"""

from __future__ import annotations

import contextvars
from collections.abc import Callable

STAGE_SINK: contextvars.ContextVar[Callable[[str], None] | None] = contextvars.ContextVar("ceo_stage_sink", default=None)
