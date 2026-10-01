"""Missing optional packages must not advertise unimplemented operations."""
from importlib.metadata import PackageNotFoundError

from surveysync.integration_registry import inventory


def test_missing_packages_leave_builtin_usable():
    def missing(name):
        raise PackageNotFoundError(name)
    rows = {r["key"]: r for r in inventory(missing)["adapters"]}
    assert rows["dxf_builtin"]["status"] == "ready"
    assert rows["proj"]["status"] == "unavailable"
    assert rows["las"]["capabilities"] == []
    assert rows["ezdxf"]["status"] == "unavailable"


def test_installing_planned_package_does_not_enable_adapter():
    rows = {r["key"]: r for r in inventory(lambda _: "1.2.3")["adapters"]}
    assert rows["proj"]["version"] == "1.2.3"
    assert rows["proj"]["status"] == "ready"
    assert rows["shapely"]["version"] == "1.2.3"
    assert rows["shapely"]["status"] == "ready"
    assert rows["shapely"]["capabilities"]
    assert rows["geocompy"]["status"] == "planned"
    assert rows["geocompy"]["capabilities"] == []


def test_metadata_error_is_reported_and_does_not_disable_builtin():
    def broken(name):
        raise OSError("Unreadable metadata")
    rows = {r["key"]: r for r in inventory(broken)["adapters"]}
    assert rows["proj"]["status"] == "unavailable"
    assert "Unreadable" in rows["proj"]["error"]
    assert rows["dxf_builtin"]["status"] == "ready"
