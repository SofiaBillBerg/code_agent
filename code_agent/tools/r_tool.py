# tools/r_tool.py
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Any

from langchain.tools import BaseTool
from pydantic import BaseModel, Field


class RScriptArgs(BaseModel):
    """Arguments for executing an R script."""

    code: str = Field(..., description = "The R code to be executed.")


class RScriptTool(BaseTool):
    """A tool for executing R code."""

    name: str = "r-script"
    description: str = ("Use this tool to execute R code. "
                        "Provide the R code as a string. The tool will return the standard output and standard error.")
    args_schema: type[BaseModel] = RScriptArgs

    def _run(self, code: str) -> str:
        """Executes the given R code and returns the output."""

        with tempfile.NamedTemporaryFile(
                mode = "w", suffix = ".R", delete = False
                ) as temp_file:
            temp_file.write(code)
            temp_file_path = temp_file.name

        try:
            result = subprocess.run(
                    ["Rscript", temp_file_path], capture_output = True, text = True, check = False,
                    # Do not raise exception on non-zero exit code
                    )

            output = ""
            if result.stdout:
                output += f"--- STDOUT ---\n{result.stdout}\n"
            if result.stderr:
                output += f"--- STDERR ---\n{result.stderr}\n"

            if not output:
                return "✅ R script executed with no output."

            return output

        except FileNotFoundError:
            return "❌ Error: 'Rscript' command not found. Please ensure R is installed and in your system's PATH."
        except Exception as e:
            return f"❌ An unexpected error occurred while running the R script: {e}"
        finally:
            # Clean up the temporary file
            Path(temp_file_path).unlink()

    async def _arun(self, **kwargs: Any) -> str:
        """Async version."""
        code = kwargs.get("code", "")
        return self._run(code)
