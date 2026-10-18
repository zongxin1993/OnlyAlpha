from scripts import rust_kernel_check as check


def test_market_data_responsibilities_live_under_one_business_directory() -> None:
    check.validate_workspace(check.ROOT)
    for name in ("state", "construction"):
        assert (check.ROOT / f"crates/onlyalpha-kernel/market_data/{name}/Cargo.toml").is_file()
        assert not (check.ROOT / f"crates/onlyalpha-kernel/market_data_{name}").exists()
