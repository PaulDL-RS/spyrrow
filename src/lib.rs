use jagua_rs::io::ext_repr::{ExtItem as BaseItem, ExtSPolygon, ExtShape};
use jagua_rs::io::import::Importer;
use jagua_rs::probs::spp::io::ext_repr::{ExtItem, ExtSPInstance};
use pyo3::prelude::*;
use rand::prelude::SmallRng;
use rand::SeedableRng;
use sparrow::config::{
    CDE_CONFIG, COMPRESS_TIME_RATIO, EXPLORE_TIME_RATIO, MIN_ITEM_SEPARATION, SIMPL_TOLERANCE,
};
use sparrow::optimizer::{optimize, Terminator};
use sparrow::EPOCH;
use std::fs;
use std::time::Duration;

#[pyclass(name = "Item", get_all, set_all)]
#[derive(Clone)]
struct ItemPy {
    id: u64,
    demand: u64,
    allowed_orientations: Option<Vec<f32>>,
    shape: Vec<(f32, f32)>,
}

#[pymethods]
impl ItemPy {
    #[new]
    fn new(id: u64, shape: Vec<(f32, f32)>, demand: u64, allowed_orientations: Vec<f32>) -> Self {
        ItemPy {
            id,
            demand,
            allowed_orientations: Some(allowed_orientations),
            shape,
        }
    }

    fn __repr__(&self) -> String {
        format!(
            "Item(id={},shape={:?}, demand='{}', allowed_orientations={:?})",
            self.id, self.shape, self.demand, self.allowed_orientations
        )
    }
}

impl From<ItemPy> for ExtItem {
    fn from(value: ItemPy) -> Self {
        let polygon = ExtSPolygon(value.shape);
        let shape = ExtShape::SimplePolygon(polygon);
        let base = BaseItem {
            id: value.id,
            allowed_orientations: value.allowed_orientations,
            shape,
            min_quality: None,
        };
        ExtItem {
            base,
            demand: value.demand,
        }
    }
}

#[pyclass(name = "PlacedItem", get_all)]
#[derive(Clone, Debug)]
struct PlacedItemPy {
    pub id: u64,
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

impl From<StripPackingInstancePy> for ExtSPInstance {
    fn from(value: StripPackingInstancePy) -> Self {
        let items = value.items.into_iter().map(|v| v.into()).collect();
        ExtSPInstance {
            name: value.name,
            strip_height: value.height,
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

    #[pyo3(signature = (computation_time=600))]
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
        // TODO Investigate the rules about ids
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
                    id: jpi.item_id,
                    rotation: jpi.transformation.rotation,
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
    m.add_class::<StripPackingInstancePy>()?;
    m.add_class::<StripPackingSolutionPy>()?;
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    Ok(())
}
