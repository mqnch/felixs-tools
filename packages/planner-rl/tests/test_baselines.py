import subprocess

from typer.testing import CliRunner

from planner_rl.cli import app
from planner_rl.train.baselines import STOCK_MODELS, BaselineSpec, driver_script, results_path


def test_driver_serves_and_evaluates_each_stock_model_in_turn():
    text = driver_script(BaselineSpec())
    for model in STOCK_MODELS:
        assert f"serve {model} --served-model-name {model}" in text
        assert f"--model {model}" in text
    positions = [text.index(f"# --- {m}") for m in STOCK_MODELS]
    assert positions == sorted(positions)
    assert text.count("stop_vllm\nfi") == len(STOCK_MODELS)


def test_driver_waits_for_the_server_with_a_timeout():
    text = driver_script(BaselineSpec(port=8123, ready_timeout_s=600))
    assert 'curl -sf "http://127.0.0.1:${PORT}/v1/models"' in text
    assert "PORT=8123" in text and "SECONDS + 600" in text
    assert "vLLM exited before it was ready" in text


def test_driver_skips_models_whose_results_exist_and_resumes_the_rest():
    text = driver_script(BaselineSpec())
    assert results_path(BaselineSpec(), "Qwen/Qwen3.5-2B") == "results/stock-qwen3.5-2b.json"
    assert "if [ -f results/stock-qwen3.5-2b.json ]; then" in text
    # Requeue path: the pre-timeout signal stops vLLM and requeues the job.
    assert "trap on_usr1 USR1" in text and 'scontrol requeue "$SLURM_JOB_ID"' in text


def test_driver_runs_eval_on_the_full_test_split_of_all_three_corpora():
    text = driver_script(BaselineSpec())
    assert (
        "uv run planner-rl eval --data data/full/hadoop-50k --data data/full/bgl-20k "
        "--data data/full/openstack-20k --split test --model Qwen/Qwen3.5-2B "
        '--base-url "http://127.0.0.1:${PORT}/v1" --concurrency 16 --out results/stock-qwen3.5-2b.json'
    ) in text
    assert "--per-corpus" not in text and "--thinking" not in text


def test_driver_passes_extra_vllm_flags_and_is_valid_bash(tmp_path):
    text = driver_script(BaselineSpec(vllm_args=("--enforce-eager",)))
    assert text.count("--enforce-eager") == len(STOCK_MODELS)
    script = tmp_path / "d.sh"
    script.write_text(text)
    assert subprocess.run(["bash", "-n", str(script)]).returncode == 0


def test_cli_renders_the_sbatch_and_driver_without_submitting(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    out = tmp_path / "jobs" / "b.sbatch"
    result = CliRunner().invoke(app, [
        "slurm", "eval-baselines", "--out", str(out), "--workdir", str(tmp_path),
        "--vllm-bin", "~/vllm-env/bin/vllm", "--model", "Qwen/Qwen3.5-2B",
    ])
    assert result.exit_code == 0, result.output
    sbatch, driver = out.read_text(), out.with_suffix(".driver.sh").read_text()
    assert "#SBATCH --gres=gpu:rtx_3090:1,tmpdisk:40960" in sbatch
    assert "--nodelist" not in sbatch  # the rtx_3090 GRES already picks a 3090 node
    assert sbatch.splitlines()[-1] == f"srun bash {out.with_suffix('.driver.sh').resolve()}"
    assert f"{tmp_path}/home/vllm-env/bin/vllm serve Qwen/Qwen3.5-2B" in driver
    assert "Qwen3.5-0.8B" not in driver
    assert "submitted" not in result.output
