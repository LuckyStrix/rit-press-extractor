import pytest


@pytest.fixture(autouse=True)
def no_local_template(monkeypatch, tmp_path):
    """Tests never pick up this computer's own metadata template (local/ is not in git)."""
    monkeypatch.setattr("extractor.metadata.DEFAULT_TEMPLATE", tmp_path / "no-template.json")
