use jagua_rs::io::ext_repr::{ExtItem as BaseItem, ExtSPolygon, ExtShape};
use jagua_rs::io::import::Importer;
use jagua_rs::probs::spp::entities::{SPInstance, SPSolution};
use jagua_rs::probs::spp::io::ext_repr::{ExtItem, ExtSPInstance};
use pyo3::exceptions::PyValueError;
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
    strip_width: f32,
    density: f32,
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
///     for report_type, strip_width, density in queue.drain():
///         print(f"{report_type.phase_name()}: width={strip_width:.1f}, density={density:.1%}")
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
    ///     list[tuple[ReportType, float, float]]: A list of (report_type, strip_width, density) tuples.
    ///
    fn drain(&self) -> Vec<(ReportTypePy, f32, f32)> {
        let mut queue = self.inner.lock().unwrap();
        queue.drain(..).map(|r| (r.report_type, r.strip_width, r.density)).collect()
    }
}

// Implements SolutionListener to push progress reports onto a shared queue.
struct ProgressListener {
    queue: Arc<Mutex<VecDeque<ProgressReport>>>,
}

impl SolutionListener for ProgressListener {
    fn report(&mut self, report: ReportType, solution: &SPSolution, instance: &SPInstance) {
        // Export the solution to get strip_width and density.
        // This is acceptable because reports are infrequent (only on improving solutions).
        let exported = jagua_rs::probs::spp::io::export(instance, solution, *EPOCH);
        let mut queue = self.queue.lock().unwrap();
        queue.push_back(ProgressReport {
            report_type: ReportTypePy::from(report),
            strip_width: exported.strip_width,
            density: exported.density,
        });
    }
}

// Enum wrapper to avoid duplicating the optimize() call in solve().
enum SolListener {
    Dummy(DummySolListener),
    Progress(ProgressListener),
}

impl SolutionListener for SolListener {
    fn report(&mut self, report: ReportType, solution: &SPSolution, instance: &SPInstance) {
        match self {
            SolListener::Dummy(d) => d.report(report, solution, instance),
            SolListener::Progress(p) => p.report(report, solution, instance),
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

impl From<StripPackingInstancePy> for ExtSPInstance {
    fn from(value: StripPackingInstancePy) -> Self {
        let items = value
            .items
            .into_iter()
            .enumerate()
            .map(|(idx, v)| {
                let polygon = ExtSPolygon(v.shape);
                let shape = ExtShape::SimplePolygon(polygon);
                let base = BaseItem {
                    id: idx as u64,
                    allowed_orientations: v.allowed_orientations,
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
            name: value.name,
            strip_height: value.strip_height,
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
    #[pyo3(signature = (config, progress=None))]
    fn solve(&self, config: StripPackingConfigPy, progress: Option<ProgressQueuePy>, py: Python) -> StripPackingSolutionPy {
        if self.items.is_empty() {
            return StripPackingSolutionPy {
                width: 0.0,
                density: 0.0,
                placed_items:Vec::new(),
            }
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
        rs_config.min_item_separation = config.min_items_separation;

        let ext_instance = self.clone().into();
        let importer = Importer::new(
            rs_config.cde_config,
            rs_config.poly_simpl_tolerance,
            rs_config.min_item_separation,None
        );
        let instance = jagua_rs::probs::spp::io::import_instance(&importer, &ext_instance)
            .expect("Expected a Strip Packing Problem Instance");
        let mut terminator = terminator::PythonTerminator::default();

        let mut listener = match progress {
            Some(pq) => SolListener::Progress(ProgressListener { queue: pq.inner }),
            None => SolListener::Dummy(DummySolListener {}),
        };

        py.detach(move || {
            let solution = optimize(
                instance.clone(),
                rng,
                &mut listener,
                &mut terminator,
                &rs_config.expl_cfg,
                &rs_config.cmpr_cfg,
                None,
            );

            let solution = jagua_rs::probs::spp::io::export(&instance, &solution, *EPOCH);

            let placed_items: Vec<PlacedItemPy> = solution
                .layout
                .placed_items
                .into_iter()
                .map(|jpi| PlacedItemPy {
                    id: self.items[jpi.item_id as usize].id.clone(),
                    rotation: jpi.transformation.rotation, // This is in degrees already know
                    translation: jpi.transformation.translation,
                })
                .collect();

            StripPackingSolutionPy {
                width: solution.strip_width,
                density: solution.density,
                placed_items,
            }
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
