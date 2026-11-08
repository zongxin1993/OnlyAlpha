use super::*;

#[test]
fn official_hmac_vector_and_archived_client_vector() {
    // Binance 官方公开测试向量，未绑定任何账户。
    let payload = b"symbol=LTCBTC&side=BUY&type=LIMIT&timeInForce=GTC&quantity=1&price=0.1&recvWindow=5000&timestamp=1499827319559";
    assert_eq!(
        signature(
            b"NhqPtmdSJYdKjVHjA7PZj4Mge3R5YNiP1e3UZjInClVN65XAbvqqM6A7H5fATj0j",
            payload
        )
        .unwrap(),
        "c8db56825ae71d6d79447849e617115f4a920fa2acdcab2b053c4b2838bd6b71"
    );
    assert_eq!(
        signature(
            b"secret-value",
            b"recvWindow=5000&symbol=BTCUSDT&timestamp=1000"
        )
        .unwrap(),
        "3669540deb37f37c237d516b9124b86e2220f007228afb67198cf7b629c4766c"
    );
}

#[test]
fn ambiguous_side_effect_is_unknown_and_definitive_parameter_rejection_is_known() {
    for (status, code) in [
        (500, -1102),
        (503, -1000),
        (409, -2010),
        (400, -1006),
        (400, -1007),
        (400, -99999),
    ] {
        assert_eq!(error_outcome(status, Some(code)), DispatchResult::Unknown);
    }
    assert_eq!(error_outcome(400, None), DispatchResult::Unknown);
    assert_eq!(error_outcome(400, Some(-1102)), DispatchResult::Rejected);
}
