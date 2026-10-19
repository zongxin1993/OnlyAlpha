const FIXTURE: &str = include_str!("../../../../test-data/execution/domain-inputs.json");
mod support;
use onlyalpha_execution::{
    CommitIntent, Components, Error, Prepared, Record, Store, coordinate, pending_events, recover,
};
use serde_json::{Value, json};
use std::{
    fs::{self, File},
    io::Write,
    path::PathBuf,
};
use support::*;
// This real-file test adapter is outside the semantic library. It is not a Runtime Store implementation.
struct FileStore {
    path: PathBuf,
    fail: Option<&'static str>,
}
impl FileStore {
    fn new(name: &str) -> Self {
        let path = std::env::temp_dir().join(format!(
            "onlyalpha-execution-{}-{name}.json",
            std::process::id()
        ));
        assert!(!path.exists());
        let s = Self { path, fail: None };
        s.write(&json!([])).unwrap();
        s
    }
    fn read(&self) -> Result<Value, Error> {
        serde_json::from_slice(&fs::read(&self.path).map_err(|e| Error(e.to_string()))?)
            .map_err(Into::into)
    }
    fn write(&self, v: &Value) -> Result<(), Error> {
        let temp = self.path.with_extension("pending");
        let mut f = File::create(&temp).map_err(|e| Error(e.to_string()))?;
        f.write_all(&serde_json::to_vec(v)?)
            .map_err(|e| Error(e.to_string()))?;
        f.sync_all().map_err(|e| Error(e.to_string()))?;
        fs::rename(temp, &self.path).map_err(|e| Error(e.to_string()))?;
        File::open(self.path.parent().unwrap())
            .and_then(|f| f.sync_all())
            .map_err(|e| Error(e.to_string()))?;
        Ok(())
    }
    fn persist(&mut self, c: &mut Components, p: &Prepared) {
        self.fail = Some("commit-after");
        assert!(coordinate(self, c, p).is_err());
        self.fail = None;
        assert_eq!(self.get(p.sequence()).unwrap().unwrap().prepared(), p);
    }
    fn fault(&self, name: &str) -> Result<(), Error> {
        if self.fail == Some(name) {
            return Err(Error(format!("injected-{name}")));
        }
        Ok(())
    }
}
impl Store for FileStore {
    fn head(&self) -> Result<u64, Error> {
        Ok(self.read()?.as_array().unwrap().len() as u64)
    }
    fn commit(&mut self, intent: &CommitIntent) -> Result<Record, Error> {
        let p = intent.prepared();
        self.fault("commit-before")?;
        let mut v = self.read()?;
        let rows = v.as_array_mut().unwrap();
        if let Some(old) = rows
            .iter()
            .find(|r| r["prepared"]["input"]["input_id"] == p.input()["input_id"])
        {
            let existing = Record::decode(old)?;
            if existing.prepared() != p {
                return Err(Error("STORE_CONFLICT".into()));
            }
            return Ok(existing);
        }
        if p.sequence() != rows.len() as u64 + 1 {
            return Err(Error("STORE_SEQUENCE".into()));
        }
        let record = Record::new(intent);
        rows.push(record.record());
        self.write(&v)?;
        self.fault("commit-after")?;
        Ok(record)
    }
    fn get(&self, sequence: u64) -> Result<Option<Record>, Error> {
        let v = self.read()?;
        v.as_array()
            .unwrap()
            .get((sequence - 1) as usize)
            .map(Record::decode)
            .transpose()
    }
    fn mark_ready(&mut self, sequence: u64) -> Result<(), Error> {
        self.fault("ready-before")?;
        let mut v = self.read()?;
        v[(sequence - 1) as usize]["ready"] = json!(true);
        self.write(&v)?;
        self.fault("ready-after")
    }
    fn acknowledge(&mut self, sequence: u64) -> Result<(), Error> {
        let mut v = self.read()?;
        if v[(sequence - 1) as usize]["ready"] != true {
            return Err(Error("NOT_READY".into()));
        }
        v[(sequence - 1) as usize]["delivered"] = json!(true);
        self.write(&v)
    }
}
impl Drop for FileStore {
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.path);
    }
}
fn commit(s: &mut FileStore, c: &mut Components, input: &Value) {
    let p = c.prepare(s, input).unwrap();
    coordinate(s, c, &p).unwrap();
}
#[test]
fn commit_failure_and_unknown_commit_never_mutate_components() {
    for mode in ["commit-before", "commit-after"] {
        let mut s = FileStore::new(mode);
        let mut c = Components::new(config()).unwrap();
        let before = c.checkpoint().unwrap();
        let p = c.prepare(&s, &open(1, "BUY")).unwrap();
        s.fail = Some(mode);
        assert!(coordinate(&mut s, &mut c, &p).is_err());
        assert_eq!(c.checkpoint().unwrap(), before);
        assert!(pending_events(&s, &c).unwrap().is_empty());
        s.fail = None;
        coordinate(&mut s, &mut c, &p).unwrap();
        assert_eq!(pending_events(&s, &c).unwrap().len(), 1);
        coordinate(&mut s, &mut c, &p).unwrap();
        assert_eq!(pending_events(&s, &c).unwrap().len(), 1);
    }
}
#[test]
fn every_partial_projection_recovers_from_real_file_reopen() {
    for cut in 0..=6 {
        let mut s = FileStore::new(&format!("cut-{cut}"));
        let mut c = Components::new(config()).unwrap();
        let p = c.prepare(&s, &open(1, "BUY")).unwrap();
        s.persist(&mut c, &p);
        for i in 0..cut {
            c.install_projection(&s, &p, i).unwrap();
        }
        assert!(pending_events(&s, &c).unwrap().is_empty());
        let cp = c.checkpoint().unwrap();
        let mut fresh = Components::new(config()).unwrap();
        fresh
            .restore(
                &cp,
                &onlyalpha_execution::digest(&serde_json::to_vec(&cp).unwrap()),
            )
            .unwrap();
        let path = s.path.clone();
        std::mem::forget(s);
        let mut reopened = FileStore { path, fail: None };
        recover(&mut reopened, &mut fresh).unwrap();
        let mut expected = Components::new(config()).unwrap();
        for i in 0..6 {
            expected.install_projection(&reopened, &p, i).unwrap();
        }
        expected.complete(&reopened, &p).unwrap();
        assert_eq!(fresh.checkpoint().unwrap(), expected.checkpoint().unwrap());
        assert_eq!(pending_events(&reopened, &fresh).unwrap().len(), 1);
        reopened.acknowledge(1).unwrap();
        assert!(pending_events(&reopened, &fresh).unwrap().is_empty());
    }
}
#[test]
fn ready_faults_keep_queries_hidden_and_rehydrate_ready_history() {
    for mode in ["ready-before", "ready-after"] {
        let mut s = FileStore::new(mode);
        let mut c = Components::new(config()).unwrap();
        let p = c.prepare(&s, &open(1, "BUY")).unwrap();
        s.fail = Some(mode);
        assert!(coordinate(&mut s, &mut c, &p).is_err());
        assert!(c.state(&s).is_err());
        s.fail = None;
        recover(&mut s, &mut c).unwrap();
        commit(&mut s, &mut c, &stage(2, 1, "UNKNOWN"));
        commit(&mut s, &mut c, &fill(3, 1, "1", "10.00", "1.00"));
        let expected = c.checkpoint().unwrap();
        let mut fresh = Components::new(config()).unwrap();
        recover(&mut s, &mut fresh).unwrap();
        assert_eq!(fresh.checkpoint().unwrap(), expected);
    }
}
#[test]
fn unready_predecessor_conflicts_and_corruption_fail_closed() {
    let mut s = FileStore::new("predecessor");
    let mut c = Components::new(config()).unwrap();
    let p = c.prepare(&s, &open(1, "BUY")).unwrap();
    s.persist(&mut c, &p);
    let mut next = Components::new(config()).unwrap();
    let mut other = FileStore::new("predecessor-ready-copy");
    other.persist(&mut next, &p);
    for i in 0..6 {
        next.install_projection(&other, &p, i).unwrap();
    }
    other.mark_ready(1).unwrap();
    next.complete(&other, &p).unwrap();
    let p2 = next.prepare(&other, &stage(2, 1, "UNKNOWN")).unwrap();
    assert!(coordinate(&mut s, &mut c, &p2).is_err());
    assert!(pending_events(&s, &c).unwrap().is_empty());
    let before = c.checkpoint().unwrap();
    let mut rows = s.read().unwrap();
    rows[0]["prepared"]["input"]["account"] = json!("foreign");
    s.write(&rows).unwrap();
    assert!(recover(&mut s, &mut c).is_err());
    assert_eq!(before, c.checkpoint().unwrap());
}

#[test]
fn decoded_payload_cannot_be_submitted_as_a_new_planner_authority() {
    let mut s = FileStore::new("transport-admission");
    let mut c = Components::new(config()).unwrap();
    let p = c.prepare(&s, &open(1, "BUY")).unwrap();
    let decoded = Prepared::decode(&p.encode().unwrap()).unwrap();
    let before = c.checkpoint().unwrap();
    assert!(coordinate(&mut s, &mut c, &decoded).is_err());
    assert_eq!(c.checkpoint().unwrap(), before);
    assert!(s.get(1).unwrap().is_none());
}

#[test]
fn failed_ready_keeps_new_plans_blocked_and_missing_apply_index_is_recoverable() {
    let mut s = FileStore::new("missing-apply-index");
    let mut c = Components::new(config()).unwrap();
    let p = c.prepare(&s, &open(1, "BUY")).unwrap();
    s.persist(&mut c, &p);
    c.install_projection(&s, &p, 0).unwrap();
    let mut cp = c.checkpoint().unwrap();
    cp["pending"][1] = json!(0);
    let mut fresh = Components::new(config()).unwrap();
    fresh
        .restore(
            &cp,
            &onlyalpha_execution::digest(&serde_json::to_vec(&cp).unwrap()),
        )
        .unwrap();
    assert!(fresh.prepare(&s, &open(2, "BUY")).is_err());
    recover(&mut s, &mut fresh).unwrap();
    assert_eq!(pending_events(&s, &c).unwrap().len(), 1);
}

#[test]
fn subprocess_recovery_child() {
    let Ok(path) = std::env::var("ONLYALPHA_EXECUTION_TEST_STORE") else {
        return;
    };
    let mut store = FileStore {
        path: PathBuf::from(path),
        fail: None,
    };
    let mut c = Components::new(config()).unwrap();
    recover(&mut store, &mut c).unwrap();
    println!("RECOVERED_COMPONENTS_JSON {}", c.checkpoint().unwrap());
    std::mem::forget(store);
}
#[test]
fn committed_fill_rehydrates_in_a_real_fresh_process() {
    let mut s = FileStore::new("fresh-process");
    let mut c = Components::new(config()).unwrap();
    commit(&mut s, &mut c, &open(1, "BUY"));
    commit(&mut s, &mut c, &stage(2, 1, "UNKNOWN"));
    let p = c.prepare(&s, &fill(3, 1, "1", "10.00", "1.00")).unwrap();
    s.persist(&mut c, &p);
    for i in 0..3 {
        c.install_projection(&s, &p, i).unwrap();
    }
    let output = std::process::Command::new(std::env::current_exe().unwrap())
        .args([
            "--exact",
            "subprocess_recovery_child",
            "--nocapture",
            "--test-threads=1",
        ])
        .env("ONLYALPHA_EXECUTION_TEST_STORE", &s.path)
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let stdout = String::from_utf8(output.stdout).unwrap();
    let line = stdout
        .lines()
        .find(|l| l.contains("RECOVERED_COMPONENTS_JSON "))
        .unwrap();
    let restored: Value =
        serde_json::from_str(line.split_once("RECOVERED_COMPONENTS_JSON ").unwrap().1).unwrap();
    let mut fresh = Components::new(config()).unwrap();
    recover(&mut s, &mut fresh).unwrap();
    assert_eq!(fresh.checkpoint().unwrap(), restored);
    assert_eq!(
        fresh.state(&s).unwrap()["account"]["snapshot"]["cash"],
        "989.00"
    );
}
