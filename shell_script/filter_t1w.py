import os
import shutil
import json
import argparse

def process_exclusions(txt_file_path, bids_root):
    """
    Processes a list of exclusions from a text file. Moves corresponding T1w files to extra_data
    and appends the justification to the associated JSON metadata.

    Parameters:
        txt_file_path (str): Path to the tab-separated text file with PNG path and justification.
        bids_root (str): Root directory of the BIDS dataset.
    """
    with open(txt_file_path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or '\t' not in line:
                continue

            png_path, justification = line.split('\t')
            png_parts = png_path.split('/')

            # Extract subject and session
            try:
                sub_id = next(part for part in png_parts if part.startswith("sub-"))
                ses_id = next(part for part in png_parts if part.startswith("ses-"))
            except StopIteration:
                print(f"Could not parse subject/session from: {png_path}")
                continue

            anat_dir = os.path.join(bids_root, sub_id, ses_id, "anat")
            extra_dir = os.path.join(bids_root, sub_id, ses_id, "extra_data")
            os.makedirs(extra_dir, exist_ok=True)

            # Get T1w file prefix from PNG filename
            t1w_prefix = os.path.splitext(os.path.basename(png_path))[0]

            nii_path = os.path.join(anat_dir, f"{t1w_prefix}.nii.gz")
            json_path = os.path.join(anat_dir, f"{t1w_prefix}.json")

            # Move .nii.gz file
            if os.path.exists(nii_path):
                shutil.move(nii_path, os.path.join(extra_dir, os.path.basename(nii_path)))
                print(f"Moved: {nii_path} → {extra_dir}")
            else:
                print(f"WARNING: NIfTI not found: {nii_path}")

            # Update and move .json file
            if os.path.exists(json_path):
                with open(json_path, 'r') as jf:
                    json_data = json.load(jf)

                json_data["quality_control_note"] = justification.strip()

                new_json_path = os.path.join(extra_dir, os.path.basename(json_path))
                with open(new_json_path, 'w') as jf:
                    json.dump(json_data, jf, indent=4)

                os.remove(json_path)
                print(f"Updated and moved JSON: {json_path} → {extra_dir}")
            else:
                print(f"WARNING: JSON not found: {json_path}")

def main():
    parser = argparse.ArgumentParser(description="Process exclusions and move T1w files to extra_data.")
    parser.add_argument("txt_file", help="Path to the input .txt file with exclusions.")
    parser.add_argument("bids_root", help="Path to the root of the BIDS dataset.")

    args = parser.parse_args()
    process_exclusions(args.txt_file, args.bids_root)

if __name__ == "__main__":
    main()
