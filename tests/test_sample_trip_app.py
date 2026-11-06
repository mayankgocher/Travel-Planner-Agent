"""Exercise the actual sample screen without permitting outbound connections."""

import socket
from pathlib import Path

from streamlit.testing.v1 import AppTest


APP = Path(__file__).resolve().parents[1] / "frontend" / "app.py"


def test_load_saved_jaipur_trip(monkeypatch):
    def reject_connection(*args, **kwargs):
        raise AssertionError("The saved demo must not make network calls")

    monkeypatch.setattr(socket.socket, "connect", reject_connection)
    monkeypatch.setattr(socket.socket, "connect_ex", reject_connection)
    screen = AppTest.from_file(str(APP)).run()
    assert not screen.exception
    assert not screen.header

    screen.button[0].click().run()
    assert not screen.exception
    assert screen.header[0].value == "Delhi → Jaipur"
    text = "\n".join(item.value for item in screen.markdown)
    assert "Train 12015" in text and "Train 12016" in text
    assert "Demo fare: ₹1,236" in text and "Demo fare: ₹1,086" in text
    assert any(item.value == "Indie Stays Jaipur" for item in screen.text)
    assert "₹7,588 quoted for the stay" in text
    assert sum(line.startswith("- ") for line in text.splitlines()) == 9
    assert text.count("Opening hours unverified") == 6
    assert "Wed" not in text and "Thu, 19 Nov 2026" in text
    assert any("Budget fit unverified" in item.value for item in screen.warning)
    assert any(button.label == "Generate plan" for button in screen.button)
