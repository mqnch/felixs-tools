# First WATcloud session: checklist

One session that covers the slice [006](slices/006-slurm-training-scaffold.md) smoke run, the vLLM pin, and the stock Qwen3.5 baselines that slice [005](slices/005-eval-harness-and-baselines.md)'s gate is waiting on. Run the steps in order. Each one ends with what to record.

Placeholders: `<you>` is your WATcloud user and `<repo>` the checkout path on the cluster (your home is fine: code, data and the workspace venv are small).

Per WATcloud's storage rules, `/home` is SSD Ceph for small files only, and large files go on the HDD NFS mounts at `/mnt/wato-drive*`. So everything big lives under one directory there:

```bash
ls -d /mnt/wato-drive*                       # pick one you can write to
export BIG=/mnt/wato-drive<N>/<you>          # put both exports in ~/.bashrc
export UV_CACHE_DIR=$BIG/uv-cache            # torch/vLLM wheels are several GB
mkdir -p $BIG/hf $BIG/uv-cache
```

`<shared-hf>` below is `$BIG/hf` (model weights, ~15 GB for the three models) and the vLLM env is `$BIG/vllm-env` (~10 GB). The job stages weights from `$BIG/hf` onto the node-local `/tmp` (`tmpdisk` GRES, 40 GB requested), so the slow NFS is read once per job, not per request.

## 0. Access

- Be on the UW network or the UW VPN, then `ssh <you>@wato-login1.ext.watonomous.ca` (or `wato-login2`).
- `sacctmgr show user $(whoami)` must list a default account. If it's empty, every `srun`/`sbatch` fails with "Invalid account": your profile needs a *registered* affiliation (see WATcloud's SLURM troubleshooting).
- Login nodes are only for submitting jobs. Anything heavy below runs inside an `srun` allocation.
- Note WATcloud's defaults when you leave a flag out: 1 CPU, 512 MB RAM, 100 MB `/tmp`, 30 minutes. Every `srun` below sets its own values.

## 1. Get the code and data onto the cluster

```bash
# from the laptop, repo root
rsync -az --exclude .venv --exclude corpora --exclude logs ./ <you>@<login-node>:<repo>/
```

`data/full/` (149 MB) is gitignored, so it only arrives by rsync, not by `git clone`. The baselines need only `data/full/*/test.{db,jsonl}` and `manifest.json` (14 MB). Slice 007 needs the rest. `corpora/` (the raw LogHub ingest) is not needed on the cluster.

## 2. Environments

```bash
# a CPU allocation, not the login node: the vLLM install pulls several GB
srun --cpus-per-task 8 --mem 16G --gres tmpdisk:20480 --time 01:00:00 --pty bash
  cd <repo>
  uv sync --all-packages --extra train             # workspace env: planner-rl, eval, huggingface_hub

  uv venv $BIG/vllm-env --python 3.12              # vLLM in its own env (decision 0021)
  uv pip install --python $BIG/vllm-env vllm       # newest release first; see step 5
  $BIG/vllm-env/bin/vllm --version                 # record it
  exit
```

No CUDA toolkit is needed: the vLLM/torch wheels bundle their CUDA runtime, and WATcloud deliberately doesn't install CUDA. What has to match is the node's **driver**, which step 3 records.

## 3. Node check

```bash
srun --gres gpu:rtx_3090:1 --cpus-per-task 4 --mem 16G --time 00:15:00 \
    uv run planner-rl slurm env-check
srun --gres gpu:rtx_3090:1 --cpus-per-task 4 --mem 16G --time 00:15:00 \
    $BIG/vllm-env/bin/python -c "import vllm, torch; print(vllm.__version__, torch.__version__, torch.version.cuda, torch.cuda.is_available())"
```

`env-check` reports the workspace env, which has no vLLM, so "vllm unavailable" there is expected. The second command reports the vLLM env. Paste both outputs into the slice 006 doc, including the `nvidia-smi` driver version.

If `torch.cuda.is_available()` is False or there's a driver error, the wheel's CUDA is newer than the node's driver. Reinstall torch/vLLM built for an older CUDA (the vLLM install docs list per-CUDA wheel indexes); don't try to install a driver.

`--gres gpu:rtx_3090:1` lands on either 3090 node (`trpro-slurm1` or `trpro-slurm2`), which queues faster than pinning `--nodelist`. A whole GPU (`gpu`), not a `shard`, is right for vLLM: it claims `--gpu-memory-utilization` (90% by default) of the card no matter what `shard` asked for, so it would crowd out anyone sharing it.

## 4. Smoke run (checkpoint, requeue, resume)

```bash
uv run planner-rl slurm render --name smoke --run-id smoke-1 --out jobs/smoke.sbatch \
    --gpus 0 --time 00:10:00 -- uv run planner-rl slurm smoke --run-id smoke-1 --steps 900 --step-seconds 1
uv run planner-rl slurm render --name smoke --run-id smoke-1 --out jobs/smoke.sbatch \
    --gpus 0 --time 00:10:00 --submit -- uv run planner-rl slurm smoke --run-id smoke-1 --steps 900 --step-seconds 1
```

Pass when:
- `runs/smoke-1/events.jsonl` has at least one `stop` then `resume`;
- `SLURM_RESTART_COUNT` is above 0 in `logs/slurm/*-smoke.out`;
- the last event is `done` with `acc == 405450`.

Record pass or fail in slice 006 "Friction observed".

## 5. Pin vLLM: load Qwen3.5 on a 3090

```bash
# downloads ~15 GB: run it in a CPU allocation too, not on the login node
srun --cpus-per-task 4 --mem 8G --time 01:00:00 \
    bash -c 'for m in 0.8B 2B 4B; do uv run planner-rl slurm prefetch Qwen/Qwen3.5-$m --cache $BIG/hf; done'

srun --gres gpu:rtx_3090:1,tmpdisk:20480 --cpus-per-task 8 --mem 48G --time 00:45:00 --pty bash
  HF_HOME=$BIG/hf HF_HUB_OFFLINE=1 $BIG/vllm-env/bin/vllm serve Qwen/Qwen3.5-0.8B \
      --port 8000 --host 127.0.0.1 --max-model-len 16384 --dtype bfloat16 &
  curl -s localhost:8000/v1/chat/completions -H 'Content-Type: application/json' -d '{"model":"Qwen/Qwen3.5-0.8B",
    "messages":[{"role":"user","content":"Reply with {}"}],"chat_template_kwargs":{"enable_thinking":false}}'
```

If it fails to load, try these in order, stopping at the first that works:
1. A newer vLLM: `uv pip install --python $BIG/vllm-env -U vllm`. Qwen3.5 was reported unsupported on 0.16.0 (decision 0006).
2. `--enforce-eager`, which skips CUDA-graph capture.
3. If the error is about vision or multimodal profiling, `--limit-mm-per-prompt '{"image":0,"video":0}'`.
4. If it runs out of memory, `--max-model-len 8192` or `--gpu-memory-utilization 0.85`.

Every flag that works goes into step 6 as `--vllm-arg`.

Also check the reply has no `<think>` block. If it does, the server ignored `chat_template_kwargs`. The scorer strips think blocks, but the baselines must run with thinking off.

Record the pin in two places:
- the slice 006 doc, under "Decisions made here", as a decision record with the working version, flags and `env-check` output (this is the record slice 008 is blocked on);
- the planner-rl README Status section.

If no version works, fall back to Unsloth rollouts per decision 0006. The eval harness only needs an OpenAI-compatible server, so the baselines could also run on another server (e.g. SGLang) via `--base-url`.

## 6. Stock baselines (0.8B, 2B, 4B)

```bash
uv run planner-rl slurm eval-baselines --workdir <repo> --hf-cache $BIG/hf \
    --vllm-bin $BIG/vllm-env/bin/vllm [--vllm-arg=--enforce-eager ...]    # writes jobs/eval-baselines.{sbatch,driver.sh}
cat jobs/eval-baselines.driver.sh                                          # read it once
uv run planner-rl slurm eval-baselines ... --submit                        # same options plus --submit
```

The job serves each model in turn on one GPU and writes `results/stock-qwen3.5-{0.8b,2b,4b}.json`.

It is safe to requeue or resubmit:
- finished models are skipped;
- an interrupted model resumes from `results/*.partial.jsonl`.

Watch `logs/slurm/<job>-eval-baselines.out` and `logs/slurm/vllm-*.log`. If a model fails, fix the flags and resubmit; nothing is lost.

To be told when it ends: `watcloud subscription <job_id> <email>` (or `--discord <webhook>`) from a login node. Check `squeue -u $(whoami)` and `sacct --format=JobID,JobName,State,ExitCode` for state.

## 7. Bring results back and compare

```bash
# from the laptop
rsync -az <you>@<login-node>:<repo>/results/stock-qwen3.5-*.json results/
uv run planner-rl compare results/stock-qwen3.5-*.json results/stock-qwen3.5-9b.json results/frontier-sonnet-5.5-s100.json
```

`compare` scores every file on the 300 examples they all share (the Sonnet sample). For the 2B over the full 1,480 examples, run `compare results/stock-qwen3.5-2b.json results/stock-qwen3.5-9b.json`.

Answer score when format is valid (not printed by `compare`):

```bash
uv run python -c "import json,statistics as s; r=json.load(open('results/stock-qwen3.5-2b.json'));
v=[x['answer'] for x in r['records'] if x['format_valid']]; print(len(v), round(s.fmean(v),3))"
```

## 8. Read the gate (slice 005)

The gate threshold is 0.85.

| Stock 2B | Meaning | Next |
|---|---|---|
| answer < 0.85 **and** answer-when-format-valid < 0.85 | Real headroom beyond format | Slice 007 (SFT) |
| answer < 0.85 but answer-when-format-valid ≥ 0.85 | Same pattern as the 9B: the gap is mostly format, and SFT may close it and leave RL little to show | Harden the questions (e.g. stop echoing template text) or the DSL before training. This is your call; record it as a decision |
| answer ≥ 0.85 | Task too easy | Reopen slice 002 (harden the DSL) before any GPU training |

Also check that the 2B scores below the 9B. If not, decision 0019's upper-bound argument fails; record that in 0019.

Write the numbers into slice 005 "Results" and the slices index.
