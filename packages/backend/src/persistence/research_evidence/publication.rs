//! 完整 PG 发布的策略研究读取 owner；不读取文件、恢复 Runtime 或重做认证。
use crate::{
    application::{
        job_contract::{JobKind, MemberKind},
        research_run::VerifiedRun,
    },
    bootstrap::deployment::SemanticStoreId,
    persistence::job_publication::{
        PublicationError, PublicationRepository, PublishedJobResult, RunLocator,
    },
};
use onlyalpha_strategy::{SourceError, SourceRevision};
use serde_json::{Value, json};
use std::collections::BTreeMap;
use tracing::Instrument;
type Result<T> = std::result::Result<T, PublicationError>;

/// Original admission and complete immutable content, not a portable execution
/// or publication grant. There is no raw-value constructor or mutable accessor.
pub struct ResearchPublication {
    run: VerifiedRun,
    publication: PublishedJobResult,
    source: SourceRevision,
    candidate: String,
}
impl ResearchPublication {
    pub fn run(&self) -> &VerifiedRun {
        &self.run
    }
    pub fn publication(&self) -> &PublishedJobResult {
        &self.publication
    }
    pub fn source(&self) -> &SourceRevision {
        &self.source
    }
    pub fn candidate_fingerprint(&self) -> &str {
        &self.candidate
    }
    pub fn build_certification(&self) -> &Value {
        &self.run.prepared_inputs["build_certification"]
    }

    /// 冻结前的发布证明复核：发布身份、候选身份与因果执行证据身份均为完整 SHA-256，
    /// 且执行证据来自本发布自己的成员正文摘要。PG 发布自身即证据割线，
    /// 文件读锁不参与，也不得回退文件协议。
    pub(crate) fn verify_publication(&self) -> Result<()> {
        use PublicationError::Integrity;
        if !crate::is_sha256_hex(self.publication.fingerprint())
            || !crate::is_sha256_hex(&self.candidate)
        {
            return Err(Integrity);
        }
        let references = causal_execution_references(&self.publication)?;
        if references
            .iter()
            .any(|value| !crate::is_sha256_hex(value))
        {
            return Err(Integrity);
        }
        Ok(())
    }

    /// 从本发布的成员正文重算科学结果身份，并与 Run 列 `research_result_fingerprint` 核对相等
    /// （Constitution §4.1/§4.5）：读取方不信任写入方，在发布成员的同一表示上调用与生产方同一
    /// `published_result_fingerprint`，同一语义在两条轨道收敛到同一身份。读取方据此消费科学身份，
    /// 不读取文件证据，也不回退发布指纹。
    pub(crate) fn research_result_fingerprint(&self) -> Result<String> {
        use PublicationError::{Integrity, Mismatch, MissingEvidence};
        let spec = self.run.strategy_specification().map_err(|_| Mismatch)?;
        let calculations = published_member_pairs(&self.publication, MemberKind::CalculationValues)?;
        let statistics = published_member_pairs(&self.publication, MemberKind::Statistics)?;
        let recomputed =
            super::strategy::published_result_fingerprint(spec, &calculations, &statistics)
                .map_err(|_| Integrity)?;
        if !crate::is_sha256_hex(&recomputed) {
            return Err(Integrity);
        }
        let stored = self
            .publication
            .research_result_column()
            .ok_or(MissingEvidence)?;
        if recomputed != stored {
            return Err(Integrity);
        }
        Ok(recomputed)
    }

    /// 冻结关系所需的执行证据身份：正式发布因果成员正文摘要的稳定有序去重集合。
    /// 与发布者写入 Run 执行证据列的口径同一，读取器已在同一快照内证明它等于本 Run 的列值，
    /// 消费者不另立定义。
    pub(crate) fn execution_evidence_fingerprints(&self) -> Result<Vec<String>> {
        causal_execution_references(&self.publication)
    }

    /// 逐节点等价证据与交易准入语义身份：从发布正文携带的完整双实现认证
    /// （`build_certification`）复用生产推导 `equivalence::derive`，与认证路径
    /// `application::calculation_build.rs` 同一入口；不从认证摘要另造身份，
    /// 也不拼一份自抄的运行时观测通过等式。
    pub(crate) fn freeze_equivalence(&self) -> Result<(Vec<String>, String)> {
        use PublicationError::{Integrity, Mismatch};
        let specification = self.run.strategy_specification().map_err(|_| Mismatch)?;
        let graph = specification
            .calculation_graph("decision")
            .map_err(|_| Mismatch)?;
        let rows = super::strategy::equivalence::derive(
            graph,
            &specification.record()["implementation_bindings"],
            self.build_certification(),
        )
        .map_err(|_| Integrity)?;
        let ids = rows
            .iter()
            .map(|row| {
                row["evidence_fingerprint"]
                    .as_str()
                    .ok_or(Integrity)
                    .map(|value| value.to_owned())
            })
            .collect::<Result<Vec<_>>>()?;
        if ids.is_empty() || ids.iter().any(|id| !crate::is_sha256_hex(id)) {
            return Err(Integrity);
        }
        Ok((
            ids.clone(),
            super::strategy::trading_admission_identity(&ids).map_err(|_| Integrity)?,
        ))
    }

    pub(crate) fn from_published(
        run: &VerifiedRun,
        publication: PublishedJobResult,
    ) -> Result<Self> {
        use PublicationError::{Integrity, Mismatch};
        let binding = publication.binding();
        if binding.kind() != JobKind::Research
            || binding.run_id() != run.run_id()
            || binding.owner() != run.owner()
            || publication.specification_fingerprint() != run.specification_fingerprint()
            || publication.admission_fingerprint() != run.admission_resolution_fingerprint()
        {
            return Err(Mismatch);
        }
        let specification = run.strategy_specification().map_err(|_| Mismatch)?;
        let report = root(&publication, MemberKind::ResearchReport)?;
        let causal = root(&publication, MemberKind::CausalEvidence)?;
        let body = &report["body"];
        let execution = &causal["body"]["execution"];
        let candidate = specification
            .candidate_fingerprint()
            .map_err(|_| Integrity)?;
        if body["specification"] != *specification.record()
            || body["binding"] != binding.record()
            || body["candidate"] != candidate
            || causal["body"]["binding"] != binding.record()
            || execution["source"] != body["source"]
            || execution["build_certification"] != run.prepared_inputs["build_certification"]
            || execution["completion"]
                != json!({"contract":"FINITE_OWNER_FINISH_JOIN_V1","producer":"INTERNALLY_OWNED_EXECUTION_TASK","resources":"POSITIVELY_JOINED"})
        {
            return Err(Mismatch);
        }
        crate::application::research_run_execution::verify_executor_image(
            &execution["native_image"],
            &specification.record()["execution_binding"],
        )
        .map_err(|_| Mismatch)?;
        if execution["native_image"]["artifact"] != binding.record()["kernel_artifact"]
            || !run.prepared_inputs["build_certification"]["proof_fingerprint"]
                .as_str()
                .is_some_and(crate::is_sha256_hex)
            || !execution["signal_execution"]
                .as_str()
                .is_some_and(crate::is_sha256_hex)
        {
            return Err(Mismatch);
        }
        verify_references(&publication, &body["members"], true)?;
        verify_references(&publication, &causal["body"]["members"], false)?;
        let source = SourceRevision::from_json(&body["source"].to_string(), 8 * 1024 * 1024)
            .map_err(|error| match error {
                SourceError::Invalid => Integrity,
                SourceError::Unavailable => PublicationError::BudgetExceeded,
            })?;
        if binding.record()["strategy_revision"] != source.fingerprint()
            || source.to_record()["decision_graph_fingerprint"] != binding.record()["signal_graph"]
        {
            return Err(Mismatch);
        }
        let window = &specification.record()["input_window"];
        if binding.market().record()["sample_rows"] != window["observation_capacity"]
            || binding.market().record()["warmup_rows"] != window["warmup_bars"]
        {
            return Err(Mismatch);
        }
        Ok(Self {
            run: run.clone(),
            publication,
            source,
            candidate,
        })
    }
}

/// 从发布成员的存储正文（`{"axis":[键…],"rows":[行…]}` 两条平行数组）还原生产方传入
/// `published_result_fingerprint` 的 `(键, 行)` 序列：计算成员键为逐轴 5 元键、行为
/// `{decision,targets}`；统计成员键为统计身份、行为统计正文。与生产方同一表示，逐元素对应。
fn published_member_pairs(
    publication: &PublishedJobResult,
    kind: MemberKind,
) -> Result<Vec<(Value, Value)>> {
    use PublicationError::{Integrity, MissingEvidence};
    let plan = publication.binding().result_plan();
    let members = plan.members().iter().filter(|member| member.kind() == kind).collect::<Vec<_>>();
    if members.len() != 1 {
        return Err(Integrity);
    }
    let value: Value = serde_json::from_str(
        publication
            .content(members[0].key())
            .ok_or(MissingEvidence)?,
    )
    .map_err(|_| Integrity)?;
    if value["schema_version"] != 1
        || value["kind"] != serde_json::to_value(kind).map_err(|_| Integrity)?
    {
        return Err(Integrity);
    }
    let keys = value["axis"].as_array().ok_or(Integrity)?;
    let rows = value["rows"].as_array().ok_or(Integrity)?;
    if keys.len() != rows.len() {
        return Err(Integrity);
    }
    Ok(keys.iter().cloned().zip(rows.iter().cloned()).collect())
}

/// 因果执行证据身份：冻结计划中 CAUSAL_EVIDENCE 成员正文摘要的稳定有序去重集合。
/// 每个摘要都是成员正文的实际内容摘要，不是成员名、路径或外部引用。
pub(crate) fn causal_execution_references(
    publication: &PublishedJobResult,
) -> Result<Vec<String>> {
    use PublicationError::{Integrity, MissingEvidence};
    let mut references = publication
        .binding()
        .result_plan()
        .members()
        .iter()
        .filter(|member| member.kind() == MemberKind::CausalEvidence)
        .map(|member| {
            publication
                .content_fingerprint(member.key())
                .ok_or(MissingEvidence)
                .map(|value| value.to_owned())
        })
        .collect::<Result<Vec<_>>>()?;
    references.sort_unstable();
    references.dedup();
    if references.is_empty() {
        return Err(MissingEvidence);
    }
    if references.iter().any(|value| value.len() != 64) {
        return Err(Integrity);
    }
    Ok(references)
}

/// 读取本 Run 的结果证据归属：存在 PG 发布行时返回完整发布；
/// 没有发布行时返回 `None`，由调用方使用其既有证据路径。
/// 发布存在但未通过认证时直接报错，调用方不得改用其他来源。
pub async fn read_published_strategy_if_present(
    client: &mut tokio_postgres::Client,
    namespace: &SemanticStoreId,
    run: &VerifiedRun,
) -> Result<Option<ResearchPublication>> {
    let operation = onlyalpha_observability::Operation::start(
        "backend",
        "research.publication.read_if_present",
        onlyalpha_observability::Correlation {
            run_id: Some(run.run_id().into()),
            ..Default::default()
        },
    );
    let result = async {
        let Some(publication) = PublicationRepository::new(client, namespace, run.owner())
            .await?
            .read_if_present(&RunLocator::new(JobKind::Research, run.run_id())?)
            .await?
        else {
            return Ok(None);
        };
        Ok(Some(ResearchPublication::from_published(run, publication)?))
    }
    .instrument(operation.span().clone())
    .await;
    operation.finish(if result.is_ok() { "ok" } else { "failed" }, 1, 0);
    result
}

pub async fn read_published_strategy(
    client: &mut tokio_postgres::Client,
    namespace: &SemanticStoreId,
    run: &VerifiedRun,
) -> Result<ResearchPublication> {
    let operation = onlyalpha_observability::Operation::start(
        "backend",
        "research.publication.read",
        onlyalpha_observability::Correlation {
            run_id: Some(run.run_id().into()),
            ..Default::default()
        },
    );
    let result = async {
        let publication = PublicationRepository::new(client, namespace, run.owner())
            .await?
            .read(&RunLocator::new(JobKind::Research, run.run_id())?)
            .await?;
        ResearchPublication::from_published(run, publication)
    }
    .instrument(operation.span().clone())
    .await;
    operation.finish(if result.is_ok() { "ok" } else { "failed" }, 1, 0);
    result
}

fn root(publication: &PublishedJobResult, kind: MemberKind) -> Result<Value> {
    let plan = publication.binding().result_plan();
    let members = plan
        .members()
        .iter()
        .filter(|member| member.kind() == kind)
        .collect::<Vec<_>>();
    if members.len() != 1 {
        return Err(PublicationError::Integrity);
    }
    let value: Value = serde_json::from_str(
        publication
            .content(members[0].key())
            .ok_or(PublicationError::MissingEvidence)?,
    )
    .map_err(|_| PublicationError::Integrity)?;
    if value["schema_version"] != 1
        || value["kind"] != serde_json::to_value(kind).map_err(|_| PublicationError::Integrity)?
    {
        return Err(PublicationError::Integrity);
    }
    Ok(value)
}
fn verify_references(
    publication: &PublishedJobResult,
    references: &Value,
    report: bool,
) -> Result<()> {
    let mut actual = BTreeMap::new();
    for reference in references.as_array().ok_or(PublicationError::Integrity)? {
        let object = reference.as_object().ok_or(PublicationError::Integrity)?;
        if object.len() != 2 {
            return Err(PublicationError::Integrity);
        }
        let key = reference["key"]
            .as_str()
            .ok_or(PublicationError::Integrity)?;
        let content = reference["content"]
            .as_str()
            .ok_or(PublicationError::Integrity)?;
        if actual.insert(key, content).is_some() {
            return Err(PublicationError::Integrity);
        }
    }
    let plan = publication.binding().result_plan();
    let expected = plan
        .members()
        .iter()
        .filter(|member| {
            member.kind() != MemberKind::CausalEvidence
                && (!report || member.kind() != MemberKind::ResearchReport)
        })
        .map(|member| {
            publication
                .content_fingerprint(member.key())
                .map(|fingerprint| (member.key(), fingerprint))
                .ok_or(PublicationError::MissingEvidence)
        })
        .collect::<Result<BTreeMap<_, _>>>()?;
    if actual != expected {
        return Err(PublicationError::Mismatch);
    }
    Ok(())
}
