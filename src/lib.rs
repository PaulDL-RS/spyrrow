use jagua_rs::io::json_instance::{JsonInstance, JsonItem, JsonShape, JsonSimplePoly, JsonStrip};
use jagua_rs::io::parse::Parser;
use pyo3::prelude::*;
use rand::prelude::SmallRng;
use rand::SeedableRng;
use sparrow::config::{
    CDE_CONFIG, COMPRESS_TIME_RATIO, EXPLORE_TIME_RATIO, MIN_ITEM_SEPARATION, SIMPL_TOLERANCE,
};
use sparrow::optimizer::{optimize, Terminator};
use sparrow::util::io::json_export::JsonOutput;
use sparrow::util::io::to_sp_instance;
use std::fs;
use std::time::Duration;

#[pyclass(name = "Item", get_all, set_all)]
#[derive(Clone)]
struct ItemPy {
    demand: u64,
    allowed_orientations: Option<Vec<f32>>,
    shape: Vec<(f32, f32)>,
}

#[pymethods]
impl ItemPy {
    #[new]
    fn new(shape: Vec<(f32, f32)>, demand: u64, allowed_orientations: Option<Vec<f32>>) -> Self {
        ItemPy {
            demand,
            allowed_orientations,
            shape,
        }
    }

    fn __repr__(&self) -> String {
        format!(
            "Item(shape={:?}, demand='{}', allowed_orientations={:?})",
            self.shape, self.demand, self.allowed_orientations
        )
    }
}

impl From<ItemPy> for JsonItem {
    fn from(value: ItemPy) -> Self {
        let shape = JsonShape::SimplePolygon(JsonSimplePoly(value.shape));
        JsonItem {
            allowed_orientations: value.allowed_orientations,
            demand: value.demand,
            shape,
            value: None,
            base_quality: None,
        }
    }
}

#[pyclass(name = "PlacedItem", get_all)]
#[derive(Clone, Debug)]
struct PlacedItemPy {
    pub id: usize,
    pub translation: (f32, f32),
    pub rotation: f32,
}

#[pyclass(name = "StripPackingSolution", get_all)]
#[derive(Clone, Debug)]
struct StripPackingSolutionPy {
    pub width: f32,
    pub placed_items: Vec<PlacedItemPy>,
    pub density: f32,
}

#[pyclass(name = "StripPackingInstance", get_all, set_all)]
#[derive(Clone)]
struct StripPackingInstancePy {
    pub name: String,
    pub height: f32,
    pub items: Vec<ItemPy>,
}

impl From<StripPackingInstancePy> for JsonInstance {
    fn from(value: StripPackingInstancePy) -> Self {
        let items = value.items.into_iter().map(|v| v.into()).collect();
        let strip = Some(JsonStrip {
            height: value.height,
        });
        JsonInstance {
            name: value.name,
            bins: None,
            strip,
            items,
        }
    }
}

#[pymethods]
impl StripPackingInstancePy {
    #[new]
    fn new(name: String, height: f32, items: Vec<ItemPy>) -> Self {
        StripPackingInstancePy {
            name,
            height,
            items,
        }
    }

    fn solve(&self, computation_time: Option<u64>, py: Python) -> StripPackingSolutionPy {
        // Temporary output dir for intermediary solution

        // let tmp = TempDir::new().expect("could not create output directory");
        let tmp_str = String::from("tmp");
        fs::create_dir_all(&tmp_str).expect("Temporary foulder should be created");

        // Reproductibility
        let seed = rand::random();
        let rng = SmallRng::seed_from_u64(seed);

        // Execution Time
        let (explore_dur, compress_dur) = if let Some(ct) = computation_time {
            (
                Duration::from_secs(ct).mul_f32(EXPLORE_TIME_RATIO),
                Duration::from_secs(ct).mul_f32(COMPRESS_TIME_RATIO),
            )
        } else {
            (
                Duration::from_secs(600).mul_f32(EXPLORE_TIME_RATIO),
                Duration::from_secs(600).mul_f32(COMPRESS_TIME_RATIO),
            )
        };

        let json_instance = self.clone().into();
        let parser = Parser::new(CDE_CONFIG, SIMPL_TOLERANCE, MIN_ITEM_SEPARATION);
        let any_instance = parser.parse(&json_instance);
        let instance = to_sp_instance(any_instance.as_ref()).expect("Expected SPInstance");

        let terminator = Terminator::new_with_ctrlc_handler();
        py.allow_threads(move || {
            let solution = optimize(
                instance.clone(),
                rng,
                tmp_str.clone(),
                terminator,
                explore_dur,
                compress_dur,
            );
            let density = solution.density(&instance);

            let mut json_output = JsonOutput::new(json_instance.clone(), &solution, &instance);
            // TODO Verify that layouts is not empty and if that is even possible
            let solution_layout = json_output.solution.layouts.remove(0);
            let placed_items: Vec<PlacedItemPy> = solution_layout
                .placed_items
                .into_iter()
                .map(|jpi| PlacedItemPy {
                    id: jpi.index,
                    rotation: jpi.transformation.rotation,
                    translation: jpi.transformation.translation,
                })
                .collect();
            fs::remove_dir_all(&tmp_str).expect("Should be able to remove tmp dir");
            StripPackingSolutionPy {
                width: solution.strip_width,
                density,
                placed_items,
            }
        })
    }
}

/// A Python module implemented in Rust.
#[pymodule]
fn spyrrow(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<ItemPy>()?;
    m.add_class::<StripPackingInstancePy>()?;
    m.add_class::<StripPackingSolutionPy>()?;
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    Ok(())
}
