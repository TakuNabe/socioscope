from socioscope_core.core.llm_cache import cache_key


def test_cache_key_changes_with_every_component() -> None:
    base = dict(model="m", schema_name="S", schema_version="1", prompt="p")
    k = cache_key(**base)
    for field, value in [
        ("model", "m2"),
        ("schema_name", "S2"),
        ("schema_version", "2"),
        ("prompt", "q"),
    ]:
        assert cache_key(**{**base, field: value}) != k
    assert cache_key(**base) == k  # deterministic
