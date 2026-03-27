from __future__ import annotations

from importlib.resources import files


def test_package_resources_include_deep_prompts_and_web_assets() -> None:
    package_root = files("draftclaw")

    assert package_root.joinpath("resources", "prompts", "modes", "deep_plan_round.md").is_file()
    assert package_root.joinpath("resources", "prompts", "modes", "deep_execute_round.md").is_file()
    assert package_root.joinpath("resources", "prompts", "modes", "deep_validate_round.md").is_file()
    assert package_root.joinpath("web", "templates", "dashboard.html").is_file()
    assert package_root.joinpath("web", "static", "app.css").is_file()
    assert package_root.joinpath("web", "static", "app.js").is_file()
