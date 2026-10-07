"""Every tool follows the tool standard (docs/tool_standard.md), and no tool keeps a copy of the library.

Run:  test.bat core   (in the toolkit's folder)
"""
import hashlib
import json
import re
import unittest
from pathlib import Path

TOOLKIT_DIR = Path(__file__).resolve().parents[2]
TOOLS = sorted(p for p in (TOOLKIT_DIR / "tools").iterdir() if p.is_dir())
SECTIONS = ["Install", "Use", "Input", "Output", "Settings", "If something goes wrong", "Uninstall", "Files"]


class Layout(unittest.TestCase):
    def test_there_are_tools(self):
        self.assertGreaterEqual(len(TOOLS), 4)

    def test_every_tool_has_the_standard_parts(self):
        for tool in TOOLS:
            with self.subTest(tool=tool.name):
                self.assertRegex(tool.name, r"^[a-z][a-z0-9_]*$", "a tool's folder is lower case, words joined by _")
                for part in ("README.md", "install.bat", "uninstall.bat", "config/default.json", "input/README.md",
                             "output/README.md"):
                    self.assertTrue((tool / part).is_file(), f"{tool.name}/{part} is missing")
                commands = [b for b in tool.glob("*.bat") if b.name not in ("install.bat", "uninstall.bat")]
                self.assertEqual(len(commands), 1, f"{tool.name}: one command .bat, found {commands}")
                bat = commands[0].read_text(encoding="utf-8")
                self.assertIn("core\\run.cmd", bat)
                name = commands[0].stem  # <command>.bat runs <command>\cli.py
                self.assertRegex(name, r"^[a-z][a-z0-9_]*$", f"{tool.name}: the command is lower case, words joined by _")
                self.assertTrue((tool / name / "cli.py").is_file(), f"{tool.name}: no package {name}\\ with cli.py")
                self.assertIn(f'set "TOOL_MODULE={name}.cli"', bat, f"{tool.name}: {name}.bat runs {name}.cli")
                self.assertTrue(list((tool / "tests").glob("test_*.py")), f"{tool.name} has no tests")
                json.loads((tool / "config" / "default.json").read_text(encoding="utf-8"))

    def test_readme_sections_in_order(self):
        for tool in TOOLS:
            with self.subTest(tool=tool.name):
                text = (tool / "README.md").read_text(encoding="utf-8")
                self.assertTrue(text.startswith("# "), "a README starts with its title")
                headings = re.findall(r"(?m)^## (.+?)\s*$", text)
                found = [h for h in headings if h in SECTIONS]
                self.assertEqual(found, SECTIONS, f"{tool.name}: the standard sections, in order")

    def test_the_toolkit_readme_lists_every_tool(self):
        text = (TOOLKIT_DIR / "README.md").read_text(encoding="utf-8")
        for tool in TOOLS:
            self.assertIn(f"(tools/{tool.name}/README.md)", text, f"{tool.name} is not in the toolkit's README")

    def test_scripts_have_windows_line_endings(self):
        for p in [*TOOLKIT_DIR.glob("*.bat"), *(TOOLKIT_DIR / "core").glob("*.cmd"), *(TOOLKIT_DIR / "tools").glob("*/*.bat")]:
            data = p.read_bytes()
            self.assertEqual(data.count(b"\n"), data.count(b"\r\n"), f"{p.relative_to(TOOLKIT_DIR)}: use CRLF")


class NoCopies(unittest.TestCase):
    """Shared code lives in core\\ing_core only: a module copied into a tool is refused (change the library)."""

    def test_no_tool_module_is_a_copy_of_the_library(self):
        def digest(p):
            return hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest()

        def code(p):  # boilerplate of a few lines (__main__.py) is the same everywhere
            return p.read_bytes().count(b"\n") > 10
        library = {digest(p): p for p in (TOOLKIT_DIR / "core" / "ing_core").rglob("*.py") if code(p)}
        for p in (TOOLKIT_DIR / "tools").rglob("*.py"):
            if "input" not in p.parts and "output" not in p.parts and code(p) and digest(p) in library:
                self.fail(f"{p.relative_to(TOOLKIT_DIR)} is a copy of {library[digest(p)].relative_to(TOOLKIT_DIR)}")


if __name__ == "__main__":
    unittest.main()
