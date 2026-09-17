"""FRMS — IoT 플랫폼 기능요구사항 관리 시스템.

이 패키지는 Python 3.11 이상을 요구한다. 버전이 낮으면 Pydantic이나 SQLAlchemy가
어노테이션을 평가하다 죽으면서 라이브러리 내부 트레이스백을 뱉는데, 원인이 무엇인지
알아보기 어렵다. 그래서 패키지 임포트 시점(가장 먼저 실행되는 지점)에서 먼저 막는다.
"""

from __future__ import annotations

import sys

#: 최소 요구 버전. ``app/enums.py`` 의 ``StrEnum`` 이 하한을 결정한다(3.11+).
#: 그 외 ``X | None`` 유니온 문법은 3.10+ 를 요구한다.
REQUIRED_PYTHON: tuple[int, int] = (3, 11)


def _format_version(version_info) -> str:
    return ".".join(str(part) for part in tuple(version_info)[:3])


def _check_python_version(version_info=None, executable: str | None = None) -> None:
    """실행 중인 Python이 요구 버전에 못 미치면 안내와 함께 즉시 실패한다.

    ``version_info`` 를 인자로 받는 이유는 실제로 3.11에서 돌고 있는 환경에서도
    이 가드 자체를 테스트할 수 있게 하기 위함이다.
    """
    version_info = sys.version_info if version_info is None else version_info
    if tuple(version_info)[:2] >= REQUIRED_PYTHON:
        return

    required = ".".join(str(part) for part in REQUIRED_PYTHON)
    current = _format_version(version_info)
    where = sys.executable if executable is None else executable

    raise RuntimeError(
        f"\n"
        f"FRMS는 Python {required} 이상이 필요합니다.\n"
        f"  현재 버전 : {current}\n"
        f"  인터프리터: {where}\n"
        f"\n"
        f"macOS 시스템 기본 Python은 3.9라서, 그대로 venv를 만들면 이 오류가 납니다.\n"
        f"\n"
        f"해결 방법 — 3.11 이상으로 venv를 다시 만드세요:\n"
        f"\n"
        f"    brew install python@3.12        # 또는 pyenv install 3.12\n"
        f"    rm -rf .venv\n"
        f"    python3.12 -m venv .venv\n"
        f"    source .venv/bin/activate\n"
        f"    python --version                # 3.12.x 인지 확인\n"
        f"    pip install -r requirements-dev.txt\n"
        f"\n"
        f"참고: 'eval_type_backport 를 설치하라'는 Pydantic 안내를 따라도 해결되지\n"
        f"않습니다. 그 오류만 넘어갈 뿐, 바로 다음 임포트인 StrEnum(3.11+)에서\n"
        f"ImportError가 납니다.\n"
    )


_check_python_version()
