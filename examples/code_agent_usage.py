#!/usr/bin/env python3
"""
Example: Using CodeAgent with LLM Integration

This script demonstrates how to use the enhanced CodeAgent
with Ollama LLM integration for automated code and documentation generation.
"""

import os
import sys
from pathlib import Path
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool

from code_agent import (build_agent, create_from_template, create_llm, write_file, )
from code_agent.agents.base_agent import create_default_tools
from code_agent.main import load_config

# Add parent directory to path so imports work
sys.path.insert(0, str(Path(__file__).parent.parent))


# Dummy LLM for examples that don't require a real Ollama server
class DummyLLM(BaseChatModel):
    def _generate(
            self, messages: list[BaseMessage], stop: list[str] | None = None, **kwargs: Any
            ) -> ChatResult:
        return ChatResult(
                generations = [ChatGeneration(message = AIMessage(content = "Hello from DummyLLM"))]
                )

    def bind_tools(
            self, tools: list[BaseTool], **kwargs: Any
            ) -> Runnable[Any, BaseMessage]:
        return self

    @property
    def _llm_type(self) -> str:
        return "dummy-chat-model"


def example_basic_file_operations():
    """Example 1: Basic file operations without LLM."""
    print("\n" + "=" * 60)
    print("Example 1: Basic File Operations")
    print("=" * 60)

    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        # Create agent with default config
        # We need to create a dummy LLM and tools to build the agent runnable
        llm = DummyLLM()
        tools = create_default_tools(root_dir = str(tmpdir), llm = llm)
        build_agent(llm = llm, tools = tools)

        # Change to the temporary directory
        os.chdir(tmpdir)

        # Create a simple file using the utility function
        file_path = Path("example.txt")
        write_file(file_path, "Hello from CodeAgent!")
        print(f"✓ Created file: {file_path}")

        # Append to it
        # Note: append_file is a direct utility, not part of the agent_runnable
        with open(file_path, "a", encoding = "utf-8") as f:
            f.write("\nThis is additional content.")
        print("✓ Appended to file")

        # Create a template
        template_path = Path("doc.qmd")
        create_from_template(template_path, "Example Document")
        print(f"✓ Created template: {template_path}")

        # Show preview of an edit (if agent_runnable had a preview_edit method, which it doesn't directly)
        # This part of the example is conceptual for the old agent structure.
        # For LCEL, you'd invoke a tool for preview.
        print("\nPreview edit functionality would be invoked via a tool in LCEL.")


def example_llm_generation():
    """Example 2: Using LLM for content generation."""
    print("\n" + "=" * 60)
    print("Example 2: LLM Content Generation")
    print("=" * 60)
    print(
            "Note: This example requires a running Ollama server with the 'gpt-oss:20b-cloud' model."
            )

    try:
        cfg = load_config()
        llm = create_llm(cfg)  # Use real LLM here

        # We don't need a full agent graph just to invoke the LLM directly
        # The llm object itself is a Runnable

        # Generate content with LLM
        prompt = "Write a Python function to calculate the factorial of a number."
        print(f"Prompt: {prompt}")
        print("Generating...")

        response = llm.invoke(prompt)
        result = response.content if hasattr(response, "content") else str(response)
        print(f"✓ Generated content (first 200 chars):\n{result[:200]}...")
    except Exception as e:
        print(f"Error generating content: {e}")
        print("Make sure Ollama is running and the model is available")


def example_documentation_generation():
    """Example 3: Generate documentation."""
    print("\n" + "=" * 60)
    print("Example 3: Documentation Generation")
    print("=" * 60)

    import tempfile

    from code_agent.docs_generator import generate_quarto_docs

    with tempfile.TemporaryDirectory() as tmpdir:
        print(f"Generating docs in temporary directory: {tmpdir}")
        try:
            # Generate docs
            files = generate_quarto_docs(
                    output_dir = Path(tmpdir), overwrite = True, )
            print(f"✓ Generated {len(files)} documentation files:")
            for f in files:
                print(f"  - {Path(f).name}")
        except Exception as e:
            print(f"Error generating documentation: {e}")


def example_config_loading():
    """Example 4: Loading and using configuration."""
    print("\n" + "=" * 60)
    print("Example 4: Configuration Loading")
    print("=" * 60)

    from code_agent.main import create_llm, load_config

    try:
        # Load configuration
        cfg = load_config()
        print("✓ Configuration loaded:")
        print(f"  - Model: {cfg.get('ollama_model')}")
        print(f"  - Host: {cfg.get('ollama_host')}")
        print(f"  - Port: {cfg.get('ollama_port')}")
        print(f"  - Temperature: {cfg.get('temperature')}")
        print(f"  - Verbose: {cfg.get('verbose')}")

        # Create LLM instance
        print("\nCreating LLM instance...")
        llm = create_llm(cfg)
        print(f"✓ LLM created: {type(llm).__name__}")

    except Exception as e:
        print(f"Error loading configuration: {e}")


def example_article_evaluation():
    """Example 5: Article evaluation pipeline (conceptual)."""
    print("\n" + "=" * 60)
    print("Example 5: Article Evaluation Pipeline (Conceptual)")
    print("=" * 60)

    print(
            """
    The article evaluation pipeline works as follows:
    
    1. Load articles CSV with doc_id, text, summary, etc.
    2. Run PCC analysis to classify articles
    3. Call LLM (via llm_inference.generate_exclusion_reason) to generate reasons
    4. Save results to tmp_batch_results.csv
    5. Merge results back into articles using fill_exclusion_reasons.py
    
    Example commands:
    
        # Run full analysis
        export OLLAMA_MODEL=gemma2:2b
        export USE_LLM=1
        python run_full_analysis.py
    
        # Fill reasons into articles
        python fill_exclusion_reasons.py \\
            data/articles.csv \\
            output/tmp_batch_results.csv \\
            output/articles_with_reasons.csv
    
    Key features:
    - ✓ Automatic doc_id normalization
    - ✓ Retry logic with exponential backoff
    - ✓ Lock files to prevent duplicate processing
    - ✓ Progress logging
    - ✓ Graceful error handling
        """, )


def main():
    """Run all examples."""
    print("=" * 60)
    print("CodeAgent with LLM Integration - Examples")
    print("=" * 60)
    print("\nThese examples demonstrate the enhanced CodeAgent functionality.")
    print("Note: LLM examples use simulation mode to avoid requiring Ollama.\n")

    examples = [("Basic File Operations", example_basic_file_operations),
                ("LLM Content Generation", example_llm_generation),
                ("Documentation Generation", example_documentation_generation),
                ("Configuration Loading", example_config_loading), ("Article Evaluation", example_article_evaluation), ]

    for i, (name, func) in enumerate(examples, 1):
        try:
            func()
        except Exception as e:
            print(f"\n✗ Example {i} failed: {e}")
            import traceback

            traceback.print_exc()

    print("\n" + "=" * 60)
    print("Examples Complete!")
    print("=" * 60)
    print("\nFor more information, see CODE_AGENT_ENHANCEMENTS.qmd")


if __name__ == "__main__":
    main()
