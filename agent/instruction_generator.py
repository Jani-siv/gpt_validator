"""Simple instruction generator entrypoint.

Provides a `main()` which prints "hello world" and exits.
No command-line parameters.
"""


class InstructionGenerator:
    """Generator that holds an instruction list.

    Constructor takes no parameters. `instructions` is initialized
    with the single string 'add_function'.
    """

    def __init__(self):
        self.instructions = ["add_function"]

    def get_instructions(self):
        return list(self.instructions)


def main() -> int:
    print("hello world")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
