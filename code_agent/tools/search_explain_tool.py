# tools/search_explain_tool.py
from __future__ import annotations

import json
import re

from pathlib import Path
from typing import Any, Literal

from langchain.tools import BaseTool
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, ConfigDict, Field

from .edit_file_tool import FileObject


class SearchExplainArgs(BaseModel):
    """Arguments schema for searching and explaining code.

    The search query can be a string or a regular expression.
    """

    search_query: str = Field(..., description="Term or regexp to search")
    max_results: int = Field(10, description="Maximum number of hits to return")


class SearchExplainTool(BaseTool):
    """Tool for searching code and generating comprehensive explanations.

    This tool searches for a specific string or pattern in local text files and
    summarizes the snippets (and their file names). It returns the summary as
    a string and a FileObject containing the first hit's path.
    """

    name: str = "search-explain"
    description: str = (
        "Search for a specific string or pattern in local text files and "
        "summarize the snippets (and their file names). Return the summary as "
        "a string and a FileObject containing the first hit's path."
    )
    response_format: Literal["content", "content_and_artifact"] = (
        "content_and_artifact"
    )
    args_schema: type[BaseModel] = SearchExplainArgs  # pyrefly: ignore[bad-override-mutable-attribute]

    llm: BaseChatModel
    root: Path

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def __init__(
        self,
        root_dir: Path,
        llm_instance: BaseChatModel,
        max_hits: int = 10,
        **kwargs: Any,
    ) -> None:
        """Initialize the SearchExplainTool with the given root directory.

        :param root_dir: The root directory to search in.
        :param llm_instance: The language model instance to use for summarization.
        :param max_hits: The maximum number of hits to return.
        :param kwargs: Additional keyword arguments.
        :return: None
        """
        super().__init__(
            root=Path(root_dir).expanduser().resolve(),
            llm=llm_instance,
            **kwargs,
        )

    def _read_ipynb_preview(self, path: Path) -> str:
        """Read the preview of an IPython notebook file.

        :param path: The path to the IPython notebook file.
        :return: The preview of the IPython notebook file.
        """
        try:
            nb = json.loads(path.read_text(encoding="utf-8"))
            cells = nb.get("cells", [])
            texts = []
            for c in cells:
                if (
                    c.get("cell_type") == "markdown"
                    or c.get("cell_type") == "code"
                ):
                    texts.append("".join(c.get("source", [])))
            return "\n".join(texts)[:1000]
        except Exception:
            return ""

    def _run(self, **kwargs: Any) -> tuple[str, FileObject]:
        """Run the tool to search for a specific string or pattern in local text files and summarize the snippets (and their file names).

        Return the summary as a string and a FileObject containing the first hit's path.


        :param kwargs : search query
        :return tuple[str, FileObject]
        """
        search_query: str = kwargs.get("search_query", "")
        max_results: int = kwargs.get("max_results", 10)

        # compile regex safely
        try:
            pattern = re.compile(search_query, re.IGNORECASE)
        except re.error:
            pattern = None

        hits = self._gather_hits(search_query, pattern, max_results)

        if not hits:
            return (
                "❌ No matches found.",
                FileObject(path=Path(), contents="", status="No hits"),
            )

        summary, first_hit = self._summarize_hits(hits)
        file_obj = FileObject(
            path=Path(str(first_hit["file_path"])).resolve(),
            contents="",
            status="Analyzed",
        )

        return summary, file_obj

    def _gather_hits(
        self, search_query: str, pattern: re.Pattern | None, max_results: int
    ) -> list[dict[str, str]]:
        """Gather all matching files and their snippets from the root directory.

        :param search_query : The search query to look for in files
        :param pattern : A compiled regex pattern to search for
        :param max_results : The maximum number of hits to return
        :return: A list of dictionaries, each containing the file path and snippet
        """
        hits = []
        for path in self.root.rglob("*"):
            if not self._is_candidate_path(path):
                continue

            content = self._read_file_content(path)
            if content is None:
                continue

            if pattern:
                matched = bool(pattern.search(content))
            else:
                matched = search_query.lower() in content.lower()

            if not matched:
                continue

            snippet = content[:600].replace("\n", " ")
            hits.append({"file_path": str(path), "snippet": snippet})
            if len(hits) >= max_results:
                break

        return hits

    def _is_candidate_path(self, path: Path) -> bool:
        """Return True if the path should be considered for searching.

        Skip virtualenvs, large folders, and non-files.

        :param path: The path to check.
        :return: True if the path should be considered for searching.
        """
        if any(
            part
            in {
                ".venv",
                "venv",
                "node_modules",
                "packrat",
                "archive",
                "output",
            }
            for part in path.parts
        ):
            return False
        if not path.is_file():
            return False
        try:
            if path.stat().st_size > 2000000:  # 2MB
                return False
        except Exception:
            return False
        return True

    def _read_file_content(self, path: Path) -> str | None:
        """Read file content with safe fallback for notebooks and read errors.

        :param path: The path to the file to read.
        :return: The file content as a string, or None if there was an error.
        """
        try:
            if path.suffix == ".ipynb":
                return self._read_ipynb_preview(path)
            return path.read_text(encoding="utf-8")
        except Exception:
            return None

    def _summarize_hits(self, hits: list[dict]) -> tuple[str, dict[Any, Any]]:
        """Summarize the hits using the LLM.

        :param hits: A list of dictionaries, each containing the file path and snippet
        :return: A summary of the hits
        """
        snippets = "\n\n".join(
            f"File: {hit['file_path']}\nSnippet:\n{hit['snippet']}"
            for hit in hits
        )

        summary_prompt = (
            "You are an expert code analyst. Provide a comprehensive analysis of the following code snippets. "
            "Include: 1) Overall purpose and functionality, 2) Key design patterns and architectural decisions, "
            "3) Potential issues or improvements, 4) Dependencies and relationships between files, "
            "5) Best practices being followed or violated. Be thorough and detailed.\n\n"
            + snippets
        )

        response = self.llm.invoke([HumanMessage(content=summary_prompt)])
        if hasattr(response, "content"):
            summary: str = str(response.content)
        else:
            summary = str(response)

        return summary, hits[0]

    async def _arun(self, **kwargs: Any) -> tuple[str, FileObject]:
        """Run the tool asynchronously.

        :param kwargs: The arguments to pass to the tool.
        :return: The result of the tool.
        """
        return self._run(**kwargs)
