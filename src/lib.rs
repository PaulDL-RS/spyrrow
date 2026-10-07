use jagua_rs::io::ext_repr::{
    ExtItem as BaseItem, ExtOrientation, ExtRotation, ExtSPolygon, ExtShape,
};
use jagua_rs::io::import::Importer;
use jagua_rs::probs::spp::entities::SPSolution;
use jagua_rs::probs::spp::io::ext_repr::{ExtItem, ExtSPInstance};
use pyo3::exceptions::{PyRuntimeError, PyValueError};
use pyo3::prelude::*;
use rand::SeedableRng;
use rand::rngs::Xoshiro256PlusPlus;
use serde::Serialize;
use sparrow::EPOCH;
use sparrow::config::{DEFAULT_SPARROW_CONFIG, ShrinkDecayStrategy};
use sparrow::consts::{DEFAULT_FAIL_DECAY_RATIO_CMPR, DEFAULT_MAX_CONSEQ_FAILS_EXPL};
use sparrow::optimizer::optimize;
use sparrow::util::listener::{
    DummySolListener, OptimizationPhase, ReportType, SeparationProgress, SeparationResult,
    SolutionListener,
};
use std::collections::{HashSet, VecDeque};
use std::num::NonZeroU64;
use std::sync::{Arc, Mutex};
use std::time::Duration;

mod terminator;

#[pyclass(name = "Item", get_all, set_all)]
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
///
struct ItemPy {
    id: String,
    demand: NonZeroU64,
    allowed_orientations: Option<Vec<f32>>,
    shape: Vec<(f32, f32)>,
}

#[pymethods]
impl ItemPy {
    #[new]
    fn new(
        id: String,
        shape: Vec<(f32, f32)>,
        demand: NonZeroU64,
        allowed_orientations: Option<Vec<f32>>,
    ) -> Self {
        ItemPy {
            id,
            demand,
            allowed_orientations,
            shape,
        }
    }

    fn __repr__(&self) -> String {
        if self.allowed_orientations.is_some() {
            format!(
                "Item(id={},shape={:?}, demand={}, allowed_orientations={:?})",
                self.id,
                self.shape,
                self.demand,
                self.allowed_orientations.clone().unwrap()
            )
        } else {
            format!(
                "Item(id={},shape={:?}, demand={})",
                self.id, self.shape, self.demand,
            )
        }
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

#[pyclass(name = "PlacedItem", get_all)]
#[derive(Clone, Debug)]
/// An object representing where a copy of an Item was placed inside the strip.
///
/// Attributes:
///     id (str): The Item identifier referencing the items of the StripPackingInstance
///     rotation (float): The rotation angle in degrees, assuming that the original Item was defined with 0° as its rotation angle.
///       Use the origin (0.0,0.0) as the rotation point.
///     translation (tuple[float,float]): the translation vector in the X-Y axis. To apply after the rotation
///       
///
struct PlacedItemPy {
    pub id: String,
    pub translation: (f32, f32),
    pub rotation: f32,
}

#[pymethods]
impl PlacedItemPy {

    fn __deepcopy__(&self, _memo: Py<PyAny>) -> Self {
        self.clone()
    }
}

#[pyclass(name = "StripPackingSolution", get_all)]
#[derive(Clone, Debug)]
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
}

#[pyclass(name = "ReportType", eq, eq_int)]
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

    fn __repr__(&self) -> String {
        format!("ReportType.{:?}", self)
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

#[pyclass(name = "OptimizationPhase", eq, eq_int)]
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

#[pymethods]
impl OptimizationPhasePy {
    fn __repr__(&self) -> String {
        format!("OptimizationPhase.{:?}", self)
    }
}

impl From<OptimizationPhase> for OptimizationPhasePy {
    fn from(phase: OptimizationPhase) -> Self {
        match phase {
            OptimizationPhase::Exploration => OptimizationPhasePy::Exploration,
            OptimizationPhase::Compression => OptimizationPhasePy::Compression,
        }
    }
}

#[pyclass(name = "PhaseEvent", get_all, frozen)]
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
        format!("PhaseEvent(phase={})", self.phase.__repr__())
    }
}

#[pyclass(name = "SeparationProgressEvent", get_all, frozen)]
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

#[pyclass(name = "SeparationResultEvent", get_all, frozen)]
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

#[pyclass(name = "CompressionProgressEvent", get_all, frozen)]
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

#[pyclass(name = "ProgressQueue")]
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

// Enum wrapper to avoid duplicating the optimize() call in solve().
enum SolListener {
    Dummy(DummySolListener),
    Progress(ProgressListener),
}

impl SolutionListener for SolListener {
    fn report(&mut self, report: ReportType, solution: &SPSolution) {
        match self {
            SolListener::Dummy(d) => d.report(report, solution),
            SolListener::Progress(p) => p.report(report, solution),
        }
    }

    fn report_phase(&mut self, phase: OptimizationPhase) {
        if let SolListener::Progress(p) = self {
            p.report_phase(phase);
        }
    }

    fn report_separation_progress(&mut self, progress: SeparationProgress) {
        if let SolListener::Progress(p) = self {
            p.report_separation_progress(progress);
        }
    }

    fn report_separation_result(&mut self, result: SeparationResult) {
        if let SolListener::Progress(p) = self {
            p.report_separation_result(result);
        }
    }

    fn report_compression_progress(&mut self, shrink_step: f32) {
        if let SolListener::Progress(p) = self {
            p.report_compression_progress(shrink_step);
        }
    }
}

fn all_unique(strings: &[&str]) -> bool {
    let mut seen = HashSet::new();
    strings.iter().all(|s| seen.insert(*s))
}

#[pyclass(name = "StripPackingConfig", get_all, set_all)]
#[derive(Clone, Serialize)]
/// Initializes a configuration object for the strip packing algorithm.
///
/// Either `total_computation_time`, or both `exploration_time` and
///   `compression_time`, must be provided. Providing all three or only one of the latter two raises an error.
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
///
/// Raises:
///     ValueError: If the combination of time arguments is invalid.
///
struct StripPackingConfigPy {
    early_termination: bool,
    seed: u64,
    exploration_time: Duration,
    compression_time: Duration,
    quadtree_depth: u8,
    min_items_separation: Option<f32>,
    num_workers: usize,
}

#[pymethods]
impl StripPackingConfigPy {
    #[new]
    #[pyo3(signature = (early_termination=true,quadtree_depth=4,min_items_separation=None,total_computation_time=600,exploration_time=None,compression_time=None,num_workers=None,seed=None))]
    fn new(
        early_termination: bool,
        quadtree_depth: u8,
        min_items_separation: Option<f32>,
        total_computation_time: Option<u64>,
        exploration_time: Option<u64>,
        compression_time: Option<u64>,
        num_workers: Option<usize>,
        seed: Option<u64>,
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
        Ok(Self {
            early_termination,
            seed,
            exploration_time,
            compression_time,
            quadtree_depth,
            num_workers,
            min_items_separation,
        })
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

#[pyclass(name = "StripPackingInstance", get_all, set_all)]
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

// Maps spyrrow's `allowed_orientations` convention onto jagua-rs' explicit rotation modes:
// None -> free rotation, [] -> [0.], otherwise the given discrete angles.
fn to_ext_orientation(allowed_orientations: Option<Vec<f32>>) -> ExtOrientation {
    let rotation = match allowed_orientations {
        None => ExtRotation::Continuous {},
        Some(angles) if angles.is_empty() => ExtRotation::Discrete { angles: vec![0.0] },
        Some(angles) => ExtRotation::Discrete { angles },
    };
    ExtOrientation {
        rotation,
        reflection_axes: Vec::new(),
    }
}

impl StripPackingInstancePy {
    fn to_ext_instance(&self, min_item_separation: Option<f32>) -> ExtSPInstance {
        let items = self
            .items
            .iter()
            .enumerate()
            .map(|(idx, v)| {
                let polygon = ExtSPolygon(v.shape.clone());
                let shape = ExtShape::SimplePolygon(polygon);
                let base = BaseItem {
                    id: idx as u64,
                    orientation: to_ext_orientation(v.allowed_orientations.clone()),
                    shape,
                    min_quality: None,
                };
                ExtItem {
                    base,
                    demand: v.demand.get(),
                }
            })
            .collect();
        ExtSPInstance {
            name: self.name.clone(),
            min_item_separation: min_item_separation.unwrap_or(0.0),
            strip_height: self.strip_height,
            items,
        }
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

    /// The method to solve the instance.
    ///
    /// Args:
    ///     config (StripPackingConfig): The configuration object to control how the instance is solved.
    ///     progress (ProgressQueue, optional): If provided, progress reports are pushed to this
    ///       queue during optimization. Use `queue.drain()` (and `queue.drain_events()` for a detailed queue)
    ///       from another thread to monitor progress.
    ///       Defaults to None.
    ///
    /// Returns:
    ///     a StripPackingSolution
    ///
    /// Raises:
    ///     ValueError: If the instance can not be imported by the solver (invalid shape, separation larger than the strip height, ...)
    ///     RuntimeError: If the solver fails to build an initial solution
    ///
    #[pyo3(signature = (config, progress=None))]
    fn solve(&self, config: StripPackingConfigPy, progress: Option<ProgressQueuePy>, py: Python) -> PyResult<StripPackingSolutionPy> {
        if self.items.is_empty() {
            return Ok(StripPackingSolutionPy {
                width: 0.0,
                density: 0.0,
                placed_items:Vec::new(),
            })
        }
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
        rs_config.cde_config.quadtree_depth = config.quadtree_depth;

        let ext_instance = self.to_ext_instance(config.min_items_separation);
        let importer = Importer::new(
            rs_config.cde_config,
            rs_config.poly_simpl_tolerance,
            // kept disabled as in previous spyrrow versions, unlike sparrow's default
            None,
        );
        let instance = jagua_rs::probs::spp::io::import_instance(&importer, &ext_instance)
            .map_err(|e| PyValueError::new_err(format!("Invalid StripPackingInstance: {e:#}")))?;
        let mut terminator = terminator::PythonTerminator::default();

        let mut listener = match progress {
            Some(pq) => SolListener::Progress(ProgressListener {
                queue: pq.inner,
                events: pq.detailed.then_some(pq.events),
                item_ids: self.items.iter().map(|i| i.id.clone()).collect(),
            }),
            None => SolListener::Dummy(DummySolListener {}),
        };

        py.detach(move || {
            let solution = optimize(
                instance,
                rng,
                &mut listener,
                &mut terminator,
                &rs_config.expl_cfg,
                &rs_config.cmpr_cfg,
                None,
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
fn spyrrow(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<ItemPy>()?;
    m.add_class::<PlacedItemPy>()?;
    m.add_class::<StripPackingInstancePy>()?;
    m.add_class::<StripPackingConfigPy>()?;
    m.add_class::<StripPackingSolutionPy>()?;
    m.add_class::<ReportTypePy>()?;
    m.add_class::<OptimizationPhasePy>()?;
    m.add_class::<PhaseEventPy>()?;
    m.add_class::<SeparationProgressEventPy>()?;
    m.add_class::<SeparationResultEventPy>()?;
    m.add_class::<CompressionProgressEventPy>()?;
    m.add_class::<ProgressQueuePy>()?;
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    Ok(())
}
