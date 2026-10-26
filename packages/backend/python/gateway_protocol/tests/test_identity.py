from onlyalpha_gateway_protocol import canonical_test_mutation_fingerprint


def test_transport_metadata_does_not_change_canonical_test_command_fingerprint() -> None:
    payload = "canonical-intent"
    expected = canonical_test_mutation_fingerprint(payload)
    assert expected == "600188cc7b50710f869ea91c9ef9d420ae956ec3b607f5fa5cf0745077bd44b2"

    for _correlation_id, _gateway_instance_id, _deadline in (
        ("attempt-a", "instance-a", 1.0),
        ("attempt-b", "instance-b", 30.0),
    ):
        assert canonical_test_mutation_fingerprint(payload) == expected

    assert canonical_test_mutation_fingerprint("different-intent") != expected
