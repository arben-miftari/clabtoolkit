#!/bin/bash
#SBATCH --partition=cpu
#SBATCH --job-name=organize_dicom
#SBATCH --output=/scratch/amiftari/logs/out/organize_dicom_%j.out
#SBATCH --error=/scratch/amiftari/logs/err/organize_dicom_%j.err
#SBATCH --time=1-23:59:00  
#SBATCH --mem=4G
#SBATCH --cpus-per-task=1

# Load Python module (adjust as needed for your cluster)
module load python

# Activate your virtual environment (update the path as needed)
source /work/PRTNR/CHUV/NEURCLIN/gallali/clm/SOFTWARE/ARBEN/python-venv/clabtoolkit-venv/bin/activate

# Run the Python script with input and output directories as arguments
python python_scripts/organize_dicom_folder.py "$1" "$2"