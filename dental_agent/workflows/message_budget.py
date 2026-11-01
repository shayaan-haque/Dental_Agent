"""Bound model input without cutting tool-call/result pairs in half."""

import json

from langchain_core.messages import HumanMessage, ToolMessage


def model_messages(messages, max_chars=18000, previous_turns=4):
    """Keep the active turn plus a bounded tail of complete earlier turns.

    This is a character budget, not an exact tokenizer count. The active turn is
    never truncated, even if it alone exceeds the budget. Stored history and
    tool-execution safeguards are unaffected; only the model input is reduced.
    """
    turns = []
    for message in messages:
        if isinstance(message, HumanMessage) or not turns:
            turns.append([])
        turns[-1].append(message)
    if not turns:
        return []

    def size(turn):
        return sum(len(str(message.content)) + len(json.dumps(getattr(message, "tool_calls", [])))
                   for message in turn)

    selected = [turns[-1]]
    remaining = max_chars - size(turns[-1])
    older = turns[:-1][-previous_turns:] if previous_turns else []
    for turn in reversed(older):
        cost = size(turn)
        if cost > remaining:
            break
        selected.insert(0, turn)
        remaining -= cost

    result = []
    for turn in selected:
        for message in turn:
            if isinstance(message, ToolMessage):
                content = message.content
                if isinstance(content, str):
                    try:
                        content = json.loads(content)
                    except ValueError:
                        pass
                if isinstance(content, (dict, list)):
                    message = message.model_copy(update={"content": json.dumps(content, separators=(",", ":"))})
            result.append(message)
    return result
