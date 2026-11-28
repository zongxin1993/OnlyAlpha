use super::*;
use crate::{Cohort, research::Cell};
use std::collections::BTreeMap;

fn cells(values: [Option<&str>; 2]) -> Vec<Cell> {
    values
        .map(|text| text.map(|value| value.parse().unwrap()))
        .into()
}

fn panel(times: [i128; 2], warmup: usize) -> Result<ResearchPanel> {
    let axis = times
        .map(|ns| OnlyTimestamp::from_unix_nanos(ns.into()))
        .to_vec();
    let first = Cohort::from([
        ("close".into(), cells([None, Some("3")])),
        ("volume".into(), cells([Some("20"), Some("30")])),
    ]);
    let second = Cohort::from([
        ("close".into(), cells([Some("4"), Some("5")])),
        ("volume".into(), cells([Some("40"), None])),
    ]);
    ResearchPanel::new(
        &"a".repeat(64),
        vec![
            ("000002.XSHE".parse().unwrap(), axis.clone(), second),
            ("000001.XSHE".parse().unwrap(), axis, first),
        ],
        warmup,
    )
}

#[test]
fn replay_keeps_virtual_time_instrument_fields_and_warmup_rows_aligned() {
    let data = panel([7, 11], 1).unwrap();
    let mut replay = FrozenReplay::new(&data, data.snapshot(), data.content_digest()).unwrap();
    assert!(replay.virtual_time().is_none());
    for (row, expected) in [
        [[None, Some("20")], [Some("4"), Some("40")]],
        [[Some("3"), Some("30")], [Some("5"), None]],
    ]
    .into_iter()
    .enumerate()
    {
        let Some(TradingEvent::Market(bar)) = replay.next_event().unwrap() else {
            panic!("冻结行情缺失");
        };
        assert_eq!(bar.timestamp(), &data.timestamps()[row]);
        assert_eq!(replay.virtual_time(), Some(bar.timestamp()));
        assert_eq!(
            bar.instruments(),
            &[
                "000001.XSHE".parse().unwrap(),
                "000002.XSHE".parse().unwrap()
            ]
        );
        let fields = expected.map(|values| {
            BTreeMap::from_iter(
                ["close", "volume"]
                    .map(String::from)
                    .into_iter()
                    .zip(cells(values)),
            )
        });
        assert_eq!(bar.cohort(), &fields);
    }
    assert!(replay.next_event().unwrap().is_none());
    assert_eq!(replay.virtual_time(), data.timestamps().last());
    assert!(replay.next_event().unwrap().is_none());
}

#[test]
fn replay_checks_snapshot_and_content_including_warmup_boundary() {
    let data = panel([7, 11], 1).unwrap();
    let different_warmup = panel([7, 11], 0).unwrap();
    let wrong_snapshot = FrozenReplay::new(&data, &"b".repeat(64), data.content_digest());
    assert_eq!(
        wrong_snapshot.err(),
        Some(error("TRADING_REPLAY_SNAPSHOT_MISMATCH"))
    );
    let wrong_content =
        FrozenReplay::new(&data, data.snapshot(), different_warmup.content_digest());
    assert_eq!(
        wrong_content.err(),
        Some(error("RESEARCH_PANEL_CONTENT_MISMATCH"))
    );
    assert_eq!(
        panel([11, 7], 1).unwrap_err(),
        error("RESEARCH_PANEL_TIME_AXIS")
    );
}
