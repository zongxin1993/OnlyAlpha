//! Explicit deployment provisioning of a fresh Research semantic namespace.
//! Normal Product preparation only opens verified existing owners; it never repairs history.
use crate::{
    application::{factor_content::hash, qualification_policy, research_novelty as contract},
    bootstrap::deployment::{self, SemanticStoreId},
    persistence::{authority_session::AuthoritySession, research_dataset, research_evidence, research_novelty::Authority},
    security::{
        immutable_json::{Directory, SourceLock, inspect_source_layout, put, read_path},
        protected_files::{self, FilePolicy},
    },
};
use rustix::fs;
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, BTreeSet},
    fs::File,
    io::Write,
    os::fd::AsFd,
    path::{Path, PathBuf},
};
type Result<T> = std::result::Result<T, &'static str>;
const INVALID: &str = "RESEARCH_OWNER_PROFILE_INVALID";
const UNAVAILABLE: &str = "RESEARCH_OWNER_PROFILE_UNAVAILABLE";
const PROFILE_FILE: &str = ".onlyalpha-factor-research-owner-profile.json";
const STRATEGY_EXTENSION_FILE: &str = ".onlyalpha-strategy-research-owner-extension-v1.json";
const STRATEGY_WORK: usize = 64 * 1024 * 1024;
const FAMILIES: [(&str, &str, u64); 7] = [
    ("AGENT_PROVENANCE", "agent-provenance", 2),
    ("QUALIFICATION_DECISION", "qualification-decisions", 1),
    ("RESEARCH_FACTOR_PAIR_STATISTICS", "statistics-results", 1),
    ("RESEARCH_RESULT", "results", 3),
    ("RESEARCH_STATISTICS", "statistics-results", 2),
    ("RESEARCH_SUMMARY_STATISTICS", "statistics-results", 1),
    ("SEARCH_PROVENANCE", "search-provenance", 3),
];
const POLICY_FP: &str = "84c78af3aa013a6b8c74cb73c85b2ee94ea641305dcdda5c5a780ca88b6d1d5b";
const PROFILE_FP: &str = "e65c1f68866533f9779f85f6f254ce1b43115ea22b6a33bb4cd7af31ba8fc01b";
/// Frozen owner-selected policy, in the original signed Policy identity domain.
/// Constants are independently checked against the original parser on every open.
pub fn policy() -> Value {
    let rules = [
        ("CERTIFIED_NO_MATCH", "ADMIT"),
        ("EXACT_COMPLETED_EVALUATION", "REUSE"),
        ("EXACT_COMPLETED_NEGATIVE_EVIDENCE", "SUPPRESS"),
        ("OPERATIONAL_FAILURE", "REVIEW"),
        ("PROOF_INCOMPLETE", "FAIL_CLOSED"),
        ("PROOF_UNAVAILABLE", "FAIL_CLOSED"),
        ("SEARCH_OR_BUDGET_STOP", "REVIEW"),
    ];
    json!({"schema_version":1,"policy_id":"onlyalpha.factor-research","policy_version":"1",
        "rules":rules.into_iter().map(|(condition,outcome)|json!({"condition":condition,"outcome":outcome})).collect::<Vec<_>>(),"policy_fingerprint":POLICY_FP})
}
pub fn profile() -> Value {
    json!({"schema_version":1,"contract":"ONLYALPHA_FACTOR_RESEARCH_OWNER_PROFILE_V1",
        "file_source_families":FAMILIES.into_iter().map(|(family,owner,version)|json!({"family":family,"owner":owner,"source_schema_version":version,"enumeration_contract_version":1})).collect::<Vec<_>>(),
        "postgres_source_families":["PRODUCT_COMMAND_ADMISSION","PRODUCT_COMMAND_RECEIPT","RESEARCH_ATTEMPT","RESEARCH_RUN"],
        "policy_id":"onlyalpha.factor-research","policy_version":"1","policy_fingerprint":POLICY_FP,"profile_fingerprint":PROFILE_FP})
}
pub fn source_roots(user_data: &Path) -> BTreeMap<String, PathBuf> {
    FAMILIES
        .into_iter()
        .map(|(family, owner, _)| (family.to_owned(), user_data.join("research").join(owner)))
        .collect()
}
fn validate_configuration() -> Result<()> {
    let mut selected = profile();
    selected
        .as_object_mut()
        .ok_or(INVALID)?
        .remove("profile_fingerprint");
    if hash(&selected)? != PROFILE_FP {
        return Err(INVALID);
    }
    contract::policy(&policy(), "onlyalpha.factor-research", "1")
}
fn write_new(directory: &Directory, name: &str, value: &Value) -> Result<()> {
    let bytes =
        onlyalpha_metadata_json::canonical_json(&value.to_string(), 32768).map_err(|_| INVALID)?;
    let fd = fs::openat(
        &directory.fd,
        name,
        fs::OFlags::WRONLY
            | fs::OFlags::CREATE
            | fs::OFlags::EXCL
            | fs::OFlags::NOFOLLOW
            | fs::OFlags::CLOEXEC,
        fs::Mode::from_raw_mode(0o600),
    )
    .map_err(|_| UNAVAILABLE)?;
    let mut file = File::from(fd);
    file.write_all(bytes.as_bytes()).map_err(|_| UNAVAILABLE)?;
    fs::fchmod(&file, fs::Mode::from_raw_mode(0o400)).map_err(|_| UNAVAILABLE)?;
    file.sync_all().map_err(|_| UNAVAILABLE)
}
fn source_owner(root: &Directory, name: &str) -> Result<()> {
    fs::mkdirat(&root.fd, name, fs::Mode::from_raw_mode(0o700)).map_err(|_| UNAVAILABLE)?;
    let owner = root.child(name, false)?;
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
    owner.child("sha256", true)?;
    fs::fsync(&owner.fd).map_err(|_| UNAVAILABLE)
}
fn uuid4() -> Result<String> {
    let mut bytes = [0_u8; 16];
    getrandom::fill(&mut bytes).map_err(|_| UNAVAILABLE)?;
    bytes[6] = (bytes[6] & 15) | 64;
    bytes[8] = (bytes[8] & 63) | 128;
    let raw = bytes.iter().map(|b| format!("{b:02x}")).collect::<String>();
    Ok(format!(
        "{}-{}-{}-{}-{}",
        &raw[..8],
        &raw[8..12],
        &raw[12..16],
        &raw[16..20],
        &raw[20..]
    ))
}
/// Operator infrastructure only. Positive preexisting state is never a fresh token.
/// All owner creation happens in this function's exclusively reserved unpublished directory.
pub fn initialize_fresh(user_data: &Path) -> Result<SemanticStoreId> {
    validate_configuration()?;
    let parent = Directory::open(user_data)?;
    match fs::statat(&parent.fd, "research", fs::AtFlags::SYMLINK_NOFOLLOW) {
        Err(rustix::io::Errno::NOENT) => {}
        _ => return Err("RESEARCH_NAMESPACE_INITIALIZATION_CONFLICT"),
    }
    let id = SemanticStoreId::new(&uuid4()?).map_err(|_| INVALID)?;
    let stage = format!(".research-initialization-{}", uuid4()?);
    fs::mkdirat(&parent.fd, stage.as_str(), fs::Mode::from_raw_mode(0o700))
        .map_err(|_| UNAVAILABLE)?;
    let held = parent.child(&stage, false)?;
    // No API/JSON can present this directory as an existing owner: it was just reserved O_EXCL.
    write_new(
        &held,
        ".onlyalpha-semantic-store.json",
        &json!({"schema_version":1,"store_id":id.value()}),
    )?;
    research_evidence::initialize_fresh_owners(&held.path)?;
    for owner in [
        "agent-provenance",
        "qualification-decisions",
        "search-provenance",
    ] {
        source_owner(&held, owner)?;
    }
    for parts in [
        vec!["datasets", "sha256"],
        vec!["datasets", "materializations", "sha256"],
        vec!["dataset-economic-bindings"],
        vec!["experiment-memory"],
        vec!["novelty-decision-groups"],
        vec!["novelty-decisions"],
        vec!["novelty-decision-authority-locks"],
    ] {
        held.path(&parts, true)?;
    }
    // Original Policy wire format is canonical JSON without a terminal LF.
    put(
        &held,
        &["novelty-policies", "onlyalpha.factor-research", "1"],
        "manifest.json",
        &policy(),
    )?;
    write_new(&held, PROFILE_FILE, &profile())?;
    fs::fsync(&held.fd).map_err(|_| UNAVAILABLE)?;
    parent.verify()?;
    held.verify()?;
    fs::renameat_with(
        &parent.fd,
        stage.as_str(),
        &parent.fd,
        "research",
        fs::RenameFlags::NOREPLACE,
    )
    .map_err(|_| "RESEARCH_NAMESPACE_INITIALIZATION_CONFLICT")?;
    fs::fsync(&parent.fd).map_err(|_| "RESEARCH_NAMESPACE_OUTCOME_UNKNOWN")?;
    let published = parent
        .child("research", false)
        .map_err(|_| "RESEARCH_NAMESPACE_OUTCOME_UNKNOWN")?;
    let old = fs::fstat(&held.fd).map_err(|_| "RESEARCH_NAMESPACE_OUTCOME_UNKNOWN")?;
    let actual = fs::fstat(&published.fd).map_err(|_| "RESEARCH_NAMESPACE_OUTCOME_UNKNOWN")?;
    if old.st_dev != actual.st_dev || old.st_ino != actual.st_ino {
        return Err("RESEARCH_NAMESPACE_OUTCOME_UNKNOWN");
    }
    let observed = open_existing(user_data).map_err(|_| "RESEARCH_NAMESPACE_OUTCOME_UNKNOWN")?;
    if observed != id {
        return Err("RESEARCH_NAMESPACE_OUTCOME_UNKNOWN");
    }
    Ok(id)
}
/// Read existing deployment structure only. It does not certify empty history or issue cuts.
pub fn open_existing(user_data: &Path) -> Result<SemanticStoreId> {
    validate_configuration()?;
    let parent = Directory::open(user_data)?;
    let research = parent.child("research", false)?;
    let id = deployment::load_semantic_store_id_at(&research.fd).map_err(|_| INVALID)?;
    if research.read(PROFILE_FILE)? != profile() {
        return Err(INVALID);
    }
    let actual = read_path(
        &research,
        &["novelty-policies", "onlyalpha.factor-research", "1"],
        "manifest.json",
    )?;
    contract::policy(&actual, "onlyalpha.factor-research", "1")?;
    if actual != policy() {
        return Err(INVALID);
    }
    research_evidence::Store::inspect_layout(&research.path)?;
    research_dataset::Store::open(&research.path.join("datasets"), 8192, 8 * 1024 * 1024)?;
    for parts in [
        vec!["datasets", "sha256"],
        vec!["datasets", "materializations", "sha256"],
        vec!["dataset-economic-bindings"],
        vec!["experiment-memory"],
        vec!["novelty-decision-groups"],
        vec!["novelty-decisions"],
        vec!["novelty-decision-authority-locks"],
    ] {
        research.path(&parts, false)?;
    }
    let paths = source_roots(user_data)
        .into_values()
        .collect::<BTreeSet<_>>();
    for path in paths {
        let owner = Directory::open(&path)?;
        let sha = owner.child("sha256", false)?;
        inspect_source_layout(&path)?;
        sha.verify()?;
        owner.verify()?;
    }
    research.verify()?;
    parent.verify()?;
    let retained = protected_files::read_file_at(
        &research.fd,
        ".onlyalpha-semantic-store.json".as_ref(),
        FilePolicy::Metadata,
        32768,
    )
    .map_err(|_| UNAVAILABLE)?;
    if SemanticStoreId::from_document(std::str::from_utf8(&retained).map_err(|_| INVALID)?)
        .map_err(|_| INVALID)?
        != id
    {
        return Err(INVALID);
    }
    Ok(id)
}

/// Experimental evidence-completeness gate. It makes no profitability claim.
pub(crate) fn experimental_backtest_policy() -> std::result::Result<qualification_policy::Policy, qualification_policy::Error> {
    let mut record=serde_json::json!({"schema_version":1,"policy_id":"experimental-backtest","policy_version":"1","gate":"RESEARCH_TO_BACKTEST",
        "missing_evidence_behavior":"FAIL","aggregation":"ALL","criteria":[
        {"criterion_id":"calculation-count","evidence_kind":"RESEARCH_RESULT","metric":"research.calculation_result_count","comparison":"GE","threshold":"1"},
        {"criterion_id":"statistics-count","evidence_kind":"RESEARCH_RESULT","metric":"research.statistics_result_count","comparison":"GE","threshold":"2"}]});
    let mut identity=record.clone();identity["domain"]=serde_json::json!("onlyalpha.strategy.qualification-policy");
    record["policy_fingerprint"]=serde_json::json!(hash(&identity).map_err(|_|qualification_policy::Error::Conflict)?);
    qualification_policy::Policy::from_json(&record.to_string(),STRATEGY_WORK)
}
fn strategy_extension(id: &SemanticStoreId) -> Result<Value> {
    let mut value=json!({"schema_version":1,"contract":"ONLYALPHA_STRATEGY_RESEARCH_OWNER_EXTENSION_V1",
        "semantic_store_id":id.value(),"base_profile_fingerprint":PROFILE_FP,
        "file_source_extensions":[{"family":"QUALIFICATION_DECISION","owner":"strategy/qualification-decisions","source_schema_version":1,"enumeration_contract_version":2}]});
    value["extension_fingerprint"]=json!(hash(&value)?);
    Ok(value)
}
fn strategy_extension_present(research: &Directory) -> Result<bool> {
    match fs::statat(&research.fd, STRATEGY_EXTENSION_FILE, fs::AtFlags::SYMLINK_NOFOLLOW) {
        Ok(_) => Ok(true),
        Err(rustix::io::Errno::NOENT) => Ok(false),
        Err(_) => Err(UNAVAILABLE),
    }
}
fn legacy_qualification_empty(research: &Directory) -> Result<()> {
    let legacy=research.child("qualification-decisions",false)?;
    inspect_source_layout(&legacy.path)?;
    if !legacy.child("sha256",false)?.names()?.is_empty() {
        return Err("RESEARCH_LEGACY_QUALIFICATION_SOURCE_UNAVAILABLE");
    }
    Ok(())
}
fn strategy_owners_existing(research: &Directory) -> Result<()> {
    let equivalence=research.child("calculation-equivalence",false)?;
    inspect_source_layout(&equivalence.path)?;
    equivalence.path(&["evidence-v2","sha256"],false)?;
    let canonical=research.path(&["strategy","qualification-decisions"],false)?;
    inspect_source_layout(&canonical.path)?;
    canonical.child("sha256",false)?;
    research.path(&["artifacts","research-strategy-v1","runs"],false)?;
    let policies=qualification_policy::Store::open(research.fd.as_fd()).map_err(|e|e.code())?;
    let expected=experimental_backtest_policy().map_err(|e|e.code())?;
    if policies.load_exact("experimental-backtest","1",STRATEGY_WORK).map_err(|e|e.code())?!=expected {
        return Err("RESEARCH_STRATEGY_EXTENSION_INVALID");
    }
    research.verify()
}
/// Read a committed explicit extension only. Missing owners or metadata are not
/// permission to initialize or repair an existing deployment.
pub fn open_strategy_existing(user_data: &Path) -> Result<SemanticStoreId> {
    let id=open_existing(user_data)?;
    let research=Directory::open(&user_data.join("research"))?;
    if !strategy_extension_present(&research)? {
        return Err("RESEARCH_STRATEGY_EXTENSION_REQUIRED");
    }
    if research.read(STRATEGY_EXTENSION_FILE)?!=strategy_extension(&id)? {
        return Err("RESEARCH_STRATEGY_EXTENSION_INVALID");
    }
    legacy_qualification_empty(&research)?;
    strategy_owners_existing(&research)?;
    Ok(id)
}
/// V1 source_roots remains the exact historical profile mapping. New captures
/// use only this verified extension and change Qualification enumeration alone.
pub fn current_source_roots(user_data: &Path) -> Result<BTreeMap<String,PathBuf>> {
    open_strategy_existing(user_data)?;
    let mut roots=source_roots(user_data);
    roots.insert("QUALIFICATION_DECISION".into(),user_data.join("research/strategy/qualification-decisions"));
    Ok(roots)
}
/// Explicit operator lifecycle only. This borrows the original physical Node
/// writer for the complete extension; neither a new namespace nor a new binding
/// is created. Cancellation/error revokes this original session.
pub async fn extend_strategy(user_data: &Path, session: &mut AuthoritySession) -> Result<SemanticStoreId> {
    let mut owned=session.take_ownership();
    let result=extend_strategy_owned(user_data,&mut owned).await;
    match result {
        Ok(id)=>{session.restore_ownership(owned);Ok(id)},
        Err(code)=>{let _=owned.close().await;Err(code)},
    }
}
async fn extend_strategy_owned(user_data: &Path, session: &mut AuthoritySession) -> Result<SemanticStoreId> {
    session.verify().await.map_err(|e|e.code())?;
    let id=open_existing(user_data)?;
    deployment::verify_binding(session.client_mut().await.map_err(|e|e.code())?,&id).await.map_err(|e|e.code())?;
    let research=Directory::open(&user_data.join("research"))?;
    if strategy_extension_present(&research)? {
        // Once committed, this is strictly verification, including Policy. An
        // absent formerly provisioned owner is lost history, never a fresh token.
        let observed=open_strategy_existing(user_data)?;
        if observed!=id {return Err(INVALID);}
        deployment::verify_binding(session.client_mut().await.map_err(|e|e.code())?,&id).await.map_err(|e|e.code())?;
        session.verify().await.map_err(|e|e.code())?;
        return Ok(id);
    }
    let legacy=SourceLock::acquire(&research.path.join("qualification-decisions"))?;
    legacy_qualification_empty(&research)?;
    // Interrupted explicit provisioning may leave healthy empty new topology.
    // Positive unprofiled Qualification history is not silently adopted.
    let canonical_path=research.path.join("strategy/qualification-decisions");
    match fs::statat(&research.fd,"strategy",fs::AtFlags::SYMLINK_NOFOLLOW) {
        Ok(_) => {
            let strategy=research.child("strategy",false)?;
            match fs::statat(&strategy.fd,"qualification-decisions",fs::AtFlags::SYMLINK_NOFOLLOW) {
                Ok(_) => {
                    let canonical=Directory::open(&canonical_path)?;
                    inspect_source_layout(&canonical.path)?;
                    if !canonical.child("sha256",false)?.names()?.is_empty() {
                        return Err("RESEARCH_STRATEGY_EXTENSION_UNPROFILED_HISTORY");
                    }
                },
                Err(rustix::io::Errno::NOENT) => {},
                Err(_) => return Err(UNAVAILABLE),
            }
        },
        Err(rustix::io::Errno::NOENT) => {},
        Err(_) => return Err(UNAVAILABLE),
    }
    session.verify().await.map_err(|e|e.code())?;
    research_evidence::initialize_strategy_owners(&research.path)?;
    let canonical=SourceLock::acquire(&canonical_path)?;
    if !canonical.directory.child("sha256",false)?.names()?.is_empty() {
        return Err("RESEARCH_STRATEGY_EXTENSION_UNPROFILED_HISTORY");
    }
    let policies=qualification_policy::Store::open(research.fd.as_fd()).map_err(|e|e.code())?;
    policies.admit(session,&id,&[experimental_backtest_policy().map_err(|e|e.code())?],STRATEGY_WORK).await.map_err(|e|e.code())?;
    strategy_owners_existing(&research)?;
    // Publish the metadata file atomically from the existing auxiliary staging
    // namespace. A crash cannot leave a visible half-written extension marker.
    let auxiliary=research.child(".immutable-json-staging",true)?;
    if fs::fstat(&auxiliary.fd).map_err(|_|UNAVAILABLE)?.st_dev!=fs::fstat(&research.fd).map_err(|_|UNAVAILABLE)?.st_dev {
        return Err(INVALID);
    }
    let stage_name=format!(".stage-{}",uuid4()?);
    fs::mkdirat(&auxiliary.fd,stage_name.as_str(),fs::Mode::from_raw_mode(0o700)).map_err(|_|UNAVAILABLE)?;
    let stage=auxiliary.child(&stage_name,false)?;
    write_new(&stage,"manifest.json",&strategy_extension(&id)?)?;
    fs::fsync(&stage.fd).map_err(|_|UNAVAILABLE)?;
    fs::fsync(&auxiliary.fd).map_err(|_|UNAVAILABLE)?;
    if open_existing(user_data)?!=id {return Err(INVALID);}
    legacy.verify()?;canonical.verify()?;legacy_qualification_empty(&research)?;strategy_owners_existing(&research)?;
    if !canonical.directory.child("sha256",false)?.names()?.is_empty() {
        return Err("RESEARCH_STRATEGY_EXTENSION_UNPROFILED_HISTORY");
    }
    deployment::verify_binding(session.client_mut().await.map_err(|e|e.code())?,&id).await.map_err(|e|e.code())?;
    session.verify().await.map_err(|e|e.code())?;
    fs::renameat_with(&stage.fd,"manifest.json",&research.fd,STRATEGY_EXTENSION_FILE,fs::RenameFlags::NOREPLACE)
        .map_err(|_|"RESEARCH_STRATEGY_EXTENSION_OUTCOME_UNKNOWN")?;
    fs::fsync(&stage.fd).map_err(|_|"RESEARCH_STRATEGY_EXTENSION_OUTCOME_UNKNOWN")?;
    fs::fsync(&research.fd).map_err(|_|"RESEARCH_STRATEGY_EXTENSION_OUTCOME_UNKNOWN")?;
    let observed=open_strategy_existing(user_data).map_err(|_|"RESEARCH_STRATEGY_EXTENSION_OUTCOME_UNKNOWN")?;
    if observed!=id {return Err("RESEARCH_STRATEGY_EXTENSION_OUTCOME_UNKNOWN");}
    legacy.verify()?;canonical.verify()?;
    deployment::verify_binding(session.client_mut().await.map_err(|e|e.code())?,&id).await.map_err(|e|e.code())?;
    session.verify().await.map_err(|e|e.code())?;
    Ok(id)
}

/// Controller composition only. Every source owner and the exact shipped Policy must exist.
pub fn novelty(user_data: &Path) -> Result<Authority> {
    let sources=current_source_roots(user_data)?;
    Authority::new(
        user_data,
        &user_data.join("research/experiment-memory"),
        sources,
    )?.with_runtime_root(&user_data.join("runtime"))
}

mod manual_backtest;
pub use manual_backtest::{extend_manual_backtest,open_manual_backtest_existing};
pub(crate) use manual_backtest::manual_backtest_policy;
