from importlib.metadata import entry_points


def test_installed_entry_point_discovers_tushare_factory() -> None:
    matches = [
        item
        for item in entry_points(group="onlyalpha.data_sources")
        if item.name == "tushare"
    ]
    assert len(matches) == 1
    assert matches[0].load().descriptor.plugin_id == "tushare"
