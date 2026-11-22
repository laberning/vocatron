"""Fixtures shared by the fast tests, and one thread per test worker."""

import os

import pytest

from fakes.songs import FakeWorld

# The fast tests run one worker process per core (pytest-xdist). Every worker that runs a tiny
# PyTorch model would otherwise start one OpenMP/MKL thread per core as well, and the oversubscribed
# threads sometimes stall a 0.2 s test past the 10 s timeout. One thread per worker is plenty for
# models of a few thousand weights. This must be set before PyTorch is imported: pytest loads this
# file before the test modules of this folder, in the main process and in every worker. It is set
# here and not in ``tests/conftest.py`` because child processes inherit the environment: the real
# engines of the slow tests and the benchmark (``tests/slow``, ``tests/bench``) keep all threads.
for _threads in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_threads, "1")


@pytest.fixture
def world() -> FakeWorld:
    """Engines made of fakes: clock, tags and an in-memory file store."""
    return FakeWorld()
