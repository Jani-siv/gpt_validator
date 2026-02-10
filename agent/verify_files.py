"""VerifyFiles helper using rules and git file inspection.

Provides a `VerifyFiles` class which is constructed with a
`RulesParser` instance and a `project_name`. It exposes small helper
methods that delegate to the functions in `git_file_handler.py` to
discover changed/created/added/modified files under a path derived from
the project's `file_rules` when possible.
"""
from __future__ import annotations

from pathlib import Path
import fnmatch
import sys
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
        self.error_files = []
        # perform initial verification
        self.verify()

    def verify(self):
        files =[]
        self.passed = False
        self.error_files = []
        allowed_paths = []
        files.append(self.get_created_files())
        files.append(self.get_added_files())
        files.append(self.get_modified_files())
        allowed_paths = self.get_allowed_path() or []
        allowed_paths.append(self.get_relative_agent_path())
        ignored_exts = self.get_ignored_file_extensions()
        #print(f"Allowed paths: {allowed_paths}")
        #print(f"Ignored extensions: {ignored_exts}")
        #print(f"Files to verify: {files}")
        self.error_files = []
        for file_list in files:
            for f in file_list:
                if f.startswith("./"):
                    f = f[2:]
                if allowed_paths and any(f.startswith(p) for p in allowed_paths):
                    continue
                if ignored_exts and any(fnmatch.fnmatch(f, pattern) for pattern in ignored_exts):
                    continue
                self.error_files.append(f)
                print(f"File '{f}' is not in allowed paths and does not have an ignored extension.")
                    
        if not self.error_files:
            self.passed = True


    def get_relative_agent_path(self) -> str:
        """ Return the agent path relative to repository root """
        agent_path = self.script_path
        repo_root = git_file_handler.get_repo_root(agent_path)
        if repo_root and agent_path.startswith(repo_root):
            relative_agent_path = agent_path[len(repo_root):].lstrip("/")
            return relative_agent_path
        return agent_path

    def is_passed(self) -> bool:
        """Return True if the verification passed, False otherwise."""
        if self.error_files:
            print("FAIL: Verification failed for the following files:")
            for f in self.error_files:
                print(f" - {f}")
        return self.passed

    def get_ignored_file_extensions(self) -> Optional[List[str]]:
        """Return the list of ignored file extensions, or None."""
        #print(f"File rules: {self.file_rules}")
        if self.file_rules and "ignored_file_extensions" in self.file_rules:
            exts = self.file_rules["ignored_file_extensions"]
            if isinstance(exts, list) and exts:
                return exts
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
