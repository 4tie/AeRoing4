"""Tests for save_rendered_strategy and delete_rendered_strategy."""

from pathlib import Path

from backend.services.strategy.strategy_code_writer import (
    SaveResult,
    delete_rendered_strategy,
    save_rendered_strategy,
)

_VALID_SOURCE = "class MyStrategy(IStrategy):\n    pass\n"


def test_saves_new_rendered_strategy(tmp_path):
    base = tmp_path / "user_data" / "strategies" / "rendered"
    result = save_rendered_strategy(
        source=_VALID_SOURCE,
        strategy_name="MyStrategy",
        run_id="run_001",
        base_path=str(base),
    )
    assert result.errors == []
    assert result.path is not None
    assert result.path.exists()
    assert result.path.read_text(encoding="utf-8") == _VALID_SOURCE
    assert result.path.name == "MyStrategy.py"
    assert result.path.parent.name == "run_001"
    assert result.path.parent.parent == base.resolve()


def test_does_not_overwrite_existing_file(tmp_path):
    base = tmp_path / "rendered"
    result1 = save_rendered_strategy(
        source=_VALID_SOURCE,
        strategy_name="MyStrategy",
        run_id="run_001",
        base_path=str(base),
    )
    assert result1.errors == []
    assert result1.path.name == "MyStrategy.py"

    result2 = save_rendered_strategy(
        source=_VALID_SOURCE,
        strategy_name="MyStrategy",
        run_id="run_001",
        base_path=str(base),
    )
    assert result2.errors == []
    assert result2.path is not None
    assert result2.path.name == "MyStrategy_v1.py"
    assert result2.path.exists()
    assert len(result2.warnings) == 1
    assert "already existed" in result2.warnings[0]


def test_rejects_unsafe_names(tmp_path):
    base = tmp_path / "rendered"
    for bad_name in ["My/Strategy", "../Strategy", "My\\Strategy", "My\0Strategy"]:
        result = save_rendered_strategy(
            source=_VALID_SOURCE,
            strategy_name=bad_name,
            run_id="run_001",
            base_path=str(base),
        )
        assert result.path is None, f"Should reject strategy_name={bad_name!r}"
        assert len(result.errors) > 0


def test_rejects_run_id_path_traversal(tmp_path):
    base = tmp_path / "rendered"
    for bad_run in ["../evil", "a/b", "foo\\bar", "with\0byte"]:
        result = save_rendered_strategy(
            source=_VALID_SOURCE,
            strategy_name="MyStrategy",
            run_id=bad_run,
            base_path=str(base),
        )
        assert result.path is None, f"Should reject run_id={bad_run!r}"
        assert len(result.errors) > 0


def test_rejects_bad_python_syntax(tmp_path):
    base = tmp_path / "rendered"
    result = save_rendered_strategy(
        source="class MyStrategy(IStrategy):\n    break\n",
        strategy_name="MyStrategy",
        run_id="run_001",
        base_path=str(base),
    )
    assert result.path is None
    assert len(result.errors) > 0
    assert "syntax" in result.errors[0].lower()


def test_supports_candidate_label(tmp_path):
    base = tmp_path / "rendered"
    result = save_rendered_strategy(
        source=_VALID_SOURCE,
        strategy_name="MyStrategy",
        run_id="run_001",
        candidate_label="v2",
        base_path=str(base),
    )
    assert result.errors == []
    assert result.path is not None
    assert result.path.name == "MyStrategy_v2.py"


def test_deletes_file_and_empty_run_folder(tmp_path):
    base = tmp_path / "rendered"
    save = save_rendered_strategy(
        source=_VALID_SOURCE,
        strategy_name="MyStrategy",
        run_id="run_001",
        base_path=str(base),
    )
    assert save.path is not None
    assert save.path.exists()

    del_result = delete_rendered_strategy(
        path=str(save.path),
        base_path=str(base),
    )
    assert del_result.errors == []
    assert del_result.path == save.path.resolve()
    assert not save.path.exists()
    # Parent run dir should be removed since it's empty
    assert not save.path.parent.exists()


def test_delete_does_not_remove_base_path(tmp_path):
    base = tmp_path / "rendered"
    save = save_rendered_strategy(
        source=_VALID_SOURCE,
        strategy_name="MyStrategy",
        run_id="run_001",
        base_path=str(base),
    )
    assert save.path is not None

    # Create another file in the same run dir so parent stays non-empty
    other = save.path.parent / "OtherStrategy.py"
    other.write_text(_VALID_SOURCE)

    del_result = delete_rendered_strategy(
        path=str(save.path),
        base_path=str(base),
    )
    assert del_result.errors == []
    assert not save.path.exists()
    assert save.path.parent.exists()  # run dir still has OtherStrategy.py
    assert base.resolve().exists()


def test_rejects_empty_source(tmp_path):
    base = tmp_path / "rendered"
    for empty in ["", "   ", "\n\n"]:
        result = save_rendered_strategy(
            source=empty,
            strategy_name="MyStrategy",
            run_id="run_001",
            base_path=str(base),
        )
        assert result.path is None
        assert len(result.errors) > 0
        assert "empty" in result.errors[0].lower()


def test_rejects_delete_outside_base(tmp_path):
    base = tmp_path / "rendered"
    outside = tmp_path / "outside.py"
    outside.write_text(_VALID_SOURCE)

    result = delete_rendered_strategy(
        path=str(outside),
        base_path=str(base),
    )
    assert len(result.errors) > 0
    assert "outside" in result.errors[0].lower()


def test_rejects_delete_of_base_itself(tmp_path):
    base = tmp_path / "rendered"
    base.mkdir(parents=True)

    result = delete_rendered_strategy(
        path=str(base),
        base_path=str(base),
    )
    assert len(result.errors) > 0
    assert "base path" in result.errors[0].lower()
