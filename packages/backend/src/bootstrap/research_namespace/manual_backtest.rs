//! Explicit extension of the same Research semantic store. Reads never repair it.
use super::*;
const MARKER: &str = ".onlyalpha-manual-backtest-owner-extension-v1.json";
const REQUIRED: &str = "RESEARCH_MANUAL_BACKTEST_EXTENSION_REQUIRED";
const MISMATCH: &str = "RESEARCH_MANUAL_BACKTEST_EXTENSION_INVALID";
const POSITIVE: &str = "RESEARCH_MANUAL_BACKTEST_UNPROFILED_HISTORY";
const UNKNOWN: &str = "RESEARCH_MANUAL_BACKTEST_EXTENSION_OUTCOME_UNKNOWN";
pub(crate) fn manual_backtest_policy()
-> std::result::Result<qualification_policy::Policy, qualification_policy::Error> {
    let mut record = json!({"schema_version":1,"policy_id":"manual-backtest","policy_version":"1","gate":"MANUAL_STRATEGY_TO_BACKTEST",
        "missing_evidence_behavior":"FAIL","aggregation":"ALL","criteria":[{"criterion_id":"execution-validation","evidence_kind":"STRATEGY_VALIDATION","metric":"strategy.execution_validation_passed","comparison":"EQ","threshold":"1"}]});
    let mut identity = record.clone();
    identity["domain"] = json!("onlyalpha.strategy.qualification-policy");
    record["policy_fingerprint"] =
        json!(hash(&identity).map_err(|_| qualification_policy::Error::Conflict)?);
    qualification_policy::Policy::from_json(&record.to_string(), STRATEGY_WORK)
}
fn extension(id: &SemanticStoreId) -> Result<Value> {
    let original = strategy_extension(id)?;
    let policy = manual_backtest_policy()
        .map_err(|error| error.code())?
        .to_record();
    let mut value = json!({"schema_version":1,"contract":"ONLYALPHA_MANUAL_BACKTEST_OWNER_EXTENSION_V1","semantic_store_id":id.value(),
        "base_profile_fingerprint":PROFILE_FP,"strategy_extension_fingerprint":original["extension_fingerprint"],
        "qualification_policy":{"policy_id":"manual-backtest","policy_version":"1","policy_fingerprint":policy["policy_fingerprint"]},
        "validation_owner":"backtest/strategy-validation","validation_layout_version":1});
    value["extension_fingerprint"] = json!(hash(&value)?);
    Ok(value)
}
fn present(directory: &Directory, name: &str) -> Result<bool> {
    match fs::statat(&directory.fd, name, fs::AtFlags::SYMLINK_NOFOLLOW) {
        Ok(_) => Ok(true),
        Err(rustix::io::Errno::NOENT) => Ok(false),
        Err(_) => Err(UNAVAILABLE),
    }
}
fn private_directory(directory: &Directory) -> Result<()> {
    let metadata = fs::fstat(&directory.fd).map_err(|_| UNAVAILABLE)?;
    if metadata.st_mode & 0o777 != 0o700 {
        return Err(MISMATCH);
    }
    directory.verify()
}
fn lock_existing(owner: &Directory) -> Result<()> {
    let lock = fs::openat(
        &owner.fd,
        ".source-cut.lock",
        fs::OFlags::RDONLY | fs::OFlags::NOFOLLOW | fs::OFlags::NONBLOCK | fs::OFlags::CLOEXEC,
        fs::Mode::empty(),
    )
    .map_err(|_| UNAVAILABLE)?;
    let metadata = fs::fstat(&lock).map_err(|_| UNAVAILABLE)?;
    if fs::FileType::from_raw_mode(metadata.st_mode) != fs::FileType::RegularFile
        || metadata.st_mode & 0o777 != 0o600
        || metadata.st_nlink != 1
        || metadata.st_size != 0
    {
        return Err(MISMATCH);
    }
    inspect_source_layout(&owner.path)?;
    owner.verify()
}
fn layout(research: &Directory) -> Result<Directory> {
    let owner = research.path(&["backtest", "strategy-validation"], false)?;
    private_directory(&owner)?;
    lock_existing(&owner)?;
    let rows = owner.child("by-preparation", false)?;
    private_directory(&rows)?;
    for name in owner.names()? {
        match name.as_str() {
            ".source-cut.lock" | "by-preparation" => {}
            ".immutable-json-staging" => private_directory(&owner.child(&name, false)?)?,
            _ => return Err(MISMATCH),
        }
    }
    rows.verify()?;
    owner.verify()?;
    Ok(owner)
}
fn policy_existing(research: &Directory) -> Result<()> {
    let store =
        qualification_policy::Store::open(research.fd.as_fd()).map_err(|error| error.code())?;
    if store
        .load_exact("manual-backtest", "1", STRATEGY_WORK)
        .map_err(|error| error.code())?
        != manual_backtest_policy().map_err(|error| error.code())?
    {
        return Err(MISMATCH);
    }
    research.verify()
}
/// Strict observer of committed layout and exact Policy. No parent, lock or file is created.
pub fn open_manual_backtest_existing(user_data: &Path) -> Result<SemanticStoreId> {
    let id = open_strategy_existing(user_data)?;
    let research = Directory::open(&user_data.join("research"))?;
    if !present(&research, MARKER)? {
        return Err(REQUIRED);
    }
    if research.read(MARKER)? != extension(&id)? {
        return Err(MISMATCH);
    }
    layout(&research)?;
    policy_existing(&research)?;
    research.verify()?;
    Ok(id)
}
fn empty_partial(owner: &Directory) -> Result<()> {
    private_directory(owner)?;
    for name in owner.names()? {
        match name.as_str() {
            ".source-cut.lock" => lock_existing(owner)?,
            "by-preparation" | ".immutable-json-staging" => {
                let directory = owner.child(&name, false)?;
                private_directory(&directory)?;
                if !directory.names()?.is_empty() {
                    return Err(POSITIVE);
                }
            }
            _ => return Err(POSITIVE),
        }
    }
    Ok(())
}
fn provision_empty(research: &Directory) -> Result<Directory> {
    // Healthy empty topology from an interrupted explicit extension may continue.
    // Existing permissions, locks or positive history are never repaired/adopted.
    let parent = research.child("backtest", true)?;
    if present(&parent, "strategy-validation")? {
        empty_partial(&parent.child("strategy-validation", false)?)?;
    }
    let owner = parent.child("strategy-validation", true)?;
    private_directory(&owner)?;
    if !present(&owner, ".source-cut.lock")? {
        let lock = fs::openat(
            &owner.fd,
            ".source-cut.lock",
            fs::OFlags::RDWR
                | fs::OFlags::CREATE
                | fs::OFlags::EXCL
                | fs::OFlags::NOFOLLOW
                | fs::OFlags::CLOEXEC,
            fs::Mode::from_raw_mode(0o600),
        )
        .map_err(|_| UNAVAILABLE)?;
        fs::fchmod(&lock, fs::Mode::from_raw_mode(0o600)).map_err(|_| UNAVAILABLE)?;
        fs::fsync(&lock).map_err(|_| UNAVAILABLE)?;
        fs::fsync(&owner.fd).map_err(|_| UNAVAILABLE)?;
    }
    let rows = owner.child("by-preparation", true)?;
    private_directory(&rows)?;
    empty_partial(&owner)?;
    layout(research)
}
/// Operator-only. Retains the original physical Node session through namespace,
/// Policy, source lock and immutable marker publication. Any error revokes it.
pub async fn extend_manual_backtest(
    user_data: &Path,
    session: &mut AuthoritySession,
) -> Result<SemanticStoreId> {
    let mut owned = session.take_ownership();
    let result = extend_owned(user_data, &mut owned).await;
    match result {
        Ok(id) => {
            session.restore_ownership(owned);
            Ok(id)
        }
        Err(code) => {
            let _ = owned.close().await;
            Err(code)
        }
    }
}
async fn extend_owned(user_data: &Path, session: &mut AuthoritySession) -> Result<SemanticStoreId> {
    session.verify().await.map_err(|error| error.code())?;
    let id = open_strategy_existing(user_data)?;
    deployment::verify_binding(
        session.client_mut().await.map_err(|error| error.code())?,
        &id,
    )
    .await
    .map_err(|error| error.code())?;
    let research = Directory::open(&user_data.join("research"))?;
    if present(&research, MARKER)? {
        if open_manual_backtest_existing(user_data)? != id {
            return Err(MISMATCH);
        }
        deployment::verify_binding(
            session.client_mut().await.map_err(|error| error.code())?,
            &id,
        )
        .await
        .map_err(|error| error.code())?;
        session.verify().await.map_err(|error| error.code())?;
        return Ok(id);
    }
    session.verify().await.map_err(|error| error.code())?;
    let owner = provision_empty(&research)?;
    let lock = SourceLock::acquire(&owner.path)?;
    empty_partial(&owner)?;
    let policies =
        qualification_policy::Store::open(research.fd.as_fd()).map_err(|error| error.code())?;
    policies
        .admit(
            session,
            &id,
            &[manual_backtest_policy().map_err(|error| error.code())?],
            STRATEGY_WORK,
        )
        .await
        .map_err(|error| error.code())?;
    policy_existing(&research)?;
    layout(&research)?;
    let auxiliary = research.child(".immutable-json-staging", true)?;
    if fs::fstat(&auxiliary.fd).map_err(|_| UNAVAILABLE)?.st_dev
        != fs::fstat(&research.fd).map_err(|_| UNAVAILABLE)?.st_dev
    {
        return Err(MISMATCH);
    }
    let stage_name = format!(".stage-{}", uuid4()?);
    fs::mkdirat(
        &auxiliary.fd,
        stage_name.as_str(),
        fs::Mode::from_raw_mode(0o700),
    )
    .map_err(|_| UNAVAILABLE)?;
    let stage = auxiliary.child(&stage_name, false)?;
    write_new(&stage, "manifest.json", &extension(&id)?)?;
    fs::fsync(&stage.fd).map_err(|_| UNAVAILABLE)?;
    fs::fsync(&auxiliary.fd).map_err(|_| UNAVAILABLE)?;
    if open_strategy_existing(user_data)? != id {
        return Err(MISMATCH);
    }
    owner.verify()?;
    lock.verify()?;
    empty_partial(&owner)?;
    policy_existing(&research)?;
    deployment::verify_binding(
        session.client_mut().await.map_err(|error| error.code())?,
        &id,
    )
    .await
    .map_err(|error| error.code())?;
    session.verify().await.map_err(|error| error.code())?;
    fs::renameat_with(
        &stage.fd,
        "manifest.json",
        &research.fd,
        MARKER,
        fs::RenameFlags::NOREPLACE,
    )
    .map_err(|_| UNKNOWN)?;
    fs::fsync(&stage.fd).map_err(|_| UNKNOWN)?;
    fs::fsync(&research.fd).map_err(|_| UNKNOWN)?;
    if open_manual_backtest_existing(user_data).map_err(|_| UNKNOWN)? != id {
        return Err(UNKNOWN);
    }
    owner.verify()?;
    lock.verify()?;
    deployment::verify_binding(
        session.client_mut().await.map_err(|error| error.code())?,
        &id,
    )
    .await
    .map_err(|error| error.code())?;
    session.verify().await.map_err(|error| error.code())?;
    Ok(id)
}
