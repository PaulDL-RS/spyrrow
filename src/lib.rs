//! `spyrrow._core`: the native layer of spyrrow.
//!
//! * [`engine`]: the 1.0 engine, JSON in / JSON out, wrapped by `python/spyrrow/_engine.py`.
//! * [`v0`]: the frozen 0.10 API, re-exported by `spyrrow.v0`.

use pyo3::prelude::*;

mod engine;
mod terminator;
mod v0;

#[pymodule]
fn _core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(engine::solve, m)?)?;
    m.add_function(wrap_pyfunction!(engine::validate, m)?)?;
    m.add_function(wrap_pyfunction!(engine::sparrow_defaults, m)?)?;
    v0::register(m)?;
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    Ok(())
}
