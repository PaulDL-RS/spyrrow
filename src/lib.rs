use jagua_rs::io::ext_repr::{
    ExtItem as BaseItem, ExtLayout, ExtOrientation, ExtPlacedItem, ExtRotation, ExtSPolygon,
    ExtShape, ExtTransformation,
};
use jagua_rs::io::import::Importer;
use jagua_rs::probs::spp::entities::{SPProblem, SPSolution};
use jagua_rs::probs::spp::io::ext_repr::{ExtItem, ExtSPInstance, ExtSPSolution};
use pyo3::exceptions::{PyRuntimeError, PyValueError};
use pyo3::prelude::*;
use rand::SeedableRng;
use rand::rngs::Xoshiro256PlusPlus;
use serde::Serialize;
use sparrow::EPOCH;
use sparrow::config::{DEFAULT_SPARROW_CONFIG, ShrinkDecayStrategy};
use sparrow::consts::{DEFAULT_FAIL_DECAY_RATIO_CMPR, DEFAULT_MAX_CONSEQ_FAILS_EXPL};
use sparrow::optimizer::optimize;
use sparrow::quantify::tracker::CollisionTracker;
use sparrow::util::io::ExtSPOutput;
use sparrow::util::listener::{
    OptimizationPhase, ReportType, SeparationProgress, SeparationResult, SolutionListener,
};
use std::collections::{HashMap, HashSet, VecDeque};
use std::num::NonZeroU64;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

mod terminator;

// Defaults of the advanced options, taken from sparrow so that they follow its default configuration.
const DEFAULT_POLY_SIMPL_TOLERANCE: Option<f32> = DEFAULT_SPARROW_CONFIG.poly_simpl_tolerance;
const DEFAULT_N_CONTAINER_SAMPLES: usize = DEFAULT_SPARROW_CONFIG
    .expl_cfg
    .separator_config
    .sample_config
    .n_container_samples;
const DEFAULT_N_FOCUSSED_SAMPLES: usize = DEFAULT_SPARROW_CONFIG
    .expl_cfg
    .separator_config
    .sample_config
    .n_focussed_samples;
const DEFAULT_CD_THRESHOLD: u8 = DEFAULT_SPARROW_CONFIG.cde_config.cd_threshold;

#[pyclass(name = "Item", get_all, set_all, from_py_object)]
#[derive(Clone, Serialize)]
/// An Item represents any closed 2D shape by its outer boundary.
///
/// Spyrrow doesn't support hole(s) inside the shape as of yet. Therefore no Item can be nested inside another.
///
///
/// Args:
///     id (str): The Item identifier
///       Needs to be unique accross all Items of a StripPackingInstance
///     shape (Sequence[tuple[float,float]]): An ordered Sequence of (x,y) defining the shape boundary. The shape is represented as a polygon formed by this list of points.
///       The origin point can be included twice as the finishing point. If not, [last point, first point] is infered to be the last straight line of the shape.
///     demand (int): The quantity of identical Items to be placed inside the strip. Should be strictly positive.
///     allowed_orientations (Sequence[float]|None): Sequence of angles in degrees allowed.
///       An empty Sequence is equivalent to [0.].
///       A None value means that the item is free to rotate
///       The algorithmn is only very weakly sensible to the length of the Sequence given.
///     reflection_axis (float|None): Angle in degrees, from the x axis, of an axis across which the Item may be mirrored. Defaults to None.
///       None means that the Item is never reflected.
///       When set, the solver is free to place the Item either as is or mirrored across this axis (it is not forced to mirror).
///       The axis is taken modulo 180° and is expressed in the Item's own coordinate system, before any rotation.
///       The rotations allowed (see `allowed_orientations`) are applied after the reflection.
///       For instance, with `allowed_orientations=[]` and `reflection_axis=0.`, the Item can only be mirrored across its x axis.
///       Mirrored placements are reported by `PlacedItem.reflected`.
///       Note: the sparrow version bundled (0.3.0) only samples the non-reflected orientations, so the solver currently never returns a reflected placement.
///       The axis is still imported and validated by the underlying jagua-rs, and will take effect once the solver explores reflections.
///     rotation_step (float|None): Angle in degrees of a regular rotation step. Defaults to None.
///       The Item is then allowed the angles 0, step, 2*step, ... below 360°.
///       Must be in (0, 360] and evenly divide 360° (e.g. 90., 45., 60., 360.). 360. means no rotation.
///       Can only be used with `allowed_orientations=None`.
///
/// Raises:
///     ValueError: If `reflection_axis` is not finite, if both `allowed_orientations` and `rotation_step` are provided, or if `rotation_step` is not a valid step.
///       The attributes can also be set after construction. In this case, the same checks are done by `StripPackingInstance.solve`.
///
struct ItemPy {
    id: String,
    demand: NonZeroU64,
    allowed_orientations: Option<Vec<f32>>,
    shape: Vec<(f32, f32)>,
    // Omitted from the JSON when None, to keep the output of items without reflection unchanged
    #[serde(skip_serializing_if = "Option::is_none")]
    reflection_axis: Option<f32>,
    // Omitted from the JSON when None, to keep the output of items without rotation step unchanged
    #[serde(skip_serializing_if = "Option::is_none")]
    rotation_step: Option<f32>,
}

#[pymethods]
impl ItemPy {
    #[new]
    #[pyo3(signature = (id, shape, demand, allowed_orientations, reflection_axis=None, rotation_step=None))]
    fn new(
        id: String,
        shape: Vec<(f32, f32)>,
        demand: NonZeroU64,
        allowed_orientations: Option<Vec<f32>>,
        reflection_axis: Option<f32>,
        rotation_step: Option<f32>,
    ) -> PyResult<Self> {
        if let Some(axis) = reflection_axis
            && !axis.is_finite()
        {
            return Err(PyValueError::new_err(format!(
                "reflection_axis must be finite, got {axis}"
            )));
        }
        to_ext_rotation(&allowed_orientations, rotation_step)?;
        Ok(ItemPy {
            id,
            demand,
            allowed_orientations,
            shape,
            reflection_axis,
            rotation_step,
        })
    }

    fn __repr__(&self) -> String {
        let mut repr = format!(
            "Item(id={},shape={:?}, demand={}",
            self.id, self.shape, self.demand
        );
        if let Some(orientations) = &self.allowed_orientations {
            repr.push_str(&format!(", allowed_orientations={:?}", orientations));
        }
        if let Some(axis) = self.reflection_axis {
            repr.push_str(&format!(", reflection_axis={:?}", axis));
        }
        if let Some(step) = self.rotation_step {
            repr.push_str(&format!(", rotation_step={:?}", step));
        }
        repr.push(')');
        repr
    }

    fn __deepcopy__(&self, _memo: Py<PyAny>) -> Self {
        self.clone()
    }

    /// Return a string of the JSON representation of the object
    ///
    /// Returns:
    ///     str
    ///
    fn to_json_str(&self) -> String {
        serde_json::to_string(&self).unwrap()
    }
}

#[pyclass(name = "PlacedItem", get_all, skip_from_py_object)]
#[derive(Clone, Debug, Serialize)]
/// An object representing where a copy of an Item was placed inside the strip.
///
/// Attributes:
///     id (str): The Item identifier referencing the items of the StripPackingInstance
///     rotation (float): The rotation angle in degrees, assuming that the original Item was defined with 0° as its rotation angle.
///       Use the origin (0.0,0.0) as the rotation point.
///     translation (tuple[float,float]): the translation vector in the X-Y axis. To apply after the rotation
///     reflected (bool): Whether the Item is mirrored in this placement. False for Items without a `reflection_axis`.
///
/// The placed shape is obtained from the original Item shape by applying, in this order:
///
///     1. if `reflected`, the mirroring (x, y) -> (x, -y)
///     2. the rotation by `rotation` degrees (counter-clockwise), around the origin (0.0,0.0)
///     3. the translation by `translation`
///
/// Since mirroring across an axis at angle `a` is the mirroring (x, y) -> (x, -y) followed by a rotation of `2*a`,
/// the `rotation` of a reflected placement includes this `2*a` term (modulo 360°).
///
struct PlacedItemPy {
    pub id: String,
    pub translation: (f32, f32),
    pub rotation: f32,
    pub reflected: bool,
}

#[pymethods]
impl PlacedItemPy {

    fn __deepcopy__(&self, _memo: Py<PyAny>) -> Self {
        self.clone()
    }
}

#[pyclass(name = "StripPackingSolution", get_all, from_py_object)]
#[derive(Clone, Debug, Serialize)]
/// An object representing the solution to a given StripPackingInstance.
///
/// Can not be directly instanciated. Result from StripPackingInstance.solve.
///
/// Attributes:
///     width (float): the width of the strip found to contains all Items. In the same unit as input.
///     placed_items (list[PlacedItem]): a list of all PlacedItems, describing how Items are placed in the solution
///     density (float): the fraction of the final strip used by items.
///
struct StripPackingSolutionPy {
    pub width: f32,
    pub placed_items: Vec<PlacedItemPy>,
    pub density: f32,
}

#[pymethods]
impl StripPackingSolutionPy {

    fn __deepcopy__(&self, _memo: Py<PyAny>) -> Self {
        self.clone()
    }

    /// Return a string of the JSON representation of the object
    ///
    /// Returns:
    ///     str
    ///
    fn to_json_str(&self) -> String {
        serde_json::to_string(&self).unwrap()
    }
}

#[pyclass(name = "ReportType", eq, eq_int, skip_from_py_object)]
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
/// The type of progress report emitted by the solver.
///
/// Variants:
///     ExplFeas: Feasible solution found during exploration.
///     ExplInfeas: Infeasible solution during exploration.
///     ExplImproving: Improving solution during exploration (not yet feasible).
///     CmprFeas: Feasible solution found during compression.
///     Final: The final solution.
///
enum ReportTypePy {
    ExplFeas = 0,
    ExplInfeas = 1,
    ExplImproving = 2,
    CmprFeas = 3,
    Final = 4,
}

#[pymethods]
impl ReportTypePy {
    /// Return a human-readable phase name.
    ///
    /// Returns:
    ///     Literal["exploring", "compressing", "final"]: string representing the phase
    ///
    fn phase_name(&self) -> &'static str {
        match self {
            ReportTypePy::ExplFeas | ReportTypePy::ExplInfeas | ReportTypePy::ExplImproving => "exploring",
            ReportTypePy::CmprFeas => "compressing",
            ReportTypePy::Final => "final",
        }
    }

}

impl From<ReportType> for ReportTypePy {
    fn from(rt: ReportType) -> Self {
        match rt {
            ReportType::ExplFeas => ReportTypePy::ExplFeas,
            ReportType::ExplInfeas => ReportTypePy::ExplInfeas,
            ReportType::ExplImproving => ReportTypePy::ExplImproving,
            ReportType::CmprFeas => ReportTypePy::CmprFeas,
            ReportType::Final => ReportTypePy::Final,
        }
    }
}

struct ProgressReport {
    report_type: ReportTypePy,
    solution: StripPackingSolutionPy,
}

#[pyclass(name = "OptimizationPhase", eq, eq_int, skip_from_py_object)]
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
/// A phase of the optimization, as announced by a `PhaseEvent`.
///
/// Variants:
///     Exploration: The solver is searching for a feasible strip width.
///     Compression: The solver is squeezing the best feasible solution.
///
enum OptimizationPhasePy {
    Exploration = 0,
    Compression = 1,
}

impl From<OptimizationPhase> for OptimizationPhasePy {
    fn from(phase: OptimizationPhase) -> Self {
        match phase {
            OptimizationPhase::Exploration => OptimizationPhasePy::Exploration,
            OptimizationPhase::Compression => OptimizationPhasePy::Compression,
        }
    }
}

#[pyclass(name = "PhaseEvent", get_all, frozen, skip_from_py_object)]
#[derive(Clone, Debug)]
/// The solver entered a new optimization phase.
///
/// Attributes:
///     phase (OptimizationPhase): the phase that just started.
///
struct PhaseEventPy {
    phase: OptimizationPhasePy,
}

#[pymethods]
impl PhaseEventPy {
    fn __repr__(&self) -> String {
        format!("PhaseEvent(phase=OptimizationPhase.{:?})", self.phase)
    }
}

#[pyclass(name = "SeparationProgressEvent", get_all, frozen, skip_from_py_object)]
#[derive(Clone, Debug)]
/// Progress of one separation attempt (the solver tries to remove all overlaps at a given strip width).
///
/// Emitted once for the initial layout (`iteration == 0`), then after each completed iteration.
/// This is a high-frequency event.
///
/// Attributes:
///     strip_width (float): the strip width being separated.
///     density (float): the density of the layout, as a fraction in [0, 1] (same convention as `StripPackingSolution.density`).
///     iteration (int): the iteration counter within the separation attempt.
///     min_loss (float): the lowest overlap loss found so far in this attempt; 0.0 means the layout is feasible.
///
struct SeparationProgressEventPy {
    strip_width: f32,
    density: f32,
    iteration: usize,
    min_loss: f32,
}

#[pymethods]
impl SeparationProgressEventPy {
    fn __repr__(&self) -> String {
        format!(
            "SeparationProgressEvent(strip_width={}, density={}, iteration={}, min_loss={})",
            self.strip_width, self.density, self.iteration, self.min_loss
        )
    }
}

#[pyclass(name = "SeparationResultEvent", get_all, frozen, skip_from_py_object)]
#[derive(Clone, Debug)]
/// Outcome of a finished separation attempt.
///
/// Attributes:
///     success (bool): whether all overlaps were removed.
///     elapsed_seconds (float): wall-clock duration of the attempt.
///     total_evals (int): number of placement evaluations performed.
///     total_moves (int): number of item moves performed.
///     iterations (int): number of iterations performed.
///
struct SeparationResultEventPy {
    success: bool,
    elapsed_seconds: f32,
    total_evals: usize,
    total_moves: usize,
    iterations: usize,
}

#[pymethods]
impl SeparationResultEventPy {
    fn __repr__(&self) -> String {
        format!(
            "SeparationResultEvent(success={}, elapsed_seconds={}, total_evals={}, total_moves={}, iterations={})",
            if self.success { "True" } else { "False" },
            self.elapsed_seconds,
            self.total_evals,
            self.total_moves,
            self.iterations
        )
    }
}

#[pyclass(name = "CompressionProgressEvent", get_all, frozen, skip_from_py_object)]
#[derive(Clone, Debug)]
/// The compression phase starts a new attempt to shrink the strip.
///
/// Attributes:
///     shrink_step (float): the relative shrink of the strip width attempted (0.001 means 0.1%).
///
struct CompressionProgressEventPy {
    shrink_step: f32,
}

#[pymethods]
impl CompressionProgressEventPy {
    fn __repr__(&self) -> String {
        format!("CompressionProgressEvent(shrink_step={})", self.shrink_step)
    }
}

// Internal, GIL-free representation of the detailed events.
enum ProgressEvent {
    Phase(OptimizationPhasePy),
    SeparationProgress(SeparationProgressEventPy),
    SeparationResult(SeparationResultEventPy),
    CompressionProgress(CompressionProgressEventPy),
}

impl ProgressEvent {
    fn into_py_any(self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        Ok(match self {
            ProgressEvent::Phase(phase) => Py::new(py, PhaseEventPy { phase })?.into_any(),
            ProgressEvent::SeparationProgress(e) => Py::new(py, e)?.into_any(),
            ProgressEvent::SeparationResult(e) => Py::new(py, e)?.into_any(),
            ProgressEvent::CompressionProgress(e) => Py::new(py, e)?.into_any(),
        })
    }
}

// Bounded buffer of detailed events. Drops the oldest event when full.
struct EventBuffer {
    events: VecDeque<ProgressEvent>,
    max_events: usize,
    dropped: u64,
}

impl EventBuffer {
    fn push(&mut self, event: ProgressEvent) {
        if self.events.len() >= self.max_events {
            self.events.pop_front();
            self.dropped += 1;
        }
        self.events.push_back(event);
    }
}

const DEFAULT_MAX_EVENTS: usize = 10_000;

#[pyclass(name = "ProgressQueue", from_py_object)]
#[derive(Clone)]
/// A thread-safe queue that collects progress reports from the solver.
///
/// Create one before calling `solve()` and pass it as the `progress` argument.
/// While the solver runs (in a background thread), call `drain()` to retrieve
/// any new reports.
///
/// With `detailed=True`, the queue additionally records fine-grained solver events
/// (phase changes, separation progress, compression attempts), retrieved with `drain_events()`.
/// These are kept apart from `drain()`, which is never affected by `detailed`.
/// Separation progress events are high-frequency (one per solver iteration, typically
/// hundreds to thousands per second), so the event buffer is bounded: when it holds
/// `max_events` events, the oldest one is dropped to make room. Call `drain_events()`
/// regularly to avoid losing events; `dropped_events` counts what was lost.
/// The reports retrieved by `drain()` are not bounded.
///
/// Args:
///     detailed (bool, optional): Whether to also record fine-grained events. Defaults to False.
///     max_events (int, optional): Capacity of the event buffer. Must be strictly positive.
///       Only used if `detailed` is True. Defaults to 10000.
///
/// Raises:
///     ValueError: If `max_events` is zero.
///
/// Example::
///
///     queue = spyrrow.ProgressQueue(detailed=True)
///     # run solve in a thread, passing progress=queue
///     for report_type, solution in queue.drain():
///         print(f"{report_type.phase_name()}: width={solution.width:.1f}, density={solution.density:.1%}")
///     for event in queue.drain_events():
///         if isinstance(event, spyrrow.PhaseEvent):
///             print(f"entered {event.phase}")
///
struct ProgressQueuePy {
    inner: Arc<Mutex<VecDeque<ProgressReport>>>,
    events: Arc<Mutex<EventBuffer>>,
    detailed: bool,
}

#[pymethods]
impl ProgressQueuePy {
    #[new]
    #[pyo3(signature = (detailed=false, max_events=DEFAULT_MAX_EVENTS))]
    fn new(detailed: bool, max_events: usize) -> PyResult<Self> {
        if max_events == 0 {
            return Err(PyValueError::new_err("max_events must be strictly positive"));
        }
        Ok(ProgressQueuePy {
            inner: Arc::new(Mutex::new(VecDeque::new())),
            events: Arc::new(Mutex::new(EventBuffer {
                events: VecDeque::new(),
                max_events,
                dropped: 0,
            })),
            detailed,
        })
    }

    /// Drain all pending progress reports from the queue.
    ///
    /// Returns:
    ///     list[tuple[ReportType, StripPackingSolution]]: A list of (report_type, solution) tuples.
    ///
    fn drain(&self) -> Vec<(ReportTypePy, StripPackingSolutionPy)> {
        let mut queue = self.inner.lock().unwrap();
        queue.drain(..).map(|r| (r.report_type, r.solution)).collect()
    }

    /// Drain all pending detailed events from the queue, oldest first.
    ///
    /// Always empty if the queue was not created with `detailed=True`.
    ///
    /// Returns:
    ///     list[PhaseEvent | SeparationProgressEvent | SeparationResultEvent | CompressionProgressEvent]
    ///
    #[pyo3(signature = () -> "list[PhaseEvent | SeparationProgressEvent | SeparationResultEvent | CompressionProgressEvent]")]
    fn drain_events(&self, py: Python<'_>) -> PyResult<Vec<Py<PyAny>>> {
        let events: Vec<ProgressEvent> = {
            let mut buffer = self.events.lock().unwrap();
            buffer.events.drain(..).collect()
        };
        events.into_iter().map(|e| e.into_py_any(py)).collect()
    }

    /// bool: Whether the queue records detailed events.
    #[getter]
    fn detailed(&self) -> bool {
        self.detailed
    }

    /// int: Capacity of the detailed event buffer.
    #[getter]
    fn max_events(&self) -> usize {
        self.events.lock().unwrap().max_events
    }

    /// int: Number of detailed events dropped so far because the buffer was full.
    #[getter]
    fn dropped_events(&self) -> u64 {
        self.events.lock().unwrap().dropped
    }
}

// Implements SolutionListener to push progress reports onto a shared queue.
struct ProgressListener {
    queue: Arc<Mutex<VecDeque<ProgressReport>>>,
    events: Option<Arc<Mutex<EventBuffer>>>,
    item_ids: Vec<String>,
}

impl ProgressListener {
    fn push_event(&self, event: ProgressEvent) {
        if let Some(events) = &self.events {
            events.lock().unwrap().push(event);
        }
    }
}

impl SolutionListener for ProgressListener {
    fn report(&mut self, report: ReportType, solution: &SPSolution) {
        // Export is acceptable because reports are infrequent (only on improving solutions).
        let exported = jagua_rs::probs::spp::io::export(solution, *EPOCH);
        let placed_items: Vec<PlacedItemPy> = exported
            .layout
            .placed_items
            .into_iter()
            .map(|jpi| PlacedItemPy {
                id: self.item_ids[jpi.item_id as usize].clone(),
                rotation: jpi.transformation.rotation,
                translation: jpi.transformation.translation,
                reflected: jpi.transformation.reflected,
            })
            .collect();
        let mut queue = self.queue.lock().unwrap();
        queue.push_back(ProgressReport {
            report_type: ReportTypePy::from(report),
            solution: StripPackingSolutionPy {
                width: exported.strip_width,
                density: exported.density,
                placed_items,
            },
        });
    }

    fn report_phase(&mut self, phase: OptimizationPhase) {
        self.push_event(ProgressEvent::Phase(phase.into()));
    }

    fn report_separation_progress(&mut self, progress: SeparationProgress) {
        self.push_event(ProgressEvent::SeparationProgress(SeparationProgressEventPy {
            strip_width: progress.strip_width,
            // sparrow reports a percentage here, spyrrow uses fractions everywhere else
            density: progress.density / 100.0,
            iteration: progress.iteration,
            min_loss: progress.min_loss,
        }));
    }

    fn report_separation_result(&mut self, result: SeparationResult) {
        self.push_event(ProgressEvent::SeparationResult(SeparationResultEventPy {
            success: result.success,
            elapsed_seconds: result.elapsed_seconds,
            total_evals: result.total_evals,
            total_moves: result.total_moves,
            iterations: result.iterations,
        }));
    }

    fn report_compression_progress(&mut self, shrink_step: f32) {
        self.push_event(ProgressEvent::CompressionProgress(CompressionProgressEventPy {
            shrink_step,
        }));
    }
}

// Listener given to optimize(): forwards reports to the optional progress queue,
// and counts the evaluations for the evaluation budget of the terminator.
struct SolListener {
    progress: Option<ProgressListener>,
    evals: Arc<AtomicU64>,
}

impl SolutionListener for SolListener {
    fn report(&mut self, report: ReportType, solution: &SPSolution) {
        if let Some(p) = self.progress.as_mut() {
            p.report(report, solution);
        }
    }

    fn report_phase(&mut self, phase: OptimizationPhase) {
        if let Some(p) = self.progress.as_mut() {
            p.report_phase(phase);
        }
    }

    fn report_separation_progress(&mut self, progress: SeparationProgress) {
        if let Some(p) = self.progress.as_mut() {
            p.report_separation_progress(progress);
        }
    }

    fn report_separation_result(&mut self, result: SeparationResult) {
        self.evals.fetch_add(result.total_evals as u64, Ordering::Relaxed);
        if let Some(p) = self.progress.as_mut() {
            p.report_separation_result(result);
        }
    }

    fn report_compression_progress(&mut self, shrink_step: f32) {
        if let Some(p) = self.progress.as_mut() {
            p.report_compression_progress(shrink_step);
        }
    }
}

// Splits the evaluation budget between exploration and compression like their times.
fn split_budget(budget: u64, exploration_time: Duration, compression_time: Duration) -> [u64; 2] {
    let total = exploration_time + compression_time;
    let exploration_ratio = if total.is_zero() {
        0.8
    } else {
        exploration_time.as_secs_f64() / total.as_secs_f64()
    };
    let exploration = (budget as f64 * exploration_ratio).round() as u64;
    [exploration, budget - exploration]
}

fn all_unique(strings: &[&str]) -> bool {
    let mut seen = HashSet::new();
    strings.iter().all(|s| seen.insert(*s))
}

#[pyclass(name = "StripPackingConfig", get_all, set_all, from_py_object)]
#[derive(Clone, Serialize)]
/// Initializes a configuration object for the strip packing algorithm.
///
/// Either `total_computation_time`, or both `exploration_time` and `compression_time`, must be provided.
/// Providing all three or only one of the latter two raises an error.
/// If `total_computation_time` is provided, 80% of it is allocated to exploration and 20% to compression.
/// If `seed` is not provided, a random seed will be generated.
///
///
/// Args:
///     early_termination (bool, optional): Whether to allow early termination of the algorithm. Defaults to True.
///     quadtree_depth (int, optional): Maximum depth of the quadtree used by the collision detection engine jagua-rs.
///       Must be positive, common values are 3,4,5. Defaults to 4.
///     min_items_separation (Optional[float], optional): Minimum required distance between packed items. Defaults to None.
///     total_computation_time (Optional[int], optional): Total time budget in seconds.
///       Used if `exploration_time` and `compression_time` are not provided. Defaults to 600.
///     exploration_time (Optional[int], optional): Time in seconds allocated to exploration. Defaults to None.
///     compression_time (Optional[int], optional): Time in seconds allocated to compression. Defaults to None.
///     num_workers (Optional[int], optional): Number of threads used by the collision detection engine during exploration.
///       When set to None, detect the number of logical CPU cores on the execution plateform. Defaults to None.
///     seed (Optional[int], optional): Optional random seed to give reproductibility. If None, a random seed is generated. Defaults to None.
///     max_evaluations (Optional[int], optional): Budget of evaluations (candidate placements evaluated by sparrow), split between
///       exploration and compression in the same proportion as their times. Each phase stops at its budget or its time limit,
///       whichever comes first. The budget is checked after each separation, so a phase can slightly exceed it.
///       Unlike time, the work done for a given budget does not depend on the speed of the machine:
///       with a fixed `seed` and a time limit large enough not to be reached, a run gives the same result on any machine
///       (up to floating point differences between CPU architectures).
///       When set, compression shrinks its steps after failures (as with `early_termination`) instead of over time.
///       Must be strictly positive. Defaults to None (no budget).
///     narrow_concavity_cutoff (Optional[tuple[float, float]], optional): Shape preprocessing. Narrow concavities of the items
///       are closed by a straight edge (a conservative change: the item gets slightly larger, never smaller).
///       Given as (max_distance_ratio, max_area_ratio): the maximum distance between the two vertices bounding the concavity,
///       as a fraction of the item's diameter, and the maximum area of the closed sub-shape, as a fraction of the item's area.
///       Both must be finite and non-negative. None disables the closing, which is spyrrow's historical behaviour.
///       The sparrow command line tool uses (0.01, 0.01). Defaults to None.
///     poly_simpl_tolerance (Optional[float], optional): Shape preprocessing. Maximum allowed inflation of an item, as a ratio of its area,
///       when its polygon is simplified. Must be finite and non-negative. None disables the simplification.
///       Defaults to 0.001, sparrow's default.
///     max_conseq_failed_attempts (Optional[int], optional): Exploration stops after this many consecutive failed attempts to
///       reach a narrower strip, and the solver moves on to compression. Must be strictly positive.
///       If None, `early_termination` decides: 10 (sparrow's `DEFAULT_MAX_CONSEQ_FAILS_EXPL`) if it is True, no limit if it is False.
///       An explicit value always takes precedence over `early_termination`. Defaults to None.
///     compression_failure_decay_ratio (Optional[float], optional): If set, the compression phase shrinks the strip by a step
///       that decays geometrically by this ratio each time an attempt fails (sparrow's `FailureBased` strategy).
///       Must be strictly between 0 and 1; smaller values make compression give up sooner.
///       If None, `early_termination` decides: ratio 0.9 (sparrow's `DEFAULT_FAIL_DECAY_RATIO_CMPR`) if it is True,
///       a step decaying linearly with time if it is False.
///       An explicit value always takes precedence over `early_termination`. Defaults to None.
///     iter_no_imprv_limit (Optional[int], optional): Separator: number of consecutive iterations without improvement
///       after which a strike is counted. Must be strictly positive.
///       If None, sparrow's per-phase defaults are used (200 in exploration, 100 in compression).
///       If set, the value is used for both phases. Defaults to None.
///     strike_limit (Optional[int], optional): Separator: number of strikes after which a separation attempt is abandoned.
///       Must be strictly positive.
///       If None, sparrow's per-phase defaults are used (3 in exploration, 5 in compression).
///       If set, the value is used for both phases. Defaults to None.
///     n_container_samples (int, optional): Number of placements sampled uniformly in the strip for each item move.
///       Must be strictly positive. Defaults to 50, sparrow's default.
///     n_focussed_samples (int, optional): Number of placements sampled around the item's current position for each item move.
///       Can be 0. Defaults to 25, sparrow's default.
///     cd_threshold (int, optional): Collision detection engine: the quadtree traversal stops and edges are tested directly
///       when a node holds fewer edges than this threshold. Must fit in 0..=255. Defaults to 64, sparrow's default.
///
/// Raises:
///     ValueError: If the combination of time arguments is invalid, if `max_evaluations` is 0, or if an advanced option has an invalid value.
///
/// The advanced options are meant for power users, the defaults reproduce the historical behaviour of spyrrow exactly.
///
struct StripPackingConfigPy {
    early_termination: bool,
    seed: u64,
    exploration_time: Duration,
    compression_time: Duration,
    quadtree_depth: u8,
    min_items_separation: Option<f32>,
    num_workers: usize,
    #[serde(skip_serializing_if = "Option::is_none")]
    max_evaluations: Option<NonZeroU64>,
    narrow_concavity_cutoff: Option<(f32, f32)>,
    poly_simpl_tolerance: Option<f32>,
    max_conseq_failed_attempts: Option<usize>,
    compression_failure_decay_ratio: Option<f32>,
    iter_no_imprv_limit: Option<usize>,
    strike_limit: Option<usize>,
    n_container_samples: usize,
    n_focussed_samples: usize,
    cd_threshold: u8,
}

impl StripPackingConfigPy {
    // Checks the advanced options. Called by the constructor and again by `solve`, since the attributes are settable.
    fn validate_advanced(&self) -> PyResult<()> {
        let non_negative = |v: f32| v.is_finite() && v >= 0.0;
        if let Some((distance_ratio, area_ratio)) = self.narrow_concavity_cutoff
            && !(non_negative(distance_ratio) && non_negative(area_ratio))
        {
            return Err(PyValueError::new_err(
                "narrow_concavity_cutoff must be None or a pair of finite non-negative floats",
            ));
        }
        if let Some(tolerance) = self.poly_simpl_tolerance
            && !non_negative(tolerance)
        {
            return Err(PyValueError::new_err(
                "poly_simpl_tolerance must be None or a finite non-negative float",
            ));
        }
        if self.max_conseq_failed_attempts == Some(0) {
            return Err(PyValueError::new_err(
                "max_conseq_failed_attempts must be None or strictly positive",
            ));
        }
        if let Some(ratio) = self.compression_failure_decay_ratio
            && !(ratio.is_finite() && ratio > 0.0 && ratio < 1.0)
        {
            return Err(PyValueError::new_err(
                "compression_failure_decay_ratio must be None or strictly between 0 and 1",
            ));
        }
        if self.iter_no_imprv_limit == Some(0) {
            return Err(PyValueError::new_err(
                "iter_no_imprv_limit must be None or strictly positive",
            ));
        }
        if self.strike_limit == Some(0) {
            return Err(PyValueError::new_err(
                "strike_limit must be None or strictly positive",
            ));
        }
        if self.n_container_samples == 0 {
            return Err(PyValueError::new_err(
                "n_container_samples must be strictly positive",
            ));
        }
        Ok(())
    }
}

#[pymethods]
impl StripPackingConfigPy {
    #[new]
    #[allow(clippy::too_many_arguments)]
    #[pyo3(signature = (early_termination=true,quadtree_depth=4,min_items_separation=None,total_computation_time=600,exploration_time=None,compression_time=None,num_workers=None,seed=None,max_evaluations=None,narrow_concavity_cutoff=None,poly_simpl_tolerance=DEFAULT_POLY_SIMPL_TOLERANCE,max_conseq_failed_attempts=None,compression_failure_decay_ratio=None,iter_no_imprv_limit=None,strike_limit=None,n_container_samples=DEFAULT_N_CONTAINER_SAMPLES,n_focussed_samples=DEFAULT_N_FOCUSSED_SAMPLES,cd_threshold=DEFAULT_CD_THRESHOLD))]
    fn new(
        early_termination: bool,
        quadtree_depth: u8,
        min_items_separation: Option<f32>,
        total_computation_time: Option<u64>,
        exploration_time: Option<u64>,
        compression_time: Option<u64>,
        num_workers: Option<usize>,
        seed: Option<u64>,
        max_evaluations: Option<NonZeroU64>,
        narrow_concavity_cutoff: Option<(f32, f32)>,
        poly_simpl_tolerance: Option<f32>,
        max_conseq_failed_attempts: Option<usize>,
        compression_failure_decay_ratio: Option<f32>,
        iter_no_imprv_limit: Option<usize>,
        strike_limit: Option<usize>,
        n_container_samples: usize,
        n_focussed_samples: usize,
        cd_threshold: u8,
    ) -> PyResult<Self> {
        let (exploration_time, compression_time) = match (
            total_computation_time,
            exploration_time,
            compression_time,
        ) {
            (None, Some(exploration_time), Some(compression_time)) => (
                Duration::from_secs(exploration_time),
                Duration::from_secs(compression_time),
            ),
            (Some(total_computation_time), None, None) => (
                Duration::from_secs(total_computation_time).mul_f32(0.8),
                Duration::from_secs(total_computation_time).mul_f32(0.2),
            ),
            _ => {
                return Err(PyValueError::new_err(
                    "Either total_computation_time or both exploration_time and compression_time should be provided, not all 3 or some other combination",
                ));
            }
        };
        let seed = seed.unwrap_or_else(rand::random);
        let num_workers = num_workers.unwrap_or_else(num_cpus::get);
        let config = Self {
            early_termination,
            seed,
            exploration_time,
            compression_time,
            quadtree_depth,
            num_workers,
            min_items_separation,
            max_evaluations,
            narrow_concavity_cutoff,
            poly_simpl_tolerance,
            max_conseq_failed_attempts,
            compression_failure_decay_ratio,
            iter_no_imprv_limit,
            strike_limit,
            n_container_samples,
            n_focussed_samples,
            cd_threshold,
        };
        config.validate_advanced()?;
        Ok(config)
    }

    fn __deepcopy__(&self, _memo: Py<PyAny>) -> Self {
        self.clone()
    }

    /// Return a string of the JSON representation of the object
    ///
    /// Returns:
    ///     str
    ///
    fn to_json_str(&self) -> String {
        serde_json::to_string(&self).unwrap()
    }
}

#[pyclass(name = "StripPackingInstance", get_all, set_all, skip_from_py_object)]
#[derive(Clone, Serialize)]
/// An Instance of a Strip Packing Problem.
///
/// Args:
///     name (str): The name of the instance. Required by the underlying sparrow library.
///       An empty string '' can be used, if the user doesn't have a use for this name.
///     strip_height (float): the fixed height of the strip. The unit should be compatible with the Item
///     items (Sequence[Item]): The Items which defines the instances. All Items should be defined with the same scale ( same length unit).
///
///  Raises:
///     ValueError
///
struct StripPackingInstancePy {
    pub name: String,
    pub strip_height: f32,
    pub items: Vec<ItemPy>,
}

// Maps spyrrow's `allowed_orientations` and `rotation_step` onto jagua-rs' explicit rotation modes:
// None -> free rotation (or stepped rotation if a step is given), [] -> [0.], otherwise the given discrete angles.
// A step is validated with the rule of jagua-rs' importer, to fail early with a clear error.
fn to_ext_rotation(
    allowed_orientations: &Option<Vec<f32>>,
    rotation_step: Option<f32>,
) -> PyResult<ExtRotation> {
    match (allowed_orientations, rotation_step) {
        (Some(_), Some(_)) => Err(PyValueError::new_err(
            "allowed_orientations and rotation_step can not be both provided",
        )),
        (None, Some(step)) => {
            if !(step.is_finite() && step > 0.0 && step <= 360.0) {
                return Err(PyValueError::new_err(format!(
                    "rotation_step must be finite and in (0, 360], got {step}"
                )));
            }
            let step_f64 = f64::from(step);
            let count = (360.0 / step_f64).round();
            if count > 65_536.0
                || (count * step_f64 - 360.0).abs() > 360.0 * f64::from(f32::EPSILON)
            {
                return Err(PyValueError::new_err(format!(
                    "rotation_step must evenly divide 360 into at most 65536 angles, got {step}"
                )));
            }
            Ok(ExtRotation::Stepped { step })
        }
        (None, None) => Ok(ExtRotation::Continuous {}),
        (Some(angles), None) if angles.is_empty() => Ok(ExtRotation::Discrete { angles: vec![0.0] }),
        (Some(angles), None) => Ok(ExtRotation::Discrete {
            angles: angles.clone(),
        }),
    }
}

// The optional reflection axis is given as is, jagua-rs normalizes it.
fn to_ext_orientation(
    allowed_orientations: &Option<Vec<f32>>,
    rotation_step: Option<f32>,
    reflection_axis: Option<f32>,
) -> PyResult<ExtOrientation> {
    Ok(ExtOrientation {
        rotation: to_ext_rotation(allowed_orientations, rotation_step)?,
        reflection_axes: reflection_axis.into_iter().collect(),
    })
}

impl StripPackingInstancePy {
    fn to_ext_instance(&self, py: Python, min_item_separation: Option<f32>) -> PyResult<ExtSPInstance> {
        let items = self
            .items
            .iter()
            .enumerate()
            .map(|(idx, v)| {
                let orientation = to_ext_orientation(&v.allowed_orientations, v.rotation_step, v.reflection_axis)
                    .map_err(|e| {
                        PyValueError::new_err(format!("Invalid Item '{}': {}", v.id, e.value(py)))
                    })?;
                let polygon = ExtSPolygon(v.shape.clone());
                let shape = ExtShape::SimplePolygon(polygon);
                let base = BaseItem {
                    id: idx as u64,
                    orientation,
                    shape,
                    min_quality: None,
                };
                Ok(ExtItem {
                    base,
                    demand: v.demand.get(),
                })
            })
            .collect::<PyResult<Vec<_>>>()?;
        Ok(ExtSPInstance {
            name: self.name.clone(),
            min_item_separation: min_item_separation.unwrap_or(0.0),
            strip_height: self.strip_height,
            items,
        })
    }
}

impl StripPackingInstancePy {
    // Converts a spyrrow solution back to jagua-rs' external representation.
    // String ids are mapped to the item index (the external id used by `to_ext_instance`).
    // Raises a ValueError on an unknown id.
    fn to_ext_solution(&self, solution: &StripPackingSolutionPy) -> PyResult<ExtSPSolution> {
        let index_of: HashMap<&str, u64> = self
            .items
            .iter()
            .enumerate()
            .map(|(idx, item)| (item.id.as_str(), idx as u64))
            .collect();
        let placed_items = solution
            .placed_items
            .iter()
            .map(|pi| {
                let item_id = *index_of.get(pi.id.as_str()).ok_or_else(|| {
                    PyValueError::new_err(format!(
                        "The solution places an item with id '{}' which is not an item of the instance",
                        pi.id
                    ))
                })?;
                Ok(ExtPlacedItem {
                    item_id,
                    transformation: ExtTransformation {
                        reflected: pi.reflected,
                        rotation: pi.rotation,
                        translation: pi.translation,
                    },
                })
            })
            .collect::<PyResult<Vec<_>>>()?;
        Ok(ExtSPSolution {
            strip_width: solution.width,
            layout: ExtLayout {
                container_id: 0,
                placed_items,
                density: solution.density,
            },
            density: solution.density,
            run_time_sec: 0,
        })
    }
}


#[pymethods]
impl StripPackingInstancePy {
    #[new]
    fn new(name: String, strip_height: f32, items: Vec<ItemPy>) -> PyResult<Self> {
        let item_ids: Vec<&str> = items.iter().map(|i| i.id.as_str()).collect();
        if !all_unique(&item_ids) {
            let error_string = format!("The item ids are not uniques: {item_ids:#?}");
            return Err(PyValueError::new_err(error_string));
        }
        Ok(StripPackingInstancePy {
            name,
            strip_height,
            items,
        })
    }

    /// Return a string of the JSON representation of the object
    ///
    /// Returns:
    ///     str
    ///
    fn to_json_str(&self) -> String {
        serde_json::to_string(&self).unwrap()
    }

    fn __deepcopy__(&self, _memo: Py<PyAny>) -> Self {
        self.clone()
    }

    /// Return a JSON string in the input format of the sparrow command line tool (and Sparrow Studio),
    /// to reproduce or debug a spyrrow run outside of Python.
    ///
    /// Without `solution`, the result is an instance file, to be given to `sparrow -i`.
    /// With `solution`, the instance and the solution are put in a single document (the format of
    /// the output of sparrow), which `sparrow -i` uses as a warm start.
    /// Items are identified by their index in `items` (the string ids are not exported).
    /// Only `min_items_separation` of the configuration is part of the instance;
    /// the time limits, seed, number of workers, ... are options of the sparrow command line.
    ///
    /// Warning: the solution is exported as is. If `config` has a `min_items_separation` (or the instance a
    /// `strip_height`) different from the one the solution was computed with, the exported warm start is
    /// infeasible, and the sparrow command line handles an infeasible start poorly (it may run far past its
    /// time limit, or return the infeasible layout). Export a solution with the config it was solved with.
    ///
    /// Args:
    ///     config (StripPackingConfig, optional): If given, its `min_items_separation` is exported
    ///       as the minimum separation of the instance. Defaults to None, meaning no separation.
    ///     solution (StripPackingSolution, optional): A solution of this instance to export along with it.
    ///       Defaults to None.
    ///
    /// Returns:
    ///     str
    ///
    /// Raises:
    ///     ValueError: If the solution places an item which is not an item of the instance.
    ///
    #[pyo3(signature = (config=None, solution=None))]
    fn to_sparrow_json_str(
        &self,
        py: Python,
        config: Option<StripPackingConfigPy>,
        solution: Option<StripPackingSolutionPy>,
    ) -> PyResult<String> {
        let ext_instance = self.to_ext_instance(py, config.and_then(|c| c.min_items_separation))?;
        let json = match solution {
            None => serde_json::to_string(&ext_instance),
            Some(solution) => serde_json::to_string(&ExtSPOutput {
                instance: ext_instance,
                solution: self.to_ext_solution(&solution)?,
            }),
        };
        json.map_err(|e| PyRuntimeError::new_err(format!("{e:#}")))
    }

    /// The method to solve the instance.
    ///
    /// Args:
    ///     config (StripPackingConfig): The configuration object to control how the instance is solved.
    ///     progress (ProgressQueue, optional): If provided, progress reports are pushed to this
    ///       queue during optimization. Use `queue.drain()` (and `queue.drain_events()` for a detailed queue)
    ///       from another thread to monitor progress.
    ///       Defaults to None.
    ///     initial_solution (StripPackingSolution, optional): A solution to warm start from, instead of
    ///       building one from scratch. Typically the result of a previous `solve` of the same instance.
    ///       It must place every item exactly `demand` times, using the ids of this instance.
    ///       Its width is used as the starting strip width, and the solver then tries to shrink it:
    ///       if the solution is feasible, the returned width is not larger than its width.
    ///       The strip height is always the one of this instance, and is not checked against the solution:
    ///       a solution computed for another strip height or another set of items is not meaningful.
    ///       The solution must be feasible for this instance and this config (no overlap, items inside the strip,
    ///       `min_items_separation` respected), otherwise a ValueError is raised: the solver assumes a feasible start.
    ///       A solution computed with a smaller separation or another strip height is typically not feasible.
    ///       Ignored for an instance without items (which must then be given an empty solution).
    ///       Defaults to None.
    ///
    /// Returns:
    ///     a StripPackingSolution
    ///
    /// Raises:
    ///     ValueError: If an advanced option of the config was set to an invalid value after its creation.
    ///     ValueError: If the instance can not be imported by the solver (invalid shape, separation larger than the strip height, ...),
    ///       or if the initial solution is not valid for this instance (unknown item id, item count different from the demand, invalid width, infeasible layout, ...)
    ///     RuntimeError: If the solver fails to build an initial solution
    ///
    #[pyo3(signature = (config, progress=None, initial_solution=None))]
    fn solve(&self, config: StripPackingConfigPy, progress: Option<ProgressQueuePy>, initial_solution: Option<StripPackingSolutionPy>, py: Python) -> PyResult<StripPackingSolutionPy> {
        let ext_initial_solution = initial_solution
            .as_ref()
            .map(|s| self.to_ext_solution(s))
            .transpose()?;
        if self.items.is_empty() {
            return Ok(StripPackingSolutionPy {
                width: 0.0,
                density: 0.0,
                placed_items:Vec::new(),
            })
        }
        config.validate_advanced()?;
        let mut rs_config = DEFAULT_SPARROW_CONFIG;
        rs_config.rng_seed = Some(config.seed as usize);
        rs_config.expl_cfg.time_limit = config.exploration_time;
        rs_config.expl_cfg.separator_config.n_workers = config.num_workers;
        rs_config.cmpr_cfg.time_limit = config.compression_time;
        rs_config.cmpr_cfg.separator_config.n_workers = config.num_workers;
        let rng =  Xoshiro256PlusPlus::seed_from_u64(config.seed);
        if config.early_termination {
            rs_config.expl_cfg.max_conseq_failed_attempts = Some(DEFAULT_MAX_CONSEQ_FAILS_EXPL);
            rs_config.cmpr_cfg.shrink_decay =
                ShrinkDecayStrategy::FailureBased(DEFAULT_FAIL_DECAY_RATIO_CMPR);
        }
        if config.max_evaluations.is_some() {
            // The time based decay would barely move under a time limit that is only a safety net
            rs_config.cmpr_cfg.shrink_decay =
                ShrinkDecayStrategy::FailureBased(DEFAULT_FAIL_DECAY_RATIO_CMPR);
        }
        // Explicit values take precedence over what `early_termination` implies
        if let Some(n) = config.max_conseq_failed_attempts {
            rs_config.expl_cfg.max_conseq_failed_attempts = Some(n);
        }
        if let Some(ratio) = config.compression_failure_decay_ratio {
            rs_config.cmpr_cfg.shrink_decay = ShrinkDecayStrategy::FailureBased(ratio);
        }
        for separator_config in [
            &mut rs_config.expl_cfg.separator_config,
            &mut rs_config.cmpr_cfg.separator_config,
        ] {
            if let Some(limit) = config.iter_no_imprv_limit {
                separator_config.iter_no_imprv_limit = limit;
            }
            if let Some(limit) = config.strike_limit {
                separator_config.strike_limit = limit;
            }
            separator_config.sample_config.n_container_samples = config.n_container_samples;
            separator_config.sample_config.n_focussed_samples = config.n_focussed_samples;
        }
        rs_config.cde_config.quadtree_depth = config.quadtree_depth;
        rs_config.cde_config.cd_threshold = config.cd_threshold;
        rs_config.poly_simpl_tolerance = config.poly_simpl_tolerance;
        rs_config.narrow_concavity_cutoff_ratio = config.narrow_concavity_cutoff;

        let ext_instance = self.to_ext_instance(py, config.min_items_separation)?;
        let importer = Importer::new(
            rs_config.cde_config,
            rs_config.poly_simpl_tolerance,
            // disabled by default as in previous spyrrow versions, unlike sparrow's default
            rs_config.narrow_concavity_cutoff_ratio,
        );
        let instance = jagua_rs::probs::spp::io::import_instance(&importer, &ext_instance)
            .map_err(|e| PyValueError::new_err(format!("Invalid StripPackingInstance: {e:#}")))?;
        let initial_solution = ext_initial_solution
            .map(|ext_solution| {
                let mut counts = vec![0u64; self.items.len()];
                for pi in &ext_solution.layout.placed_items {
                    counts[pi.item_id as usize] += 1;
                }
                for (item, count) in self.items.iter().zip(&counts) {
                    if *count != item.demand.get() {
                        return Err(PyValueError::new_err(format!(
                            "Invalid initial_solution: item '{}' is placed {} time(s) but its demand is {}",
                            item.id, count, item.demand
                        )));
                    }
                }
                let solution = jagua_rs::probs::spp::io::import_solution(&instance, &ext_solution)
                    .map_err(|e| PyValueError::new_err(format!("Invalid initial_solution: {e:#}")))?;
                // The solver assumes its starting point is feasible (same criterion as sparrow: zero total loss).
                let mut prob = SPProblem::new(instance.clone())
                    .map_err(|e| PyValueError::new_err(format!("Invalid StripPackingInstance: {e:#}")))?;
                prob.restore(&solution);
                let loss = CollisionTracker::new(prob.layout()).get_total_loss();
                if loss > 0.0 {
                    return Err(PyValueError::new_err(format!(
                        "Invalid initial_solution: it is not feasible for this instance and configuration \
                         (collision loss {loss}). Items overlap each other or exceed the strip, possibly because the \
                         strip height or min_items_separation differ from the ones the solution was computed with."
                    )));
                }
                Ok(solution)
            })
            .transpose()?;
        let evals = Arc::new(AtomicU64::new(0));
        let mut terminator = terminator::PythonTerminator::default();
        terminator.eval_budget = config.max_evaluations.map(|budget| {
            terminator::EvalBudget::new(
                evals.clone(),
                split_budget(budget.get(), config.exploration_time, config.compression_time),
            )
        });

        let mut listener = SolListener {
            progress: progress.map(|pq| ProgressListener {
                queue: pq.inner,
                events: pq.detailed.then_some(pq.events),
                item_ids: self.items.iter().map(|i| i.id.clone()).collect(),
            }),
            evals,
        };

        py.detach(move || {
            let solution = optimize(
                instance,
                rng,
                &mut listener,
                &mut terminator,
                &rs_config.expl_cfg,
                &rs_config.cmpr_cfg,
                initial_solution.as_ref(),
            )
            .map_err(|e| PyRuntimeError::new_err(format!("{e:#}")))?;

            let solution = jagua_rs::probs::spp::io::export(&solution, *EPOCH);

            let placed_items: Vec<PlacedItemPy> = solution
                .layout
                .placed_items
                .into_iter()
                .map(|jpi| PlacedItemPy {
                    id: self.items[jpi.item_id as usize].id.clone(),
                    rotation: jpi.transformation.rotation, // This is in degrees already now
                    translation: jpi.transformation.translation,
                    reflected: jpi.transformation.reflected,
                })
                .collect();

            Ok(StripPackingSolutionPy {
                width: solution.strip_width,
                density: solution.density,
                placed_items,
            })
        })
    }
}

/// A Python module implemented in Rust.
#[pymodule]
mod spyrrow {
    #[pymodule_export]
    use super::{
        CompressionProgressEventPy, ItemPy, OptimizationPhasePy, PhaseEventPy, PlacedItemPy,
        ProgressQueuePy, ReportTypePy, SeparationProgressEventPy, SeparationResultEventPy,
        StripPackingConfigPy, StripPackingInstancePy, StripPackingSolutionPy,
    };

    #[pymodule_export]
    #[allow(non_upper_case_globals)]
    const __version__: &str = env!("CARGO_PKG_VERSION");
}
