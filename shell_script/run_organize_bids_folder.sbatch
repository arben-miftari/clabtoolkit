#!/bin/bash
#SBATCH --partition=cpu
#SBATCH --job-name=organize_dicom
#SBATCH --output=/scratch/amiftari/logs/organize_dicom_%j/out.out
#SBATCH --error=/scratch/amiftari/logs/organize_dicom_%j/err.err
#SBATCH --time=1-23:59:00  
#SBATCH --cpus-per-task=1

# Load Python module
module load python

# Activate virtual environment
source /work/PRTNR/CHUV/NEURCLIN/gallali/clm/SOFTWARE/ARBEN/python-venv/clabtoolkit-venv/bin/activate

# Run the Python script with input, output directories, and list of subject ids as arguments
python organize_bids_folder.py "$1" "$2" "$3"