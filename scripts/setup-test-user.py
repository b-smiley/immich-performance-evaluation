#!/usr/bin/env python3
"""Create or authenticate the ephemeral Immich load-test user."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path


def request(
    opener: urllib.request.OpenerDirector,
    url: str,
    method: str,
    payload: dict[str, object] | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, object]]:
    body = None if payload is None else json.dumps(payload).encode()
    request_headers = {"Content-Type": "application/json", **(headers or {})}
    request = urllib.request.Request(
        url,
        data=body,
        headers=request_headers,
        method=method,
    )
    try:
        with opener.open(request) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        raw_body = error.read().decode()
        try:
            details = json.loads(raw_body)
        except json.JSONDecodeError:
            details = {"message": raw_body}
        return error.code, details


def update_env(path: Path, key: str) -> None:
    lines = path.read_text().splitlines() if path.exists() else []
    replaced = False
    for index, line in enumerate(lines):
        if line.startswith("IMMICH_API_KEY="):
            lines[index] = f"IMMICH_API_KEY={key}"
            replaced = True
            break
    if not replaced:
        lines.append(f"IMMICH_API_KEY={key}")
    path.write_text("\n".join(lines) + "\n")


def main() -> int:
    base_url = os.environ.get("IMMICH_URL", "http://localhost:2283").rstrip("/")
    email = os.environ.get("IMMICH_TEST_EMAIL", "loadtest@example.invalid")
    password = os.environ.get("IMMICH_TEST_PASSWORD", "LoadTestPassword123!")
    name = os.environ.get("IMMICH_TEST_NAME", "Ephemeral Load Test")
    env_path = Path(os.environ.get("IMMICH_ENV_FILE", ".env"))

    cookie_jar = CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(cookie_jar)
    )
    credentials = {"email": email, "password": password}

    signup_status, signup_response = request(
        opener,
        f"{base_url}/api/auth/admin-sign-up",
        "POST",
        {"email": email, "name": name, "password": password},
    )
    if signup_status not in {200, 201, 400, 403}:
        print(
            f"Immich admin signup failed with HTTP {signup_status}: "
            f"{signup_response.get('message', signup_response)}",
            file=sys.stderr,
        )
        return 1

    login_status, login_response = request(
        opener, f"{base_url}/api/auth/login", "POST", credentials
    )
    if login_status not in {200, 201}:
        message = login_response.get("message", login_response)
        print(
            f"Immich test-user login failed with HTTP {login_status}: {message}. "
            "For a reused local database, set IMMICH_TEST_EMAIL and "
            "IMMICH_TEST_PASSWORD to the existing test account or run "
            "`docker compose down -v` before starting a fresh stack.",
            file=sys.stderr,
        )
        return 1

    auth_headers: dict[str, str] = {}
    access_token = login_response.get("accessToken")
    if isinstance(access_token, str):
        auth_headers["Authorization"] = f"Bearer {access_token}"

    key_status, key_response = request(
        opener,
        f"{base_url}/api/api-keys",
        "POST",
        {"name": "ephemeral-load-test", "permissions": ["all"]},
        auth_headers,
    )
    if key_status not in {200, 201}:
        message = key_response.get("message", key_response)
        print(
            f"Immich API-key creation failed with HTTP {key_status}: {message}",
            file=sys.stderr,
        )
        return 1

    api_key = next(
        (
            key_response.get(field)
            for field in ("secret", "key", "apiKey")
            if isinstance(key_response.get(field), str)
        ),
        None,
    )
    if not isinstance(api_key, str) or not api_key:
        print("Immich API-key response did not contain a key.", file=sys.stderr)
        return 1

    update_env(env_path, api_key)
    print(f"Configured ephemeral Immich API key in {env_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
