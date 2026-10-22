//! Descriptor-relative retained WAL roots. Opening/recovery never initializes a
//! semantic store. New capture directories are created only by admitted work.
use crate::{
    host::{Failure, Host, ROWS, WORK},
    startup::Directory,
};
use onlyalpha_product_runtime::{
    market_data::{Catalog, Storage},
    market_data_wal::Wal,
    market_product::{drain_historical_capture, drain_market_capture},
    protected_files::{self, ReadError},
};
use std::{
    ffi::OsStr,
    os::fd::{AsFd, BorrowedFd, OwnedFd},
};
fn code(_: ReadError) -> Failure {
    Failure::unavailable("MARKET_DATA_WAL_ROOT_UNAVAILABLE")
}
fn children(directory: &OwnedFd) -> Result<Vec<String>, Failure> {
    let mut names = vec![];
    let entries = rustix::fs::Dir::read_from(directory)
        .map_err(|_| Failure::unavailable("MARKET_DATA_WAL_ROOT_UNAVAILABLE"))?;
    for entry in entries {
        let entry = entry.map_err(|_| Failure::unavailable("MARKET_DATA_WAL_ROOT_UNAVAILABLE"))?;
        let name = entry.file_name().to_bytes();
        if matches!(name, b"." | b"..") {
            continue;
        }
        if names.len() >= 4096 || name.len() > 256 {
            return Err(Failure::unavailable("MARKET_DATA_WAL_INVENTORY_CAPACITY"));
        }
        names.push(
            std::str::from_utf8(name)
                .map_err(|_| Failure::unavailable("MARKET_DATA_WAL_ROOT_INVALID"))?
                .into(),
        );
    }
    names.sort();
    Ok(names)
}
fn optional(parent: &impl AsFd, name: &str) -> Result<Option<OwnedFd>, Failure> {
    match protected_files::open_directory_at(parent, OsStr::new(name)) {
        Ok(fd) => Ok(Some(fd)),
        Err(ReadError::Missing) => Ok(None),
        Err(e) => Err(code(e)),
    }
}
fn create(parent: &impl AsFd, name: &str) -> Result<OwnedFd, Failure> {
    if name.is_empty()
        || name.len() > 256
        || !name
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'.' | b'-' | b'_'))
        || matches!(name, "." | "..")
    {
        return Err(Failure::unavailable("MARKET_DATA_WAL_ROOT_INVALID"));
    }
    match rustix::fs::mkdirat(parent, name, rustix::fs::Mode::from_raw_mode(0o700)) {
        Ok(()) | Err(rustix::io::Errno::EXIST) => {}
        Err(_) => return Err(Failure::unavailable("MARKET_DATA_WAL_ROOT_UNAVAILABLE")),
    }
    protected_files::open_directory_at(parent, OsStr::new(name)).map_err(code)
}
impl Host {
    pub(crate) fn capture_wal(&self, source: &str, stream: Option<&str>) -> Result<Wal, Failure> {
        let root = create(
            &self.inputs.roots().directory(Directory::UserData),
            "market-data",
        )?;
        let source = create(&root, source)?;
        let parent = if let Some(stream) = stream {
            let realtime = create(&source, "realtime")?;
            create(&realtime, stream)?
        } else {
            source
        };
        let wal = create(&parent, "wal")?;
        Wal::from_directory(wal.as_fd(), 128 * 1024 * 1024)
            .map_err(|e| Failure::unavailable(e.code()))
    }
    pub(crate) async fn recover_market_data(&self) -> Result<(), Failure> {
        let Some(root) = optional(
            &self.inputs.roots().directory(Directory::UserData),
            "market-data",
        )?
        else {
            return Ok(());
        };
        for source in children(&root)? {
            if source.starts_with('.') {
                continue;
            }
            let source =
                protected_files::open_directory_at(&root, OsStr::new(&source)).map_err(code)?;
            if let Some(wal) = optional(&source, "wal")? {
                self.recover_wal(wal.as_fd()).await?;
            }
            if let Some(realtime) = optional(&source, "realtime")? {
                for stream in children(&realtime)? {
                    let stream = protected_files::open_directory_at(&realtime, OsStr::new(&stream))
                        .map_err(code)?;
                    if let Some(wal) = optional(&stream, "wal")? {
                        self.recover_wal(wal.as_fd()).await?;
                    }
                }
            }
        }
        Ok(())
    }
    async fn recover_wal(&self, directory: BorrowedFd<'_>) -> Result<(), Failure> {
        let mut wal = Wal::from_directory(directory, 128 * 1024 * 1024)
            .map_err(|e| Failure::unavailable(e.code()))?;
        let mut authority = self.writer.lock().await;
        let client = authority
            .as_mut()
            .ok_or_else(|| Failure::unavailable("PRODUCT_AUTHORITY_UNAVAILABLE"))?
            .client_mut()
            .await
            .map_err(|_| Failure::unavailable("PRODUCT_AUTHORITY_UNAVAILABLE"))?;
        let mut store = Storage::new(Catalog::new(client, ROWS, WORK)?, &self.clickhouse, 100000)?;
        store.recover_wal_inputs(&mut wal).await?;
        let ids = wal
            .published_sealed()
            .map_err(|e| Failure::unavailable(e.code()))?;
        let mut history = vec![];
        let mut live = vec![];
        for id in ids {
            let metadata = wal
                .load_segment(&id)
                .map_err(|e| Failure::unavailable(e.code()))?;
            match metadata["capture_mode"].as_str() {
                Some("REST_BACKFILL") => history.push(id),
                Some("REALTIME_STREAM") => live.push(id),
                _ => {
                    return Err(Failure::unavailable(
                        "MARKET_DATA_WAL_PROVENANCE_UNPROVABLE",
                    ));
                }
            }
        }
        let mut sealed = wal
            .sealed_handle()
            .map_err(|e| Failure::unavailable(e.code()))?;
        let at = crate::host::now()?.to_string();
        drain_historical_capture(&mut sealed, &mut store, &history, &at).await?;
        drain_market_capture(&mut sealed, &mut store, &live, &at).await?;
        Ok(())
    }
}
