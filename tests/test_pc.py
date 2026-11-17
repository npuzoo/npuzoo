"""npuzoo doctor --pc: the x86 machine that converts models."""
from npuzoo.pc import diagnose_pc, largest_convertible_b, conversion_peak_gb, _pins

BASE = {"machine": "x86_64", "system": "Linux", "python": "3.10.12", "mem_gb": 31.2,
        "disk_free_gb": 120.0, "gpu": None, "toolkit": "1.3.1",
        "requires": ["torch==2.6.0", "transformers==5.8.0", "numpy<=1.26.4,>=1.23.1"],
        "installed": {"torch": "2.6.0+cpu", "transformers": "5.8.0", "numpy": "1.26.4"},
        "pkg_resources": True, "pyarrow_pyextensiontype": None}


def by(checks):
    return {c["name"]: c for c in checks}


def test_healthy_pc():
    c = by(diagnose_pc(dict(BASE)))
    assert c["cpu"]["status"] == "OK" and c["rkllm-toolkit"]["status"] == "OK"
    assert c["dependencies"]["status"] == "OK"      # torch 2.6.0+cpu satisfies ==2.6.0
    assert "4B models" in c["memory"]["detail"]


def test_arm_board_cannot_convert():
    c = by(diagnose_pc(dict(BASE, machine="aarch64")))
    assert c["cpu"]["status"] == "FAIL" and "x86_64 only" in c["cpu"]["detail"]


def test_missing_pkg_resources():
    c = by(diagnose_pc(dict(BASE, pkg_resources=False)))
    assert c["setuptools"]["status"] == "FAIL" and "setuptools<80" in c["setuptools"]["fix"]


def test_old_datasets_with_new_pyarrow():
    info = dict(BASE, toolkit="1.1.4", python="3.10.12", pyarrow_pyextensiontype=False,
                installed=dict(BASE["installed"], datasets="2.14.6"))
    c = by(diagnose_pc(info))
    assert c["pyarrow"]["status"] == "FAIL" and "pyarrow<15" in c["pyarrow"]["fix"]


def test_python_without_a_wheel():
    c = by(diagnose_pc(dict(BASE, python="3.13.1")))
    assert c["python"]["status"] == "WARN" and "3.10, 3.11, 3.12" in c["python"]["detail"]


def test_dependency_drift():
    info = dict(BASE, installed=dict(BASE["installed"], transformers="5.20.2"))
    c = by(diagnose_pc(info))
    assert c["dependencies"]["status"] == "WARN" and "transformers 5.20.2 (wants 5.8.0)" in c["dependencies"]["detail"]


def test_no_toolkit():
    c = by(diagnose_pc(dict(BASE, toolkit=None, requires=[], installed={})))
    assert c["rkllm-toolkit"]["status"] == "WARN" and "dependencies" not in c


def test_small_machine_and_disk():
    c = by(diagnose_pc(dict(BASE, mem_gb=8.0, disk_free_gb=9.0)))
    assert c["memory"]["status"] == "WARN" and c["disk"]["status"] == "WARN"


def test_memory_model_matches_measurements():
    assert abs(conversion_peak_gb(0.6) - 6.9) < 0.5
    assert abs(conversion_peak_gb(1.5) - 12.7) < 0.5
    assert 1.9 < largest_convertible_b(16) < 2.1


def test_pins():
    assert _pins(["torch==2.6.0", "numpy<=1.26.4,>=1.23.1", "tqdm>=4.64.0; python_version>'3'"]) == {"torch": "2.6.0"}
