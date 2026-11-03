"""The licence, and what the wheel and the sdist say about Kresorter (decision 0015, items 5-7).

The licence is MIT, held by KKrecker, in the repository and in both artifacts, beside Lucide's
licence for the icons; neither artifact carries anything of Qt, which pip installs from its own
wheels. The metadata names the author without an e-mail address, the repository, and only the
systems Kresorter is built and tested for.
"""

import re
import tomllib
from pathlib import Path

from support.artifacts import Built, metadata, sdist_files, wheel_files
from support.markdown import section

ROOT = Path(__file__).resolve().parents[1]
LICENCES = ["LICENSE", "src/kresorter/ui/icons/LICENSE"]
REPOSITORY = "https://github.com/KKrecker/kresorter"
PYTHONS = ["3.11", "3.12", "3.13", "3.14"]
CLASSIFIERS = [
    "Development Status :: 3 - Alpha",
    "Environment :: Console",
    "Environment :: Win32 (MS Windows)",
    "Environment :: X11 Applications :: Qt",
    "Intended Audience :: End Users/Desktop",
    "Operating System :: Microsoft :: Windows",
    "Operating System :: POSIX :: Linux",
    "Programming Language :: Python :: 3 :: Only",
    *(f"Programming Language :: Python :: {version}" for version in PYTHONS),
    "Topic :: System :: Filesystems",
    "Topic :: Utilities",
    "Typing :: Typed",
]
QT = re.compile(r"pyside6|shiboken6|(lib)?qt\d", re.IGNORECASE)


def project() -> dict[str, object]:
    found = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert isinstance(found, dict)
    return found


# --- the licence [0015.5] ------------------------------------------------------------------------


def test_the_licence_is_mit_held_by_kkrecker() -> None:
    # [0015.5]
    text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert text.splitlines()[:3] == ["MIT License", "", "Copyright (c) 2026 KKrecker"]
    assert "Permission is hereby granted, free of charge, to any person obtaining a copy" in text
    assert 'THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND' in text


def test_pyproject_declares_it_as_pep_639_says() -> None:
    # [0015.5] an SPDX expression and the files, no table
    assert project()["license"] == "MIT"
    assert project()["license-files"] == LICENCES


def test_the_wheel_and_the_sdist_carry_both_licences(built: Built) -> None:
    # [0015.5]
    licences = [
        name.split(".dist-info/licenses/", 1)[1]
        for name in wheel_files(built.wheel)
        if ".dist-info/licenses/" in name
    ]
    assert sorted(licences) == LICENCES
    assert set(LICENCES) <= set(sdist_files(built.sdist))
    assert metadata(built.wheel).get_all("License-File") == LICENCES
    assert metadata(built.wheel)["License-Expression"] == "MIT"


def test_the_readme_names_both_licences() -> None:
    # [0015.5] MIT for Kresorter, ISC for Lucide's icons
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    text = " ".join(section(readme, "License"))
    assert "MIT" in text
    assert "[`LICENSE`](LICENSE)" in text
    assert "ISC" in text
    assert "Lucide" in text
    assert "[`src/kresorter/ui/icons/LICENSE`](src/kresorter/ui/icons/LICENSE)" in text


# --- nothing of Qt [0015.6] ----------------------------------------------------------------------


def test_neither_artifact_carries_anything_of_qt(built: Built) -> None:
    # [0015.6]
    names = [*wheel_files(built.wheel), *sdist_files(built.sdist)]
    assert [name for name in names if QT.search(name)] == []


def test_qt_comes_from_its_own_wheels_with_the_extra(built: Built) -> None:
    # [0015.6] the core requires nothing; PySide6 only with an extra
    required = metadata(built.wheel).get_all("Requires-Dist") or []
    qt = [line for line in required if line.lower().startswith("pyside6")]
    assert "pyside6-essentials<7,>=6.8; extra == 'ui'" in qt
    assert all("extra ==" in line for line in required)


# --- the metadata [0015.7] -----------------------------------------------------------------------


def test_the_author_without_an_e_mail_address(built: Built) -> None:
    # [0015.7]
    found = metadata(built.wheel)
    assert project()["authors"] == [{"name": "KKrecker"}]
    assert found["Author"] == "KKrecker"
    assert found["Author-email"] is None
    assert found["Maintainer-email"] is None


def test_the_urls_are_the_repository_s(built: Built) -> None:
    # [0015.7]
    assert metadata(built.wheel).get_all("Project-URL") == [
        f"Homepage, {REPOSITORY}",
        f"Source, {REPOSITORY}",
        f"Issues, {REPOSITORY}/issues",
        f"Changelog, {REPOSITORY}/blob/main/CHANGELOG.md",
    ]


def test_the_classifiers_and_keywords(built: Built) -> None:
    # [0015.7] Windows and Linux, no macOS, no licence classifier
    found = metadata(built.wheel)
    assert found.get_all("Classifier") == sorted(CLASSIFIERS)
    assert not any(c.startswith("License ::") for c in CLASSIFIERS)
    assert found["Keywords"]
    assert found["Requires-Python"] == ">=3.11"


def test_the_pythons_are_those_of_ci() -> None:
    # [0015.7] the classifiers, requires-python and CI's matrix agree
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    matrix = "python-version: [" + ", ".join(f'"{v}"' for v in PYTHONS) + "]"
    assert matrix in workflow
    assert project()["requires-python"] == f">={PYTHONS[0]}"
