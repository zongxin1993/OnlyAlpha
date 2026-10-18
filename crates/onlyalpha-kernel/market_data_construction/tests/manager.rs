mod support;
use onlyalpha_market_data_construction::*;
use support::*;
#[test]
fn shared_registrations_preserve_state_and_absent_unregister_is_atomic() {
    let mut m = manager();
    let g = one_graph(3);
    m.register("first", g.clone()).unwrap();
    assert!(m.process("source", &fact(1), &stamp(1)).unwrap().is_empty());
    m.register("second", g.clone()).unwrap();
    assert_eq!(m.creation_count(), &1u32.into());
    let id = m.plan().lanes()[0].lane_id().to_string();
    assert_eq!(m.lane_reference_count(&id), 2);
    let before = m.capture_checkpoint().unwrap();
    assert!(m.unregister("absent").is_err());
    assert_eq!(m.capture_checkpoint().unwrap(), before);
    assert!(m.register("first", g).is_err());
    assert_eq!(m.capture_checkpoint().unwrap(), before);
    m.unregister("first").unwrap();
    m.process("source", &fact(2), &stamp(2)).unwrap();
    let out = m.process("source", &fact(3), &stamp(3)).unwrap();
    assert_eq!(out[0].volume().value().to_string(), "300");
    m.unregister("second").unwrap();
    assert_eq!(m.registration_count(), 0);
    assert_eq!(m.plan().lanes().len(), 0);
    assert_eq!(m.creation_count(), &1u32.into());
    assert_eq!(out[0].volume().value().to_string(), "300");
}
#[test]
fn graph_conflicts_and_unavailable_factories_do_not_change_owner() {
    let mut m = manager();
    m.register("first", one_graph(3)).unwrap();
    let before = m.capture_checkpoint().unwrap();
    let foreign = OnlyConstructionGraph::new(
        vec![OnlyConstructionInput::Bar(kind(A, 2))],
        vec![edge(2, 3)],
    )
    .unwrap();
    assert!(m.register("conflict", foreign).is_err());
    assert_eq!(m.capture_checkpoint().unwrap(), before);
    let native =
        OnlyConstructionGraph::new(vec![OnlyConstructionInput::Bar(kind(A, 3))], vec![]).unwrap();
    assert!(m.register("native", native).is_err());
    assert_eq!(m.capture_checkpoint().unwrap(), before);
    let e = edge(1, 7);
    let r = OnlyConstructionRecipe::derived(
        e.target().semantic().clone(),
        OnlyConstructionSemantic::Bar(kind(A, 1).semantic().clone()),
        "ROLLING_TIME_BAR",
        1u32.into(),
        OnlyMissingPolicy::Reject,
        OnlyIncompletePolicy::Drop,
    )
    .unwrap();
    let g = OnlyConstructionGraph::new(
        vec![e.source().clone()],
        vec![OnlyConstructionEdge::new(e.source().clone(), e.target().clone(), r).unwrap()],
    )
    .unwrap();
    assert!(m.register("unavailable", g).is_err());
    assert_eq!(m.capture_checkpoint().unwrap(), before);
    assert!(m.process("foreign", &fact(1), &stamp(1)).is_err());
    assert!(!m.is_failed());
    assert_eq!(m.capture_checkpoint().unwrap(), before);
}
#[test]
fn dag_reaches_fixpoint_in_global_level_and_lane_order() {
    let mut m = manager();
    let g = OnlyConstructionGraph::new(
        vec![OnlyConstructionInput::Bar(kind(A, 1))],
        vec![edge(1, 3), edge(1, 5), edge(3, 6), edge(5, 10)],
    )
    .unwrap();
    let mut reverse = manager();
    reverse
        .register(
            "graph",
            OnlyConstructionGraph::new(
                g.providers().to_vec(),
                g.edges().iter().cloned().rev().collect(),
            )
            .unwrap(),
        )
        .unwrap();
    m.register("graph", g).unwrap();
    for end in 1..=30 {
        let out = m.process("source", &fact(end), &stamp(end)).unwrap();
        assert_eq!(
            out,
            reverse.process("source", &fact(end), &stamp(end)).unwrap()
        );
        let order: Vec<_> = out
            .iter()
            .map(|b| {
                let lane = m
                    .plan()
                    .lanes()
                    .iter()
                    .find(|l| l.edge().target() == b.bar_type())
                    .unwrap();
                (lane.level(), lane.lane_id().to_string())
            })
            .collect();
        let mut sorted = order.clone();
        sorted.sort();
        assert_eq!(order, sorted);
        if end == 30 {
            assert_eq!(out.len(), 4);
            let six = out.iter().find(|b| b.bar_type() == &kind(A, 6)).unwrap();
            assert_eq!(six.volume().value().to_string(), "600");
            let ten = out.iter().find(|b| b.bar_type() == &kind(A, 10)).unwrap();
            assert_eq!(ten.volume().value().to_string(), "1000");
        }
    }
    assert_eq!(
        m.capture_checkpoint().unwrap(),
        reverse.capture_checkpoint().unwrap()
    );
}
