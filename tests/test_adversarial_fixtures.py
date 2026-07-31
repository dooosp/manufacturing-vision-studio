from __future__ import annotations

import hashlib
from pathlib import Path

FIXTURE_ROOT = Path(__file__).parents[1] / "fixtures" / "adversarial"


def test_checked_in_adversarial_fixture_bytes_are_stable() -> None:
    expected = {
        "corrupt-mask.png": "9b0cdf40521c8b9281fefb59b7df0413e5f917ee6809c67ea6912255421eddc6",
        "fake-signature.png": "032dd60b508fb439beaaff64ca22db4cd683d871f376515b72852c887c7b0457",
        "traversal-member-name.txt": (
            "762eecefc724c699190375ac32f57744b2fa39b76cf1c79df7961b532541ebae"
        ),
        "truncated.png": "b81b5b3ad3c0b73b5c9681cb868862ac74fca6f51df25643f7e186eb610aff1c",
        "unknown-pipeline.json": (
            "75adc3fd55921b6cc381d8abf0a5ae8b91a26c3727bfb5893b529928887b2015"
        ),
        "unsupported.pgm": "603c098feb47538e0cab87747559e553ee7530164c0e935d2dbc320a9c9cf223",
    }

    actual = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in FIXTURE_ROOT.iterdir()
        if path.name in expected
    }

    assert actual == expected


def test_adversarial_fixture_corpus_is_small_and_offline() -> None:
    fixture_files = [path for path in FIXTURE_ROOT.iterdir() if path.is_file()]

    assert fixture_files
    assert sum(path.stat().st_size for path in fixture_files) < 32_000
    assert not any(path.is_symlink() for path in fixture_files)
