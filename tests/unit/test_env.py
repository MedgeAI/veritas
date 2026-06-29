from __future__ import annotations

from engine.env import (
    NO_ENV_FILE_MARKER,
    load_project_env,
    parse_env_file,
    strip_proxy_env,
    strip_proxy_env_inplace,
)


def test_parse_env_file_supports_basic_quotes_and_export(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "# comment",
                "DASHSCOPE_API_KEY='dashscope-secret'",
                'MINERU_API_TOKEN="mineru-secret"',
                "export EXTRA_TOKEN=extra-secret",
            ]
        ),
        encoding="utf-8",
    )

    values = parse_env_file(env_file)

    assert values == {
        "DASHSCOPE_API_KEY": "dashscope-secret",
        "MINERU_API_TOKEN": "mineru-secret",
        "EXTRA_TOKEN": "extra-secret",
    }


def test_load_project_env_adds_dotenv_without_overriding_existing(tmp_path) -> None:
    (tmp_path / ".env").write_text(
        "DASHSCOPE_API_KEY=from-dotenv\nMINERU_API_TOKEN=mineru\n",
        encoding="utf-8",
    )

    env = load_project_env(
        tmp_path,
        base_env={"DASHSCOPE_API_KEY": "from-shell"},
    )

    assert env["DASHSCOPE_API_KEY"] == "from-shell"
    assert env["MINERU_API_TOKEN"] == "mineru"


def test_load_project_env_can_be_disabled(tmp_path) -> None:
    (tmp_path / ".env").write_text("DASHSCOPE_API_KEY=from-dotenv\n", encoding="utf-8")

    env = load_project_env(tmp_path, include_env_file=False, base_env={})

    assert "DASHSCOPE_API_KEY" not in env
    assert env[NO_ENV_FILE_MARKER] == "1"


def test_strip_proxy_env_removes_process_proxy_values_by_default() -> None:
    env = strip_proxy_env(
        {
            "ALL_PROXY": "socks5h://127.0.0.1:18808",
            "HTTPS_PROXY": "http://proxy.local:8080",
            "DASHSCOPE_API_KEY": "key",
        }
    )

    assert "ALL_PROXY" not in env
    assert "HTTPS_PROXY" not in env
    assert env["DASHSCOPE_API_KEY"] == "key"


def test_strip_proxy_env_preserves_values_when_explicitly_trusted() -> None:
    env = strip_proxy_env(
        {
            "VERITAS_TRUST_PROXY_ENV": "1",
            "ALL_PROXY": "socks5h://127.0.0.1:18808",
        }
    )

    assert env["ALL_PROXY"] == "socks5h://127.0.0.1:18808"


def test_strip_proxy_env_inplace_mutates_mapping() -> None:
    env = {
        "ALL_PROXY": "socks5h://127.0.0.1:18808",
        "NO_PROXY": "localhost",
        "KEEP": "1",
    }

    strip_proxy_env_inplace(env)

    assert env == {"KEEP": "1"}


def test_load_project_env_strips_proxy_values_from_dotenv(tmp_path) -> None:
    (tmp_path / ".env").write_text(
        "ALL_PROXY=socks5h://127.0.0.1:18808\nDASHSCOPE_API_KEY=from-dotenv\n",
        encoding="utf-8",
    )

    env = load_project_env(tmp_path, base_env={})

    assert "ALL_PROXY" not in env
    assert env["DASHSCOPE_API_KEY"] == "from-dotenv"


def test_load_project_env_dotenv_can_opt_into_proxy_values(tmp_path) -> None:
    (tmp_path / ".env").write_text(
        "VERITAS_TRUST_PROXY_ENV=1\nALL_PROXY=socks5h://127.0.0.1:18808\n",
        encoding="utf-8",
    )

    env = load_project_env(tmp_path, base_env={})

    assert env["ALL_PROXY"] == "socks5h://127.0.0.1:18808"
