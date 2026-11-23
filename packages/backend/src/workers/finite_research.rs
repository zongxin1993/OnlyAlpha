//! Single original Research Run: PG recovery/claim, exact memory preparation,
//! positively joined execution and same-session atomic publication.
use super::{
    research::SharedAuthority, research_service::Configuration, source_sessions::SourceSessions,
};
use crate::{
    application::{
        finite_job::{FiniteOutcome, PreparationTask, PreparedExecution},
        job_contract::JobKind,
        job_input::MemoryBudget,
        job_recovery::{RecoveryDecision, RecoveryRefusal},
        research_admission::PreparationError,
        research_run::VerifiedRun,
    },
    bootstrap::{deployment::SemanticStoreId, workstation_startup::JobReadConnections},
    persistence::{
        job_publication::{
            AttemptClaim, AttemptExecutionBinding, PublicationRepository, RunLocator,
        },
        research_execution::{
            Claim, Failure, FailurePhase, ResearchExecution, RetryDecision, RunState, RunStatus,
        },
    },
};
use onlyalpha_domain::time::OnlyUtcDateTime;
use std::time::Duration;
const UNKNOWN: &str = "RESEARCH_EXECUTION_OWNERSHIP_UNKNOWN";
type Result<T> = std::result::Result<T, PreparationError>;

pub(crate) async fn observe(writer: &SharedAuthority, run: &VerifiedRun) -> Result<RunStatus> {
    let mut held = writer.lock().await;
    ResearchExecution::observe_guarded(held.as_mut().ok_or(UNKNOWN)?, run)
        .await
        .map_err(Into::into)
}
pub(crate) async fn recover(
    writer: &SharedAuthority,
    namespace: &SemanticStoreId,
    run: &VerifiedRun,
    at: OnlyUtcDateTime,
) -> Result<RecoveryDecision> {
    let mut held = writer.lock().await;
    ResearchExecution::recover_finite_guarded(held.as_mut().ok_or(UNKNOWN)?, namespace, run, at)
        .await
        .map_err(Into::into)
}
/// Terminal cleanup accepts only a full PG publication or a current terminal
/// absence proof. It never opens a legacy result/evidence directory.
pub(crate) async fn terminal(
    writer: &SharedAuthority,
    namespace: &SemanticStoreId,
    run: &VerifiedRun,
    at: OnlyUtcDateTime,
) -> Result<bool> {
    Ok(matches!(
        recover(writer, namespace, run, at).await?,
        RecoveryDecision::AlreadyPublished(_)
            | RecoveryDecision::Refused(RecoveryRefusal::Terminal, _)
    ))
}
pub(crate) async fn run(
    readers: &mut Option<JobReadConnections>,
    writer: &SharedAuthority,
    sources: &SourceSessions,
    run: VerifiedRun,
    config: &Configuration,
    worker: &str,
    attempt: &str,
    clock: &(impl Fn() -> Result<OnlyUtcDateTime> + Send + Sync),
) -> Result<RunStatus> {
    let namespace = readers.as_ref().ok_or(UNKNOWN)?.namespace().clone();
    match recover(writer, &namespace, &run, clock()?).await? {
        RecoveryDecision::RecomputeWithNewClaim(_) => {}
        RecoveryDecision::AlreadyPublished(_)
        | RecoveryDecision::Refused(RecoveryRefusal::Terminal, _)
        | RecoveryDecision::WaitForResolution => return observe(writer, &run).await,
        _ => {
            return Err(PreparationError::unknown(
                "RESEARCH_RECOVERY_STATE_UNKNOWN",
                None,
            ));
        }
    }
    let claim = {
        let mut held = writer.lock().await;
        ResearchExecution::claim_recompute(
            held.as_mut().ok_or(UNKNOWN)?,
            &namespace,
            &run,
            worker,
            attempt,
            clock()?,
        )
        .await?
    };
    let Some(mut claim) = claim else {
        return observe(writer, &run).await;
    };
    let execution = AttemptExecutionBinding::capture(&AttemptClaim::from_research(&claim))
        .map_err(|_| UNKNOWN)?;
    // Frozen values are read before Source lookup, never reconstructed from
    // mutable preparation. This read is not a READY or execution permission.
    let binding = {
        let (_, facts) = readers
            .as_mut()
            .ok_or(UNKNOWN)?
            .clients_mut()
            .await
            .map_err(|_| "RESEARCH_INPUT_READER_UNAVAILABLE")?;
        PublicationRepository::new(facts, &namespace, run.owner())
            .await
            .map_err(|_| "RESEARCH_FROZEN_BINDING_UNAVAILABLE")?
            .frozen_binding(
                &RunLocator::new(JobKind::Research, run.run_id())
                    .map_err(|_| "RESEARCH_FROZEN_BINDING_INVALID")?,
            )
            .await
            .map_err(|_| "RESEARCH_FROZEN_BINDING_UNAVAILABLE")?
    };
    let preparing = PreparationTask::start(
        readers.take().ok_or(UNKNOWN)?,
        sources.clone(),
        run.clone(),
        binding,
        execution,
        config.runtime_root.clone(),
        config.algorithms.clone(),
        MemoryBudget::new(crate::transport::host::ROWS, crate::transport::host::WORK)
            .map_err(|_| "RESEARCH_INPUT_BUDGET_INVALID")?,
    );
    let stop = preparing.cancellation();
    let preparation = preparing.join();
    tokio::pin!(preparation);
    let mut ticks = tokio::time::interval(Duration::from_secs(5));
    ticks.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
    let mut heartbeat = tokio::time::Instant::now() + Duration::from_secs(30);
    let mut primary = None;
    let mut cancellation = false;
    let prepared = loop {
        tokio::select! {
            result=&mut preparation=>break result?,
            _=ticks.tick(),if primary.is_none()=>{
                match tick(writer,&run,&mut claim,&mut heartbeat).await {
                    Ok(status) if status.state==RunState::CancelRequested=>{cancellation=true;stop.send_replace(true);},
                    Ok(_)=>{},
                    Err(error)=>{primary=Some(error);stop.send_replace(true);},
                }
            }
        }
    };
    let task = match prepared {
        PreparedExecution::Aborted {
            readers: returned,
            proof,
            error,
        } => {
            *readers = Some(returned);
            if let Some(primary) = primary {
                return Err(if error.recovery_owner().is_some() {
                    error
                } else {
                    primary
                });
            }
            if unknown(&error) {
                return Err(error);
            }
            let mut held = writer.lock().await;
            let authority = held.as_mut().ok_or(UNKNOWN)?;
            let status = ResearchExecution::observe_guarded(authority, &run).await?;
            return if status.state == RunState::CancelRequested {
                ResearchExecution::cancel_preparation_guarded(
                    authority,
                    &namespace,
                    &run,
                    &mut claim,
                    &proof,
                    clock()?,
                )
                .await
                .map_err(Into::into)
            } else {
                let failure = Failure::new(
                    FailurePhase::Admission,
                    error.code(),
                    "Finite Research preparation failed before any execution task was created",
                )?;
                ResearchExecution::fail_preparation_guarded(
                    authority,
                    &namespace,
                    &run,
                    &mut claim,
                    &proof,
                    &failure,
                    RetryDecision::FinalFail,
                    clock()?,
                )
                .await
                .map_err(Into::into)
            };
        }
        PreparedExecution::Ready {
            readers: returned,
            value: task,
        } => {
            *readers = Some(returned);
            task
        }
    };
    let control = task.cancellation();
    let mut reaper = Reaper::default();
    if cancellation || primary.is_some() {
        reaper.request(&control, run.run_id());
    }
    let completed = task.finish();
    tokio::pin!(completed);
    // Pin one execution join and retain one original reaper across every tick.
    let finished = loop {
        tokio::select! {
            result=&mut completed=>break result,
            _=ticks.tick(),if primary.is_none()=>{
                if reaper.finished() {
                    if let Err(error)=reaper.join().await {primary=Some(error);continue;}
                }
                match tick(writer,&run,&mut claim,&mut heartbeat).await {
                    Ok(status) if status.state==RunState::CancelRequested=>reaper.request(&control,run.run_id()),
                    Ok(_)=>{},
                    Err(error)=>{primary=Some(error);reaper.request(&control,run.run_id());},
                }
            }
        }
    };
    // Joining the same reaper also happens when the execution join failed.
    reaper.join().await?;
    let finished = finished?;
    if let Some(error) = primary {
        return Err(error);
    }
    #[cfg(test)]
    super::research_service::owner_tests::finished_gate(run.run_id()).await;
    let status = observe(writer, &run).await?;
    if status.state == RunState::CancelRequested {
        reaper.request(&control, run.run_id());
        reaper.join().await?;
        let drained = finished.into_drained()?;
        let mut held = writer.lock().await;
        return ResearchExecution::cancel_finite_guarded(
            held.as_mut().ok_or(UNKNOWN)?,
            &namespace,
            &run,
            &mut claim,
            &drained,
            clock()?,
        )
        .await
        .map_err(Into::into);
    }
    if status.state != RunState::Running {
        return Err(PreparationError::unknown(
            "RESEARCH_EXECUTION_TERMINAL_RACE_UNKNOWN",
            None,
        ));
    }
    match finished.into_outcome()? {
        FiniteOutcome::Completed(candidate) => {
            #[cfg(test)]
            super::research_service::owner_tests::candidate_gate(
                run.run_id(),
                candidate.fingerprint(),
            )
            .await;
            let mut held = writer.lock().await;
            PublicationRepository::publish_guarded(
                held.as_mut().ok_or(UNKNOWN)?,
                &namespace,
                &AttemptClaim::from_research(&claim),
                &candidate,
            )
            .await
            .map_err(|error| {
                tracing::warn!(
                    run_id = run.run_id(),
                    ?error,
                    "finite Research publication refused"
                );
                publication_error(error)
            })?;
            ResearchExecution::observe_guarded(held.as_mut().ok_or(UNKNOWN)?, &run)
                .await
                .map_err(Into::into)
        }
        FiniteOutcome::Failed { drained, error } => {
            let mut held = writer.lock().await;
            let authority = held.as_mut().ok_or(UNKNOWN)?;
            let failure = Failure::new(
                FailurePhase::Execution,
                error.code(),
                "Finite Research execution failed after positive task reclamation",
            )?;
            ResearchExecution::fail_finite_guarded(
                authority,
                &namespace,
                &run,
                &mut claim,
                &drained,
                &failure,
                RetryDecision::FinalFail,
                clock()?,
            )
            .await
            .map_err(Into::into)
        }
    }
}
#[derive(Default)]
struct Reaper {
    requested: bool,
    task: Option<tokio::task::JoinHandle<Result<()>>>,
}
impl Reaper {
    fn request(
        &mut self,
        control: &crate::application::research_run_execution::Control,
        run_id: &str,
    ) {
        if self.requested {
            return;
        }
        self.requested = true;
        control.request_stop();
        let control = control.clone();
        let dispatch = tracing::dispatcher::get_default(Clone::clone);
        let parent = tracing::Span::current();
        let run_id = run_id.to_owned();
        self.task = Some(tokio::task::spawn_blocking(move || {
            tracing::dispatcher::with_default(&dispatch, || {
                parent.in_scope(|| {
                    let correlation = onlyalpha_observability::Correlation {
                        run_id: Some(run_id.clone()),
                        ..Default::default()
                    };
                    let result = onlyalpha_observability::measure(
                        "backend",
                        "research.reaper",
                        correlation,
                        || control.stop(),
                    );
                    #[cfg(test)]
                    super::research_service::owner_tests::reaper_finished(&run_id, result.is_ok());
                    result
                })
            })
        }));
    }
    fn finished(&self) -> bool {
        self.task.as_ref().is_some_and(|task| task.is_finished())
    }
    async fn join(&mut self) -> Result<()> {
        let Some(task) = self.task.as_mut() else {
            return Ok(());
        };
        let outcome = task
            .await
            .map_err(|_| PreparationError::unknown("RESEARCH_REAPER_JOIN_UNKNOWN", None));
        self.task.take();
        outcome?
    }
}
fn publication_error(
    error: crate::persistence::job_publication::PublicationError,
) -> PreparationError {
    use crate::persistence::job_publication::PublicationError as P;
    match error {
        P::OutcomeUnknown => {
            PreparationError::unknown("RESEARCH_PUBLICATION_OUTCOME_UNKNOWN", None)
        }
        P::OwnershipLost => "RESEARCH_PUBLICATION_OWNERSHIP_LOST".into(),
        P::Unavailable => "RESEARCH_PUBLICATION_UNAVAILABLE".into(),
        P::Denied => "RESEARCH_PUBLICATION_DENIED".into(),
        P::MissingEvidence => "RESEARCH_PUBLICATION_MISSING_EVIDENCE".into(),
        P::BudgetExceeded => "RESEARCH_PUBLICATION_BUDGET_EXCEEDED".into(),
        P::Integrity | P::Mismatch => "RESEARCH_PUBLICATION_INTEGRITY_MISMATCH".into(),
        P::Conflict => "RESEARCH_PUBLICATION_CONFLICT".into(),
    }
}

fn unknown(error: &PreparationError) -> bool {
    error.code().contains("UNKNOWN")
        || error.code().contains("UNCERTAIN")
        || error.recovery_owner().is_some_and(|owner| {
            owner.state() != onlyalpha_calculation_bridge::ProcessState::Joined
        })
}
async fn tick(
    writer: &SharedAuthority,
    run: &VerifiedRun,
    claim: &mut Claim,
    heartbeat: &mut tokio::time::Instant,
) -> Result<RunStatus> {
    let mut held = writer.lock().await;
    let result = async {
        let authority = held.as_mut().ok_or(UNKNOWN)?;
        if tokio::time::Instant::now() >= *heartbeat {
            ResearchExecution::heartbeat_guarded(authority, claim).await?;
            *heartbeat = tokio::time::Instant::now() + Duration::from_secs(30);
        }
        let status = ResearchExecution::observe_guarded(authority, run).await?;
        if !matches!(status.state, RunState::Running | RunState::CancelRequested) {
            return Err(UNKNOWN);
        }
        Ok::<_, &'static str>(status)
    }
    .await;
    result.map_err(|code| {
        claim.revoke_certainty();
        tracing::warn!(
            run_id = run.run_id(),
            attempt_id = claim.attempt_id(),
            rejection = code,
            "finite Research control observation failed"
        );
        PreparationError::unknown(UNKNOWN, None)
    })
}
