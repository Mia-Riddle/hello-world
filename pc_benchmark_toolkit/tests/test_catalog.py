from pc_benchmark.catalog import load_catalog, shop_links, suggest_upgrades, total_cost
from pc_benchmark.scanner import HardwareSnapshot
from pc_benchmark.scoring import ComponentVerdict, Evaluation, Status
from pc_benchmark.workload import WorkflowAnswers, compute_requirements


def test_catalog_loads_all_categories():
    catalog = load_catalog()
    for cat in ("cpu", "gpu", "ram", "storage"):
        assert catalog[cat], f"{cat} catalog should not be empty"


def test_suggest_upgrades_only_for_bottlenecks():
    evaluation = Evaluation(verdicts=[
        ComponentVerdict("CPU", Status.BAD, "too slow", "detail"),
        ComponentVerdict("RAM", Status.GOOD, "fine", "detail"),
    ])
    req = compute_requirements(WorkflowAnswers("4k", "raw_braw_red", 2, "heavy"))
    snapshot = HardwareSnapshot(
        os_name="x", cpu_name="x", physical_cores=4, logical_cores=8, cpu_max_ghz=3.0,
        ram_total_gb=16, disks=[], gpu_name="x", gpu_vram_gb=8, gpu_detected_automatically=False,
    )
    suggestions = suggest_upgrades(evaluation, snapshot, req)
    assert len(suggestions) == 1
    assert suggestions[0].category == "CPU"
    assert total_cost(suggestions) == suggestions[0].price_usd


def test_shop_links_are_well_formed():
    links = shop_links("Test Part")
    assert links
    assert all(url.startswith("https://") for url in links.values())
