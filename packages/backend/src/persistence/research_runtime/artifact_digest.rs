//! One bounded immutable bytes -> SHA result. No path, FD, Source or Ready proof.
use sha2::{Digest, Sha256};
use std::sync::{
    Arc, Mutex,
    atomic::{AtomicBool, Ordering},
};
const MIN: u64 = 1024 * 1024;
const MAX: u64 = 64 * 1024 * 1024;
pub(super) struct ContentDigest {
    bytes: Vec<u8>,
    digest: [u8; 32],
}
pub(super) struct ArtifactDigestMemo {
    pub(super) slot: Mutex<Option<Arc<ContentDigest>>>,
    pub(super) capturing: AtomicBool,
    #[cfg(test)]
    pub(super) hashed_bytes: std::sync::atomic::AtomicU64,
}
impl ArtifactDigestMemo {
    pub(super) const fn new() -> Self {
        Self {
            slot: Mutex::new(None),
            capturing: AtomicBool::new(false),
            #[cfg(test)]
            hashed_bytes: std::sync::atomic::AtomicU64::new(0),
        }
    }
    pub(super) fn stream(&self, size: u64) -> StreamHash<'_> {
        let mut cached = None;
        let mut permit = None;
        if (MIN..=MAX).contains(&size)
            && let Ok(slot) = self.slot.try_lock()
        {
            if let Some(value) = slot.as_ref() {
                if value.bytes.len() as u64 == size {
                    cached = Some(Arc::clone(value));
                }
            } else if self
                .capturing
                .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
                .is_ok()
            {
                permit = Some(CapturePermit(self));
            }
        }
        let capture = permit.and_then(|permit| {
            let mut bytes = Vec::new();
            let size = usize::try_from(size).ok()?;
            // Allocation is optional, bounded and outside the slot lock.
            if bytes.try_reserve_exact(size).is_err() || bytes.capacity() as u64 > MAX {
                return None;
            }
            Some(Capture {
                bytes,
                limit: size,
                permit,
            })
        });
        let hash = if cached.is_some() {
            None
        } else {
            Some(Sha256::new())
        };
        StreamHash {
            cached,
            hash,
            matched: 0,
            capture,
            #[cfg(test)]
            memo: self,
        }
    }
}
struct CapturePermit<'a>(&'a ArtifactDigestMemo);
impl Drop for CapturePermit<'_> {
    fn drop(&mut self) {
        self.0.capturing.store(false, Ordering::Release);
    }
}
struct Capture<'a> {
    bytes: Vec<u8>,
    limit: usize,
    permit: CapturePermit<'a>,
}
pub(super) struct StreamHash<'a> {
    cached: Option<Arc<ContentDigest>>,
    hash: Option<Sha256>,
    matched: usize,
    capture: Option<Capture<'a>>,
    #[cfg(test)]
    memo: &'a ArtifactDigestMemo,
}
impl StreamHash<'_> {
    fn feed(&mut self, bytes: &[u8]) {
        #[cfg(test)]
        self.memo
            .hashed_bytes
            .fetch_add(bytes.len() as u64, Ordering::Relaxed);
        self.hash
            .as_mut()
            .expect("cold SHA initialized")
            .update(bytes);
    }
    pub(super) fn update(&mut self, bytes: &[u8]) {
        if self.hash.is_none() {
            let cached = self.cached.as_ref().expect("warm content selected");
            if self
                .matched
                .checked_add(bytes.len())
                .and_then(|end| cached.bytes.get(self.matched..end))
                == Some(bytes)
            {
                self.matched += bytes.len();
                return;
            }
            // Prefix bytes have just matched the actual reads. Feed that exact
            // prefix before the first different actual chunk, then stay cold.
            let cached = self.cached.take().expect("warm content selected");
            self.hash = Some(Sha256::new());
            self.feed(&cached.bytes[..self.matched]);
        }
        self.feed(bytes);
        if self.capture.as_ref().is_some_and(|capture| {
            capture
                .bytes
                .len()
                .checked_add(bytes.len())
                .is_none_or(|end| end > capture.limit)
        }) {
            // A growing actual file cannot cause a second/unbounded allocation.
            self.capture = None;
        }
        if let Some(capture) = self.capture.as_mut() {
            capture.bytes.extend_from_slice(bytes);
        }
    }
    pub(super) fn finish(mut self) -> [u8; 32] {
        // This private type is also an exact pure stream hash for a shorter
        // sequence; the physical owner independently rejects incorrect totals.
        if self.hash.is_none()
            && self
                .cached
                .as_ref()
                .is_some_and(|cached| self.matched != cached.bytes.len())
        {
            let cached = self.cached.take().expect("warm content selected");
            self.hash = Some(Sha256::new());
            self.feed(&cached.bytes[..self.matched]);
        }
        let digest = if let Some(hash) = self.hash.take() {
            let mut digest = [0; 32];
            digest.copy_from_slice(&hash.finalize());
            digest
        } else {
            self.cached
                .as_ref()
                .expect("matching complete content")
                .digest
        };
        if let Some(capture) = self.capture.take()
            && capture.bytes.len() == capture.limit
        {
            let Capture { bytes, permit, .. } = capture;
            let data = Arc::new(ContentDigest { bytes, digest });
            if let Ok(mut slot) = permit.0.slot.try_lock() {
                // The first content wins. Never allocate a replacement while
                // old readers retain the original slot's bounded bytes.
                if slot.is_none() {
                    *slot = Some(data);
                }
            }
        }
        digest
    }
}
