from concurrent.futures import ThreadPoolExecutor, as_completed


import spyrrow
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
)

def instance1_res() -> spyrrow.StripPackingSolution:
    logger = logging.getLogger("Instance1")
    logger.setLevel(logging.INFO)
    rectangle1 = spyrrow.Item(
        "rectangle",
        [(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)],
        demand=40,
        allowed_orientations=[0],
    )
    triangle1 = spyrrow.Item(
        "triangle",
        [(0, 0), (1, 0), (1, 1), (0, 0)],
        demand=60,
        allowed_orientations=[0, 90, 180, -90],
    )

    instance = spyrrow.StripPackingInstance(
        "test", strip_height=2.001, items=[rectangle1, triangle1]
    )
    config = spyrrow.StripPackingConfig(
        early_termination=True, total_computation_time=600, num_workers=3, seed=0
    )
    logger.info("Start solving")
    res = instance.solve(config)
    logger.info("End solving")
    return res


def instance2_res() -> spyrrow.StripPackingSolution:
    logger = logging.getLogger("Instance2")
    logger.setLevel(logging.INFO)
    octagon = spyrrow.Item(
        "octagon ",
        [
            (1.3065629649, 0.0),
            (0.9238795325, 0.9238795325),
            (0.0, 1.3065629649),
            (-0.9238795325, 0.9238795325),
            (-1.3065629649, 0.0),
            (-0.9238795325, -0.9238795325),
            (0.0, -1.3065629649),
            (0.9238795325, -0.9238795325),
        ],
        demand=10,
        allowed_orientations=None,
    )
    pentagon = spyrrow.Item(
        "pentagon",
        [
            (0.8506508083, 0.0),
            (0.2639320225, 0.8090169944),
            (-0.6881909602, 0.5),
            (-0.6881909602, -0.5),
            (0.2639320225, -0.8090169944),
        ],
        demand=10,
        allowed_orientations=None,
    )

    instance = spyrrow.StripPackingInstance(
        "test", strip_height=4.001, items=[octagon, pentagon]
    )
    config = spyrrow.StripPackingConfig(
        early_termination=True, total_computation_time=600, num_workers=3, seed=0
    )
    logger.info("Start solving")
    res = instance.solve(config)
    logger.info("End solving")
    return res

# tasks = [instance1_res,instance2_res]
# with ThreadPoolExecutor(max_workers=2) as pool:
#     futures = [pool.submit(task) for task in tasks]
#     all_res = []
#     for f in as_completed(futures):
#         res = f.result()
#         all_res.append(res)
#         print("One instance finished")


import threading
import spyrrow

# ... set up instance and config ...
rectangle1 = spyrrow.Item(
        "rectangle",
        [(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)],
        demand=40,
        allowed_orientations=[0],
    )
triangle1 = spyrrow.Item(
        "triangle",
        [(0, 0), (1, 0), (1, 1), (0, 0)],
        demand=60,
        allowed_orientations=[0, 90, 180, -90],
    )

instance = spyrrow.StripPackingInstance(
        "test", strip_height=2.001, items=[rectangle1, triangle1]
    )
config = spyrrow.StripPackingConfig(
        early_termination=True, total_computation_time=600, num_workers=3, seed=0
    )

queue = spyrrow.ProgressQueue()
result = [None]

def run():
    result[0] = instance.solve(config, progress=queue)

thread = threading.Thread(target=run)
thread.start()
while thread.is_alive():
    for report_type, solution in queue.drain():
        print(f"{report_type.phase_name()}: width={solution.width:.1f}, density={solution.density:.1%}")
    thread.join(timeout=0.5)

solution = result[0]