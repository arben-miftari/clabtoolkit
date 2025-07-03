import clabtoolkit.qcqatools as cltqcqa

import glob
import os
import argparse

def main():
    parser = argparse.ArgumentParser(description="Organize DICOM folder.")
    parser.add_argument("input_dir", help="Path to BIDS directory")
    parser.add_argument("output_dir", help="Path where to save images for QC")
    args = parser.parse_args()

    path_to_anat_per_subject_and_session = glob.glob(os.path.join(args.input_dir, "sub-*", "ses-*", "anat"))
    os.makedirs(args.output_dir, exist_ok=True)

    for tmp_path in path_to_anat_per_subject_and_session:
        parts = tmp_path.split(os.sep)
        sub_id = next(p for p in parts if p.startswith("sub-"))
        ses_id = next(p for p in parts if p.startswith("ses-"))
        output_folder = os.path.join(args.output_dir, sub_id, ses_id)
        os.makedirs(output_folder, exist_ok=True)
        _ = cltqcqa.recursively_generate_slices(tmp_path, and_filter="T1w", or_filter="", output_folder=output_folder)

        cltqcqa.create_png_webpage_from_generated_slices(
            root_directory=output_folder
        )

if __name__ == "__main__":
    main()