mod support;
use onlyalpha_calculation_bridge::{Worker, WorkerError};
use std::{
    io::{Read, Write},
    os::unix::net::UnixStream,
    thread,
    time::Duration,
};
#[test]
fn malformed_peer_is_unknown_and_poisoned() {
    let (socket, mut peer) = UnixStream::pair().unwrap();
    let task = thread::spawn(move || {
        let mut head = [0; 4];
        peer.read_exact(&mut head).unwrap();
        let mut data = vec![0; u32::from_be_bytes(head) as usize];
        peer.read_exact(&mut data).unwrap();
        peer.write_all(&u32::MAX.to_be_bytes()).unwrap();
    });
    let mut worker = Worker::from_stream(
        socket,
        "a".repeat(64),
        "b".repeat(64),
        support::control(),
        1024 * 1024,
    )
    .unwrap();
    assert!(matches!(
        worker.handshake(Duration::from_secs(2)),
        Err(WorkerError::Unknown(_))
    ));
    assert!(matches!(
        worker.handshake(Duration::from_secs(2)),
        Err(WorkerError::Unknown(_))
    ));
    task.join().unwrap();
}
#[test]
fn cancellation_wakes_blocked_exchange_without_sleep() {
    let (socket, mut peer) = UnixStream::pair().unwrap();
    let mut worker = Worker::from_stream(
        socket,
        "a".repeat(64),
        "b".repeat(64),
        support::control(),
        1024 * 1024,
    )
    .unwrap();
    let cancellation = worker.cancellation().unwrap();
    let task = thread::spawn(move || worker.handshake(Duration::from_secs(10)));
    let mut head = [0; 4];
    peer.read_exact(&mut head).unwrap();
    assert_eq!(
        cancellation.state(),
        onlyalpha_calculation_bridge::ProcessState::Running
    );
    cancellation.cancel().unwrap();
    assert_eq!(
        cancellation.state(),
        onlyalpha_calculation_bridge::ProcessState::Joined
    );
    assert!(matches!(task.join().unwrap(), Err(WorkerError::Unknown(_))));
}

#[test]
fn total_deadline_on_partial_prefix_and_crash_are_unknown() {
    use std::sync::mpsc;
    let (socket, mut peer) = UnixStream::pair().unwrap();
    let (release_tx, release_rx) = mpsc::channel();
    let peer_task = thread::spawn(move || {
        let mut head = [0; 4];
        peer.read_exact(&mut head).unwrap();
        let mut body = vec![0; u32::from_be_bytes(head) as usize];
        peer.read_exact(&mut body).unwrap();
        peer.write_all(&[0]).unwrap();
        release_rx.recv().unwrap();
    });
    let mut worker = Worker::from_stream(
        socket,
        "a".repeat(64),
        "b".repeat(64),
        support::control(),
        1024 * 1024,
    )
    .unwrap();
    assert!(matches!(
        worker.handshake(Duration::from_millis(20)),
        Err(WorkerError::Unknown(_))
    ));
    release_tx.send(()).unwrap();
    peer_task.join().unwrap();
    let (socket, peer) = UnixStream::pair().unwrap();
    drop(peer);
    let mut worker = Worker::from_stream(
        socket,
        "a".repeat(64),
        "b".repeat(64),
        support::control(),
        1024 * 1024,
    )
    .unwrap();
    assert!(matches!(
        worker.handshake(Duration::from_secs(2)),
        Err(WorkerError::Unknown(_))
    ));
}

#[test]
fn stale_scope_generation_sequence_and_malformed_wire_are_never_accepted() {
    use onlyalpha_gateway_protocol::{
        CalculationRecord, CalculationResponse, calculation_response,
    };
    use prost::Message;
    for variant in 0..7 {
        let (socket, mut peer) = UnixStream::pair().unwrap();
        let task = thread::spawn(move || {
            let mut head = [0; 4];
            peer.read_exact(&mut head).unwrap();
            let mut body = vec![0; u32::from_be_bytes(head) as usize];
            peer.read_exact(&mut body).unwrap();
            let mut response = CalculationResponse {
                protocol_version: 1,
                generation: "a".repeat(64),
                sequence: 1,
                artifact_fingerprint: "b".repeat(64),
                diagnostic_compute_ns: 0,
                outcome: Some(calculation_response::Outcome::Result(CalculationRecord {
                    record_json: br#"{"max_batch":256,"max_instances":16,"schema_version":1}"#
                        .to_vec(),
                })),
            };
            match variant {
                0 => response.generation = "c".repeat(64),
                1 => response.sequence = 2,
                2 => response.artifact_fingerprint = "c".repeat(64),
                3 => response.protocol_version = 2,
                4 => response.outcome = None,
                5 => {
                    response.outcome =
                        Some(calculation_response::Outcome::Result(CalculationRecord {
                            record_json: br#"{"x":1,"x":2}"#.to_vec(),
                        }))
                }
                _ => {}
            }
            let data = if variant == 6 {
                vec![255; 10]
            } else {
                response.encode_to_vec()
            };
            peer.write_all(&(data.len() as u32).to_be_bytes()).unwrap();
            peer.write_all(&data).unwrap();
        });
        let mut worker = Worker::from_stream(
            socket,
            "a".repeat(64),
            "b".repeat(64),
            support::control(),
            1024 * 1024,
        )
        .unwrap();
        assert!(matches!(
            worker.handshake(Duration::from_secs(2)),
            Err(WorkerError::Unknown(_))
        ));
        task.join().unwrap();
    }
}

#[test]
fn chart_operation_uses_the_same_fail_closed_wire_and_does_not_retry() {
    use onlyalpha_gateway_protocol::{CalculationRequest, calculation_request};
    use prost::Message;
    for crash in [false, true] {
        let (socket, mut peer) = UnixStream::pair().unwrap();
        let task = thread::spawn(move || {
            let mut head = [0; 4];
            peer.read_exact(&mut head).unwrap();
            let mut body = vec![0; u32::from_be_bytes(head) as usize];
            peer.read_exact(&mut body).unwrap();
            let request = CalculationRequest::decode(body.as_slice()).unwrap();
            assert!(matches!(
                request.operation,
                Some(calculation_request::Operation::Chart(_))
            ));
            if !crash {
                peer.write_all(&u32::MAX.to_be_bytes()).unwrap();
            }
        });
        let mut worker = Worker::from_stream(
            socket,
            "a".repeat(64),
            "b".repeat(64),
            support::control(),
            1024 * 1024,
        )
        .unwrap();
        for _ in 0..2 {
            assert!(matches!(
                worker.exchange_chart(serde_json::json!({"op":"CATALOG"}), Duration::from_secs(2)),
                Err(WorkerError::Unknown(_))
            ));
        }
        task.join().unwrap();
    }
}
