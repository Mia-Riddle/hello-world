from pc_benchmark.benchmarks import BenchmarkResults
from pc_benchmark.scanner import HardwareSnapshot
from pc_benchmark.scoring import Status, evaluate
from pc_benchmark.workload import WorkflowAnswers, compute_requirements


def make_snapshot(**overrides):
    base = dict(
        os_name="TestOS", cpu_name="Test CPU", physical_cores=8, logical_cores=16,
        cpu_max_ghz=4.5, ram_total_gb=32, disks=[], gpu_name="Test GPU",
        gpu_vram_gb=16, gpu_detected_automatically=True,
    )
    base.update(overrides)
    return HardwareSnapshot(**base)


def make_bench(**overrides):
    base = dict(cpu_hash_mb_per_sec=1000, ram_copy_gb_per_sec=10,
                disk_write_mb_per_sec=2000, disk_read_mb_per_sec=2000)
    base.update(overrides)
    return BenchmarkResults(**base)


def test_beefy_pc_passes_light_workflow():
    req = compute_requirements(WorkflowAnswers("1080p", "h264_h265_long_gop", 1, "light"))
    evaluation = evaluate(make_snapshot(), make_bench(), req)
    assert all(v.status in (Status.GOOD, Status.INFO) for v in evaluation.verdicts)


def test_weak_pc_fails_heavy_workflow():
    req = compute_requirements(WorkflowAnswers("8k", "raw_braw_red", 4, "heavy"))
    weak_snapshot = make_snapshot(logical_cores=4, ram_total_gb=8, gpu_vram_gb=4)
    weak_bench = make_bench(disk_read_mb_per_sec=100, disk_write_mb_per_sec=100)
    evaluation = evaluate(weak_snapshot, weak_bench, req)
    assert evaluation.bottlenecks
    assert any(v.category == "Storage" and v.status == Status.BAD for v in evaluation.verdicts)


def test_unknown_gpu_vram_is_info_not_bad():
    req = compute_requirements(WorkflowAnswers("4k", "h264_h265_long_gop", 1, "moderate"))
    snapshot = make_snapshot(gpu_vram_gb=None)
    evaluation = evaluate(snapshot, make_bench(), req)
    gpu_verdict = next(v for v in evaluation.verdicts if v.category == "GPU")
    assert gpu_verdict.status == Status.INFO
