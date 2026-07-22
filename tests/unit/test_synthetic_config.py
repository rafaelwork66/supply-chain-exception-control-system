"""Unit tests for synthetic generator configuration."""

from scecs.synthetic.config import ci_config, default_portfolio_config


def test_default_portfolio_config_matches_governed_scale() -> None:
    """The default profile should preserve the approved portfolio baseline."""

    config = default_portfolio_config()

    assert config.site_count == 2
    assert config.supplier_count == 120
    assert config.product_count == 1_000
    assert config.po_line_count >= 50_000
    assert config.target_open_line_count == 1_500
    assert config.reporting_currency == "AUD"
    assert config.base_uom == "EA"


def test_ci_config_is_small_but_structurally_valid() -> None:
    """The CI profile should be fast while preserving the same contracts."""

    config = ci_config()

    assert config.site_count == 2
    assert config.supplier_count < default_portfolio_config().supplier_count
    assert config.product_count < default_portfolio_config().product_count
    assert config.target_open_line_count > 0
