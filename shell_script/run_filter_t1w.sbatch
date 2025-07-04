#!/bin/bash
#SBATCH --partition=cpu
#SBATCH --job-name=filter_t1w
#SBATCH --output=/scratch/amiftari/logs/filter_t1w/out_%j.out
#SBATCH --error=/scratch/amiftari/logs/filter_t1w/err_%j.err
#SBATCH --time=1-23:59:00  
#SBATCH --cpus-per-task=1

# Load Python module
module load python

# Activate virtual environment
source /work/PRTNR/CHUV/NEURCLIN/gallali/clm/SOFTWARE/ARBEN/python-venv/clabtoolkit-venv/bin/activate

# Run the Python script with .txt file for T1w to move and the bids root folder
python filter_t1w.py "$1" "$2"
