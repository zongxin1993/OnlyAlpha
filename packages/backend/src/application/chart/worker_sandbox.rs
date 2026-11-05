//! Linux syscall policy for the single-threaded Chart numeric worker.

use super::{Error, Result};

pub(super) const POLICY: &str = "LINUX_SECCOMP_NO_NEW_PRIVS_RLIMIT_V1";

#[cfg(target_os = "linux")]
pub(super) fn restrict() -> Result<()> {
    use seccompiler::{
        BpfProgram, SeccompAction, SeccompCmpArgLen, SeccompCmpOp, SeccompCondition, SeccompFilter,
        SeccompRule,
    };
    use std::collections::BTreeMap;

    // No pathname opens, sockets, descriptor duplication, or process creation.
    // The worker owns only its inherited stream and local computation memory.
    let allowed = [
        libc::SYS_close,
        libc::SYS_munmap,
        libc::SYS_mremap,
        libc::SYS_madvise,
        libc::SYS_brk,
        libc::SYS_futex,
        libc::SYS_clock_gettime,
        libc::SYS_sigaltstack,
        libc::SYS_rt_sigreturn,
        libc::SYS_exit,
        libc::SYS_exit_group,
    ];
    let mut rules = allowed
        .into_iter()
        .map(|call| (call, Vec::new()))
        .collect::<BTreeMap<_, _>>();
    let condition = |argument, operation, value| {
        SeccompCondition::new(argument, SeccompCmpArgLen::Dword, operation, value)
            .map_err(|_| Error::Unavailable)
    };
    let rule = |conditions| SeccompRule::new(conditions).map_err(|_| Error::Unavailable);
    for (syscall, descriptors) in [
        (libc::SYS_read, &[0][..]),
        (libc::SYS_write, &[1, 2][..]),
        (libc::SYS_writev, &[1, 2][..]),
        (libc::SYS_fstat, &[0, 1, 2][..]),
    ] {
        let descriptors = descriptors
            .iter()
            .map(|&fd| rule(vec![condition(0, SeccompCmpOp::Eq, fd)?]))
            .collect::<Result<Vec<_>>>()?;
        rules.insert(syscall, descriptors);
    }
    let non_executable = || condition(2, SeccompCmpOp::MaskedEq(libc::PROT_EXEC as u64), 0);
    let anonymous = libc::MAP_ANONYMOUS as u64;
    rules.insert(
        libc::SYS_mmap,
        vec![rule(vec![
            non_executable()?,
            condition(3, SeccompCmpOp::MaskedEq(anonymous), anonymous)?,
        ])?],
    );
    rules.insert(libc::SYS_mprotect, vec![rule(vec![non_executable()?])?]);
    let filter = SeccompFilter::new(
        rules,
        SeccompAction::Errno(libc::EPERM as u32),
        SeccompAction::Allow,
        std::env::consts::ARCH
            .try_into()
            .map_err(|_| Error::Unavailable)?,
    )
    .map_err(|_| Error::Unavailable)?;
    let program: BpfProgram = filter.try_into().map_err(|_| Error::Unavailable)?;
    seccompiler::apply_filter_all_threads(&program).map_err(|_| Error::Unavailable)?;

    // Without the filter, RLIMIT_NOFILE alone yields EMFILE rather than EPERM.
    let denied = |result: std::io::Result<()>| {
        result.is_err_and(|error| error.raw_os_error() == Some(libc::EPERM))
    };
    if !denied(std::fs::File::open("/proc/self/status").map(drop))
        || !denied(std::net::TcpListener::bind((std::net::Ipv4Addr::LOCALHOST, 0)).map(drop))
    {
        return Err(Error::Unavailable);
    }
    Ok(())
}

#[cfg(not(target_os = "linux"))]
pub(super) fn restrict() -> Result<()> {
    Err(Error::Unavailable)
}
