import time
import torch
import numpy as np
import multiprocessing
import pandas as pd

from layernorm_hidet import benchmark_hidet
from layernorm_tvm import benchmark_tvm, benchmark_tvm_single
from layernorm_triton import benchmark_triton, benchmark_triton_single

benchmark = "layernorm"


def benchmark_torch(a_np, num_threads=None):
    """Benchmark PyTorch layernorm performance."""
    a = torch.tensor(a_np, dtype=torch.float32)

    if num_threads is None:
        num_threads = multiprocessing.cpu_count()
    torch.set_num_threads(num_threads)

    times = [time.perf_counter() - time.perf_counter() for _ in range(10)]
    for i in range(10):
        start = time.perf_counter()
        result = torch.nn.LayerNorm(a.shape[1])(a)
        end = time.perf_counter()
        times[i] = end - start

    with torch.no_grad():
        result_np = result.numpy()

    return np.mean(times), result_np


def run_benchmark(method_name, method_func, shape, a_np, torch_result):
    """Run a single benchmark and validate results."""
    exec_time, result = method_func(a_np)

    assert np.allclose(
        result, torch_result, atol=1e-3, rtol=1e-3
    ), f"{method_name} result mismatch!"

    return {
        "Benchmark": benchmark,
        "Shape": shape,
        "Method": method_name,
        "Time(ms)": exec_time,
        # TODO: Implement tuning and capture tuning time
        "TuningTime(ms)": 0.0,
    }


def main():
    """Main function to benchmark different matrix multiplication methods."""
    shape = (512, 512)
    a_np = np.random.rand(shape[0], shape[1]).astype(np.float32)
    records = []

    # Torch benchmark as baseline
    print(f"Running torch benchmark...")
    torch_time, torch_result = benchmark_torch(a_np)
    records.append(
        {
            "Benchmark": benchmark,
            "Shape": shape,
            "Method": "torch",
            "Time(ms)": torch_time,
            "TuningTime(ms)": 0.0,
        }
    )
    print(f"Running torch_single benchmark...")
    torch_time_single, _ = benchmark_torch(a_np, 1)
    records.append(
        {
            "Benchmark": benchmark,
            "Shape": shape,
            "Method": "torch_single",
            "Time(ms)": torch_time_single,
            "TuningTime(ms)": 0.0,
        }
    )

    # Other methods
    methods = [
        ("hidet", benchmark_hidet),
        ("tvm", benchmark_tvm),
        ("triton", benchmark_triton),
        ("tvm_single", benchmark_tvm_single),
        ("triton_single", benchmark_triton_single),
    ]

    for method, method_func in methods:
        print(f"Running {method} benchmark...")
        records.append(run_benchmark(method, method_func, shape, a_np, torch_result))

    df = pd.DataFrame(records)
    df.sort_values(by=["Benchmark", "Shape"], inplace=True)
    print(df)
    df.to_csv("./performance_report.csv", index=False)


if __name__ == "__main__":
    main()
