"""Python 버전 가드 (app/__init__.py).

로컬에서 macOS 시스템 기본 Python(3.9)으로 venv를 만들면 Pydantic이 `str | None`
어노테이션을 평가하다 죽는다. 그 라이브러리 내부 트레이스백 대신 무엇을 해야 하는지
알려주는 것이 이 가드의 목적이므로, 메시지 내용까지 확인한다.
"""

from __future__ import annotations

import sys

import pytest

from app import REQUIRED_PYTHON, _check_python_version


@pytest.mark.parametrize("version", [(3, 9, 6), (3, 10, 13), (2, 7, 18)])
def test_rejects_versions_below_requirement(version):
    with pytest.raises(RuntimeError) as exc:
        _check_python_version(version, executable="/usr/bin/python3")

    message = str(exc.value)
    assert "3.11" in message  # 필요한 버전
    assert ".".join(str(p) for p in version) in message  # 현재 버전
    assert "/usr/bin/python3" in message  # 어느 인터프리터가 문제인지
    assert "python3.12 -m venv" in message  # 그대로 따라 할 수 있는 명령
    assert "eval_type_backport" in message  # 잘못된 길로 새지 않도록


@pytest.mark.parametrize("version", [(3, 11, 0), (3, 12, 4), (3, 13, 1), (4, 0, 0)])
def test_accepts_versions_at_or_above_requirement(version):
    _check_python_version(version)  # 예외가 나지 않아야 한다


def test_running_interpreter_satisfies_requirement():
    """지금 테스트를 돌리는 인터프리터도 당연히 요구 버전을 만족해야 한다."""
    assert sys.version_info[:2] >= REQUIRED_PYTHON


def test_guard_runs_on_package_import():
    """가드가 실제로 패키지 임포트 시점에 걸리는지.

    app/__init__.py 는 `python -m app.seed` 와 `uvicorn app.main:app` 양쪽에서
    가장 먼저 실행되므로, 여기서 막으면 라이브러리 트레이스백에 도달하지 않는다.
    """
    source = (
        __import__("pathlib").Path(__file__).parent.parent / "app" / "__init__.py"
    ).read_text(encoding="utf-8")
    # 모듈 최상단에서 호출되어야 한다. 함수 정의만 있고 호출이 없으면 무용지물이다.
    assert "\n_check_python_version()\n" in source
