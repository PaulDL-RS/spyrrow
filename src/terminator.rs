use jagua_rs::Instant;
use pyo3::Python;
use sparrow::util::terminator::Terminator;
use std::cell::Cell;
use std::time::Duration;
use std::sync::RwLock;

#[derive(Default)]
pub struct PythonTerminator {
    pub timeout: Option<Instant>,
    // This is to circumvent the fact that kill borrow immutably but there is two loops: exploration and compression
    finished: RwLock<Cell<bool>>,
}

impl Terminator for PythonTerminator {
    fn kill(&self) -> bool {
        self.finished.read().expect("I fucked up the lock mechanism").get()
            || self.timeout.is_some_and(|timeout| Instant::now() > timeout)
            || (Python::attach(|py| match py.check_signals() {
                Ok(_) => false,
                Err(_) => {
                    *self.finished.write().expect("I fucked up the lock mechanism").get_mut() = true;
                    true
                }
            }))
    }

    /// Sets a new timeout duration
    fn new_timeout(&mut self, timeout: Duration) {
        self.timeout = Some(Instant::now() + timeout);
    }

    /// Returns the instant when a timeout was set, if any
    fn timeout_at(&self) -> Option<Instant> {
        self.timeout
    }
}
