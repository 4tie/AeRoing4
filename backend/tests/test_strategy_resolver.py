import pytest
from pathlib import Path
from unittest.mock import MagicMock
from backend.services.ai.strategy_resolver import (
    resolve_strategy,
    StrategyNotFoundError,
    AmbiguousStrategyError,
    _extract_class_name,
)


@pytest.fixture
def mock_strategies_dir(tmp_path):
    strat_dir = tmp_path / "strategies"
    strat_dir.mkdir()
    
    # Create AIStrategy.py with a matching class name
    ai_strat = strat_dir / "AIStrategy.py"
    ai_strat.write_text("class AIStrategy:\n    pass")
    
    # Create a strategy where file name != class name
    weird_strat = strat_dir / "my_cool_strat.py"
    weird_strat.write_text("class AwesomeStrategy:\n    pass")
    
    # Create a completely empty file
    empty_strat = strat_dir / "EmptyStrat.py"
    empty_strat.write_text("")
    
    return strat_dir


def test_resolves_by_exact_stem(mock_strategies_dir):
    res = resolve_strategy("AIStrategy", mock_strategies_dir)
    assert res.stem == "AIStrategy"
    assert res.class_name == "AIStrategy"
    assert res.py_path == mock_strategies_dir / "AIStrategy.py"


def test_resolves_case_insensitive(mock_strategies_dir):
    res = resolve_strategy("aistrategy", mock_strategies_dir)
    assert res.stem == "AIStrategy"
    assert res.py_path == mock_strategies_dir / "AIStrategy.py"


def test_resolves_with_extension(mock_strategies_dir):
    res = resolve_strategy("AIStrategy.py", mock_strategies_dir)
    assert res.stem == "AIStrategy"
    assert res.py_path == mock_strategies_dir / "AIStrategy.py"


def test_resolves_with_different_class_name(mock_strategies_dir):
    res = resolve_strategy("my_cool_strat", mock_strategies_dir)
    assert res.stem == "my_cool_strat"
    assert res.class_name == "AwesomeStrategy"
    assert res.py_path == mock_strategies_dir / "my_cool_strat.py"


def test_fallback_to_stem_when_no_class_found(mock_strategies_dir):
    res = resolve_strategy("EmptyStrat", mock_strategies_dir)
    assert res.stem == "EmptyStrat"
    assert res.class_name == "EmptyStrat"


def test_not_found_error(mock_strategies_dir):
    with pytest.raises(StrategyNotFoundError):
        resolve_strategy("DoesNotExist", mock_strategies_dir)


def test_ambiguity_error(tmp_path, monkeypatch):
    strat_dir = tmp_path / "strategies"
    
    mock_path1 = MagicMock()
    mock_path1.stem = "TestStrat"
    mock_path1.name = "TestStrat.py"
    mock_path1.is_file.return_value = True
    mock_path1.read_text.return_value = "class TestStrat:\n    pass"

    mock_path2 = MagicMock()
    mock_path2.stem = "teststrat"
    mock_path2.name = "teststrat.py"
    mock_path2.is_file.return_value = True
    mock_path2.read_text.return_value = "class teststrat:\n    pass"

    monkeypatch.setattr(Path, "glob", lambda self, pattern: iter([mock_path1, mock_path2]))
    
    # Resolving exact match should work and pick the right one
    res1 = resolve_strategy("TestStrat", strat_dir)
    assert res1.py_path.name == "TestStrat.py"
    
    res2 = resolve_strategy("teststrat", strat_dir)
    assert res2.py_path.name == "teststrat.py"
    
    # Resolving with a third case should throw ambiguous error
    with pytest.raises(AmbiguousStrategyError) as exc:
        resolve_strategy("TESTSTRAT", strat_dir)
    
    assert "ambiguous" in str(exc.value)
    assert "TestStrat.py" in str(exc.value)
    assert "teststrat.py" in str(exc.value)
