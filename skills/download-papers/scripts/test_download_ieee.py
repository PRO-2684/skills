#!/usr/bin/env python3
"""Small dependency-free checks for download_ieee.py."""

import json
import os
from pathlib import Path
import tempfile

import download_ieee


def main() -> None:
    assert download_ieee.document_id("9757872") == "9757872"
    assert download_ieee.TRANSPORTS[0] == "aria2c"
    access = download_ieee.BrowserAccess.from_agent_browser(
        '"{\\"institution\\":\\"Example U\\",\\"blocked\\":false,\\"ready\\":true}"'
    )
    assert access.institution == "Example U"
    metadata = download_ieee.DownloadMetadata(
        document_id="9757872",
        title="Example",
        subject="10.1109/example",
        pages=1,
        path="/tmp/9757872.pdf",
        byte_count=5,
        sha256="0" * 64,
        downloader="aria2c",
        institution="Example U",
    )
    assert json.loads(metadata.to_json())["bytes"] == 5

    os.environ["HTTPS_PROXY"] = "http://proxy.invalid"
    assert "HTTPS_PROXY" not in download_ieee.direct_environment()

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        state = root / "state.json"
        jar = root / "cookies.txt"
        state.write_text(
            json.dumps(
                {
                    "cookies": [
                        {
                            "domain": ".ieeexplore.ieee.org",
                            "path": "/",
                            "secure": True,
                            "expires": -1,
                            "name": "session",
                            "value": "secret",
                        },
                        {
                            "domain": ".example.com",
                            "path": "/",
                            "secure": True,
                            "expires": -1,
                            "name": "ignored",
                            "value": "secret",
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )
        download_ieee.write_cookie_jar(state, jar)
        assert "session" in jar.read_text(encoding="utf-8")
        assert "ignored" not in jar.read_text(encoding="utf-8")
        assert jar.stat().st_mode & 0o777 == 0o600
        for transport in download_ieee.TRANSPORTS:
            command = download_ieee.downloader_command(
                transport, jar, "9757872", root / "9757872.pdf"
            )
            assert command[0] == transport
            assert any("9757872" in argument for argument in command)

    print("download_ieee checks passed")


if __name__ == "__main__":
    main()
