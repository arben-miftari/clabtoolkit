import argparse
import clabtoolkit.dictomtools as cltdicomtools

def main():
    parser = argparse.ArgumentParser(description="Organize DICOM folder.")
    parser.add_argument("input_dir", help="Path to input directory")
    parser.add_argument("output_dir", help="Path to output directory")
    args = parser.parse_args()

    cltdicomtools.org_conv_dicoms(
        in_dic_dir=args.input_dir,
        out_dic_dir=args.output_dir
    )

if __name__ == "__main__":
    main()