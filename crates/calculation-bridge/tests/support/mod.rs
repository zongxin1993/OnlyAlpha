use onlyalpha_calculation_bridge::{ProcessControl, ProcessState, Result};
use std::sync::{
    Arc,
    atomic::{AtomicBool, Ordering},
};
#[derive(Default)]
struct Peer(AtomicBool);
impl ProcessControl for Peer {
    fn state(&self) -> ProcessState {
        if self.0.load(Ordering::SeqCst) {
            ProcessState::Joined
        } else {
            ProcessState::Running
        }
    }
    fn terminate(&self, _: bool) -> Result<()> {
        self.0.store(true, Ordering::SeqCst);
        Ok(())
    }
}
pub fn control() -> Arc<dyn ProcessControl> {
    Arc::new(Peer::default())
}
