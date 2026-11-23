//! Background construction within the existing backend process. PostgreSQL owns
//! the queue; wake/status are hints and never readiness or publication authority.
use crate::{
    application::factor_build::{BuildStatus, FactorBuildService},
    bootstrap::deployment::SemanticStoreId,
};
use onlyalpha_calculation_bridge::ChartInstallation;
use std::sync::{
    Arc,
    atomic::{AtomicU8, Ordering},
};
use tokio::{
    sync::{Notify, watch},
    task::JoinHandle,
};
use tokio_postgres::Client;
const UNAVAILABLE: &str = "FACTOR_BUILD_SERVICE_UNAVAILABLE";
const UNKNOWN: &str = "FACTOR_BUILD_SERVICE_OUTCOME_UNKNOWN";
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Status {
    Starting,
    Idle,
    Published { revision: String },
    Rejected,
    Unavailable,
    Stopped,
}
struct Admission {
    state: AtomicU8,
    changed: Notify,
}
#[derive(Clone)]
pub(crate) struct Wake(Arc<Admission>);
impl Wake {
    pub(crate) fn notify(&self) {
        self.0.changed.notify_one();
    }
    pub(crate) fn stop(&self) {
        self.0.state.fetch_or(2, Ordering::AcqRel);
        self.notify();
    }
    fn begin(&self) -> bool {
        self.0
            .state
            .compare_exchange(0, 1, Ordering::AcqRel, Ordering::Acquire)
            .is_ok()
    }
    fn finish(&self) {
        let _ = self
            .0
            .state
            .compare_exchange(1, 0, Ordering::AcqRel, Ordering::Acquire);
        let _ = self
            .0
            .state
            .compare_exchange(3, 2, Ordering::AcqRel, Ordering::Acquire);
    }
    fn stopped(&self) -> bool {
        self.0.state.load(Ordering::Acquire) & 2 != 0
    }
}
pub struct Service {
    wake: Wake,
    status: watch::Receiver<Status>,
    task: Option<JoinHandle<Result<(), &'static str>>>,
    drained: Option<Result<(), &'static str>>,
}
impl Service {
    pub async fn start(
        mut client: Client,
        mut driver: JoinHandle<Result<(), tokio_postgres::Error>>,
        namespace: SemanticStoreId,
        installation: Arc<ChartInstallation>,
    ) -> Result<Self, &'static str> {
        let checked=async {
   client.batch_execute("SET ROLE onlyalpha_factor_builder; SET application_name='onlyalpha-factor-build'").await.map_err(|_|UNAVAILABLE)?;
   FactorBuildService::new(&mut client,&namespace,installation.clone()).await.map_err(|_|UNAVAILABLE)?;Ok(())
  }.await;
        if let Err(e) = checked {
            drop(client);
            driver.abort();
            let _ = driver.await;
            return Err(e);
        }
        let wake = Wake(Arc::new(Admission {
            state: AtomicU8::new(0),
            changed: Notify::new(),
        }));
        let selected = wake.clone();
        let (status, observed) = watch::channel(Status::Starting);
        // No await after spawning: cancellation of start cannot orphan an admitted task.
        let task = tokio::spawn(async move {
            let result=async {
    let mut owner=FactorBuildService::new(&mut client,&namespace,installation).await.map_err(|_|UNAVAILABLE)?;
    let mut poll=tokio::time::interval(std::time::Duration::from_secs(5));poll.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
    loop {
     if selected.stopped(){break;}
     if !selected.begin(){break;}
     let result=owner.run_pending().await;selected.finish();
     match result {
      Ok(Some(report)) if report.status==BuildStatus::Ready => {
       // Report exists only after COMMIT; owning readers still verify PG.
       status.send_replace(Status::Published{revision:report.revision});
      },
      Ok(Some(report)) if report.status==BuildStatus::Failed => {status.send_replace(Status::Rejected);},
      Ok(Some(_))|Ok(None)=>{if matches!(*status.borrow(),Status::Starting){status.send_replace(Status::Idle);}tokio::select!{_ = selected.0.changed.notified()=>{},_ = poll.tick()=>{}}},
      Err(_)=>return Err(UNKNOWN),
     }
    }Ok(())
   }.await;
            drop(client);
            let closed =
                match tokio::time::timeout(std::time::Duration::from_secs(5), &mut driver).await {
                    Ok(Ok(Ok(()))) => Ok(()),
                    _ => {
                        driver.abort();
                        let _ = driver.await;
                        Err(UNKNOWN)
                    }
                };
            let outcome = result.and(closed);
            status.send_replace(if outcome.is_ok() {
                Status::Stopped
            } else {
                Status::Unavailable
            });
            outcome
        });
        Ok(Self {
            wake,
            status: observed,
            task: Some(task),
            drained: None,
        })
    }
    pub fn subscribe(&self) -> watch::Receiver<Status> {
        self.status.clone()
    }
    pub(crate) fn wake(&self) -> Wake {
        self.wake.clone()
    }
    pub async fn drain(&mut self) -> Result<(), &'static str> {
        self.wake.stop();
        if let Some(result) = self.drained {
            return result;
        }
        let task = self.task.as_mut().ok_or(UNKNOWN)?;
        let result = task.await.unwrap_or(Err(UNKNOWN));
        self.task.take();
        self.drained = Some(result);
        result
    }
}
impl Drop for Service {
    fn drop(&mut self) {
        self.wake.stop();
    }
}
