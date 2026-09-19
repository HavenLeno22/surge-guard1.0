"""The line protocol spoken to the alert hardware's firmware."""

from __future__ import annotations

import pytest

from app.hardware.levels import HardwareLevel
from app.hardware.protocol import HardwareCommand, Reply, ReplyKind, level_command, parse_reply


def test_levels_are_sent_as_their_names() -> None:
    assert level_command(HardwareLevel.NORMAL).wire == "NORMAL"
    assert level_command(HardwareLevel.WARNING).wire == "WARNING"
    assert level_command(HardwareLevel.CRITICAL).wire == "CRITICAL"
    assert level_command(HardwareLevel.NO_DATA).wire == "NO_DATA"


def test_test_commands_carry_the_test_prefix() -> None:
    assert HardwareCommand.TEST_SEQUENCE.wire == "TEST SEQUENCE"
    assert HardwareCommand.TEST_WARNING_TONE.wire == "TEST WARNING_TONE"
    assert HardwareCommand.TEST_RED.is_test
    assert not HardwareCommand.CRITICAL.is_test


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        (
            "READY SURGEGUARD-ALERT 1.0.0 R9 G10 B11 BUZZER8 CATHODE",
            Reply(ReplyKind.READY, "SURGEGUARD-ALERT 1.0.0 R9 G10 B11 BUZZER8 CATHODE"),
        ),
        ("OK CRITICAL", Reply(ReplyKind.OK, "CRITICAL")),
        ("OK TEST SEQUENCE", Reply(ReplyKind.OK, "TEST SEQUENCE")),
        ("PONG NORMAL", Reply(ReplyKind.PONG, "NORMAL")),
        ("ERR UNKNOWN_COMMAND BOGUS", Reply(ReplyKind.ERROR, "UNKNOWN_COMMAND BOGUS")),
        ("LINK_LOST", Reply(ReplyKind.LINK_LOST, "")),
        ("  OK NORMAL\r", Reply(ReplyKind.OK, "NORMAL")),
        ("garbage from a reset", Reply(ReplyKind.OTHER, "garbage from a reset")),
    ],
)
def test_replies_are_parsed(line: str, expected: Reply) -> None:
    assert parse_reply(line) == expected
