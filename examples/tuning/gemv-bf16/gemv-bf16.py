import torch

import triton
import triton.language as tl

BLOCK_SIZE_M = 2
BLOCK_SIZE_N = 64
USE_GPU = False
"""
Kernel for computing Y = A @ X, where A is a dense matrix with
M rows and N columns.
- Input X has shape (N,)
- A has shape (M, N)
- Output has shape (M,)
"""

@triton.autotune(
    configs=[
        triton.Config({'BLOCK_SIZE_M': 16, 'BLOCK_SIZE_N': 64}, num_threads=1),
    ],
    key=["M", "N"],
)
@triton.jit
def gemv_kernel_T1(
    Y,
    A,
    X,
    M,
    N,
    stride_am,
    BLOCK_SIZE_M: tl.constexpr,
    BLOCK_SIZE_N: tl.constexpr,
):
    start_m = tl.program_id(0)
    rm = start_m * BLOCK_SIZE_M + tl.arange(0, BLOCK_SIZE_M)
    rn = tl.arange(0, BLOCK_SIZE_N)

    A = A + (rm[:, None] * stride_am + rn[None, :])
    X = X + rn

    acc = tl.zeros((BLOCK_SIZE_M, ), dtype=tl.float32)
    for n in range(N, 0, -BLOCK_SIZE_N):
        a = tl.load(A)
        x = tl.load(X)
        acc += tl.sum(a * x[None, :], axis=1)
        A += BLOCK_SIZE_N
        X += BLOCK_SIZE_N

    y = acc.to(tl.bfloat16)
    Y = Y + rm
    tl.store(Y, y)


@triton.autotune(
    configs=[
        triton.Config({'BLOCK_SIZE_M': 2, 'BLOCK_SIZE_N': 64}, num_threads=8),
    ],
    key=["M", "N"],
)
@triton.jit
def gemv_kernel_T8(
    Y,
    A,
    X,
    M,
    N,
    stride_am,
    BLOCK_SIZE_M: tl.constexpr,
    BLOCK_SIZE_N: tl.constexpr,
):
    start_m = tl.program_id(0)
    rm = start_m * BLOCK_SIZE_M + tl.arange(0, BLOCK_SIZE_M)
    rn = tl.arange(0, BLOCK_SIZE_N)

    A = A + (rm[:, None] * stride_am + rn[None, :])
    X = X + rn

    acc = tl.zeros((BLOCK_SIZE_M, ), dtype=tl.float32)
    for n in range(N, 0, -BLOCK_SIZE_N):
        a = tl.load(A)
        x = tl.load(X)
        acc += tl.sum(a * x[None, :], axis=1)
        A += BLOCK_SIZE_N
        X += BLOCK_SIZE_N

    y = acc.to(tl.bfloat16)
    Y = Y + rm
    tl.store(Y, y)


@triton.autotune(
    configs=[
        triton.Config({'BLOCK_SIZE_M': 1, 'BLOCK_SIZE_N': 64}, num_threads=16),
    ],
    key=["M", "N"],
)
@triton.jit
def gemv_kernel_T16(
    Y,
    A,
    X,
    M,
    N,
    stride_am,
    BLOCK_SIZE_M: tl.constexpr,
    BLOCK_SIZE_N: tl.constexpr,
):
    start_m = tl.program_id(0)
    rm = start_m * BLOCK_SIZE_M + tl.arange(0, BLOCK_SIZE_M)
    rn = tl.arange(0, BLOCK_SIZE_N)

    A = A + (rm[:, None] * stride_am + rn[None, :])
    X = X + rn

    acc = tl.zeros((BLOCK_SIZE_M, ), dtype=tl.float32)
    for n in range(N, 0, -BLOCK_SIZE_N):
        a = tl.load(A)
        x = tl.load(X)
        acc += tl.sum(a * x[None, :], axis=1)
        A += BLOCK_SIZE_N
        X += BLOCK_SIZE_N

    y = acc.to(tl.bfloat16)
    Y = Y + rm
    tl.store(Y, y)


def gemv(
    weight: torch.Tensor,
    x: torch.Tensor,
    output: torch.Tensor,
    num_threads=16,
):
    assert weight.shape[1] == x.shape[0], "Incompatible dimensions"
    assert weight.is_contiguous() and x.is_contiguous(), "Input and weight must be contiguous"
    assert x.dtype == weight.dtype, f"Input and weight must have the same dtype, got {x.dtype} and {weight.dtype}"

    M, N = weight.shape

    # TODO: Currently masked load is not supported yet.
    assert M % BLOCK_SIZE_M == 0 and N % BLOCK_SIZE_N == 0, "Masking currently not supported, Matrix dimensions must be multiples of block size"

    if output is None:
        # Allocates output.
        output = torch.empty((M, ), device=x.device, dtype=x.dtype)
    else:
        assert output.shape == (M, ) and output.dtype == x.dtype, "Incompatible output"

    # 1D launch kernel where each block gets its own program.
    grid = lambda META: (triton.cdiv(M, META["BLOCK_SIZE_M"]), )

    if num_threads == 1:
        gemv_kernel_T1[grid](output, weight, x, M, N, weight.stride(0))
    elif num_threads == 8:
        gemv_kernel_T8[grid](output, weight, x, M, N, weight.stride(0))
    elif num_threads == 16:
        gemv_kernel_T16[grid](output, weight, x, M, N, weight.stride(0))

    return output


torch.manual_seed(0)

triton.runtime.driver.set_active_to_cpu()

# weight = torch.randn((8, 64), device='cpu', dtype=torch.bfloat16)
# x = torch.randn((64), device='cpu', dtype=torch.bfloat16)
# triton_output = gemv(weight, x, None)
# compiled_matmul = torch.compile(torch.matmul)
# # Note: torch.matmul for bf16 on Arm Linux will trigger error on old torch versions:
# # RuntimeError: could not create a primitive descriptor for a matmul primitive
# # So we recommend using torch 2.4.0 onwards.
# torch_output = torch.matmul(weight, x)
# #print(f"triton_cpu_output_with_{weight.dtype}_inputs={triton_output}")
# #print(f"torch_cpu_output_with_{weight.dtype}_inputs={torch_output}")
# rtol = 0
# if torch.allclose(triton_output, torch_output, atol=1e-4, rtol=rtol):
#     print("✅ TritonCPU and TorchCPU match")
# else:
#     print("❌ TritonCPU and TorchCPU differ, the maximum difference is "
#           f'{torch.max(torch.abs(triton_output - torch_output))}')

LINE_VALS = [
    'triton-cpu-T1', 'triton-cpu-T8', 'triton-cpu-T16', 'torch-cpu-T1', 'torch-cpu-T16',
]
LINE_NAMES = LINE_VALS
LINE_STYLES = [('blue', '--'), ('blue', '-'), ('blue', ':'), ('green', '--'), ('green', ':'),]


# %%
# Seems like we're good to go!

# %%
# Benchmark
# ---------


@triton.testing.perf_report(
    triton.testing.Benchmark(
        x_names=["M", "N"],  # Argument names to use as an x-axis for the plot
        x_vals=[(16 * i, 64) for i in range(1, 9, 1)],  # Different possible values for `x_name`
        line_arg='provider',  # Argument name whose value corresponds to a different line in the plot.
        line_vals=LINE_VALS,  # Possible values for `line_arg`.
        line_names=LINE_NAMES,  # Label name for the lines.
        styles=LINE_STYLES,  # Line styles.
        ylabel='MFLOPS',  # Label name for the y-axis.
        plot_name=
        # Name for the plot. Used also as a file name for saving the plot.
        f'gemv-performance-bf16',
        args={},  # Values for function arguments not in `x_names` and `y_name`.
    ))
def benchmark(M, N, provider):

    device = 'cpu' if 'cpu' in provider else 'cuda'
    weight = torch.randn((M, N), device=device, dtype=torch.bfloat16)
    x = torch.randn((N), device=device, dtype=torch.bfloat16)

    output = torch.empty((M), device=x.device, dtype=x.dtype)
    triton.runtime.driver.set_active_to_cpu()


    quantiles = [0.5, 0.2, 0.8]
    if 'torch-cpu-T1' in provider:
        torch.set_num_threads(1)
        ms, min_ms, max_ms = triton.testing.do_bench(lambda: torch.matmul(weight, x, out=output), quantiles=quantiles)
    elif 'torch-cpu-T16' in provider:
        torch.set_num_threads(16)
        ms, min_ms, max_ms = triton.testing.do_bench(lambda: torch.matmul(weight, x, out=output), quantiles=quantiles)
    elif 'triton-cpu-T1' in provider:
        ms, min_ms, max_ms = triton.testing.do_bench(lambda: gemv(weight, x, output, num_threads=1),
                                                     quantiles=quantiles)
    elif 'triton-cpu-T8' in provider:
        ms, min_ms, max_ms = triton.testing.do_bench(lambda: gemv(weight, x, output, num_threads=8),
                                                     quantiles=quantiles)
    elif 'triton-cpu-T16' in provider:
        ms, min_ms, max_ms = triton.testing.do_bench(lambda: gemv(weight, x, output, num_threads=16),
                                                     quantiles=quantiles)

    perf = lambda ms: 2 * M * N * 1e-6 / (ms * 1e-3)
    return perf(ms), perf(max_ms), perf(min_ms)


# %%
# We can now run the decorated function above. Pass `print_data=True` to see the performance number, `show_plots=True` to plot them, and/or
# `save_path='/path/to/results/' to save them to disk along with raw CSV data:
benchmark.run(print_data=True, show_plots=True, save_path=".")

