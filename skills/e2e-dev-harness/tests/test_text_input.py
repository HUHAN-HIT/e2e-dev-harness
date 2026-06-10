"""Text-input integrity for start: file-sourced text + mojibake guard.

Root cause this protects against: on Windows/git-bash, non-ASCII argv is
decoded with the console codepage (e.g. cp936), which is *lossy* for UTF-8
bytes and yields U+FFFD replacement chars. The corruption is irreversible
in-process, so it must be (a) avoided via a UTF-8 file channel and (b)
detected and rejected loudly instead of silently mis-tiering to minimal.
"""
from __future__ import annotations

import pytest

from e2e_harness.core import text_input


def test_clean_chinese_is_not_corrupted():
    assert text_input.is_corrupted("在支付/退款/转账/分账做风控") is False


def test_replacement_char_is_corrupted():
    # what cp936-decoded UTF-8 Chinese actually looks like
    assert text_input.is_corrupted("֧���˿����") is True


def test_read_inline_value_passthrough():
    assert text_input.read_text_arg(inline="支付退款", file_path=None, name="request") == "支付退款"


def test_read_from_utf8_file(tmp_path):
    f = tmp_path / "req.txt"
    f.write_text("在支付/退款/转账/分账四个场景做多级资金清结算", encoding="utf-8")
    assert text_input.read_text_arg(
        inline=None, file_path=str(f), name="request"
    ) == "在支付/退款/转账/分账四个场景做多级资金清结算"


def test_both_inline_and_file_is_error():
    with pytest.raises(ValueError, match="both"):
        text_input.read_text_arg(inline="x", file_path="y", name="request")


def test_neither_inline_nor_file_is_error():
    with pytest.raises(ValueError, match="--request"):
        text_input.read_text_arg(inline=None, file_path=None, name="request")


def test_corrupted_inline_is_rejected():
    with pytest.raises(ValueError, match="corrupt"):
        text_input.read_text_arg(inline="支�付", file_path=None, name="request")
