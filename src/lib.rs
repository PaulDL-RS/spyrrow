use jagua_rs::io::ext_repr::{ExtItem as BaseItem, ExtSPolygon, ExtShape};
use jagua_rs::io::import::Importer;
use jagua_rs::probs::spp::io::ext_repr::{ExtItem, ExtSPInstance};
use num_cpus;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use rand::SeedableRng;
use rand::prelude::SmallRng;
use serde::Serialize;
use sparrow::EPOCH;
use sparrow::config::{DEFAULT_SPARROW_CONFIG, ShrinkDecayStrategy};
use sparrow::consts::{DEFAULT_FAIL_DECAY_RATIO_CMPR, DEFAULT_MAX_CONSEQ_FAILS_EXPL};
use sparrow::optimizer::optimize;
use sparrow::util::listener::DummySolListener;
use sparrow::util::terminator::BasicTerminator;
use std::collections::HashSet;

use std::time::Duration;

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
///     shape (list[tuple[float,float]]): An ordered list of (x,y) defining the shape boundary. The shape is represented as a polygon formed by this list of points.
///       The origin point can be included twice as the finishing point. If not, [last point, first point] is infered to be the last straight line of the shape.
///     demand (int): The quantity of identical Items to be placed inside the strip. Should be positive.
///     allowed_orientations (list[float]|None): List of angles in degrees allowed.
///       An empty list is equivalent to [0.].
///       A None value means that the item is free to rotate
///       The algorithmn is only very weakly sensible to the length of the list given.
///
struct ItemPy {
    id: String,
    demand: u64,
    allowed_orientations: Option<Vec<f32>>,
    shape: Vec<(f32, f32)>,
}

#[pymethods]
impl ItemPy {
    #[new]
    fn new(
        id: String,
        shape: Vec<(f32, f32)>,
        demand: u64,
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

fn all_unique(strings: &[&str]) -> bool {
    let mut seen = HashSet::new();
    strings.iter().all(|s| seen.insert(*s))
}

#[pyclass(name = "StripPackingConfig", get_all, set_all)]
#[derive(Clone, Serialize)]
/// Initializes a configuration object for the strip packing algorithm.
///
/// Either `total_computation_time`, or both `exploration_time` and
/// `compression_time`, must be provided. Providing all three or only
///  one of the latter two raises an error.
///
///  If `total_computation_time` is provided, 80% of it is allocated to
///  exploration and 20% to compression.
///
///  If `seed` is not provided, a random seed will be generated.
///
///  Args:
///      early_termination (bool, optional): Whether to allow early termination of the algorithm. Defaults to True.
///      quadtree_depth (int, optional): Maximum depth of the quadtree used by the collision detection engine jagua-rs.
///        Must be positive, common values are 3,4,5. Defaults to 4.
///      min_items_separation (Optional[float], optional): Minimum required distance between packed items. Defaults to None.
///      total_computation_time (Optional[int], optional): Total time budget in seconds.
///        Used if `exploration_time` and `compression_time` are not provided. Defaults to 600.
///      exploration_time (Optional[int], optional): Time in seconds allocated to exploration. Defaults to None.
///      compression_time (Optional[int], optional): Time in seconds allocated to compression. Defaults to None.
///      num_workers (Optional[int], optional): Number of threads used by the collision detection engine during exploration.
///         When set to None, detect the number of logical CPU cores on the execution plateform. Defaults to None.
///      seed (Optional[int], optional): Optional random seed to give reproductibility. If None, a random seed is generated. Defaults to None.
///
///  Raises:
///     ValueError: If the combination of time arguments is invalid.
struct StripPackingConfigPy {
    early_termination: bool,
    seed: u64,
    exploration_time: Duration,
    compression_time: Duration,
    quadtree_depth: u8,
    min_items_separation: Option<f32>,
    num_wokers: usize,
}

#[pymethods]
impl StripPackingConfigPy {
    #[new]
    #[pyo3(signature = (early_termination=true,quadtree_depth=4,min_items_separation=None,total_computation_time=600,exploration_time=None,compression_time=None,num_wokers=None,seed=None))]
    fn new(
        early_termination: bool,
        quadtree_depth: u8,
        min_items_separation: Option<f32>,
        total_computation_time: Option<u64>,
        exploration_time: Option<u64>,
        compression_time: Option<u64>,
        num_wokers: Option<usize>,
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
        let num_wokers = num_wokers.unwrap_or_else(num_cpus::get);
        Ok(Self {
            early_termination,
            seed,
            exploration_time,
            compression_time,
            quadtree_depth,
            num_wokers,
            min_items_separation,
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
}

#[pyclass(name = "StripPackingInstance", get_all, set_all)]
#[derive(Clone, Serialize)]
/// An Instance of a Strip Packing Problem.
///
/// Args:
///     name (str): The name of the instance. Required by the underlying sparrow library.
///       An empty string '' can be used, if the user doesn't have a use for this name.
///     strip_height (float): the fixed height of the strip. The unit should be compatible with the Item
///     items (list[Item]): The Items which defines the instances. All Items should be defined with the same scale ( same length unit).
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
                    demand: v.demand,
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

    /// The method to solve the instance.
    ///
    /// Args:
    ///     computation_time (int): The total computation time in seconds used to find a solution.
    ///       The algorithm won't exit early.Waht you input is what you get. Default is 600 s = 10 minutes.
    ///
    /// Returns:
    ///     a StripPackingSolution
    ///
    fn solve(&self, config_py: StripPackingConfigPy, py: Python) -> StripPackingSolutionPy {
        let mut config = DEFAULT_SPARROW_CONFIG;
        config.rng_seed = Some(config_py.seed as usize);
        config.expl_cfg.time_limit = config_py.exploration_time;
        config.expl_cfg.separator_config.n_workers = config_py.num_wokers;
        config.cmpr_cfg.time_limit = config_py.compression_time;
        let rng = SmallRng::seed_from_u64(config_py.seed);
        if config_py.early_termination {
            config.expl_cfg.max_conseq_failed_attempts = Some(DEFAULT_MAX_CONSEQ_FAILS_EXPL);
            config.cmpr_cfg.shrink_decay =
                ShrinkDecayStrategy::FailureBased(DEFAULT_FAIL_DECAY_RATIO_CMPR);
        }
        config.cde_config.quadtree_depth = config_py.quadtree_depth;
        config.min_item_separation = config_py.min_items_separation;

        let ext_instance = self.clone().into();
        let importer = Importer::new(
            config.cde_config,
            config.poly_simpl_tolerance,
            config.min_item_separation,
        );
        let instance = jagua_rs::probs::spp::io::import(&importer, &ext_instance)
            .expect("Expected a Strip Packing Problem Instance");
        let mut terminator = BasicTerminator::new();

        // The Python code is not concerned with intermediary solution for now
        let mut dummy_exporter = DummySolListener {};

        py.allow_threads(move || {
            let solution = optimize(
                instance.clone(),
                rng,
                &mut dummy_exporter,
                &mut terminator,
                &config.expl_cfg,
                &config.cmpr_cfg,
            );

            let solution = jagua_rs::probs::spp::io::export(&instance, &solution, *EPOCH);

            let placed_items: Vec<PlacedItemPy> = solution
                .layout
                .placed_items
                .into_iter()
                .map(|jpi| PlacedItemPy {
                    id: self.items[jpi.item_id as usize].id.clone(),
                    rotation: jpi.transformation.rotation.to_degrees(), // Until sparrow exports to degrees instead of radians
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
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    Ok(())
}
