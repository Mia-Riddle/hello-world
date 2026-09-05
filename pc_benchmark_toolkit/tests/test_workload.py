from pc_benchmark.workload import WorkflowAnswers, compute_requirements


def test_higher_resolution_demands_more():
    hd = compute_requirements(WorkflowAnswers("1080p", "h264_h265_long_gop", 1, "light"))
    uhd = compute_requirements(WorkflowAnswers("4k", "h264_h265_long_gop", 1, "light"))
    assert uhd.min_threads >= hd.min_threads
    assert uhd.recommended_ram_gb >= hd.recommended_ram_gb
    assert uhd.min_storage_mb_s > hd.min_storage_mb_s


def test_raw_codec_demands_more_gpu_than_h264():
    h264 = compute_requirements(WorkflowAnswers("4k", "h264_h265_long_gop", 1, "moderate"))
    raw = compute_requirements(WorkflowAnswers("4k", "raw_braw_red", 1, "moderate"))
    assert raw.recommended_gpu_vram_gb > h264.recommended_gpu_vram_gb


def test_multicam_increases_demand():
    single = compute_requirements(WorkflowAnswers("4k", "prores_dnxhr", 1, "moderate"))
    multi = compute_requirements(WorkflowAnswers("4k", "prores_dnxhr", 4, "moderate"))
    assert multi.min_threads > single.min_threads
    assert multi.min_storage_mb_s > single.min_storage_mb_s


def test_heavier_grading_increases_gpu_target_only():
    light = compute_requirements(WorkflowAnswers("4k", "h264_h265_long_gop", 1, "light"))
    heavy = compute_requirements(WorkflowAnswers("4k", "h264_h265_long_gop", 1, "heavy"))
    assert heavy.recommended_gpu_vram_gb > light.recommended_gpu_vram_gb
    assert heavy.min_storage_mb_s == light.min_storage_mb_s
