from __future__ import annotations

from weshub.config import Settings


def test_settings_load_server_and_catalog_config(tmp_path) -> None:
    config = tmp_path / "hub.yaml"
    config.write_text(
        """server:
  host: 0.0.0.0
  port: 9000
  data_dir: state
  poll_interval: 5
catalog:
  repo: ssh://git@example.com/team/workflows.git
  branch: production
"""
    )

    settings = Settings.from_file(config)

    assert settings.host == "0.0.0.0"
    assert settings.port == 9000
    assert settings.data_dir == tmp_path / "state"
    assert settings.poll_interval == 5
    assert settings.catalog_repo == "ssh://git@example.com/team/workflows.git"
    assert settings.catalog_branch == "production"
