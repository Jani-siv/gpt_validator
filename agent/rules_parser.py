
"""Simple parser for .agent_rules.json to extract test runner info.

Provides a `RulesParser` class with `get_test_runner(project_type)` which
returns the `test_runner` dictionary for the requested project type or `None`.
"""
from pathlib import Path
import json
from typing import Any, Dict, Optional


class RulesParser:
    """Load and query an .agent_rules.json file.

    Example:
        rp = RulesParser()
        runner = rp.get_test_runner("zephyr")
    """

    def __init__(self, rules_path: Optional[Path | str] = None):
        script_dir = Path(__file__).parent
        self.rules_path = Path(rules_path) if rules_path else script_dir / ".agent_rules.json"
        if not self.rules_path.exists():
            raise FileNotFoundError(f"rules file not found: {self.rules_path}")
        self.rules = self.load_rules()

    def load_rules(self) -> Dict[str, Any]:
        with self.rules_path.open() as fh:
            return json.load(fh)

    def get_test_runner(self, project_type: str) -> Optional[Dict[str, Any]]:
        """Return the `test_runner` dict for `project_type`, or None if missing."""
        for pc in self.rules.get("project_configurations", []):
            if pc.get("project_type") == project_type:
                return pc.get("testframework", {}).get("test_runner")
        return None

    def get_test_builder(self, project_type: str) -> Optional[Dict[str, Any]]:
        """Return the `test_builder` dict for `project_type`, or None if missing."""
        for pc in self.rules.get("project_configurations", []):
            if pc.get("project_type") == project_type:
                return pc.get("testframework", {}).get("test_builder")
        return None


__all__ = ["RulesParser"]
