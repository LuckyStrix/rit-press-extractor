"""The one-command launcher (run.py): what it checks, without installing anything."""
import importlib.util
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("run_launcher", Path(__file__).resolve().parent.parent / "run.py")
run = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(run)


def test_models_are_reported_missing_in_an_empty_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(run, "ROOT", tmp_path)
    assert not run.models_present()
    (tmp_path / "models" / "doctr").mkdir(parents=True)
    for f in run.MODEL_FILES:
        (tmp_path / f).write_bytes(b"x")
    assert not run.models_present()  # docTR's folder is still empty
    (tmp_path / "models" / "doctr" / "m.pt").write_bytes(b"x")
    assert run.models_present()


def test_the_launcher_needs_only_the_standard_library():
    import ast

    stdlib = set(__import__("sys").stdlib_module_names)
    tree = ast.parse(Path(run.__file__).read_text())
    imported = {n.names[0].name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import)} | {
        n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert imported <= stdlib, imported - stdlib


def test_windows_batch_file_has_windows_line_endings_and_no_unix_paths():
    raw = (Path(run.__file__).parent / "run.bat").read_bytes()
    assert b"\r\n" in raw and b"/dev/null" not in raw and b">nul" in raw
