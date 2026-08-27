"""CLI Live Demo: A small self-contained demo of the berg agents."""


def greet(name: str) -> str:
    """Greet a user by name.

    Args:
        name: The person's name to greet.

    Returns:
        A greeting message string.
    """
    return f"Hello, {name}! Welcome to the berg agents demo."


def main():
    """Run the CLI live demo."""
    print(greet("Developer"))
    print("\nThis is a self-contained Python script demonstrating:")
    print("- Type hints")
    print("- Docstrings")
    print("- A simple function with args/return value")
    print("- Standard main guard pattern")


if __name__ == "__main__":
    main()
