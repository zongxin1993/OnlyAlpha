//! Private-instance pure SHA work and original actual-read/error behavior.
use super::{INVALID, UNAVAILABLE, artifact_digest::ArtifactDigestMemo, verify_read_bytes};
use sha2::{Digest, Sha256};
use std::{
    cell::Cell,
    io::{self, Read},
    rc::Rc,
    sync::{Arc, atomic::Ordering},
};
const SIZE: usize = 1024 * 1024 + 73;
fn expected(bytes: &[u8]) -> String {
    Sha256::digest(bytes)
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect()
}
struct Actual {
    bytes: Vec<u8>,
    at: usize,
    chunk: usize,
    fail_at: Option<usize>,
    read: Rc<Cell<usize>>,
    eof: Rc<Cell<bool>>,
}
impl Read for Actual {
    fn read(&mut self, output: &mut [u8]) -> io::Result<usize> {
        if self.fail_at.is_some_and(|at| self.at >= at) {
            return Err(io::Error::other("controlled late read failure"));
        }
        let end = self.bytes.len().min(self.fail_at.unwrap_or(usize::MAX));
        let n = output.len().min(self.chunk).min(end - self.at);
        output[..n].copy_from_slice(&self.bytes[self.at..self.at + n]);
        self.at += n;
        self.read.set(self.at);
        if n == 0 && !output.is_empty() {
            self.eof.set(true);
        }
        Ok(n)
    }
}
fn actual(
    bytes: &[u8],
    chunk: usize,
    fail_at: Option<usize>,
) -> (Actual, Rc<Cell<usize>>, Rc<Cell<bool>>) {
    let read = Rc::new(Cell::new(0));
    let eof = Rc::new(Cell::new(false));
    (
        Actual {
            bytes: bytes.to_vec(),
            at: 0,
            chunk,
            fail_at,
            read: read.clone(),
            eof: eof.clone(),
        },
        read,
        eof,
    )
}
fn verify(memo: &ArtifactDigestMemo, bytes: &[u8], digest: &str) -> &'static str {
    let (reader, read, eof) = actual(bytes, 65536, None);
    let result = verify_read_bytes(reader, digest, bytes.len() as u64, memo);
    assert_eq!(read.get(), bytes.len());
    assert!(eof.get());
    result.err().unwrap_or("OK")
}
#[test]
fn matching_warm_content_reuses_only_sha_and_still_reads_all_actual_bytes_to_eof() {
    let memo = ArtifactDigestMemo::new();
    let bytes = vec![37; SIZE];
    let digest = expected(&bytes);
    assert_eq!(verify(&memo, &bytes, &digest), "OK");
    assert_eq!(memo.hashed_bytes.load(Ordering::Relaxed), SIZE as u64);
    memo.hashed_bytes.store(0, Ordering::Relaxed);
    let (reader, read, eof) = actual(&bytes, 8191, None);
    assert_eq!(
        verify_read_bytes(reader, &digest, SIZE as u64, &memo),
        Ok(())
    );
    assert_eq!(read.get(), SIZE);
    assert!(eof.get());
    assert_eq!(memo.hashed_bytes.load(Ordering::Relaxed), 0);
    assert_eq!(verify(&memo, &bytes, &"0".repeat(64)), INVALID);
    assert_eq!(memo.hashed_bytes.load(Ordering::Relaxed), 0);
}
#[test]
fn first_middle_and_last_divergence_rehash_the_actual_prefix_without_replacing_first_slot() {
    let memo = ArtifactDigestMemo::new();
    let original = vec![37; SIZE];
    assert_eq!(verify(&memo, &original, &expected(&original)), "OK");
    for offset in [0, 65536 + 17, SIZE - 1] {
        let mut different = original.clone();
        different[offset] ^= 7;
        memo.hashed_bytes.store(0, Ordering::Relaxed);
        assert_eq!(verify(&memo, &different, &expected(&different)), "OK");
        assert_eq!(memo.hashed_bytes.load(Ordering::Relaxed), SIZE as u64);
        assert_eq!(verify(&memo, &different, &expected(&original)), INVALID);
        memo.hashed_bytes.store(0, Ordering::Relaxed);
        assert_eq!(verify(&memo, &original, &expected(&original)), "OK");
        assert_eq!(memo.hashed_bytes.load(Ordering::Relaxed), 0);
    }
}
#[test]
fn mismatch_never_hides_a_later_actual_io_failure_or_checks_expected_early() {
    let memo = ArtifactDigestMemo::new();
    let original = vec![37; SIZE];
    assert_eq!(verify(&memo, &original, &expected(&original)), "OK");
    let mut different = original.clone();
    different[65536 + 17] ^= 7;
    for bytes in [&original, &different] {
        let (reader, read, eof) = actual(bytes, 8191, Some(SIZE - 5));
        assert_eq!(
            verify_read_bytes(reader, &"0".repeat(64), SIZE as u64, &memo),
            Err(UNAVAILABLE)
        );
        assert_eq!(read.get(), SIZE - 5);
        assert!(!eof.get());
    }
}
#[test]
fn incomplete_growing_or_failed_capture_does_not_publish_partial_data() {
    for kind in ["short", "long", "io"] {
        let memo = ArtifactDigestMemo::new();
        let expected_bytes = vec![37; SIZE];
        let mut bytes = expected_bytes.clone();
        if kind == "short" {
            bytes.pop();
        }
        if kind == "long" {
            bytes.push(1);
        }
        let (reader, read, _) = actual(
            &bytes,
            65536,
            if kind == "io" { Some(SIZE - 5) } else { None },
        );
        let result = verify_read_bytes(reader, &expected(&expected_bytes), SIZE as u64, &memo);
        assert_eq!(
            result,
            Err(if kind == "io" { UNAVAILABLE } else { INVALID })
        );
        assert_eq!(
            read.get(),
            if kind == "io" { SIZE - 5 } else { bytes.len() }
        );
        assert!(memo.slot.lock().unwrap().is_none());
        assert!(!memo.capturing.load(Ordering::Acquire));
    }
}
#[test]
fn small_content_lock_competition_and_poison_use_original_cold_work() {
    let memo = ArtifactDigestMemo::new();
    let small = vec![37; 65536];
    for _ in 0..2 {
        assert_eq!(verify(&memo, &small, &expected(&small)), "OK");
    }
    assert_eq!(
        memo.hashed_bytes.load(Ordering::Relaxed),
        2 * small.len() as u64
    );
    assert!(memo.slot.lock().unwrap().is_none());
    let bytes = vec![37; SIZE];
    let digest = expected(&bytes);
    let guard = memo.slot.lock().unwrap();
    assert_eq!(verify(&memo, &bytes, &digest), "OK");
    drop(guard);
    assert!(memo.slot.lock().unwrap().is_none());
    memo.capturing.store(true, Ordering::Release);
    assert_eq!(verify(&memo, &bytes, &digest), "OK");
    assert!(memo.slot.lock().unwrap().is_none());
    memo.capturing.store(false, Ordering::Release);
    let poisoned = Arc::new(ArtifactDigestMemo::new());
    let copy = poisoned.clone();
    assert!(
        std::thread::spawn(move || {
            let _guard = copy.slot.lock().unwrap();
            panic!("controlled poison");
        })
        .join()
        .is_err()
    );
    assert_eq!(verify(&poisoned, &bytes, &digest), "OK");
    assert_eq!(poisoned.hashed_bytes.load(Ordering::Relaxed), SIZE as u64);
}
#[test]
fn declared_content_outside_slot_bound_cannot_reserve_or_allocate_a_capture() {
    let memo = ArtifactDigestMemo::new();
    let stream = memo.stream(64 * 1024 * 1024 + 1);
    assert!(!memo.capturing.load(Ordering::Acquire));
    drop(stream);
    assert!(memo.slot.lock().unwrap().is_none());
}
#[test]
fn warm_content_cannot_replace_protected_open_mode_size_or_missing_file_checks() {
    use std::{
        io::{Seek, SeekFrom, Write},
        os::unix::fs::{DirBuilderExt, OpenOptionsExt, PermissionsExt},
    };
    let mut entropy = [0; 16];
    getrandom::fill(&mut entropy).unwrap();
    struct Directory(std::path::PathBuf);
    impl Drop for Directory {
        fn drop(&mut self) {
            std::fs::remove_dir_all(&self.0).unwrap();
        }
    }
    let directory =
        Directory(std::env::temp_dir().join(format!("runtime-artifact-digest-{entropy:?}")));
    std::fs::DirBuilder::new()
        .mode(0o700)
        .create(&directory.0)
        .unwrap();
    let path = directory.0.join("artifact.elf");
    let bytes = vec![37; SIZE];
    let digest = expected(&bytes);
    let memo = ArtifactDigestMemo::new();
    let mut file = std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(&path)
        .unwrap();
    file.write_all(&bytes).unwrap();
    drop(file);
    let root = super::protected::open_directory(&directory.0).unwrap();
    assert_eq!(
        super::verify_bytes_using(&root, "artifact.elf", &digest, SIZE as u64, &memo),
        Ok(())
    );
    memo.hashed_bytes.store(0, Ordering::Relaxed);
    super::metadata_read_tests::SCANNED_BYTES.with(|n| n.set(0));
    assert_eq!(
        super::verify_bytes_using(&root, "artifact.elf", &digest, SIZE as u64, &memo),
        Ok(())
    );
    super::metadata_read_tests::SCANNED_BYTES.with(|n| assert_eq!(n.get(), SIZE as u64));
    assert_eq!(memo.hashed_bytes.load(Ordering::Relaxed), 0);
    let offset = 65536 + 17;
    let mut changed = bytes.clone();
    changed[offset] ^= 7;
    let write_middle = |value: u8| {
        let mut file = std::fs::OpenOptions::new().write(true).open(&path).unwrap();
        file.seek(SeekFrom::Start(offset as u64)).unwrap();
        file.write_all(&[value]).unwrap();
    };
    write_middle(changed[offset]);
    let changed_digest = expected(&changed);
    for (expected_digest, result) in [(&digest, Err(INVALID)), (&changed_digest, Ok(()))] {
        memo.hashed_bytes.store(0, Ordering::Relaxed);
        super::metadata_read_tests::SCANNED_BYTES.with(|n| n.set(0));
        assert_eq!(
            super::verify_bytes_using(&root, "artifact.elf", expected_digest, SIZE as u64, &memo),
            result
        );
        super::metadata_read_tests::SCANNED_BYTES.with(|n| assert_eq!(n.get(), SIZE as u64));
        assert_eq!(memo.hashed_bytes.load(Ordering::Relaxed), SIZE as u64);
    }
    write_middle(bytes[offset]);
    memo.hashed_bytes.store(0, Ordering::Relaxed);
    super::metadata_read_tests::SCANNED_BYTES.with(|n| n.set(0));
    assert_eq!(
        super::verify_bytes_using(&root, "artifact.elf", &digest, SIZE as u64, &memo),
        Ok(())
    );
    super::metadata_read_tests::SCANNED_BYTES.with(|n| assert_eq!(n.get(), SIZE as u64));
    assert_eq!(memo.hashed_bytes.load(Ordering::Relaxed), 0);
    super::metadata_read_tests::SCANNED_BYTES.with(|n| n.set(0));
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o666)).unwrap();
    assert_eq!(
        super::verify_bytes_using(&root, "artifact.elf", &digest, SIZE as u64, &memo),
        Err(INVALID)
    );
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600)).unwrap();
    assert_eq!(
        super::verify_bytes_using(&root, "artifact.elf", &digest, SIZE as u64 + 1, &memo),
        Err(INVALID)
    );
    let alias = directory.0.join("alias.elf");
    std::fs::hard_link(&path, &alias).unwrap();
    assert_eq!(
        super::verify_bytes_using(&root, "artifact.elf", &digest, SIZE as u64, &memo),
        Err(INVALID)
    );
    std::fs::remove_file(&alias).unwrap();
    std::fs::remove_file(&path).unwrap();
    assert_eq!(
        super::verify_bytes_using(&root, "artifact.elf", &digest, SIZE as u64, &memo),
        Err(UNAVAILABLE)
    );
    super::metadata_read_tests::SCANNED_BYTES.with(|n| assert_eq!(n.get(), 0));
}

#[test]
fn cold_wrong_expected_may_retain_pure_digest_but_never_a_successful_verdict() {
    let memo = ArtifactDigestMemo::new();
    let bytes = vec![37; SIZE];
    let wrong = "0".repeat(64);
    assert_eq!(verify(&memo, &bytes, &wrong), INVALID);
    assert_eq!(memo.hashed_bytes.load(Ordering::Relaxed), SIZE as u64);
    assert!(memo.slot.lock().unwrap().is_some());
    memo.hashed_bytes.store(0, Ordering::Relaxed);
    assert_eq!(verify(&memo, &bytes, &wrong), INVALID);
    assert_eq!(memo.hashed_bytes.load(Ordering::Relaxed), 0);
    assert_eq!(verify(&memo, &bytes, &expected(&bytes)), "OK");
    assert_eq!(memo.hashed_bytes.load(Ordering::Relaxed), 0);
}
