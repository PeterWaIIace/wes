#!/bin/bash
#SBATCH --job-name=test_job        # nazwa zadania
#SBATCH --output=job_output.txt    # plik wyjściowy (stdout)
#SBATCH --error=job_error.txt      # plik błędów (stderr)
#SBATCH --partition=gpu            # nazwa partycji
#SBATCH --nodes=1                  # liczba węzłów
#SBATCH --ntasks=1                 # liczba zadań
#SBATCH --nodelist=flip          # wybierz GPU
#SBATCH --cpus-per-task=2          # liczba CPU na zadanie
#SBATCH --gres=gpu:1               # liczba i typ gpu
#SBATCH --mem=16G                   # pamięć RAM
#SBATCH --time=04:00:00            # maksymalny czas wykonania

# --- Komendy do wykonania ---
module load uv
export PYTHONWARNINGS="ignore"
export OPENCV_VIDEOIO_PRIORITY_MSMF=0
export QT_QPA_PLATFORM=offscreen
cd swarm-gym
export UV_CACHE_DIR=/net/obelix/homes/pwalas1/.cache/uv
uv run experiments/fly_to_point.py
