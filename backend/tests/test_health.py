from app.health import DependencyCheck, _timed_check


async def test_timed_check_reports_healthy_dependency() -> None:
    async def successful_check() -> dict[str, str]:
        return {"version": "test"}

    result = await _timed_check(
        DependencyCheck("test", successful_check),
        timeout_seconds=0.1,
    )

    assert result["status"] == "healthy"
    assert result["version"] == "test"
    assert result["latency_ms"] >= 0


async def test_timed_check_reports_dependency_error() -> None:
    async def failed_check() -> dict:
        raise RuntimeError("dependency failed")

    result = await _timed_check(
        DependencyCheck("test", failed_check),
        timeout_seconds=0.1,
    )

    assert result["status"] == "unhealthy"
    assert result["error"] == "dependency failed"

