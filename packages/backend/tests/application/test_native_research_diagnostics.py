"""提交诊断仅公开受限大小、摘要和耗时，不输出请求正文或身份。"""

from packages.backend.tests.application.support.native_research_market_fixture import _strategy_probe_diagnostics


def test_submission_layout_diagnostics_are_bounded_and_redact_other_output(capsys):
    allowed = [
        "[strategy-evidence] payload=prepared-inputs bytes=9437184 sha256=" + "a" * 64,
        "[strategy-evidence] submission_us=5000000",
        "[strategy-evidence] phase=submission-start",
    ]
    refused = [
        "[strategy-evidence] payload=secret bytes=1 sha256=" + "a" * 64,
        "[strategy-evidence] payload=prepared-inputs bytes=1 sha256=" + "a" * 65,
        "[strategy-evidence] submission_us=-1",
        "[strategy-evidence] submission_us=1 owner=private-owner",
        "dsn=password-secret",
        "[strategy-evidence] payload=prepared-inputs bytes=" + "9" * 11 + " sha256=" + "a" * 64,
    ]
    _strategy_probe_diagnostics("\n".join(allowed + refused))
    assert capsys.readouterr().err.splitlines() == allowed
