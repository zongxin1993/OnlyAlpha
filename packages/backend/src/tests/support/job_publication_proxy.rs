//! Controlled PG-wire fault adapter to the SAME canonical PostgreSQL service.
//! No SQL spoofing, mock COMMIT or alternate database instance.
use std::{
    io::{self, Read, Write},
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
    DropBeforeRoleRestore,
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
const FRAME_PREFIX_BYTES: usize = 16 * 1024;

struct Frame<'a> {
    prefix: &'a [u8],
    remaining: u64,
}

impl<'a> Frame<'a> {
    fn read(reader: &mut TcpStream, buffer: &'a mut [u8; FRAME_PREFIX_BYTES]) -> io::Result<Self> {
        reader.read_exact(&mut buffer[..5])?;
        let length = i32::from_be_bytes(buffer[1..5].try_into().unwrap());
        if length < 4 {
            return Err(io::Error::new(io::ErrorKind::InvalidData, "PG frame length"));
        }
        let frame_bytes = length as usize + 1;
        let prefix_bytes = frame_bytes.min(buffer.len());
        reader.read_exact(&mut buffer[5..prefix_bytes])?;
        Ok(Self {
            prefix: &buffer[..prefix_bytes],
            remaining: (frame_bytes - prefix_bytes) as u64,
        })
    }

    fn matches(&self, tag: u8, body: &[u8]) -> bool {
        self.remaining == 0 && self.prefix[0] == tag && &self.prefix[5..] == body
    }

    fn forward(self, reader: &mut TcpStream, writer: &mut TcpStream) -> io::Result<()> {
        writer.write_all(self.prefix)?;
        if self.remaining != 0 {
            let copied = io::copy(&mut reader.take(self.remaining), writer)?;
            if copied != self.remaining {
                return Err(io::Error::new(io::ErrorKind::UnexpectedEof, "PG frame body"));
            }
        }
        Ok(())
    }
}
impl Proxy {
    pub fn start(mode: Mode) -> Self {
        Self::launch(mode, || TcpStream::connect(("postgres", 5432)).unwrap())
    }

    #[allow(dead_code)]
    pub fn forward(mode: Mode, upstream: TcpStream) -> Self {
        Self::launch(mode, || upstream)
    }

    fn launch(mode: Mode, upstream: impl FnOnce() -> TcpStream + Send + 'static) -> Self {
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
            let mut server = upstream();
            // Forwarding PG frames individually must not add a delayed ACK window at either hop.
            client.set_nodelay(true).unwrap();
            server.set_nodelay(true).unwrap();
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
                    let mut buffer = [0; FRAME_PREFIX_BYTES];
                    loop {
                        let frame = Frame::read(&mut from_client, &mut buffer)?;
                        let fault_query = match mode {
                            Mode::DropBeforeRoleRestore => &b"RESET ROLE\0"[..],
                            _ => &b"COMMIT\0"[..],
                        };
                        if frame.matches(b'Q', fault_query)
                            && up_state.armed.swap(false, Ordering::SeqCst)
                        {
                            match mode {
                                Mode::DropBeforeCommit | Mode::DropBeforeRoleRestore => {
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
                        frame.forward(&mut from_client, &mut to_server)?;
                    }
                })();
                let _ = result;
                up_state.close();
            });
            let result = (|| -> io::Result<()> {
                let mut buffer = [0; FRAME_PREFIX_BYTES];
                loop {
                    let frame = Frame::read(&mut server, &mut buffer)?;
                    if matches!(mode, Mode::DropCommitReply)
                        && state.waiting_commit.load(Ordering::SeqCst)
                        && frame.matches(b'C', b"COMMIT\0")
                    {
                        // Server CommandComplete(COMMIT) is observed but NEVER delivered to client.
                        state.enter();
                        state.close();
                        return Ok(());
                    }
                    frame.forward(&mut server, &mut client)?;
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

    pub fn disconnect(&self) {
        self.shared.close();
        self.release();
    }
}
impl Drop for Proxy {
    fn drop(&mut self) {
        self.disconnect();
        let _ = TcpStream::connect(("127.0.0.1", self.port));
        if let Some(t) = self.thread.take() {
            t.join().unwrap();
        }
    }
}
