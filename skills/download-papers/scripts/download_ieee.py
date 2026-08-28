#!/usr/bin/env python3
"""Download IEEE Xplore PDFs by document ID through browser-authenticated access."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import random
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Mapping, cast


HOST = "ieeexplore.ieee.org"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)
PROXY_VARIABLES = {
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "no_proxy",
    "PROXY_HTTP",
    "PROXY_HOST",
    "PROXY_PORT",
    "AGENT_BROWSER_PROXY",
    "AGENT_BROWSER_PROXY_BYPASS",
}
TRANSPORTS = ("aria2c", "wget", "curl")


@dataclass(frozen=True)
class BrowserAccess:
    institution: str | None
    blocked: bool
    ready: bool

    @classmethod
    def from_agent_browser(cls, raw: str) -> BrowserAccess:
        decoded: object = json.loads(raw)
        if isinstance(decoded, str):
            decoded = json.loads(decoded)
        if not isinstance(decoded, Mapping) or not all(
            isinstance(key, str) for key in decoded
        ):
            raise RuntimeError("agent-browser returned non-object access metadata")

        # JSON is untyped; keys are validated before narrowing this boundary.
        metadata = cast(Mapping[str, object], decoded)
        institution = metadata.get("institution")
        blocked = metadata.get("blocked")
        ready = metadata.get("ready")
        if institution is not None and not isinstance(institution, str):
            raise RuntimeError("agent-browser returned an invalid institution")
        if not isinstance(blocked, bool) or not isinstance(ready, bool):
            raise RuntimeError("agent-browser returned invalid access flags")
        return cls(institution=institution, blocked=blocked, ready=ready)


@dataclass(frozen=True)
class DownloadMetadata:
    document_id: str
    title: str
    subject: str
    pages: int
    path: str
    byte_count: int
    sha256: str
    downloader: str
    institution: str | None

    def to_json(self) -> str:
        return json.dumps(
            {
                "document_id": self.document_id,
                "title": self.title,
                "subject": self.subject,
                "pages": self.pages,
                "path": self.path,
                "bytes": self.byte_count,
                "sha256": self.sha256,
                "downloader": self.downloader,
                "institution": self.institution,
            },
            ensure_ascii=False,
        )


def document_id(value: str) -> str:
    if not value.isdigit():
        raise argparse.ArgumentTypeError("document IDs must contain only digits")
    return value


def direct_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for variable in PROXY_VARIABLES:
        environment.pop(variable, None)
    return environment


def run(command: list[str], environment: dict[str, str], capture: bool = False) -> str:
    result = subprocess.run(
        command,
        check=False,
        env=environment,
        text=True,
        capture_output=capture,
    )
    if result.returncode:
        details = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"{command[0]} failed ({result.returncode}): {details}")
    return result.stdout.strip() if capture else ""


def browser_command(namespace: str, *arguments: str) -> list[str]:
    return [
        "agent-browser",
        "--namespace",
        namespace,
        "--session",
        namespace,
        "--user-agent",
        USER_AGENT,
        *arguments,
    ]


def browser_access(
    namespace: str,
    article: str,
    environment: dict[str, str],
) -> BrowserAccess:
    run(
        browser_command(namespace, "open", f"https://{HOST}/document/{article}"),
        environment,
        capture=True,
    )
    run(
        browser_command(namespace, "wait", "--load", "domcontentloaded"),
        environment,
        capture=True,
    )
    expression = (
        "JSON.stringify({"
        "institution:document.body.innerText.match(/Access provided by:\\s*([^\\n]+)/)?.[1]||null,"
        "blocked:document.body.innerText.includes('Unusual Traffic Detected'),"
        "ready:Boolean(document.querySelector('h1'))"
        "})"
    )
    for _ in range(10):
        raw = run(
            browser_command(namespace, "eval", expression), environment, capture=True
        )
        access = BrowserAccess.from_agent_browser(raw)
        if access.blocked:
            raise SystemExit("IEEE returned Unusual Traffic Detected (Error 418)")
        if access.ready:
            return access
        time.sleep(random.uniform(0.8, 1.4))
    raise RuntimeError("IEEE document page did not become ready")


def domain_applies(cookie_domain: str) -> bool:
    domain = cookie_domain.lstrip(".").lower()
    return HOST == domain or HOST.endswith("." + domain)


def write_cookie_jar(state_path: Path, jar_path: Path) -> None:
    with state_path.open(encoding="utf-8") as handle:
        state = json.load(handle)

    now = time.time()
    cookies = [
        cookie
        for cookie in state.get("cookies", [])
        if domain_applies(cookie.get("domain", ""))
        and (cookie.get("expires", -1) <= 0 or cookie["expires"] > now)
    ]
    if not cookies:
        raise SystemExit("browser state contains no live cookies for IEEE Xplore")

    lines = ["# Netscape HTTP Cookie File"]
    for cookie in cookies:
        domain = cookie["domain"]
        lines.append(
            "\t".join(
                (
                    domain,
                    "TRUE" if domain.startswith(".") else "FALSE",
                    cookie.get("path", "/"),
                    "TRUE" if cookie.get("secure") else "FALSE",
                    str(max(0, int(cookie.get("expires", 0)))),
                    cookie["name"],
                    cookie["value"],
                )
            )
        )
    jar_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    jar_path.chmod(0o600)


def choose_downloader(requested: str) -> str:
    choices = TRANSPORTS if requested == "auto" else (requested,)
    for choice in choices:
        if shutil.which(choice):
            return choice
    raise SystemExit(f"downloader not found: {', '.join(choices)}")


def require_command(command: str) -> str:
    if path := shutil.which(command):
        return path
    raise SystemExit(f"required command not found: {command}")


def downloader_command(
    downloader: str,
    jar: Path,
    article: str,
    destination: Path,
) -> list[str]:
    document_url = f"https://{HOST}/document/{article}"
    pdf_url = f"https://{HOST}/stampPDF/getPDF.jsp?tp=&arnumber={article}&ref="
    if downloader == "wget":
        return [
            "wget",
            "--no-proxy",
            "--timeout=60",
            "--tries=2",
            "--max-redirect=5",
            "--progress=dot:giga",
            f"--user-agent={USER_AGENT}",
            f"--referer={document_url}",
            f"--load-cookies={jar}",
            "-O",
            str(destination),
            pdf_url,
        ]
    if downloader == "curl":
        return [
            "curl",
            "--noproxy",
            "*",
            "--fail",
            "--location",
            "--max-redirs",
            "5",
            "--connect-timeout",
            "60",
            "--retry",
            "1",
            "--silent",
            "--show-error",
            "--user-agent",
            USER_AGENT,
            "--referer",
            document_url,
            "--cookie",
            str(jar),
            "--output",
            str(destination),
            pdf_url,
        ]
    return [
        "aria2c",
        "--all-proxy=",
        "--timeout=60",
        "--max-tries=2",
        "--max-file-not-found=0",
        "--allow-overwrite=true",
        "--auto-file-renaming=false",
        f"--user-agent={USER_AGENT}",
        f"--referer={document_url}",
        f"--load-cookies={jar}",
        f"--dir={destination.parent}",
        f"--out={destination.name}",
        pdf_url,
    ]


def read_pdfinfo(path: Path, pdfinfo: str) -> tuple[str, str, int]:
    result = subprocess.run(
        [pdfinfo, str(path)],
        check=False,
        text=True,
        capture_output=True,
    )
    if result.returncode:
        raise RuntimeError(f"pdfinfo rejected {path}: {result.stderr.strip()}")
    output = result.stdout
    fields = dict(line.split(":", 1) for line in output.splitlines() if ":" in line)
    pages = fields.get("Pages", "").strip()
    if not pages:
        raise RuntimeError("pdfinfo returned no page count")
    return (
        fields.get("Title", "").strip(),
        fields.get("Subject", "").strip(),
        int(pages),
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def download(
    article: str,
    output: Path,
    downloader: str,
    jar: Path,
    environment: dict[str, str],
    pdfinfo: str,
    force: bool,
    institution: str | None,
) -> DownloadMetadata:
    if output.exists() and not force:
        raise SystemExit(f"output exists; pass --force to replace it: {output}")
    with tempfile.NamedTemporaryFile(
        prefix=f".{output.name}.",
        suffix=".part",
        dir=output.parent,
        delete=False,
    ) as temporary:
        partial = Path(temporary.name)
    try:
        run(downloader_command(downloader, jar, article, partial), environment)
        with partial.open("rb") as handle:
            if handle.read(5) != b"%PDF-":
                raise SystemExit(f"IEEE {article} returned a non-PDF response")
        title, subject, pages = read_pdfinfo(partial, pdfinfo)
        metadata = DownloadMetadata(
            document_id=article,
            title=title,
            subject=subject,
            pages=pages,
            path=str(output.resolve()),
            byte_count=partial.stat().st_size,
            sha256=sha256_file(partial),
            downloader=downloader,
            institution=institution,
        )
        os.replace(partial, output)
        return metadata
    finally:
        partial.unlink(missing_ok=True)
        Path(f"{partial}.aria2").unlink(missing_ok=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("document_ids", nargs="+", type=document_id)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--downloader",
        choices=("auto", *TRANSPORTS),
        default="auto",
    )
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    require_command("agent-browser")
    pdfinfo = require_command("pdfinfo")
    if len(set(args.document_ids)) != len(args.document_ids):
        raise SystemExit("duplicate document IDs are not allowed")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    outputs = [args.output_dir / f"{article}.pdf" for article in args.document_ids]
    if not args.force:
        existing = [str(path) for path in outputs if path.exists()]
        if existing:
            raise SystemExit(
                "output exists; pass --force to replace: " + ", ".join(existing)
            )

    environment = direct_environment()
    downloader = choose_downloader(args.downloader)
    namespace = f"ieee-{os.getpid():x}-{secrets.token_hex(2)}"
    try:
        with tempfile.TemporaryDirectory(prefix="ieee-download-") as temp_dir:
            temp = Path(temp_dir)
            state = temp / "browser-state.json"
            jar = temp / "cookies.txt"
            access = browser_access(namespace, args.document_ids[0], environment)
            run(
                browser_command(namespace, "state", "save", str(state)),
                environment,
                capture=True,
            )
            state.chmod(0o600)
            write_cookie_jar(state, jar)

            for article, output in zip(args.document_ids, outputs):
                delay = random.uniform(3, 7)
                print(f"waiting {delay:.1f}s before IEEE {article}", file=sys.stderr)
                time.sleep(delay)
                metadata = download(
                    article,
                    output,
                    downloader,
                    jar,
                    environment,
                    pdfinfo,
                    args.force,
                    access.institution,
                )
                print(metadata.to_json(), flush=True)
    finally:
        result = subprocess.run(
            browser_command(namespace, "close"),
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode:
            details = (result.stderr or result.stdout).strip()
            print(f"agent-browser cleanup failed: {details}", file=sys.stderr)


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as error:
        raise SystemExit(str(error)) from None
