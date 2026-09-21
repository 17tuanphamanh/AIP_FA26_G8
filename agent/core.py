"""The agent loop: hand a question to Claude, let it call tools until it is done.

Uses the SDK's tool runner (client.beta.messages.tool_runner) — it handles the
"call API -> run tool -> feed the result back -> call again" cycle for us.
The default model claude-opus-5 has adaptive thinking on already; nothing to declare.
"""

import anthropic

from agent.config import Config, read_prompt
from agent.tools import TOOLS


class Agent:
    def __init__(self, config: Config | None = None, tools: list | None = None):
        self.config = config or Config.from_env()
        self.tools = TOOLS if tools is None else tools
        self.system = read_prompt("system.md")
        self.client = anthropic.Anthropic(api_key=self.config.api_key)
        # Conversation history, kept so the agent remembers earlier turns.
        self.history: list[dict] = []

    def ask(self, question: str, show_progress: bool = False) -> str:
        """Send one question, return Claude's answer as plain text."""
        self.history.append({"role": "user", "content": question})

        runner = self.client.beta.messages.tool_runner(
            model=self.config.model,
            max_tokens=self.config.max_tokens,
            system=self.system,
            tools=self.tools,
            messages=self.history,
            max_iterations=self.config.max_steps,
        )

        last = None
        for message in runner:
            last = message
            self.history.append({"role": "assistant", "content": message.content})
            tool_result = runner.generate_tool_call_response()
            if tool_result is not None:
                self.history.append(tool_result)
            if show_progress:
                for block in message.content:
                    if block.type == "tool_use":
                        print(f"  [tool] {block.name}({block.input})")

        if last is None:
            return "(không nhận được phản hồi)"
        return extract_text(last)


def extract_text(message) -> str:
    """Join the text blocks of a message into a single string."""
    return "\n".join(
        block.text for block in message.content if block.type == "text"
    ).strip()
