//! Explicit deployment provisioning of a fresh Research semantic namespace.
//! Normal Product preparation only opens verified existing owners; it never repairs history.
use crate::{
    application::{factor_content::hash, research_novelty as contract},
    bootstrap::deployment::{self, SemanticStoreId},
    persistence::{research_dataset, research_evidence, research_novelty::Authority},
    security::{
        immutable_json::{Directory, inspect_source_layout, put, read_path},
        protected_files::{self, FilePolicy},
    },
};
use rustix::fs;
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, BTreeSet},
    fs::File,
    io::Write,
    path::{Path, PathBuf},
};
type Result<T> = std::result::Result<T, &'static str>;
const INVALID: &str = "RESEARCH_OWNER_PROFILE_INVALID";
const UNAVAILABLE: &str = "RESEARCH_OWNER_PROFILE_UNAVAILABLE";
const PROFILE_FILE: &str = ".onlyalpha-factor-research-owner-profile.json";
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
/// Controller composition only. Every source owner and the exact shipped Policy must exist.
pub fn novelty(user_data: &Path) -> Result<Authority> {
    open_existing(user_data)?;
    Authority::new(
        user_data,
        &user_data.join("research/experiment-memory"),
        source_roots(user_data),
    )
}
