//! Faults against the original persisted Completed Run, never a fabricated permit.
use onlyalpha_backend::{
    application::command::{Admission, CommandId, CommandKind},
    persistence::{
        postgres::Commands,
        research_execution::{ResearchExecution, RunState},
        research_novelty::Authority,
        research_submission,
    },
    transport::host_factor_research::completed_report,
};
use serde_json::{Value, json};
use std::{
    collections::BTreeMap,
    path::{Path, PathBuf},
};

type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;

pub async fn inspect(client: &mut tokio_postgres::Client, v: &Value) -> Result<Value> {
    let command = CommandId::new(v["research_command"].as_str().ok_or("command")?)?;
    let id = research_submission::run_id(&command);
    let run = research_submission::load(client, &id, Some("local-developer")).await?;
    let semantic = Path::new(v["semantic_root"].as_str().ok_or("semantic root")?);
    let root = Path::new(v["research_root"].as_str().ok_or("research root")?);
    let roots: BTreeMap<String, PathBuf> = serde_json::from_value(v["source_roots"].clone())?;
    let authority = Authority::new(
        semantic,
        Path::new(v["projection_root"].as_str().ok_or("projection")?),
        roots,
    )?;
    let original = serde_json::to_value(completed_report(client, &authority, root, &run).await)?;
    assert_eq!(original["report_status"]["state"], "VERIFIED");
    assert_eq!(original["decision_provenance"]["state"], "VERIFIED");
    assert_eq!(
        original["report"]["instrument_id"],
        v["scope"]["instrument_id"]
    );
    assert_eq!(
        original["report"]["timeframe_minutes"],
        v["study"]["bar_ns"].as_u64().unwrap() / 60_000_000_000
    );
    assert_eq!(
        original["report"]["horizon_bars"],
        v["study"]["horizon_bars"]
    );
    for (sample, expected) in original["report"]["samples"]
        .as_array()
        .unwrap()
        .iter()
        .zip(v["study"]["samples"].as_array().unwrap())
    {
        for (wire, input) in [("start_at", "start_ns"), ("end_at", "end_ns")] {
            let exact = onlyalpha_domain::time::OnlyTimestamp::from_unix_nanos(
                expected[input].as_u64().unwrap().into(),
            )
            .to_datetime_exact()?
            .to_string();
            assert_eq!(sample[wire], exact);
        }
    }

    // Verified values may be reused within one protected read, never across
    // requests: losing any upstream owner must invalidate the next report.
    for relative in [
        "statistics-results/sha256",
        "calculation-results/sha256",
        "datasets/sha256",
    ] {
        let source = root.join(relative);
        let held = source.with_file_name("held-report-upstream");
        std::fs::rename(&source, &held)?;
        let unavailable =
            serde_json::to_value(completed_report(client, &authority, root, &run).await);
        std::fs::rename(&held, &source)?;
        let unavailable = unavailable?;
        assert!(unavailable["report"].is_null(), "{relative}");
        assert_eq!(unavailable["report_status"]["state"], "UNAVAILABLE");
        assert_eq!(
            ResearchExecution::new(client).observe(&run).await?.state,
            RunState::Completed
        );
        assert_eq!(
            serde_json::to_value(completed_report(client, &authority, root, &run).await)?,
            original
        );
    }

    let group = semantic
        .join("research/novelty-decision-groups")
        .join(command.value());
    let held = semantic.join("held-original-report-group");
    std::fs::rename(&group, &held)?;
    let missing = serde_json::to_value(completed_report(client, &authority, root, &run).await);
    std::fs::rename(&held, &group)?;
    let missing = missing?;
    assert_eq!(missing["report"], original["report"]);
    assert_eq!(missing["decision_provenance"]["state"], "UNAVAILABLE");
    assert_eq!(
        missing["decision_provenance"]["code"],
        "HISTORICAL_PROOF_UNAVAILABLE"
    );
    assert_eq!(
        ResearchExecution::new(client).observe(&run).await?.state,
        RunState::Completed
    );

    // Re-sign a well-formed Group carrying a different original Command. A valid
    // content hash is not proof of this Run's decision origin.
    let path = group.join("group.json");
    let bytes = std::fs::read(&path)?;
    let permissions = std::fs::metadata(&path)?.permissions();
    let mut changed: Value = serde_json::from_slice(&bytes)?;
    changed["product_command_id"] = json!("00000000-0000-4000-8000-000000000981");
    changed
        .as_object_mut()
        .ok_or("group")?
        .remove("group_fingerprint");
    let mut identity = changed.clone();
    identity["domain"] = json!("onlyalpha.research.novelty-decision-group-v1");
    changed["group_fingerprint"] = json!(onlyalpha_backend::application::factor_content::hash(
        &identity
    )?);
    let canonical = onlyalpha_metadata_json::canonical_json(&changed.to_string(), 8 * 1024 * 1024)?;
    // Isolated test owner only; preserve original file permissions and bytes.
    use std::os::unix::fs::PermissionsExt;
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600))?;
    std::fs::write(&path, canonical)?;
    std::fs::set_permissions(&path, permissions.clone())?;
    let wrong = serde_json::to_value(completed_report(client, &authority, root, &run).await);
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600))?;
    std::fs::write(&path, &bytes)?;
    std::fs::set_permissions(&path, permissions)?;
    let wrong = wrong?;
    assert_eq!(wrong["report"], original["report"]);
    assert_eq!(wrong["decision_provenance"]["state"], "UNAVAILABLE");
    assert_eq!(
        wrong["decision_provenance"]["code"],
        "HISTORICAL_PROOF_UNAVAILABLE"
    );
    assert_eq!(
        serde_json::to_value(completed_report(client, &authority, root, &run).await)?,
        original
    );

    // A later real, unrelated formal Command advances PG source history. The
    // historical Group still uses its captured frontier rather than today's cut.
    let unrelated = Admission::new(
        CommandId::new("00000000-0000-4000-8000-000000000982")?,
        CommandKind::SaveWorkspace,
        &"e".repeat(64),
    )?;
    Commands::new(client).admit_exact(&unrelated).await?;
    assert_eq!(
        serde_json::to_value(completed_report(client, &authority, root, &run).await)?,
        original
    );

    let result = original["report"]["research_result_fingerprint"]
        .as_str()
        .ok_or("result")?;
    let artifact = root
        .join("artifacts/research-time-series-v1/sha256")
        .join(&result[..2])
        .join(result);
    let held = root.join("held-original-report-artifact");
    std::fs::rename(&artifact, &held)?;
    let unavailable = serde_json::to_value(completed_report(client, &authority, root, &run).await);
    std::fs::rename(&held, &artifact)?;
    let unavailable = unavailable?;
    assert!(unavailable["report"].is_null());
    assert_eq!(unavailable["report_status"]["state"], "UNAVAILABLE");
    assert_eq!(
        unavailable["report_status"]["code"],
        "RESEARCH_REPORT_UNAVAILABLE"
    );
    assert_eq!(unavailable["decision_provenance"]["state"], "VERIFIED");
    let retained = research_submission::load(client, &id, Some("local-developer")).await?;
    assert_eq!(
        ResearchExecution::new(client)
            .observe(&retained)
            .await?
            .state,
        RunState::Completed
    );
    assert_eq!(
        serde_json::to_value(completed_report(client, &authority, root, &retained).await)?,
        original
    );
    Ok(json!({"run_id":id,"state":"COMPLETED","report_provenance_regressions":"VERIFIED"}))
}

/// Each independent physical-source fault keeps the original bounded probe budget.
pub async fn inspect_source_cut(client: &mut tokio_postgres::Client, v: &Value) -> Result<Value> {
    let relative = v["missing_upstream"].as_str().ok_or("upstream")?;
    if ![
        "statistics-results/sha256",
        "calculation-results/sha256",
        "datasets/sha256",
    ]
    .contains(&relative)
    {
        return Err("upstream".into());
    }
    let semantic = Path::new(v["semantic_root"].as_str().ok_or("semantic root")?);
    let root = Path::new(v["research_root"].as_str().ok_or("research root")?);
    let roots: BTreeMap<String, PathBuf> = serde_json::from_value(v["source_roots"].clone())?;
    let authority = Authority::new(
        semantic,
        Path::new(v["projection_root"].as_str().ok_or("projection")?),
        roots,
    )?;
    let projection = authority.refresh_projection(client).await?;
    assert_eq!(authority.refresh_projection(client).await?, projection);
    let source = root.join(relative);
    let held = source.with_file_name("held-source-cut-upstream");
    std::fs::rename(&source, &held)?;
    let unavailable = authority.refresh_projection(client).await;
    std::fs::rename(&held, &source)?;
    assert!(unavailable.is_err());
    assert_eq!(authority.refresh_projection(client).await?, projection);
    Ok(json!({"source_cut_regressions":"VERIFIED","missing_upstream":relative}))
}
