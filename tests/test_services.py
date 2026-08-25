from quant_harness.config import load_config
from quant_harness.services import FFOService


def test_role_caches_are_snapshot_scoped_and_distinct(tmp_path):
    config = load_config("configs/smoke.yaml")
    search = FFOService(
        config,
        config.search_endpoint,
        role="search",
        log_dir=tmp_path,
    )
    verifier = FFOService(
        config,
        config.verifier_endpoint,
        role="verifier",
        log_dir=tmp_path,
    )
    search_cache = search._effective_cache_path()
    verifier_cache = verifier._effective_cache_path()
    assert search_cache != verifier_cache
    assert search_cache.name.startswith("factor_cache-")
    assert verifier_cache.name.startswith("factor_cache-")
