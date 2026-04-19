import re
import unittest
from collections import defaultdict
from pathlib import Path


REPO_ROOT = Path(__file__).parent
CLAWD_SKILLS = REPO_ROOT.parent / "clawd" / "skills"
MCP_FILES = [REPO_ROOT / "server.py", *sorted(REPO_ROOT.glob("mcp_*_tools.py"))]


class TestToolContracts(unittest.TestCase):
    def test_mcp_tool_names_are_unique(self):
        registrations = defaultdict(list)
        pattern = re.compile(r"@mcp\.tool\(\)\s*\n\s*def\s+([a-zA-Z0-9_]+)\s*\(")

        for path in MCP_FILES:
            for match in pattern.finditer(path.read_text(errors="ignore")):
                registrations[match.group(1)].append(path.name)

        duplicates = {name: files for name, files in registrations.items() if len(files) > 1}
        self.assertEqual({}, duplicates)

    def test_skill_tool_references_exist_in_mcp(self):
        if not CLAWD_SKILLS.exists():
            self.skipTest("Clawd skills tree not present next to robin repo")

        code_text = "\n".join(path.read_text(errors="ignore") for path in MCP_FILES)
        defined = set(re.findall(r"def\s+((?:get|execute|cancel|record|backtest)_[a-zA-Z0-9_]+)\s*\(", code_text))

        skill_text = "\n".join(path.read_text(errors="ignore") for path in CLAWD_SKILLS.rglob("*.md"))
        referenced = set(
            re.findall(r"\b((?:get|execute|cancel|record|backtest)_[a-zA-Z0-9_]+)\s*\(", skill_text)
        )

        missing = sorted(name for name in referenced if name not in defined)
        self.assertEqual([], missing)


if __name__ == "__main__":
    unittest.main()
