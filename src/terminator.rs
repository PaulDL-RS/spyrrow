use jagua_rs::Instant;
use pyo3::Python;
use sparrow::util::terminator::Terminator;
use std::cell::Cell;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, RwLock};
use std::time::Duration;

#[derive(Default)]
pub struct PythonTerminator {
    pub timeout: Option<Instant>,
    // This is to circumvent the fact that kill borrow immutably but there is two loops: exploration and compression
    finished: RwLock<Cell<bool>>,
    pub eval_budget: Option<EvalBudget>,
}

/// Stops each phase after a number of evaluations instead of (or before) its time limit,
/// so that a run does the same work whatever the speed of the machine.
pub struct EvalBudget {
    /// Evaluations done in the current phase, incremented by the solution listener
    pub evals: Arc<AtomicU64>,
    /// Budgets of the exploration and compression phases
    pub phase_budgets: [u64; 2],
    phase: usize,
    current: u64,
}

impl EvalBudget {
    pub fn new(evals: Arc<AtomicU64>, phase_budgets: [u64; 2]) -> Self {
        EvalBudget {
            evals,
            phase_budgets,
            phase: 0,
            current: 0,
        }
    }

    fn exhausted(&self) -> bool {
        self.evals.load(Ordering::Relaxed) >= self.current
    }

    // sparrow calls new_timeout once at the start of each phase: exploration, then compression
    fn next_phase(&mut self) {
        self.current = self.phase_budgets[self.phase.min(1)];
        self.phase += 1;
        self.evals.store(0, Ordering::Relaxed);
    }
}

impl Terminator for PythonTerminator {
    fn kill(&self) -> bool {
        self.finished.read().expect("I fucked up the lock mechanism").get()
            || self.timeout.is_some_and(|timeout| Instant::now() > timeout)
            || self.eval_budget.as_ref().is_some_and(EvalBudget::exhausted)
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
        if let Some(budget) = self.eval_budget.as_mut() {
            budget.next_phase();
        }
    }

    /// Returns the instant when a timeout was set, if any
    fn timeout_at(&self) -> Option<Instant> {
        self.timeout
    }
}
