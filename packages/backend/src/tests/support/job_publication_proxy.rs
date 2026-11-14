//! Controlled PG-wire fault adapter to the SAME canonical PostgreSQL service.
//! No SQL spoofing, mock COMMIT or alternate database instance.
use std::{
    io::{Read, Write},
    net::{Shutdown, TcpListener, TcpStream},
    sync::{
        Arc, Mutex,
        atomic::{AtomicBool, Ordering},
        mpsc,
    },
    thread,
};
use tokio::sync::oneshot;
#[derive(Clone, Copy)]
pub enum Mode {
    PauseBeforeCommit,
    DropBeforeCommit,
    DropCommitReply,
}
struct Shared {
    armed: AtomicBool,
    waiting_commit: AtomicBool,
    stopped: AtomicBool,
    sockets: Mutex<Vec<TcpStream>>,
    entered: Mutex<Option<oneshot::Sender<()>>>,
}
impl Shared {
    fn enter(&self) {
        if let Some(tx) = self.entered.lock().unwrap().take() {
            let _ = tx.send(());
        }
    }
    fn close(&self) {
        self.stopped.store(true, Ordering::SeqCst);
        for s in self.sockets.lock().unwrap().iter() {
            let _ = s.shutdown(Shutdown::Both);
        }
    }
}
pub struct Proxy {
    port: u16,
    shared: Arc<Shared>,
    entered: Option<oneshot::Receiver<()>>,
    release: mpsc::Sender<()>,
    thread: Option<thread::JoinHandle<()>>,
}
fn frame(r: &mut TcpStream) -> std::io::Result<(u8, Vec<u8>)> {
    let mut header = [0u8; 5];
    r.read_exact(&mut header)?;
    let len = u32::from_be_bytes(header[1..5].try_into().unwrap()) as usize;
    if !(4..=8 * 1024 * 1024).contains(&len) {
        return Err(std::io::Error::other("PG frame budget"));
    }
    let mut raw = header.to_vec();
    raw.resize(len + 1, 0);
    r.read_exact(&mut raw[5..])?;
    Ok((header[0], raw))
}
impl Proxy {
    pub fn start(mode: Mode) -> Self {
        let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
        let port = listener.local_addr().unwrap().port();
        let (tx, rx) = oneshot::channel();
        let (release, wait) = mpsc::channel();
        let shared = Arc::new(Shared {
            armed: AtomicBool::new(false),
            waiting_commit: AtomicBool::new(false),
            stopped: AtomicBool::new(false),
            sockets: Mutex::new(Vec::new()),
            entered: Mutex::new(Some(tx)),
        });
        let state = shared.clone();
        let worker = thread::spawn(move || {
            let (mut client, _) = listener.accept().unwrap();
            if state.stopped.load(Ordering::SeqCst) {
                return;
            }
            let mut server = TcpStream::connect(("postgres", 5432)).unwrap();
            state
                .sockets
                .lock()
                .unwrap()
                .extend([client.try_clone().unwrap(), server.try_clone().unwrap()]);
            let up_state = state.clone();
            let mut from_client = client.try_clone().unwrap();
            let mut to_server = server.try_clone().unwrap();
            let up = thread::spawn(move || {
                let result = (|| -> std::io::Result<()> {
                    let mut len = [0; 4];
                    from_client.read_exact(&mut len)?;
                    let n = u32::from_be_bytes(len) as usize;
                    if !(8..=1024 * 1024).contains(&n) {
                        return Err(std::io::Error::other("PG startup budget"));
                    }
                    let mut startup = len.to_vec();
                    startup.resize(n, 0);
                    from_client.read_exact(&mut startup[4..])?;
                    to_server.write_all(&startup)?;
                    loop {
                        let (tag, raw) = frame(&mut from_client)?;
                        if tag == b'Q'
                            && raw[5..] == *b"COMMIT\0"
                            && up_state.armed.swap(false, Ordering::SeqCst)
                        {
                            match mode {
                                Mode::DropBeforeCommit => {
                                    up_state.enter();
                                    up_state.close();
                                    return Ok(());
                                }
                                Mode::PauseBeforeCommit => {
                                    up_state.enter();
                                    let _ = wait.recv();
                                    if up_state.stopped.load(Ordering::SeqCst) {
                                        return Ok(());
                                    }
                                }
                                Mode::DropCommitReply => {
                                    up_state.waiting_commit.store(true, Ordering::SeqCst);
                                }
                            }
                        }
                        to_server.write_all(&raw)?;
                    }
                })();
                let _ = result;
                up_state.close();
            });
            let result = (|| -> std::io::Result<()> {
                loop {
                    let (tag, raw) = frame(&mut server)?;
                    if matches!(mode, Mode::DropCommitReply)
                        && state.waiting_commit.load(Ordering::SeqCst)
                        && tag == b'C'
                        && raw[5..] == *b"COMMIT\0"
                    {
                        // Server CommandComplete(COMMIT) is observed but NEVER delivered to client.
                        state.enter();
                        state.close();
                        return Ok(());
                    }
                    client.write_all(&raw)?;
                }
            })();
            let _ = result;
            state.close();
            up.join().unwrap();
        });
        Self {
            port,
            shared,
            entered: Some(rx),
            release,
            thread: Some(worker),
        }
    }
    pub fn port(&self) -> u16 {
        self.port
    }
    pub fn arm(&self) {
        self.shared.armed.store(true, Ordering::SeqCst);
    }
    pub async fn entered(&mut self) {
        tokio::time::timeout(
            std::time::Duration::from_secs(10),
            self.entered.take().unwrap(),
        )
        .await
        .expect("PG protocol fault barrier not reached")
        .expect("PG fault adapter closed before barrier");
    }
    pub fn release(&self) {
        let _ = self.release.send(());
    }
}
impl Drop for Proxy {
    fn drop(&mut self) {
        self.shared.close();
        self.release();
        let _ = TcpStream::connect(("127.0.0.1", self.port));
        if let Some(t) = self.thread.take() {
            t.join().unwrap();
        }
    }
}
