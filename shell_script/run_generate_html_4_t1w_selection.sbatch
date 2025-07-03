#!/bin/bash
#SBATCH --partition=cpu
#SBATCH --job-name=generate_html
#SBATCH --output=/scratch/amiftari/logs/generate_html/out_%j.out
#SBATCH --error=/scratch/amiftari/logs/generate_html/err_%j.err
#SBATCH --time=1-23:59:00  
#SBATCH --cpus-per-task=1

# Load Python module
module load python

# Activate virtual environment
source /work/PRTNR/CHUV/NEURCLIN/gallali/clm/SOFTWARE/ARBEN/python-venv/clabtoolkit-venv/bin/activate

# Run the Python script with input and output directories
python generate_html_4_t1w_selection.py "$1" "$2" 