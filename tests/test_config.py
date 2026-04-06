from __future__ import annotations

import json

import pytest

from jetbrains_copr.config import load_products_config
from jetbrains_copr.errors import ConfigError


def test_load_products_config_accepts_valid_file(tmp_path):
    config_path = tmp_path / "products.json"
    config_path.write_text(
        json.dumps(
            {
                "products": [
                    {
                        "code": "IIU",
                        "name": "IntelliJ IDEA Ultimate",
                        "rpm_name": "jetbrains-idea-ultimate",
                        "executable_name": "idea",
                        "desktop_file_name": "jetbrains-idea-ultimate.desktop",
                        "icon_path": "bin/idea.png",
                        "startup_wm_class": "jetbrains-idea",
                        "comment": "JetBrains IntelliJ IDEA Ultimate IDE",
                        "categories": ["Development", "IDE"],
                        "enabled": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    config = load_products_config(config_path)

    assert len(config.products) == 1
    assert config.products[0].code == "IIU"
    assert config.products[0].release_type == "release"
    assert config.products[0].executable_name == "idea"


def test_load_products_config_rejects_missing_executable_name(tmp_path):
    config_path = tmp_path / "products.json"
    config_path.write_text(
        json.dumps(
            {
                "products": [
                    {
                        "code": "IIU",
                        "name": "IntelliJ IDEA Ultimate",
                        "rpm_name": "jetbrains-idea-ultimate",
                        "desktop_file_name": "jetbrains-idea-ultimate.desktop",
                        "icon_path": "bin/idea.png",
                        "startup_wm_class": "jetbrains-idea",
                        "comment": "JetBrains IntelliJ IDEA Ultimate IDE",
                        "categories": ["Development", "IDE"],
                        "enabled": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="executable_name"):
        load_products_config(config_path)


def test_load_products_config_rejects_duplicate_codes(tmp_path):
    config_path = tmp_path / "products.json"
    config_path.write_text(
        json.dumps(
            {
                "products": [
                    {
                        "code": "IIU",
                        "name": "IntelliJ IDEA Ultimate",
                        "rpm_name": "jetbrains-idea-ultimate",
                        "executable_name": "idea",
                        "desktop_file_name": "jetbrains-idea-ultimate.desktop",
                        "icon_path": "bin/idea.png",
                        "startup_wm_class": "jetbrains-idea",
                        "comment": "JetBrains IntelliJ IDEA Ultimate IDE",
                        "categories": ["Development", "IDE"],
                        "enabled": True,
                    },
                    {
                        "code": "IIU",
                        "name": "PyCharm Professional",
                        "rpm_name": "jetbrains-pycharm-professional",
                        "executable_name": "pycharm",
                        "desktop_file_name": "jetbrains-pycharm-professional.desktop",
                        "icon_path": "bin/pycharm.png",
                        "startup_wm_class": "jetbrains-pycharm",
                        "comment": "JetBrains PyCharm Professional IDE",
                        "categories": ["Development", "IDE"],
                        "enabled": True,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="duplicate product code"):
        load_products_config(config_path)


def test_load_products_config_allows_same_code_for_different_release_types(tmp_path):
    config_path = tmp_path / "products.json"
    config_path.write_text(
        json.dumps(
            {
                "products": [
                    {
                        "code": "IIU",
                        "name": "IntelliJ IDEA Ultimate",
                        "rpm_name": "jetbrains-idea-ultimate",
                        "executable_name": "idea",
                        "desktop_file_name": "jetbrains-idea-ultimate.desktop",
                        "icon_path": "bin/idea.png",
                        "startup_wm_class": "jetbrains-idea",
                        "comment": "JetBrains IntelliJ IDEA Ultimate IDE",
                        "categories": ["Development", "IDE"],
                        "enabled": True,
                    },
                    {
                        "code": "IIU",
                        "release_type": "eap",
                        "name": "IntelliJ IDEA EAP",
                        "rpm_name": "jetbrains-idea-eap",
                        "executable_name": "idea",
                        "desktop_file_name": "jetbrains-idea-eap.desktop",
                        "icon_path": "bin/idea.png",
                        "startup_wm_class": "jetbrains-idea",
                        "comment": "JetBrains IntelliJ IDEA EAP IDE",
                        "categories": ["Development", "IDE"],
                        "enabled": True,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    config = load_products_config(config_path)

    assert [product.identity for product in config.products] == ["IIU:release", "IIU:eap"]
