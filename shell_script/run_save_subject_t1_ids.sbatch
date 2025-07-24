#!/bin/bash
#SBATCH --partition=cpu
#SBATCH --job-name=save_subject_info
#SBATCH --output=/scratch/amiftari/logs/save_subject_info/out_%j.out
#SBATCH --error=/scratch/amiftari/logs/save_subject_info/err_%j.err
#SBATCH --time=1-23:59:00  
#SBATCH --cpus-per-task=1

# Load Python module
module load python

# Activate virtual environment
source /work/PRTNR/CHUV/NEURCLIN/gallali/clm/SOFTWARE/ARBEN/python-venv/clabtoolkit-venv/bin/activate

# Run the Python script with input folder and derivative folder as input to save subject and T1 ids
python save_subject_t1_ids.py "$1" "$2"
