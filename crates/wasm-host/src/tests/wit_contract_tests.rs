use crate::contract::{
    EXTENDED_OPERATOR_INTERFACE, MARKET_RULE_INTERFACE, STRATEGY_INTERFACE, WIT_CONTRACT_VERSION,
};
use std::collections::BTreeSet;
use std::path::PathBuf;
use wit_parser::{Resolve, WorldItem};

#[test]
fn wit_contract_v1_parses_and_enforces_zero_imports() {
    let wit_path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../contracts/wasm/v1/onlyalpha-plugin.wit");
    let mut resolve = Resolve::default();
    let pkg_id = resolve
        .push_file(&wit_path)
        .expect("contracts/wasm/v1/onlyalpha-plugin.wit must parse cleanly");
    let pkg = &resolve.packages[pkg_id];

    assert_eq!(pkg.name.to_string(), WIT_CONTRACT_VERSION);

    let interface_names: BTreeSet<String> = pkg.interfaces.keys().cloned().collect();
    assert_eq!(
        interface_names,
        BTreeSet::from([
            "extended-operator".to_owned(),
            "market-rule".to_owned(),
            "strategy".to_owned(),
        ])
    );

    // Verify exported function sets match host expectations verbatim.
    let op_iface = &resolve.interfaces[pkg.interfaces["extended-operator"]];
    let op_funcs: BTreeSet<String> = op_iface.functions.keys().cloned().collect();
    assert_eq!(
        op_funcs,
        BTreeSet::from([
            "metadata".to_owned(),
            "eval-vector".to_owned(),
            "init-event".to_owned(),
            "step-event".to_owned(),
            "capture-state".to_owned(),
            "restore-state".to_owned(),
        ])
    );

    let market_iface = &resolve.interfaces[pkg.interfaces["market-rule"]];
    let market_funcs: BTreeSet<String> = market_iface.functions.keys().cloned().collect();
    assert_eq!(
        market_funcs,
        BTreeSet::from(["metadata".to_owned(), "validate-order".to_owned()])
    );

    let strat_iface = &resolve.interfaces[pkg.interfaces["strategy"]];
    let strat_funcs: BTreeSet<String> = strat_iface.functions.keys().cloned().collect();
    assert_eq!(
        strat_funcs,
        BTreeSet::from(["metadata".to_owned(), "on-event".to_owned()])
    );

    // Verify all three worlds have ZERO imports (strictly pure deterministic computation, no WASI).
    for (world_name, expected_export) in [
        ("extended-operator-plugin", EXTENDED_OPERATOR_INTERFACE),
        ("market-rule-plugin", MARKET_RULE_INTERFACE),
        ("strategy-plugin", STRATEGY_INTERFACE),
    ] {
        let world_id = pkg.worlds[world_name];
        let world = &resolve.worlds[world_id];
        assert!(
            world.imports.is_empty(),
            "world '{world_name}' must not declare any imports (WASI forbidden)"
        );
        assert_eq!(world.exports.len(), 1);
        let export_item = world.exports.values().next().expect("single export");
        match export_item {
            WorldItem::Interface { id, .. } => {
                let iface = &resolve.interfaces[*id];
                let fq = format!(
                    "{}:{}/{}@{}",
                    pkg.name.namespace,
                    pkg.name.name,
                    iface.name.as_deref().unwrap_or(""),
                    pkg.name
                        .version
                        .as_ref()
                        .map(ToString::to_string)
                        .unwrap_or_default()
                );
                assert_eq!(fq, expected_export);
            }
            other => panic!("unexpected world export item: {other:?}"),
        }
    }
}
