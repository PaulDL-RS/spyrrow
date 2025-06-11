use jagua_rs::io::ext_repr::{ExtItem as BaseItem, ExtSPolygon, ExtShape};
use jagua_rs::io::import::Importer;
use jagua_rs::probs::spp::io::ext_repr::{ExtItem, ExtSPInstance};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use rand::SeedableRng;
use rand::prelude::SmallRng;
use serde::Serialize;
use sparrow::EPOCH;
use sparrow::config::{
    CDE_CONFIG, COMPRESS_TIME_RATIO, EXPLORE_TIME_RATIO, MIN_ITEM_SEPARATION, SIMPL_TOLERANCE,
};
use sparrow::optimizer::{Terminator, optimize};
use std::collections::HashSet;
use std::fs;
use std::time::Duration;

#[pyclass(name = "Item", get_all, set_all)]
#[derive(Clone, Serialize)]
/// An Item represents any closed 2D shape by its outer boundary.
///
/// Spyrrow doesn't support hole(s) inside the shape as of yet. Therefore no Item can be nested inside another.
///
/// Continous rotation is not supported as of yet. A workaround  is to specify any integer degrees between 0 and 360
/// to the allowed_orientations list.
///
/// Args:
///     id (str): The Item identifier
///       Needs to be unique accross all Items of a StripPackingInstance
///     shape (list[tuple[float,float]]): An ordered list of (x,y) defining the shape boundary. The shape is represented as a polygon formed by this list of points.
///       The origin point can be included twice as the finishing point. If not, [last point, first point] is infered to be the last straight line of the shape.
///     demand (int): The quantity of identical Items to be placed inside the strip. Should be positive.
///     allowed_orientations (list[float]): List of angles in degrees allowed. An empty list is equivalent to [0.].
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
        allowed_orientations: Vec<f32>,
    ) -> Self {
        ItemPy {
            id,
            demand,
            allowed_orientations: Some(allowed_orientations),
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
                    //         }
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
            let error_string = format!("The item ids are not uniques: {:#?}", item_ids);
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

    #[pyo3(signature = (computation_time=600))]
    /// The method to solve the instance.
    ///
    /// Args:
    ///     computation_time (int): The total computation time in seconds used to find a solution.
    ///       The algorithm won't exit early.Waht you input is what you get. Default is 600 s = 10 minutes.
    ///
    /// Returns:
    ///     a StripPackingSolution
    ///
    fn solve(&self, computation_time: u64, py: Python) -> StripPackingSolutionPy {
        // Temporary output dir for intermediary solution

        // let tmp = TempDir::new().expect("could not create output directory");
        let tmp_str = String::from("tmp");
        fs::create_dir_all(&tmp_str).expect("Temporary foulder should be created");

        // Reproductibility
        let seed = rand::random();
        let rng = SmallRng::seed_from_u64(seed);

        // Execution Time
        let (explore_dur, compress_dur) = (
            Duration::from_secs(computation_time).mul_f32(EXPLORE_TIME_RATIO),
            Duration::from_secs(computation_time).mul_f32(COMPRESS_TIME_RATIO),
        );

        let ext_instance = self.clone().into();
        let importer = Importer::new(CDE_CONFIG, SIMPL_TOLERANCE, MIN_ITEM_SEPARATION);
        let instance = jagua_rs::probs::spp::io::import(&importer, &ext_instance)
            .expect("Expected a Strip Packing Problem Instance");

        py.allow_threads(move || {
            let terminator = Terminator::new_without_ctrlc();
            let solution = optimize(
                instance.clone(),
                rng,
                tmp_str.clone(),
                terminator,
                explore_dur,
                compress_dur,
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
            fs::remove_dir_all(&tmp_str).expect("Should be able to remove tmp dir");
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
    m.add_class::<StripPackingSolutionPy>()?;
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    Ok(())
}
