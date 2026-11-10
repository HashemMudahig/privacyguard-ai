"""Shared pytest fixtures.

The real challenge dataset lives in a read-only sibling repository. Integration
tests skip with a clear message when that dataset is unavailable.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from privacyguard.config import PROJECT_ROOT, Settings
from privacyguard.identity.index import IdentityIndex
from privacyguard.identity.resolver import IdentityResolver
from privacyguard.io.bundle import load_dataset


@pytest.fixture(scope="session")
def settings() -> Settings:
    resolved = Settings.from_environment()
    if not resolved.dataset_dir.is_dir():
        pytest.skip(
            f"Challenge dataset not found at {resolved.dataset_dir}; "
            "set PG_DATASET_DIR to run integration tests"
        )
    return resolved


@pytest.fixture(scope="session")
def bundle(settings: Settings):
    return load_dataset(settings)


@pytest.fixture(scope="session")
def identity_index(bundle):
    return IdentityIndex(bundle.identities, bundle.audit_events)


@pytest.fixture(scope="session")
def resolver(identity_index: IdentityIndex) -> IdentityResolver:
    return IdentityResolver(identity_index)


@pytest.fixture()
def project_tmp_path() -> Path:
    """A temporary directory inside the project, never outside it."""
    path = PROJECT_ROOT / ".pytest_tmp" / uuid.uuid4().hex
    path.mkdir(parents=True)
    try:
        yield path
    finally:
        for child in sorted(path.rglob("*"), reverse=True):
            if child.is_file():
                child.unlink()
            elif child.is_dir():
                child.rmdir()
        path.rmdir()
        parent = path.parent
        if parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
