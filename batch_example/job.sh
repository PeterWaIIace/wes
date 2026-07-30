#!/bin/bash
#SBATCH --output=job_output.txt    # plik wyjściowy (stdout)
#SBATCH --error=job_error.txt      # plik błędów (stderr)
#SBATCH --partition=gpu            # nazwa partycji
#SBATCH --nodes=1                  # liczba węzłów
#SBATCH --ntasks=1                 # liczba zadań
#SBATCH --nodelist=h86             # wybierz GPU
#SBATCH --cpus-per-task=4          # liczba CPU na zadanie
#SBATCH --gres=gpu:1               # liczba i typ gpu
#SBATCH --mem=16G                  # pamięć RAM
#SBATCH --time=02:00:00            # maksymalny czas wykonania

# --- Komendy do wykonania ---
echo "=== Job started: $(date) ==="
echo "Host: $(hostname)"
echo "GPU: $(nvidia-smi -L 2>/dev/null || echo 'none')"

module load uv
which uv || echo "uv not found after module load"
echo "PATH=$PATH"
cd swarm-gym
uv sync --active
set -x
uv run experiments/fly_to_point.py --steps 1000000 --lr 0.01
