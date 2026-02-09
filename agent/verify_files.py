"""VerifyFiles helper using rules and git file inspection.

Provides a `VerifyFiles` class which is constructed with a
`RulesParser` instance and a `project_name`. It exposes small helper
methods that delegate to the functions in `git_file_handler.py` to
discover changed/created/added/modified files under a path derived from
the project's `file_rules` when possible.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from rules_parser import RulesParser
import git_file_handler


class VerifyFiles:
    """Inspect repository files for a project using provided rules.

    The class keeps a reference to the `RulesParser` used to obtain
    project-specific `file_rules`. When a search path is not provided
    to the query methods, the first entry in `allowed_to_modify` (if
    present) will be used as a sensible default.
    """

    def __init__(self, rules_parser: RulesParser, project_name: str):
        """Create a new VerifyFiles instance.

        Args:
            rules_parser: An initialized `RulesParser` instance.
            project_name: The project type/name as found in the rules.
        """
        if not isinstance(rules_parser, RulesParser):
            raise TypeError("rules_parser must be a RulesParser instance")

        self.rules_parser = rules_parser
        self.project_name = project_name
        # directory containing this script; used as default repo path
        self.script_path = str(Path(__file__).parent)
        # load file_rules for the project (may be None)
        self.file_rules: Optional[Dict[str, Any]] = rules_parser.get_file_rules(project_name)
        self.passed = False
        # perform initial verification
        self.verify()

    def verify(self):
        files =[]
        files.append(self.get_created_files())
        files.append(self.get_added_files())
        files.append(self.get_modified_files())
        allowed_paths = self.rules_parser.get_allowed_path()
        allowed_exts = self.rules_parser.get_allowed_extensions()
        for file_list in files:
            for f in file_list:
                if allowed_paths and not any(f.startswith(p) for p in allowed_paths):
                    print(f"FAIL: File {f} is not under any allowed path {allowed_paths}")
                    self.passed = False
                    return
                if allowed_exts and not any(f.endswith(ext) for ext in allowed_exts):
                    print(f"FAIL: File {f} does not have an allowed extension {allowed_exts}")
                    self.passed = False
                    return
        self.passed = True

    def is_passed(self) -> bool:
        """Return True if the verification passed, False otherwise."""
        return self.passed

    def get_allowed_extensions(self) -> Optional[List[str]]:
        """Return the list of allowed file extensions for includes, or None."""
        if self.file_rules and "not_allowed_include_extensions" in self.file_rules:
            return self.file_rules["not_allowed_include_extensions"]
        return None

    def get_allowed_path(self) -> Optional[list[str]]:
        """Return the first entry in `allowed_to_modify` for the project, or None."""
        if self.file_rules and "allowed_to_modify" in self.file_rules:
            allowed = self.file_rules["allowed_to_modify"]
            if isinstance(allowed, list) and allowed:
                return allowed
        return None

    def get_created_files(self) -> List[str]:
        """ Get created files from git using git_file_handler"""
        return git_file_handler.get_created_files(self.script_path)
        

    def get_added_files(self) -> List[str]:
        """Return files staged as added under `path`."""
        return git_file_handler.get_added_files(self.script_path)


    def get_modified_files(self) -> List[str]:
        """Return files modified (staged or unstaged) under `path`."""
        return git_file_handler.get_modified_files(self.script_path)



__all__ = ["VerifyFiles"]
