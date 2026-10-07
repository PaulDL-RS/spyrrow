//! The spyrrow 1.0 solve engine.
//!
//! Everything crosses the Python/Rust boundary as JSON in jagua-rs' external format
//! (`ExtSPInstance`, `ExtSPSolution`) plus a resolved configuration (`ConfigIn`). The Python
//! layer (`python/spyrrow`) owns all user facing types and validation.

use jagua_rs::io::import::Importer;
use jagua_rs::probs::spp::entities::SPSolution;
use jagua_rs::probs::spp::io::ext_repr::{ExtSPInstance, ExtSPSolution};
use jagua_rs::{Instant, probs::spp::io};
use pyo3::prelude::*;
use rand::SeedableRng;
use rand::rngs::Xoshiro256PlusPlus;
use serde::{Deserialize, Serialize};
use sparrow::config::{
    CompressionConfig, DEFAULT_SPARROW_CONFIG, ExplorationConfig, ShrinkDecayStrategy,
    SparrowConfig,
};
use sparrow::consts::{
    DEFAULT_EXPLORE_TIME_RATIO, DEFAULT_FAIL_DECAY_RATIO_CMPR, DEFAULT_MAX_CONSEQ_FAILS_EXPL,
};
use sparrow::optimizer::optimize;
use sparrow::optimizer::separator::SeparatorConfig;
use sparrow::sample::search::SampleConfig;
use sparrow::util::listener::{
    OptimizationPhase, ReportType, SeparationProgress, SeparationResult, SolutionListener,
};
use std::sync::Arc;
use std::time::Duration;

use crate::terminator::{Control, EngineTerminator};

pub const EVENT_PHASE: u32 = 1;
pub const EVENT_SOLUTION: u32 = 2;
pub const EVENT_SEPARATION: u32 = 4;
pub const EVENT_COMPRESSION: u32 = 8;

// ---------------------------------------------------------------------------------------------
// Configuration schema (mirror of sparrow's config structs, `deny_unknown_fields` everywhere)
// ---------------------------------------------------------------------------------------------

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct SampleCfg {
    n_container_samples: usize,
    n_focussed_samples: usize,
    n_coord_descents: usize,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct SeparatorCfg {
    iter_no_imprv_limit: usize,
    strike_limit: usize,
    sample_config: SampleCfg,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct ExplorationCfg {
    time_limit: f64,
    shrink_step: f32,
    max_conseq_failed_attempts: Option<usize>,
    solution_pool_distribution_stddev: f32,
    large_item_ch_area_cutoff_percentile: f32,
    separator: SeparatorCfg,
}

#[derive(Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
enum ShrinkDecayCfg {
    TimeBased,
    FailureBased { ratio: f32 },
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct CompressionCfg {
    time_limit: f64,
    shrink_range: (f32, f32),
    shrink_decay: ShrinkDecayCfg,
    separator: SeparatorCfg,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct CdeCfg {
    quadtree_depth: u8,
    cd_threshold: u8,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct ShapeCfg {
    simplify_tolerance: Option<f32>,
    narrow_concavity_cutoff: Option<(f32, f32)>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ConfigIn {
    seed: u64,
    num_workers: Option<usize>,
    exploration: ExplorationCfg,
    compression: CompressionCfg,
    cde: CdeCfg,
    shape: ShapeCfg,
}

#[derive(Serialize)]
struct EarlyTerminationDefaults {
    max_conseq_failed_attempts: usize,
    fail_decay_ratio: f32,
}

#[derive(Serialize)]
struct Defaults {
    explore_time_ratio: f32,
    early_termination: EarlyTerminationDefaults,
    exploration: ExplorationCfg,
    compression: CompressionCfg,
    cde: CdeCfg,
    shape: ShapeCfg,
}

fn sep_to_cfg(s: &SeparatorConfig) -> SeparatorCfg {
    SeparatorCfg {
        iter_no_imprv_limit: s.iter_no_imprv_limit,
        strike_limit: s.strike_limit,
        sample_config: SampleCfg {
            n_container_samples: s.sample_config.n_container_samples,
            n_focussed_samples: s.sample_config.n_focussed_samples,
            n_coord_descents: s.sample_config.n_coord_descents,
        },
    }
}

fn apply_sep(target: &mut SeparatorConfig, s: &SeparatorCfg, n_workers: usize) {
    target.iter_no_imprv_limit = s.iter_no_imprv_limit;
    target.strike_limit = s.strike_limit;
    target.n_workers = n_workers;
    target.sample_config = SampleConfig {
        n_container_samples: s.sample_config.n_container_samples,
        n_focussed_samples: s.sample_config.n_focussed_samples,
        n_coord_descents: s.sample_config.n_coord_descents,
    };
}

/// The defaults of sparrow (as compiled in) in the schema accepted by [`solve`].
#[pyfunction]
pub fn sparrow_defaults() -> String {
    let d = DEFAULT_SPARROW_CONFIG;
    let defaults = Defaults {
        explore_time_ratio: DEFAULT_EXPLORE_TIME_RATIO,
        early_termination: EarlyTerminationDefaults {
            max_conseq_failed_attempts: DEFAULT_MAX_CONSEQ_FAILS_EXPL,
            fail_decay_ratio: DEFAULT_FAIL_DECAY_RATIO_CMPR,
        },
        exploration: ExplorationCfg {
            time_limit: d.expl_cfg.time_limit.as_secs_f64(),
            shrink_step: d.expl_cfg.shrink_step,
            max_conseq_failed_attempts: d.expl_cfg.max_conseq_failed_attempts,
            solution_pool_distribution_stddev: d.expl_cfg.solution_pool_distribution_stddev,
            large_item_ch_area_cutoff_percentile: d.expl_cfg.large_item_ch_area_cutoff_percentile,
            separator: sep_to_cfg(&d.expl_cfg.separator_config),
        },
        compression: CompressionCfg {
            time_limit: d.cmpr_cfg.time_limit.as_secs_f64(),
            shrink_range: d.cmpr_cfg.shrink_range,
            shrink_decay: match d.cmpr_cfg.shrink_decay {
                ShrinkDecayStrategy::TimeBased => ShrinkDecayCfg::TimeBased,
                ShrinkDecayStrategy::FailureBased(ratio) => ShrinkDecayCfg::FailureBased { ratio },
            },
            separator: sep_to_cfg(&d.cmpr_cfg.separator_config),
        },
        cde: CdeCfg {
            quadtree_depth: d.cde_config.quadtree_depth,
            cd_threshold: d.cde_config.cd_threshold,
        },
        shape: ShapeCfg {
            simplify_tolerance: d.poly_simpl_tolerance,
            narrow_concavity_cutoff: d.narrow_concavity_cutoff_ratio,
        },
    };
    serde_json::to_string(&defaults).expect("defaults are serializable")
}

fn build_sparrow_config(cfg: &ConfigIn) -> Result<SparrowConfig, String> {
    let n_workers = cfg.num_workers.unwrap_or_else(num_cpus::get);
    if n_workers == 0 {
        return Err("num_workers must be at least 1".into());
    }
    for t in [cfg.exploration.time_limit, cfg.compression.time_limit] {
        if !t.is_finite() || t < 0.0 {
            return Err("time limits must be finite and non-negative".into());
        }
    }
    let mut c = DEFAULT_SPARROW_CONFIG;
    c.rng_seed = Some(cfg.seed as usize);

    let e = &cfg.exploration;
    c.expl_cfg = ExplorationConfig {
        shrink_step: e.shrink_step,
        time_limit: Duration::from_secs_f64(e.time_limit),
        max_conseq_failed_attempts: e.max_conseq_failed_attempts,
        solution_pool_distribution_stddev: e.solution_pool_distribution_stddev,
        large_item_ch_area_cutoff_percentile: e.large_item_ch_area_cutoff_percentile,
        separator_config: c.expl_cfg.separator_config,
    };
    apply_sep(&mut c.expl_cfg.separator_config, &e.separator, n_workers);

    let m = &cfg.compression;
    c.cmpr_cfg = CompressionConfig {
        shrink_range: m.shrink_range,
        time_limit: Duration::from_secs_f64(m.time_limit),
        shrink_decay: match m.shrink_decay {
            ShrinkDecayCfg::TimeBased => ShrinkDecayStrategy::TimeBased,
            ShrinkDecayCfg::FailureBased { ratio } => ShrinkDecayStrategy::FailureBased(ratio),
        },
        separator_config: c.cmpr_cfg.separator_config,
    };
    apply_sep(&mut c.cmpr_cfg.separator_config, &m.separator, n_workers);

    c.cde_config.quadtree_depth = cfg.cde.quadtree_depth;
    c.cde_config.cd_threshold = cfg.cde.cd_threshold;
    c.poly_simpl_tolerance = cfg.shape.simplify_tolerance;
    c.narrow_concavity_cutoff_ratio = cfg.shape.narrow_concavity_cutoff;
    Ok(c)
}

// ---------------------------------------------------------------------------------------------
// Results
// ---------------------------------------------------------------------------------------------

fn error_json(kind: &str, message: impl std::fmt::Display) -> String {
    serde_json::json!({"status": "error", "kind": kind, "message": message.to_string()}).to_string()
}

#[derive(Serialize)]
struct OkOut {
    status: &'static str,
    solution: ExtSPSolution,
    run_time: f64,
    interrupted: &'static str,
    seed: u64,
}

// ---------------------------------------------------------------------------------------------
// Listener
// ---------------------------------------------------------------------------------------------

struct EngineListener {
    start: Instant,
    callback: Option<Py<PyAny>>,
    mask: u32,
    control: Arc<Control>,
}

impl EngineListener {
    /// Calls the Python callback `(kind, elapsed, payload)`.
    /// The (Python side) callback wrapper returns True to ask for a graceful stop.
    fn emit<F>(&self, flag: u32, kind: &str, payload: F)
    where
        F: for<'py> FnOnce(Python<'py>) -> PyResult<Bound<'py, PyAny>>,
    {
        let Some(callback) = &self.callback else {
            return;
        };
        if self.mask & flag == 0 || self.control.is_stopped() {
            return;
        }
        let elapsed = self.start.elapsed().as_secs_f64();
        let res = Python::attach(|py| -> PyResult<bool> {
            let payload = payload(py)?;
            let ret = callback.call1(py, (kind, elapsed, payload))?;
            ret.bind(py).is_truthy()
        });
        match res {
            Ok(true) => self.control.request_graceful_stop(),
            Ok(false) => {}
            Err(e) => self.control.fail_with(e),
        }
    }
}

fn kind_name(report: &ReportType) -> &'static str {
    match report {
        ReportType::ExplFeas => "expl_feas",
        ReportType::ExplInfeas => "expl_infeas",
        ReportType::ExplImproving => "expl_improving",
        ReportType::CmprFeas => "cmpr_feas",
        ReportType::Final => "final",
    }
}

impl SolutionListener for EngineListener {
    fn report(&mut self, report: ReportType, solution: &SPSolution) {
        if self.callback.is_none() || self.mask & EVENT_SOLUTION == 0 {
            return;
        }
        let start = self.start;
        // Export is acceptable: reports are infrequent (improving solutions only).
        let ext = io::export(solution, start);
        let run_time = solution.time_stamp.duration_since(start).as_secs_f64();
        let json = serde_json::json!({"solution": ext, "run_time": run_time}).to_string();
        self.emit(EVENT_SOLUTION, kind_name(&report), move |py| {
            Ok(pyo3::types::PyString::new(py, &json).into_any())
        });
    }

    fn report_phase(&mut self, phase: OptimizationPhase) {
        let name = match phase {
            OptimizationPhase::Exploration => "exploration",
            OptimizationPhase::Compression => "compression",
        };
        self.emit(EVENT_PHASE, "phase", move |py| {
            Ok(pyo3::types::PyString::new(py, name).into_any())
        });
    }

    fn report_separation_progress(&mut self, p: SeparationProgress) {
        self.emit(EVENT_SEPARATION, "separation_progress", move |py| {
            Ok(pyo3::types::PyTuple::new(
                py,
                [
                    p.strip_width.into_pyobject(py)?.into_any(),
                    p.density.into_pyobject(py)?.into_any(),
                    p.iteration.into_pyobject(py)?.into_any(),
                    p.min_loss.into_pyobject(py)?.into_any(),
                ],
            )?
            .into_any())
        });
    }

    fn report_separation_result(&mut self, r: SeparationResult) {
        self.emit(EVENT_SEPARATION, "separation_result", move |py| {
            Ok(pyo3::types::PyTuple::new(
                py,
                [
                    r.success.into_pyobject(py)?.to_owned().into_any(),
                    r.elapsed_seconds.into_pyobject(py)?.into_any(),
                    r.total_evals.into_pyobject(py)?.into_any(),
                    r.total_moves.into_pyobject(py)?.into_any(),
                    r.iterations.into_pyobject(py)?.into_any(),
                ],
            )?
            .into_any())
        });
    }

    fn report_compression_progress(&mut self, shrink_step: f32) {
        self.emit(EVENT_COMPRESSION, "compression_step", move |py| {
            Ok(shrink_step.into_pyobject(py)?.into_any())
        });
    }
}

// ---------------------------------------------------------------------------------------------
// Entry points
// ---------------------------------------------------------------------------------------------

fn parse<'a, T: Deserialize<'a>>(what: &str, s: &'a str) -> Result<T, String> {
    serde_json::from_str(s).map_err(|e| format!("cannot parse {what}: {e}"))
}

/// Imports the instance and builds the sparrow config. Errors are `(kind, message)`.
fn prepare(
    instance_json: &str,
    config_json: &str,
) -> Result<(ConfigIn, SparrowConfig, jagua_rs::probs::spp::entities::SPInstance), (&'static str, String)>
{
    let cfg: ConfigIn = parse("config", config_json).map_err(|e| ("invalid_config", e))?;
    let sparrow_cfg = build_sparrow_config(&cfg).map_err(|e| ("invalid_config", e))?;
    let ext_instance: ExtSPInstance =
        parse("instance", instance_json).map_err(|e| ("invalid_instance", e))?;
    let importer = Importer::new(
        sparrow_cfg.cde_config,
        sparrow_cfg.poly_simpl_tolerance,
        sparrow_cfg.narrow_concavity_cutoff_ratio,
    );
    let instance = io::import_instance(&importer, &ext_instance)
        .map_err(|e| ("invalid_instance", format!("{e:#}")))?;
    Ok((cfg, sparrow_cfg, instance))
}

/// Checks that an instance can be imported by jagua-rs. Returns a JSON `{"status": "ok"}` or an error.
#[pyfunction]
pub fn validate(py: Python<'_>, instance_json: &str, config_json: &str) -> String {
    py.detach(|| match prepare(instance_json, config_json) {
        Ok(_) => serde_json::json!({"status": "ok"}).to_string(),
        Err((kind, msg)) => error_json(kind, msg),
    })
}

/// Solves an instance. Returns a JSON string, see `OkOut` / `error_json`.
/// Exceptions raised by the callback propagate as Python exceptions.
#[pyfunction]
#[pyo3(signature = (instance_json, config_json, initial_solution_json=None, callback=None, event_mask=0))]
pub fn solve(
    py: Python<'_>,
    instance_json: &str,
    config_json: &str,
    initial_solution_json: Option<&str>,
    callback: Option<Py<PyAny>>,
    event_mask: u32,
) -> PyResult<String> {
    let prepared = py.detach(|| prepare(instance_json, config_json));
    let (cfg, sparrow_cfg, instance) = match prepared {
        Ok(p) => p,
        Err((kind, msg)) => return Ok(error_json(kind, msg)),
    };
    let initial = match initial_solution_json.map(|s| {
        let ext: ExtSPSolution = parse("initial solution", s)?;
        io::import_solution(&instance, &ext).map_err(|e| format!("{e:#}"))
    }) {
        None => None,
        Some(Ok(sol)) => Some(sol),
        Some(Err(e)) => return Ok(error_json("invalid_solution", e)),
    };

    let control = Control::new();
    let mut terminator = EngineTerminator::new(control.clone());
    let start = Instant::now();
    let mut listener = EngineListener {
        start,
        callback,
        mask: event_mask,
        control: control.clone(),
    };
    let rng = Xoshiro256PlusPlus::seed_from_u64(cfg.seed);

    let result = py.detach(move || {
        optimize(
            instance,
            rng,
            &mut listener,
            &mut terminator,
            &sparrow_cfg.expl_cfg,
            &sparrow_cfg.cmpr_cfg,
            initial.as_ref(),
        )
        .map_err(|e| format!("{e:#}"))
    });

    if let Some(err) = control.take_error() {
        return Err(err);
    }
    match result {
        Err(e) => Ok(error_json("solver", e)),
        Ok(solution) => {
            let run_time = start.elapsed().as_secs_f64();
            let out = OkOut {
                status: "ok",
                solution: io::export(&solution, start),
                run_time,
                interrupted: control.interruption(),
                seed: cfg.seed,
            };
            Ok(serde_json::to_string(&out).expect("solution is serializable"))
        }
    }
}
