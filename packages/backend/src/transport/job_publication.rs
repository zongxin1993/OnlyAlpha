//! 只投影 PostgreSQL 完整发布；不恢复输入、执行策略或读取文件 Evidence。
use crate::{
    application::research_run::VerifiedRun,
    persistence::{
        job_publication::PublicationError,
        research_evidence::{ResearchPublication, read_published_strategy},
    },
    transport::research_wire::StrategyResearchReport,
};
use onlyalpha_domain::time::OnlyTimestamp;
use tracing::Instrument;

pub(crate) async fn read_research_report(
    client: &mut tokio_postgres::Client,
    namespace: &crate::bootstrap::deployment::SemanticStoreId,
    run: &VerifiedRun,
) -> Result<StrategyResearchReport, PublicationError> {
    let operation = onlyalpha_observability::Operation::start(
        "backend",
        "result.research.read",
        onlyalpha_observability::Correlation {
            run_id: Some(run.run_id().into()),
            ..Default::default()
        },
    );
    let result = async {
        let publication = read_published_strategy(client, namespace, run).await?;
        project_research(&publication)
    }
    .instrument(operation.span().clone())
    .await;
    operation.finish(if result.is_ok() { "ok" } else { "failed" }, 1, 0);
    result
}
pub(crate) fn failure_code(error: PublicationError) -> &'static str {
    error.code()
}

/// Pure display regression over actual owning values, never a fixture grant.
#[cfg(test)]
pub(crate) fn research_report(
    run: &VerifiedRun,
    publication: &crate::persistence::job_publication::PublishedJobResult,
) -> Result<StrategyResearchReport, PublicationError> {
    project_research(&ResearchPublication::from_published(
        run,
        publication.clone(),
    )?)
}
fn project_research(
    publication: &ResearchPublication,
) -> Result<StrategyResearchReport, PublicationError> {
    onlyalpha_observability::measure(
        "backend",
        "result.research.project",
        onlyalpha_observability::Correlation {
            run_id: Some(publication.run().run_id().into()),
            ..Default::default()
        },
        || {
            use PublicationError::Integrity;
            let specification = publication
                .run()
                .strategy_specification()
                .map_err(|_| Integrity)?;
            let window = &specification.record()["input_window"];
            let time = |key: &str| {
                let ns = window[key]
                    .as_str()
                    .ok_or(Integrity)?
                    .parse::<bigdecimal::num_bigint::BigInt>()
                    .map_err(|_| Integrity)?;
                OnlyTimestamp::from_unix_nanos(ns)
                    .to_datetime_exact()
                    .map(|value| value.to_string())
                    .map_err(|_| Integrity)
            };
            Ok(StrategyResearchReport {
                candidate_fingerprint: publication.candidate_fingerprint().into(),
                // 与文件轨道研究报告同一科学结果身份（成员正文重算并核对 Run 列后取值），
                // 客户端据此提交资格证据，冻结关系与资格审查同用此身份（§4.1）。
                research_result_fingerprint: publication.research_result_fingerprint()?,
                start_at: time("observation_start_ns")?,
                end_at: time("observation_end_ns")?,
                observation_count: window["observation_capacity"].as_u64().ok_or(Integrity)?,
                warmup_bars: window["warmup_bars"].as_u64().ok_or(Integrity)?,
                node_count: specification.record()["decision"]["decision_graph"]["nodes"]
                    .as_array()
                    .ok_or(Integrity)?
                    .len()
                    .try_into()
                    .map_err(|_| Integrity)?,
                execution_graph_verified: true,
                limitations: vec![
                    "本次研究验证了完整计算和交易信号的一致性，尚未评估策略收益。".into(),
                    "后续回测仅作探索；样本较短，不代表未来表现。".into(),
                ],
            })
        },
    )
}
