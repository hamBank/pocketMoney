"""requirements.txt is guarded by a test, not left to CI's fresh venv (fleet spec CI-3, STK-5).

deploy.sh runs `pip install -r requirements.txt` into a long-lived venv (update_code). pip
counts an already-installed version that satisfies a requirement as done, so a floor lower
than what the code needs never upgrades the venv, and the deploy then dies later, in alembic
or on import, after the old process has stopped serving nothing but before the new one is
checked. CI builds a fresh venv every run and installs the newest allowed versions, so it
cannot see this. travelCompantion hit exactly that on 2026-10-28: prod stayed on sqlmodel
0.0.39 because the declared floor still allowed it.

So the declared ranges are tested here, as text, in the same pattern as travelCompantion's
tests/test_requirements_floor.py.
"""
from importlib.metadata import version
from pathlib import Path

from packaging.requirements import Requirement
from packaging.version import Version

REQUIREMENTS = Path(__file__).resolve().parent.parent / "requirements.txt"

# sqlmodel 0.0.48 made `datetime` fields timestamptz and rejects naive values; the models and
# the migrations assume exactly that (see the comment in requirements.txt and CLAUDE.md's
# incident rules). Raise this, and the floor, in the same commit as any code that needs more.
MIN_SQLMODEL = Version("0.0.48")

# Deliberately uncapped, with the reason. Anything not listed here must have an upper bound.
UNCAPPED_OK = {
    "tzdata": "date-versioned IANA data (2024.1, 2025.2, ...): there is no breaking major to cap below",
}


def requirements() -> dict[str, Requirement]:
    found = {}
    for line in REQUIREMENTS.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            req = Requirement(line)
            found[req.name.lower()] = req
    return found


def has_floor(req: Requirement) -> bool:
    return any(spec.operator in (">=", ">", "==", "~=") for spec in req.specifier)


def has_cap(req: Requirement) -> bool:
    return any(spec.operator in ("<", "<=", "==", "~=") for spec in req.specifier)


def test_every_dependency_declares_a_floor():
    """Without a floor, any old version already in the venv counts as satisfying it."""
    missing = sorted(name for name, req in requirements().items() if not has_floor(req))
    assert not missing, f"no lower bound in requirements.txt for: {missing}"


def test_every_dependency_is_capped_except_the_stated_exceptions():
    """deploy.sh installs whatever the range allows on every push, so an open top end means
    the next deploy can pull in an untested major. Equality (not subset) so that an exception
    that is no longer needed has to be removed from UNCAPPED_OK."""
    uncapped = {name for name, req in requirements().items() if not has_cap(req)}
    assert uncapped == set(UNCAPPED_OK), (
        f"uncapped in requirements.txt: {sorted(uncapped)}; allowed to be uncapped: {sorted(UNCAPPED_OK)}"
    )


def test_sqlmodel_floor_excludes_versions_the_code_cannot_run_on():
    spec = requirements()["sqlmodel"].specifier
    for old in ("0.0.19", "0.0.39", "0.0.44", "0.0.47"):
        assert not spec.contains(Version(old)), (
            f"requirements.txt allows sqlmodel {old}: an already-installed older venv would "
            f"never be upgraded. The floor must be >= {MIN_SQLMODEL}."
        )
    assert spec.contains(MIN_SQLMODEL), "the floor must still allow the release the code needs"


def test_sqlmodel_is_capped_below_the_next_untested_release():
    """Pre-1.0 sqlmodel can change datetime handling in any release (0.0.48 did)."""
    spec = requirements()["sqlmodel"].specifier
    for newer in ("0.0.49", "0.1.0", "1.0.0"):
        assert not spec.contains(Version(newer)), (
            f"requirements.txt allows sqlmodel {newer}, which this suite has not run on; "
            f"run the suite on it, then raise the cap on purpose."
        )


def test_the_declared_sqlmodel_range_is_the_one_ci_actually_runs():
    """CI's fresh venv installs the newest release the range allows; if that is outside the
    range, the range or the environment has drifted."""
    assert version("sqlmodel") in requirements()["sqlmodel"].specifier
