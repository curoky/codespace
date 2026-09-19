from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_PLATFORM = _ROOT / "platform"
_FRAMEWORKS = _PLATFORM / "container/frameworks"
_SERVICES = _PLATFORM / "container/services"


def _dockerfiles() -> list[Path]:
    return sorted(
        path
        for path in _PLATFORM.rglob("*")
        if path.name == "Dockerfile" or path.suffix == ".Dockerfile"
    )


def test_internal_images_are_not_build_arguments() -> None:
    for path in _dockerfiles():
        dockerfile = path.read_text()
        assert "ARG S6_BASE_IMAGE" not in dockerfile
        assert "ARG BASE_IMAGE=ghcr.io/curoky/codespace:" not in dockerfile

    wsl_build = (_PLATFORM / "wsl/build.sh").read_text()
    wsl_workflow = (_ROOT / ".github/workflows/publish-wsl.yaml").read_text()
    assert (
        "FROM ghcr.io/curoky/codespace:workspace-ubuntu26.04"
        in (_PLATFORM / "wsl/Dockerfile").read_text()
    )
    assert "--build-arg" not in wsl_build
    assert "build-args:" not in wsl_workflow


@pytest.mark.parametrize("framework", ["pytorch", "sglang", "vllm"])
def test_framework_images_copy_managed_python_to_runtime(framework: str) -> None:
    for path in (_FRAMEWORKS / framework).glob("*.Dockerfile"):
        dockerfile = path.read_text()
        assert "UV_PYTHON_INSTALL_DIR=/opt/codespace/frameworks/python" in dockerfile
        assert 'venv "${FRAMEWORK_VENV}" --python 3.12 --managed-python' in dockerfile
        assert (
            "COPY --from=builder /opt/codespace/frameworks/python /opt/codespace/frameworks/python"
        ) in dockerfile
        assert 'RUN python -c "import ' in dockerfile


def test_sglang_framework_images_preserve_runtime_contract() -> None:
    for path in (_FRAMEWORKS / "sglang").glob("*.Dockerfile"):
        dockerfile = path.read_text()
        assert (
            "COPY --from=builder /opt/codespace/frameworks/src/sglang "
            "/opt/codespace/frameworks/src/sglang"
        ) in dockerfile
        assert "ca-certificates g++ libgomp1" in dockerfile
        assert '"sglang-kernel==0.4.6.post1"' in dockerfile
        assert '"sgl-deep-gemm==0.1.5.post3"' in dockerfile
        assert "nvcc -std=c++20 -arch=sm_90a" in dockerfile


def test_cuda12_sglang_images_rewrite_cuda13_dependencies() -> None:
    paths = [
        _FRAMEWORKS / "sglang/sglang0.5.18-cu12.9.1-cudnn9-gcc12-py3.12.Dockerfile",
        _SERVICES / "sglang/Dockerfile",
    ]
    for path in paths:
        dockerfile = path.read_text()
        assert "s/cuda-python>=13\\.0/cuda-python>=12,<13/" in dockerfile
        assert "s/flashinfer_python\\[cu13\\]/flashinfer_python[cu12]/" in dockerfile
        assert "s/nvidia-cutlass-dsl\\[cu13\\]/nvidia-cutlass-dsl/" in dockerfile


def test_vllm_service_uses_exact_commit_wheel() -> None:
    dockerfile = (_SERVICES / "vllm/Dockerfile").read_text()
    assert '"vllm==0.28.1rc1.dev132+ge126687a9"' in dockerfile
    assert "assert vllm.__version__ == '0.28.1rc1.dev132+ge126687a9'" in dockerfile
