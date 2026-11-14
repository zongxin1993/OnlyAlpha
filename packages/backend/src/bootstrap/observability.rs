//! 后端配置与唯一全局订阅器入口；算法协议和纯导出角色不调用本模块。
use onlyalpha_observability::{Config, Mode, Session};
use std::{
    fs::OpenOptions,
    os::unix::fs::OpenOptionsExt,
    path::Path,
    sync::atomic::{AtomicBool, Ordering},
};
static INITIALIZED: AtomicBool = AtomicBool::new(false);

pub fn mode(configured: Option<&str>, legacy_profile: Option<&str>) -> Result<Mode, &'static str> {
    match configured {
        Some("off") => Ok(Mode::Off),
        Some("basic") => Ok(Mode::Basic),
        Some("detail") => Ok(Mode::Detail),
        Some(_) => Err("OBSERVABILITY_CONFIGURATION_INVALID"),
        None if legacy_profile == Some("1") => Ok(Mode::Detail),
        None => Ok(Mode::Basic),
    }
}
pub fn start(mode: Mode, output: Option<&Path>) -> Result<Option<Session>, &'static str> {
    if mode == Mode::Off {
        return Ok(None);
    }
    // 每进程只尝试一次；配置/输出失败也不自行重试或更换全局 subscriber。
    if INITIALIZED.swap(true, Ordering::AcqRel) {
        return Err("OBSERVABILITY_ALREADY_INITIALIZED");
    }
    let mut entropy = [0u8; 16];
    getrandom::fill(&mut entropy).map_err(|_| "OBSERVABILITY_ID_UNAVAILABLE")?;
    let instance: String = entropy.iter().map(|byte| format!("{byte:02x}")).collect();
    let config = Config::new(mode, instance, 8192);
    let session = match output {
        Some(path) => {
            let file = OpenOptions::new()
                .write(true)
                .create_new(true)
                .mode(0o600)
                .open(path)
                .map_err(|_| "OBSERVABILITY_OUTPUT_UNAVAILABLE")?;
            Session::new(config, file)
        }
        None => Session::new(config, std::io::stderr()),
    }?;
    tracing::dispatcher::set_global_default(session.dispatch().clone())
        .map_err(|_| "OBSERVABILITY_ALREADY_INITIALIZED")?;
    Ok(Some(session))
}
