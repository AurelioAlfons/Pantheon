"""Aizen's real handler -- the writer. Two unrelated jobs, split by an explicit task_type.

Unlike every agent before it, Aizen doesn't have one job. It either writes up a change
(changelog + commit message + optional post + summary) or draws the schema diagram. The
caller says which via payload["task_type"] -- no Claude call wasted guessing from prose.
"""

import json

import anthropic

from app.agents.base_agent import BaseAgent
from app.core.settings import settings

# ===== SCHEMA DESCRIPTION (for the schema_diagram job) =====

# Aizen has no external tools (aizen.md's hard restriction), so it can't introspect the live DB.
# instead we hand it an accurate static description of models.py and let it reason over that --
# same "no tools, just what it's given" shape as every other agent. keep this in sync with
# models.py by hand; it's the source of truth for the diagram, so a wrong line here = a wrong diagram.
SCHEMA_DESCRIPTION = """\
The database has exactly three tables:

1. agents (id PK, name unique, role, model, status, updated_at)
2. tasks (id PK, status, payload, result, created_by, assigned_to, parent_task_id, project_id, depth, created_at, updated_at)
3. events (id PK, task_id, agent_name, event_type, message, created_at)

Foreign keys (these are the ONLY real relationships -- draw exactly these, no others):
- tasks.parent_task_id -> tasks.id  (self-referential: a task can spawn child tasks)
- events.task_id -> tasks.id  (each event belongs to one task)

Important: agents has NO foreign key to anything. The tasks.assigned_to and tasks.created_by
columns are plain strings holding an agent's name, NOT foreign keys -- do not draw a relationship
between agents and tasks. agents stands on its own."""

# ===== JSON-ONLY INSTRUCTIONS (one per job) =====

# appended to aizen.md's system prompt so the reply is parseable JSON, not prose -- same trick
# prometheus/hermes use. one instruction per job since the two output shapes are unrelated.
WRITEUP_INSTRUCTION = (
    "\n\nYou are writing up a completed, reviewed change. Respond with JSON only, matching this shape: "
    '{"changelog_entry": string, "commit_message": string, "shareable_post": string or null, '
    '"summary_for_assist": string}. '
    "Set shareable_post to a blog/LinkedIn-style draft ONLY if the change is genuinely "
    "portfolio-worthy; otherwise set it to null -- that judgment is yours to make from the change "
    "itself. No prose outside the JSON object."
)

SCHEMA_DIAGRAM_INSTRUCTION = (
    "\n\nGenerate a Mermaid erDiagram of the described schema. Respond with JSON only, matching this "
    'shape: {"diagram": string}. '
    "The diagram value is a single Mermaid erDiagram as plain text (no ``` fences). Include every "
    "table, every column, and exactly the foreign-key relationships described -- no invented ones. "
    "No prose outside the JSON object."
)


class AizenAgent(BaseAgent):
    """writes about finished work, or draws the schema -- task_type picks which, an unknown one fails loudly"""

    def execute(self, payload: dict) -> dict:
        task_type = payload.get("task_type")

        if task_type == "writeup":
            user_content = self._build_writeup_prompt(payload)
            instruction = WRITEUP_INSTRUCTION
        elif task_type == "schema_diagram":
            user_content = f"Here is the schema to diagram:\n\n{SCHEMA_DESCRIPTION}"
            instruction = SCHEMA_DIAGRAM_INSTRUCTION
        else:
            # don't guess -- a missing/unknown task_type is a caller bug, surface it. BaseAgent.run()
            # catches this and lands the task failed with the message attached
            raise ValueError(
                f"Aizen got an unknown task_type: {task_type!r} -- expected 'writeup' or 'schema_diagram'"
            )

        return self._call_claude(instruction, user_content)

    def _build_writeup_prompt(self, payload: dict) -> str:
        """packs Asmoday's code + Khepri's verdict into one message -- verdict is freeform text until Khepri exists"""
        return (
            f"Code that was built:\n{payload.get('code', '')}\n\n"
            f"Review verdict:\n{payload.get('review_verdict', '')}\n\n"
            "Write up this change."
        )

    def _call_claude(self, instruction: str, user_content: str) -> dict:
        """one Claude call, same guarded extraction pattern every agent shares"""
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        response = client.messages.create(
            model=self.config.model,
            max_tokens=8192,  # thinking can eat a small budget whole before any text -- same reason as the others
            system=self.config.system_prompt + instruction,
            messages=[{"role": "user", "content": user_content}],
        )
        # thinking block can precede the text block, so content[0] isn't reliably the answer.
        # no text block at all means thinking ate the whole budget -- raise something debuggable
        try:
            raw_text = next(block.text for block in response.content if block.type == "text")
        except StopIteration:
            raise ValueError(
                f"Aizen's reply had no text block (stop_reason={response.stop_reason!r}) -- "
                "likely ran out of max_tokens while still thinking"
            ) from None
        try:
            return json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Aizen returned invalid JSON: {raw_text}") from exc
