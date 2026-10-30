use onlyalpha_backend::application::research_specification::{Role, Sample, Study};
use onlyalpha_backend::application::research_statistics::Metric;

fn study() -> Study {
    Study {
        schema_version: 1,
        bar_ns: 60_000_000_000,
        horizon_bars: 2,
        samples: vec![
            Sample {
                role: Role::Development,
                start_ns: 1_200_000_000_000,
                end_ns: 7_200_000_000_000,
            },
            Sample {
                role: Role::OutOfSample,
                start_ns: 7_200_000_000_000,
                end_ns: 13_200_000_000_000,
            },
        ],
        protected_start_ns: 13_200_000_000_000,
        protected_end_ns: 19_200_000_000_000,
        expected_block_length: 4,
        replicates: 4096,
        confidence_bps: 9500,
        seed: "00".repeat(32),
    }
}
#[test]
fn complete_comparison_membership_is_derived_from_the_frozen_samples() {
    let s = study();
    let family = s.comparison_family().unwrap();
    assert_eq!(family.len(), 4);
    assert_eq!(family[0].metric, Metric::Pearson);
    assert_eq!(family[1].metric, Metric::Spearman);
    assert_eq!(family[2].start_ns, s.samples[1].start_ns);
    assert_eq!(
        s.logical_fingerprint().unwrap(),
        s.clone().logical_fingerprint().unwrap()
    );
    let mut changed = s.clone();
    changed.seed = "01".repeat(32);
    assert_ne!(
        s.logical_fingerprint().unwrap(),
        changed.logical_fingerprint().unwrap()
    );
}
#[test]
fn protected_access_overlapping_or_relabelled_samples_are_not_admitted() {
    let s = study();
    for n in 0..5 {
        let mut changed = s.clone();
        match n {
            0 => changed.samples[1].end_ns += changed.bar_ns,
            1 => changed.samples[1].start_ns -= changed.bar_ns,
            2 => changed.samples[1].role = Role::Development,
            3 => changed.horizon_bars = 100,
            _ => changed.samples.reverse(),
        }
        assert!(changed.comparison_family().is_err(), "mutation {n}");
    }
}

#[test]
fn forward_return_is_exact_half_even_and_not_binary_floating_point() {
    use onlyalpha_backend::application::research_run_execution::close_forward_return;
    assert_eq!(close_forward_return("3", "4").unwrap(), "0.333333333333");
    assert_eq!(
        close_forward_return("2000000000000", "2000000000001").unwrap(),
        "0.000000000000"
    );
    assert_eq!(
        close_forward_return("2000000000000", "2000000000003").unwrap(),
        "0.000000000002"
    );
    assert_eq!(
        close_forward_return("2000000000000", "1999999999997").unwrap(),
        "-0.000000000002"
    );
    assert!(close_forward_return("0", "1").is_err());
    assert!(close_forward_return("1e-18", "1").is_err());
}
