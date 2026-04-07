"""Thin wrapper around CAMEL's TerminalToolkit.

Aligns behavior with eigent's implementation:
- Default shell_exec timeout of 20 seconds (not 1800) so long-running
  processes like HTTP servers auto-convert to background sessions quickly.
- Auto-generate session IDs when not provided by the LLM.
- Return explicit success message for empty blocking output.
"""

import time

from camel.toolkits.terminal_toolkit import (
    TerminalToolkit as BaseTerminalToolkit,
)


class TerminalToolkit(BaseTerminalToolkit):

    def shell_exec(
        self,
        command: str,
        id: str | None = None,
        block: bool = True,
        timeout: float = 20.0,
    ) -> str:
        r"""Executes a shell command in blocking or non-blocking mode.

        Args:
            command (str): The shell command to execute.
            id (str, optional): A unique identifier for the command's session.
                If not provided, a unique ID will be automatically generated.
            block (bool, optional): Determines the execution mode.
                Defaults to True.
            timeout (float, optional): Timeout in seconds for blocking mode.
                Defaults to 20.0.

        Returns:
            str: The output of the command execution.
        """
        # Auto-generate ID if not provided
        if id is None:
            id = f"auto_{int(time.time() * 1000)}"

        result = super().shell_exec(
            id=id, command=command, block=block, timeout=timeout
        )

        # If the command executed successfully but returned empty output,
        # provide a clear success message to help the AI agent understand
        # that the command completed without error.
        if block and result == "":
            return "Command executed successfully (no output)."

        return result
