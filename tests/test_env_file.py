from app.env_file import load_env_file


def test_loads_keys_without_overriding_existing_environment(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("# comment\n\nGOVFLOW_A=one\nGOVFLOW_B = \"two.with.dots\"\nGOVFLOW_C='x'\n", encoding="utf-8")
    monkeypatch.delenv("GOVFLOW_A", raising=False)
    monkeypatch.delenv("GOVFLOW_B", raising=False)
    monkeypatch.setenv("GOVFLOW_C", "already-set")
    loaded = load_env_file(env)
    import os
    assert os.environ["GOVFLOW_A"] == "one"
    assert os.environ["GOVFLOW_B"] == "two.with.dots"
    assert os.environ["GOVFLOW_C"] == "already-set"      # shell wins over file
    assert loaded == ["GOVFLOW_A", "GOVFLOW_B"]            # names only, never values


def test_missing_file_is_not_an_error(tmp_path):
    assert load_env_file(tmp_path / "nope.env") == []
