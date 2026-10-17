use std::{
    io::Write,
    process::{Command, Stdio},
};

fn run(frame: &[u8]) -> std::process::Output {
    let mut child = Command::new(env!("CARGO_BIN_EXE_predicate-diagnostic"))
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .spawn()
        .unwrap();
    child.stdin.take().unwrap().write_all(frame).unwrap();
    child.wait_with_output().unwrap()
}

#[test]
fn real_diagnostic_process_matches_all_recorded_rows_and_order() {
    let corpus = include_str!("../../../test-data/predicate/boolean-v1.tsv");
    let header = format!("ONLYALPHA_PREDICATE_DIAGNOSTIC_V2\t{}\n", "a".repeat(64));
    let mut request = header.clone();
    let mut expected = header;
    for (i, row) in corpus.lines().skip(1).enumerate() {
        let f: Vec<_> = row.split('\t').collect();
        let operands = if f[1].ends_with(".and") || f[1].ends_with(".or") {
            format!("{}\t{}", f[3], f[4])
        } else {
            f[3].to_owned()
        };
        let line = format!("{i}\t{}\t{}\t{operands}", f[1], f[2]);
        request.push_str(&format!("{line}\n"));
        expected.push_str(&format!("{line}\tOK\t{}\n", f[5]));
    }
    let output = run(request.as_bytes());
    assert!(output.status.success());
    assert_eq!(output.stdout, expected.as_bytes());
}

#[test]
fn malformed_or_oversized_frames_never_produce_partial_results() {
    let header = format!("ONLYALPHA_PREDICATE_DIAGNOSTIC_V2\t{}\n", "a".repeat(64));
    for frame in [
        vec![],
        vec![255],
        vec![b'x'; 65537],
        header.as_bytes().to_vec(),
        format!("{header}0\tonlyalpha.predicate.internal.boolean.not\t1\t1\n").into_bytes(),
        format!("{header}1\tonlyalpha.predicate.internal.boolean.not\t1\ttrue\n").into_bytes(),
    ] {
        let out = run(&frame);
        assert!(!out.status.success());
        assert!(out.stdout.is_empty());
    }
}

#[test]
fn errors_are_distinct_from_nullable_scalars() {
    let header = format!("ONLYALPHA_PREDICATE_DIAGNOSTIC_V2\t{}\n", "a".repeat(64));
    for (id, version, operands, error) in [
        ("unknown", "1", "true", "UnknownType"),
        (
            "onlyalpha.predicate.internal.compare.eq.integer.refs",
            "2",
            "1\t1",
            "UnknownVersion",
        ),
        (
            "onlyalpha.predicate.internal.compare.unknown.integer.refs",
            "1",
            "1\t1",
            "UnknownType",
        ),
        (
            "onlyalpha.predicate.internal.compare.eq.integer.refs",
            "1",
            "null",
            "InvalidArity",
        ),
        (
            "onlyalpha.predicate.internal.boolean.not",
            "2",
            "true",
            "UnknownVersion",
        ),
        (
            "onlyalpha.predicate.internal.boolean.not",
            "1",
            "true\tfalse",
            "InvalidArity",
        ),
    ] {
        let row = format!("0\t{id}\t{version}\t{operands}");
        let out = run(format!("{header}{row}\n").as_bytes());
        assert!(out.status.success());
        assert_eq!(
            out.stdout,
            format!("{header}{row}\tERROR\t{error}\n").as_bytes()
        );
    }
}

#[test]
fn sealed_python_generation_compares_the_actual_native_executable() {
    let script = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("tests/predicate_comparison_acceptance.py");
    let output = Command::new("python")
        .arg(script)
        .arg(env!("CARGO_BIN_EXE_predicate-diagnostic"))
        .output()
        .expect("canonical Linux dev Python must be present");
    assert!(
        output.status.success(),
        "{}\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(
        String::from_utf8_lossy(&output.stdout)
            .contains("SEALED_PYTHON_NATIVE_PREDICATE_COMPARISON: PASS")
    );
}

#[test]
fn actual_integer_process_preserves_all_recorded_exact_values() {
    let rows: Vec<_> = include_str!("../../../test-data/predicate/integer-refs-v1.tsv")
        .lines()
        .skip(1)
        .collect();
    assert_eq!(rows.len(), 216);
    for batch in rows.chunks(100) {
        let header = format!("ONLYALPHA_PREDICATE_DIAGNOSTIC_V2\t{}\n", "a".repeat(64));
        let mut request = header.clone();
        let mut expected = header;
        for (index, row) in batch.iter().enumerate() {
            let f: Vec<_> = row.split('\t').collect();
            let line = format!("{index}\t{}\t{}\t{}\t{}", f[1], f[2], f[3], f[4]);
            request.push_str(&format!("{line}\n"));
            expected.push_str(&format!("{line}\tOK\t{}\n", f[5]));
        }
        let out = run(request.as_bytes());
        assert!(out.status.success());
        assert_eq!(out.stdout, expected.as_bytes());
    }
}

#[test]
fn integer_frames_reject_wrong_scalar_family_and_oversized_operands_without_partial_output() {
    let header = format!("ONLYALPHA_PREDICATE_DIAGNOSTIC_V2\t{}\n", "a".repeat(64));
    let good = "0\tonlyalpha.predicate.internal.compare.eq.integer.refs\t1\t1\t1\n";
    for token in [
        "true".to_owned(),
        "01".to_owned(),
        "-0".to_owned(),
        "1e3".to_owned(),
        "9".repeat(257),
    ] {
        let frame = format!(
            "{header}{good}1\tonlyalpha.predicate.internal.compare.eq.integer.refs\t1\t{token}\t1\n"
        );
        let out = run(frame.as_bytes());
        assert!(!out.status.success());
        assert!(out.stdout.is_empty());
    }
    let out = run(format!("{}{good}", header.replace("V2", "V1")).as_bytes());
    assert!(!out.status.success());
    assert!(out.stdout.is_empty());
}

#[test]
fn maximum_signed_integer_tokens_round_trip_exactly() {
    let header = format!("ONLYALPHA_PREDICATE_DIAGNOSTIC_V2\t{}\n", "a".repeat(64));
    for value in ["9".repeat(256), format!("-{}", "9".repeat(256))] {
        let row =
            format!("0\tonlyalpha.predicate.internal.compare.eq.integer.refs\t1\t{value}\t{value}");
        let out = run(format!("{header}{row}\n").as_bytes());
        assert!(out.status.success());
        assert_eq!(out.stdout, format!("{header}{row}\tOK\ttrue\n").as_bytes());
    }
}
