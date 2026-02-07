
"""Simple parser for .agent_rules.json to extract test runner info.

Provides a `RulesParser` class with `get_test_runner(project_type)` which
returns the `test_runner` dictionary for the requested project type or `None`.
"""
from pathlib import Path
import json
import os
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
        if not self.rules_path.is_file():
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

    def load_project_config(self, project_type: Optional[str]) -> dict:
        """Return a project configuration from the already-loaded rules.

        Uses `self.rules` loaded during initialization. Raises ValueError
        or json.JSONDecodeError on error. The FileNotFoundError will have
        been raised during construction if the rules file was missing.
        """
        rules = self.rules
        projects = rules.get('project_configurations', [])
        if not projects:
            raise ValueError('No project_configurations found in .agent_rules.json')

        if isinstance(projects, dict):
            if 'project_type' in projects:
                project_entries = [projects]
            else:
                project_entries = []
                for key, value in projects.items():
                    if isinstance(value, dict):
                        entry = dict(value)
                        entry.setdefault('project_type', key)
                        project_entries.append(entry)
        elif isinstance(projects, list):
            project_entries = [p for p in projects if isinstance(p, dict)]
        else:
            project_entries = []
        if not project_entries:
            raise ValueError('project_configurations must contain objects with project_type')

        if project_type is None:
            if len(project_entries) == 1:
                return project_entries[0]
            raise ValueError('Multiple project_configurations found; use --project to select one')

        project_key = project_type.lower()
        for project in project_entries:
            candidate = str(project.get('project_type', '')).lower()
            if candidate == project_key:
                return project

        available = ', '.join(sorted({str(p.get('project_type', '')).lower() for p in project_entries if p.get('project_type')}))
        raise ValueError(f"Unknown project type '{project_type}'. Available: {available}")


__all__ = ["RulesParser"]
