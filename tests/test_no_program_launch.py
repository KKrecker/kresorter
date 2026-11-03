"""kresorter launches no program, so it installs, starts and updates nothing (decision 0013).

Ollama is installed and started by the user [0013.2]. The guard reads the AST of ``src``:
no module imports what starts a process, or names a function of ``os`` that does. Tests may
start processes (crash helpers do); the product may not.
"""

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"

# Modules whose only purpose here would be to start another program, and their submodules.
FORBIDDEN_MODULES = frozenset({"subprocess", "pty", "multiprocessing"})
# Functions of ``os`` that run, replace or fork a process, by exact name or by prefix.
FORBIDDEN_OS_NAMES = frozenset({"system", "popen", "startfile", "fork", "forkpty"})
FORBIDDEN_OS_PREFIXES = ("exec", "spawn", "posix_spawn")


def _launches(name: str) -> bool:
    return name in FORBIDDEN_OS_NAMES or name.startswith(FORBIDDEN_OS_PREFIXES)


def _forbidden_module(name: str) -> bool:
    return name.split(".")[0] in FORBIDDEN_MODULES


def find_launches(source: str) -> list[int]:
    """Line numbers where ``source`` imports or names a way to start a program."""
    lines: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            lines.extend(node.lineno for alias in node.names if _forbidden_module(alias.name))
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            if _forbidden_module(node.module):
                lines.append(node.lineno)
            elif node.module == "os":
                lines.extend(node.lineno for alias in node.names if _launches(alias.name))
        elif (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "os"
            and _launches(node.attr)
        ):
            lines.append(node.lineno)
    return lines


@pytest.mark.parametrize(
    "snippet",
    [
        "import subprocess",
        "import subprocess as sp",
        "from subprocess import run",
        "import multiprocessing.connection",
        "from multiprocessing import Process",
        "import pty",
        "import os\nos.system('ollama pull llama3.2')",
        "import os\nos.popen('ollama serve')",
        "import os\nos.startfile('OllamaSetup.exe')",
        "import os\nos.execvp('ollama', ['ollama'])",
        "import os\nos.spawnlp(os.P_NOWAIT, 'ollama', 'ollama')",
        "import os\nos.posix_spawnp('ollama', ['ollama'], {})",
        "import os\npid = os.fork()",
        "import os\nrun = os.system",  # naming it is as good as calling it
        "from os import system",
        "from os import execv as replace_me",
    ],
)
def test_detector_flags_a_launch(snippet: str) -> None:
    assert find_launches(snippet) != []


def test_detector_allows_the_rest_of_os() -> None:
    source = "import os\nfrom os import fsync, replace\nos.stat('x')\nos.environ.get('HOME')"
    assert find_launches(source) == []


def test_detector_allows_unrelated_modules() -> None:
    assert find_launches("import subprocessing_notes\nfrom ptyx import y\nimport osx") == []


def test_no_module_of_kresorter_launches_a_program() -> None:
    offenders = [
        f"{path.relative_to(SRC).as_posix()}:{line}"
        for path in sorted(SRC.rglob("*.py"))
        for line in find_launches(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []
