def test_help_prints_available_params(capsys):
    import importlib.util
    import pathlib

    def _load_gpt_validator_module():
        root = pathlib.Path(__file__).resolve().parents[1]
        mod_path = root / "gpt_validator.py"
        spec = importlib.util.spec_from_file_location("gpt_validator", str(mod_path))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    gpt_validator = _load_gpt_validator_module()

    rc = gpt_validator.main(["--help"])

    captured = capsys.readouterr()
    assert rc == 0
    assert "Available params:" in captured.out
    assert "--help" in captured.out
