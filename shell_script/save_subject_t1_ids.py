import os
from pathlib import Path
import argparse
from glob import glob
from clabtoolkit.bidstools import get_subjects


def save_subject_info(input_folder: str, derivative_folder: str = None) -> list:
    """
    Gets subject IDs and T1-weighted image filenames, and optionally saves them.

    Parameters
    ----------
    input_folder : str
        Root BIDS dataset path.

    derivative_folder : str, optional
        Where to save text files (subject IDs and T1 paths).

    Returns
    -------
    list
        List of subject IDs.
    """
    list_subjects = get_subjects(input_folder)
    
    if not derivative_folder:
        print("Need to define derivative folder to save information")
    else:
        os.makedirs(derivative_folder, exist_ok=True)

        # Save subject IDs
        subj_file_path = os.path.join(derivative_folder, "all_subj_ids.txt")
        with open(subj_file_path, "w") as f_subj:
            for subj in list_subjects:
                f_subj.write(subj + "\n")
        print(f"Subject IDs saved to {subj_file_path}")

        # Save T1-weighted filenames (only inside anat/)
        t1_list = []
        for subj in list_subjects:
            anat_dirs = glob(os.path.join(input_folder, subj, "**", "anat"), recursive=True)
            for anat_dir in anat_dirs:
                t1s = glob(os.path.join(anat_dir, "*T1w.nii*"))
                t1_list.extend(t1s)

        t1_file_path = os.path.join(derivative_folder, "t1_ids.txt")
        with open(t1_file_path, "w") as f_t1:
            for tmp_t1 in t1_list:
                f_t1.write(os.path.basename(tmp_t1).split(".")[0] + "\n")
        print(f"T1w filenames saved to {t1_file_path}")

    return list_subjects


def main():
    parser = argparse.ArgumentParser(description="Save subject ids and save T1w filenames.")
    parser.add_argument("input_dir", help="Path to BIDS directory")
    parser.add_argument("derivative_folder", help="Folder to save subject ids and T1 files")
    args = parser.parse_args()

    # Call your function (make sure get_subject_info is defined/imported)
    subjects = save_subject_info(args.input_dir, args.derivative_folder)

    print(f"Processed {len(subjects)} subjects. Info saved to {args.derivative_folder}")

if __name__ == "__main__":
    main()