from __future__ import annotations

from engine.env import NO_ENV_FILE_MARKER, load_project_env, parse_env_file


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
