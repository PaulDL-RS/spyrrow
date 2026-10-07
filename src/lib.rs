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
use sparrow::util::listener::{DummySolListener, ReportType, SolutionListener};
use std::collections::{HashSet, VecDeque};
use std::num::NonZeroU64;
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

#[pyclass(name = "ProgressQueue")]
#[derive(Clone)]
/// A thread-safe queue that collects progress reports from the solver.
///
/// Create one before calling `solve()` and pass it as the `progress` argument.
/// While the solver runs (in a background thread), call `drain()` to retrieve
/// any new reports.
///
/// Example::
///
///     queue = spyrrow.ProgressQueue()
///     # run solve in a thread, passing progress=queue
///     for report_type, solution in queue.drain():
///         print(f"{report_type.phase_name()}: width={solution.width:.1f}, density={solution.density:.1%}")
///
struct ProgressQueuePy {
    inner: Arc<Mutex<VecDeque<ProgressReport>>>,
}

#[pymethods]
impl ProgressQueuePy {
    #[new]
    fn new() -> Self {
        ProgressQueuePy {
            inner: Arc::new(Mutex::new(VecDeque::new())),
        }
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
}

// Implements SolutionListener to push progress reports onto a shared queue.
struct ProgressListener {
    queue: Arc<Mutex<VecDeque<ProgressReport>>>,
    item_ids: Vec<String>,
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
///     ValueError: If the combination of time arguments is invalid, or if an advanced option has an invalid value.
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
    #[pyo3(signature = (early_termination=true,quadtree_depth=4,min_items_separation=None,total_computation_time=600,exploration_time=None,compression_time=None,num_workers=None,seed=None,narrow_concavity_cutoff=None,poly_simpl_tolerance=DEFAULT_POLY_SIMPL_TOLERANCE,max_conseq_failed_attempts=None,compression_failure_decay_ratio=None,iter_no_imprv_limit=None,strike_limit=None,n_container_samples=DEFAULT_N_CONTAINER_SAMPLES,n_focussed_samples=DEFAULT_N_FOCUSSED_SAMPLES,cd_threshold=DEFAULT_CD_THRESHOLD))]
    fn new(
        early_termination: bool,
        quadtree_depth: u8,
        min_items_separation: Option<f32>,
        total_computation_time: Option<u64>,
        exploration_time: Option<u64>,
        compression_time: Option<u64>,
        num_workers: Option<usize>,
        seed: Option<u64>,
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
    ///       queue during optimization. Use `queue.drain()` from another thread to monitor progress.
    ///       Defaults to None.
    ///
    /// Returns:
    ///     a StripPackingSolution
    ///
    /// Raises:
    ///     ValueError: If an advanced option of the config was set to an invalid value after its creation.
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

        let ext_instance = self.to_ext_instance(config.min_items_separation);
        let importer = Importer::new(
            rs_config.cde_config,
            rs_config.poly_simpl_tolerance,
            // disabled by default as in previous spyrrow versions, unlike sparrow's default
            rs_config.narrow_concavity_cutoff_ratio,
        );
        let instance = jagua_rs::probs::spp::io::import_instance(&importer, &ext_instance)
            .map_err(|e| PyValueError::new_err(format!("Invalid StripPackingInstance: {e:#}")))?;
        let mut terminator = terminator::PythonTerminator::default();

        let mut listener = match progress {
            Some(pq) => SolListener::Progress(ProgressListener {
                queue: pq.inner,
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
    m.add_class::<ProgressQueuePy>()?;
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    Ok(())
}
