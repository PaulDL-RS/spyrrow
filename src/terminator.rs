//! Cooperative termination for the 1.0 engine.
//!
//! One shared [`Control`] is read by the sparrow [`Terminator`] (polled very frequently by
//! the solver) and written by the event listener (callback asked to stop / failed) and by the
//! Ctrl-C probe.

use jagua_rs::Instant;
use pyo3::{PyErr, Python};
use sparrow::util::terminator::Terminator;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

/// Minimum delay between two probes of Python's signal state.
/// `Terminator::kill` is polled in hot loops, taking the GIL on every poll is wasteful.
const SIGNAL_PROBE_INTERVAL_MS: u64 = 50;

pub struct Control {
    /// Set when the solver must stop as soon as possible, whatever the reason.
    stop: AtomicBool,
    /// The stop was caused by a pending signal (Ctrl-C).
    signal: AtomicBool,
    /// The stop was requested by an event callback (graceful).
    callback_stop: AtomicBool,
    /// The error raised by an event callback, to re-raise from `solve`.
    callback_error: Mutex<Option<PyErr>>,
    last_probe_ms: AtomicU64,
    epoch: Instant,
}

impl Control {
    pub fn new() -> Arc<Self> {
        Arc::new(Self {
            stop: AtomicBool::new(false),
            signal: AtomicBool::new(false),
            callback_stop: AtomicBool::new(false),
            callback_error: Mutex::new(None),
            last_probe_ms: AtomicU64::new(0),
            epoch: Instant::now(),
        })
    }

    pub fn is_stopped(&self) -> bool {
        self.stop.load(Ordering::Relaxed)
    }

    pub fn request_graceful_stop(&self) {
        self.callback_stop.store(true, Ordering::Relaxed);
        self.stop.store(true, Ordering::Relaxed);
    }

    pub fn fail_with(&self, err: PyErr) {
        let mut slot = self.callback_error.lock().expect("poisoned lock");
        if slot.is_none() {
            *slot = Some(err);
        }
        self.stop.store(true, Ordering::Relaxed);
    }

    pub fn take_error(&self) -> Option<PyErr> {
        self.callback_error.lock().expect("poisoned lock").take()
    }

    pub fn interruption(&self) -> &'static str {
        if self.signal.load(Ordering::Relaxed) {
            "signal"
        } else if self.callback_stop.load(Ordering::Relaxed) {
            "callback"
        } else {
            "none"
        }
    }

    /// Returns true if a signal (Ctrl-C) is pending. Rate limited.
    fn probe_signals(&self) -> bool {
        let now = self.epoch.elapsed().as_millis() as u64;
        let last = self.last_probe_ms.load(Ordering::Relaxed);
        if now.saturating_sub(last) < SIGNAL_PROBE_INTERVAL_MS
            || self
                .last_probe_ms
                .compare_exchange(last, now, Ordering::Relaxed, Ordering::Relaxed)
                .is_err()
        {
            return false;
        }
        // `check_signals` only runs handlers on the main thread, elsewhere it is a no-op.
        let interrupted = Python::attach(|py| py.check_signals().is_err());
        if interrupted {
            self.signal.store(true, Ordering::Relaxed);
            self.stop.store(true, Ordering::Relaxed);
        }
        interrupted
    }
}

pub struct EngineTerminator {
    timeout: Option<Instant>,
    control: Arc<Control>,
}

impl EngineTerminator {
    pub fn new(control: Arc<Control>) -> Self {
        Self {
            timeout: None,
            control,
        }
    }
}

impl Terminator for EngineTerminator {
    fn kill(&self) -> bool {
        self.control.is_stopped()
            || self.timeout.is_some_and(|t| Instant::now() > t)
            || self.control.probe_signals()
    }

    fn new_timeout(&mut self, timeout: Duration) {
        self.timeout = Some(Instant::now() + timeout);
    }

    fn timeout_at(&self) -> Option<Instant> {
        self.timeout
    }
}
