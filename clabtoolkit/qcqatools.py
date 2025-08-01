import os
import glob
import json
from typing import List, Tuple, Optional, Union, Literal, Dict, Any
import nibabel as nib
import numpy as np
import logging
import matplotlib.pyplot as plt
from pathlib import Path

from concurrent.futures import ProcessPoolExecutor, as_completed
import threading
import queue
import time
from rich.console import Console
from rich.progress import (
    Progress, 
    SpinnerColumn, 
    TextColumn, 
    BarColumn, 
    TimeRemainingColumn, 
    MofNCompleteColumn
)
import clabtoolkit.bidstools as cltbids
import clabtoolkit.misctools as cltmisc


def get_valid_slices(
    data: np.ndarray, 
    ignore_value: Optional[int] = None,
    slice_positions: List[float] = [0.3, 0.5, 0.7]
) -> Tuple[List[int], List[int], List[int]]:
    """
    Get valid slice indices along each dimension, identifying regions with signal.
    
    Parameters
    ----------
    data : np.ndarray
        3D neuroimaging data array
    ignore_value : Optional[int], optional
        Value to ignore when determining valid regions. If None, will use 0 as background,
        by default None
    slice_positions : List[float], optional
        Relative positions (0-1) for the slices along each axis, by default [0.3, 0.5, 0.7]
    
    Returns
    -------
    Tuple[List[int], List[int], List[int]]
        Lists of slice indices for sagittal, coronal, and axial views
    """
    # Determine which values to consider as foreground
    if ignore_value is None:
        # Default: consider 0 as background, everything else as foreground
        valid_voxels = data != 0
    else:
        valid_voxels = data != ignore_value
    
    # Find the bounds of the foreground in each dimension
    x_indices = np.where(valid_voxels.any(axis=(1, 2)))[0]
    y_indices = np.where(valid_voxels.any(axis=(0, 2)))[0]
    z_indices = np.where(valid_voxels.any(axis=(0, 1)))[0]
    
    # Handle empty arrays (no foreground found)
    if len(x_indices) == 0:
        x_min, x_max = 0, data.shape[0] - 1
    else:
        x_min, x_max = x_indices[[0, -1]]
        
    if len(y_indices) == 0:
        y_min, y_max = 0, data.shape[1] - 1
    else:
        y_min, y_max = y_indices[[0, -1]]
        
    if len(z_indices) == 0:
        z_min, z_max = 0, data.shape[2] - 1
    else:
        z_min, z_max = z_indices[[0, -1]]
    
    def get_slices(min_val: int, max_val: int) -> List[int]:
        return [
            int(min_val + position * (max_val - min_val))
            for position in slice_positions
        ]
    
    return get_slices(x_min, x_max), get_slices(y_min, y_max), get_slices(z_min, z_max)

def generate_slices(
    nifti_path: Union[str, Path],
    output_path: Optional[Union[str, Path]] = None,
    slice_positions: List[float] = [0.3, 0.5, 0.7],
    ignore_value: Optional[int] = None,
    remove_invalid: bool = True,
    fig_size: Optional[Tuple[int, int]] = None,
    dpi: int = 300,
    bg_color: str = "black",
    text_color: str = "white",
    cmap: str = "gray",
    intensity_percentiles: Tuple[float, float] = (1, 99),
    show_colorbar: bool = True,
    colorbar_width_inches: float = 0.2,  # Fixed width in inches
    colorbar_height_fraction: float = 0.7,  # Control height
    overwrite: bool = False
) -> Optional[str]:
    """
    Generate a visualization of brain image slices from a NIfTI file.
    
    This function loads a neuroimaging file, selects slices at the specified positions
    along each dimension, and creates a composite figure with all slices arranged in a row.
    Intensity scaling is consistent across all slices.
    
    Parameters
    ----------
    nifti_path : Union[str, Path]
        Path to the input neuroimaging file (NIfTI, MGZ, MINC, etc.)
    output_path : Optional[Union[str, Path]], optional
        Path where the output PNG should be saved. If None, will create a 'figures'
        directory in the session folder based on BIDS convention, by default None
    slice_positions : List[float], optional
        Relative positions (0-1) for the slices along each axis, by default [0.3, 0.5, 0.7]
    ignore_value : Optional[int], optional
        Value to ignore when determining valid regions. If None, will use 0 as background,
        by default None
    remove_invalid : bool, optional
        Whether to remove invalid files when detected, by default True
    fig_size : Optional[Tuple[int, int]], optional
        Figure size in inches (width, height). If None, it will be calculated based on
        the number of slices, by default None
    dpi : int, optional
        Output image resolution in dots per inch, by default 300
    bg_color : str, optional
        Background color of the figure, by default "black"
    text_color : str, optional
        Color of text elements, by default "white"
    cmap : str, optional
        Colormap for displaying the image slices, by default "gray"
    intensity_percentiles : Tuple[float, float], optional
        Lower and upper percentiles for intensity normalization, by default (1, 99)
        Used to determine consistent intensity scaling across all slices
    show_colorbar : bool, optional
        Whether to display a single colorbar at the right side of the figure, by default True
    colorbar_width_inches : float, optional
        Width of the colorbar in inches, by default 0.2
    colorbar_height_fraction : float, optional
        Height of the colorbar as a fraction of the figure height, by default 0.7
    overwrite : bool, optional
        Whether to overwrite existing PNG files, by default False
    
    Returns
    -------
    Optional[str]
        Path to the generated PNG file, or None if generation failed or was skipped
    """
    
    # Convert to Path object for easier path manipulation
    nifti_path = Path(nifti_path)
    
    # Check if file exists
    if not nifti_path.exists():
        raise FileNotFoundError(f"Input file not found: {nifti_path}")
    
    # Determine output path if not provided
    if output_path is None:
        figures_dir = nifti_path.parent
        
        file_name = nifti_path.stem
        
        tmp_name = str(nifti_path)
        
        if tmp_name.endswith('.nii.gz'):
            tmp_name = tmp_name.replace('.nii.gz', '.png')
        elif tmp_name.endswith('.nii'):
            tmp_name = tmp_name.replace('.nii', '.png')
        else:
            # Detect file extension
            file_extension = nifti_path.suffix
            tmp_name = tmp_name.replace(file_extension, '.png')
            
        output_path = Path(tmp_name)
    else:
        output_path = Path(output_path)
        # Make sure the directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Check if output file already exists and handle overwrite logic
    if output_path.exists() and not overwrite:
        print(f"PNG already exists and overwrite=False: {output_path}")
        return str(output_path)  # Return existing file path
    
    # Load the image
    try:
        img = nib.load(nifti_path)
    except Exception as e:
        raise ValueError(f"Failed to load {nifti_path}: {str(e)}")
    
    try:
        data = img.get_fdata()
        
        # Detect if data has NaN values and put them to 0
        if np.isnan(data).any():
            data[np.isnan(data)] = 0
        
    except Exception as e:
        print(f"Skipping {nifti_path} due to invalid data: {str(e)}")
        return None
    
    # If the data is 4D select the first volume
    if data.ndim == 4:
        data = data[..., 0]
    elif data.ndim != 3:
        print(f"Skipping {nifti_path} due to invalid dimensions: {data.ndim}")
        
        if remove_invalid:
            nii_file = nifti_path
            json_file = nifti_path.with_suffix('').with_suffix('.json')
            
            if nii_file.exists():
                os.remove(nii_file)
            if json_file.exists():
                os.remove(json_file)
            
        return None
    
    # Detect if one dimension is equal to 1
    if np.any(np.array(data.shape) == 1):
        print(f"Skipping {nifti_path} due to invalid shape: {data.shape}")
        
        if remove_invalid:
            nii_file = nifti_path
            json_file = nifti_path.with_suffix('').with_suffix('.json')
            
            if nii_file.exists():
                os.remove(nii_file)
            if json_file.exists():
                os.remove(json_file)
        
        return None
    
    affine = img.affine
    zooms = img.header.get_zooms()
    
    # Get slice indices for each view
    slices_sagittal, slices_coronal, slices_axial = get_valid_slices(
        data, 
        ignore_value=ignore_value,
        slice_positions=slice_positions
    )
    
    # Calculate total number of slices
    num_slices = len(slice_positions) * 3
    
    # Calculate figure size if not provided
    if fig_size is None:
        # Base size per slice
        slice_width = 2.0
        slice_height = 2.0 * 3  # Higher aspect ratio
        
        # Calculate total width 
        total_width = slice_width * num_slices
            
        fig_size = (total_width, slice_height)
    
    # Calculate global intensity range for consistent display across all slices
    if ignore_value is not None:
        mask = data != ignore_value
    else:
        mask = data != 0
    
    # Get foreground voxels
    foreground_values = data[mask]
    
    # If no foreground values, use the full data range
    if len(foreground_values) == 0:
        vmin, vmax = np.min(data), np.max(data)
    else:
        # Calculate percentiles to exclude outliers
        vmin = np.percentile(foreground_values, intensity_percentiles[0])
        vmax = np.percentile(foreground_values, intensity_percentiles[1])
    
    # Create a standard figure - we'll place the colorbar differently
    fig, axes = plt.subplots(1, num_slices, figsize=fig_size)
    fig.patch.set_facecolor(bg_color)
    
    # Ensure axes is always a list
    if num_slices == 1:
        axes = [axes]
    
    def plot_slice(ax, img_slice, direction, slice_num, extent):
        # Use the global vmin and vmax for all slices
        im = ax.imshow(np.rot90(img_slice), cmap=cmap, extent=extent, vmin=vmin, vmax=vmax)
        # Round coordinates to 1 decimal place
        ax.set_title(f"{direction} = {slice_num:.1f} mm", fontsize=10, color=text_color)
        ax.axis("off")
        return im
    
    # Define extents
    x_mm = np.linspace(affine[0, 3], affine[0, 3] + data.shape[0] * zooms[0], data.shape[0])
    y_mm = np.linspace(affine[1, 3], affine[1, 3] + data.shape[1] * zooms[1], data.shape[1])
    z_mm = np.linspace(affine[2, 3], affine[2, 3] + data.shape[2] * zooms[2], data.shape[2])
    
    # Store the last image for the colorbar
    last_im = None
    
    # Plot slices for each view
    # Sagittal view (X)
    for i, s in enumerate(slices_sagittal):
        im = plot_slice(axes[i], data[s, :, :], "X", s * zooms[0], 
                    [y_mm[0], y_mm[-1], z_mm[0], z_mm[-1]])
        last_im = im
    
    # Coronal view (Y)
    sag_offset = len(slices_sagittal)
    for i, s in enumerate(slices_coronal):
        im = plot_slice(axes[i + sag_offset], data[:, s, :], "Y", 
                  s * zooms[1], [x_mm[0], x_mm[-1], z_mm[0], z_mm[-1]])
        last_im = im
    
    # Axial view (Z)
    cor_offset = sag_offset + len(slices_coronal)
    for i, s in enumerate(slices_axial):
        im = plot_slice(axes[i + cor_offset], data[:, :, s], "Z", 
                  s * zooms[2], [x_mm[0], x_mm[-1], y_mm[0], y_mm[-1]])
        last_im = im
    
    # Adjust the layout before adding colorbar
    plt.tight_layout()
    
    # Add a single colorbar if requested
    if show_colorbar and last_im is not None:
        # Get figure dimensions
        fig_width, fig_height = fig.get_size_inches()
        
        # Convert fixed width in inches to fraction of figure width
        colorbar_width_fraction = colorbar_width_inches / fig_width
        
        # Create an axis for the colorbar
        # Position: [left, bottom, width, height] in figure coordinates (0-1)
        cbar_left = 1.0 - colorbar_width_fraction * 1.2  # Position it near the right edge
        cbar_bottom = (1.0 - colorbar_height_fraction) / 2  # Center vertically
        cbar_width = colorbar_width_fraction  # Thin width (now in figure fraction)
        cbar_height = colorbar_height_fraction  # Shorter than full height
        
        # Create the colorbar axis
        cbar_ax = fig.add_axes([cbar_left, cbar_bottom, cbar_width, cbar_height])
        
        # Create the colorbar with fewer ticks
        cbar = plt.colorbar(last_im, cax=cbar_ax, ticks=[vmin, (vmin+vmax)/2, vmax])
        cbar.ax.tick_params(labelsize=8)  # Smaller text
        
        # Style the colorbar ticks and labels
        cbar_ax.tick_params(axis='y', colors=text_color, length=2)  # Shorter ticks
        for label in cbar_ax.get_yticklabels():
            label.set_color(text_color)
            label.set_fontsize(8)  # Smaller font
    
    # Save figure without using tight_layout again (it's already applied)
    plt.savefig(output_path, bbox_inches="tight", dpi=dpi, facecolor=bg_color)
    plt.close()
    
    return str(output_path)


# Move process_file function to module level so it can be pickled for multiprocessing
def _process_single_file(args):
    """
    Process a single file - moved to module level for multiprocessing compatibility.
    
    Parameters
    ----------
    args : tuple
        Tuple containing (file_path, input_folder, output_folder, slice_positions, ignore_value, overwrite)
    
    Returns
    -------
    tuple
        (success, result_or_error_message)
    """
    file_path, input_folder, output_folder, slice_positions, ignore_value, overwrite = args
    
    try:
        # Check if the file is a valid neuroimaging file
        try:
            img = nib.load(file_path)
            # Try to get data - this will fail for invalid files
            _ = img.shape
        except Exception as e:
            return (False, f"Invalid file {file_path}: {str(e)}")
        
        # Determine output path
        if output_folder is not None:
            # If output_folder is provided, use it
            rel_path = os.path.relpath(file_path, input_folder)
            if os.path.dirname(rel_path):
                # Preserve directory structure
                out_dir = output_folder / os.path.dirname(rel_path)
                out_dir.mkdir(parents=True, exist_ok=True)
            else:
                out_dir = output_folder
            
            file_name = Path(file_path).stem
            if file_name.endswith('.nii'):
                file_name = file_name[:-4]
            
            output_path = out_dir / f"{file_name}.png"
        else:
            # If no output_folder, let generate_slices determine the path
            output_path = None
        
        # Generate the slices visualization
        result = generate_slices(
            file_path, 
            output_path=output_path,
            slice_positions=slice_positions,
            ignore_value=ignore_value,
            overwrite=overwrite
        )
        
        return (True, result)
        
    except Exception as e:
        return (False, f"Error processing {file_path}: {str(e)}")


def recursively_generate_slices(
    input_folder: Union[str, Path],
    output_folder: Optional[Union[str, Path]] = None,
    and_filter: Optional[Union[str, list, dict]] = None,
    or_filter: Optional[Union[str, list, dict]] = None,
    slice_positions: List[float] = [0.3, 0.5, 0.7],
    ignore_value: Optional[int] = None,
    recursive: bool = True,
    n_jobs: int = 1,
    file_extensions: List[str] = ['.nii', '.nii.gz', '.mgz', '.mnc'],
    overwrite: bool = False,
    verbose: bool = True
) -> List[str]:
    """
    Recursively traverse a folder, detect neuroimaging files, and generate PNG visualizations.
    
    Parameters
    ----------
    input_folder : Union[str, Path]
        Path to the input folder containing neuroimaging files
    output_folder : Optional[Union[str, Path]], optional
        Path to the output folder for saving PNG images. If None, PNGs will be saved in a 
        'figures' subdirectory within the same directory structure, by default None
    and_filter : Optional[Union[str, list, dict]], optional
        AND filter to apply when searching for files, by default None
    or_filter : Optional[Union[str, list, dict]], optional
        OR filter to apply when searching for files, by default None
    slice_positions : List[float], optional
        Relative positions (0-1) for the slices along each axis, by default [0.3, 0.5, 0.7]
    ignore_value : Optional[int], optional
        Value to ignore when determining valid regions, by default None
    recursive : bool, optional
        Whether to recursively search through subdirectories, by default True
    n_jobs : int, optional
        Number of parallel jobs to run when processing files, by default 1
    file_extensions : List[str], optional
        List of file extensions to consider as neuroimaging files,
        by default ['.nii', '.nii.gz', '.mgz', '.mnc']
    overwrite : bool, optional
        Whether to overwrite existing PNG files, by default False
    verbose : bool, optional
        Whether to display progress information, by default True
    
    Returns
    -------
    List[str]
        List of paths to the generated PNG images
    
    Raises
    ------
    FileNotFoundError
        If the input folder does not exist
    
    Examples
    --------
    Basic usage with default settings:
    >>> output_files = recursively_generate_slices("/path/to/dataset")
    
    Filter files containing "T1w" in the filename:
    >>> output_files = recursively_generate_slices("/path/to/dataset", and_filter="T1w")
    
    Specify output folder and process files in parallel with overwrite:
    >>> output_files = recursively_generate_slices(
    ...     "/path/to/dataset", 
    ...     output_folder="/path/to/output_dir",
    ...     n_jobs=4,
    ...     overwrite=True
    ... )
    """
    # Initialize rich console
    console = Console()
    
    # Set up logging
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    # Convert paths to Path objects
    input_folder = Path(input_folder)
    if output_folder is not None:
        output_folder = Path(output_folder)
        output_folder.mkdir(parents=True, exist_ok=True)
    
    # Check if input folder exists
    if not input_folder.exists():
        raise FileNotFoundError(f"Input folder not found: {input_folder}")
    
    # Get all neuroimaging files using the provided filter function
    all_files = cltmisc.detect_recursive_files(input_folder)
    all_files = cltmisc.filter_by_substring(
        all_files,
        and_filter=and_filter,
        or_filter=or_filter
    )

    # Filter files by extension
    neuroimaging_files = [
        f for f in all_files if any(f.lower().endswith(ext) for ext in file_extensions)
    ]
    
    num_files = len(neuroimaging_files)
    logging.info(f"Found {num_files} neuroimaging files to process")
    
    # Create a message queue to communicate across threads
    progress_queue = queue.Queue()
    
    # Start a separate thread for the progress bar
    def progress_monitor(progress_queue, total_files, progress_task, stop_event):
        completed = 0
        errors = 0
        skipped = 0
        
        while (completed + errors + skipped < total_files) and not stop_event.is_set():
            try:
                success, message = progress_queue.get(timeout=0.1)
                
                if success:
                    if "already exists and overwrite=False" in str(message):
                        skipped += 1
                    else:
                        completed += 1
                else:
                    errors += 1
                    console.print(f"[bold red]Error: {message}[/bold red]")
                
                # Update progress bar
                progress.update(
                    progress_task,
                    completed=completed + skipped,
                    description=f"[yellow]Processing files - {completed} completed, {skipped} skipped, {errors} errors",
                )
                
                # Important: mark the task as done in the queue
                progress_queue.task_done()
                
            except queue.Empty:
                # No updates, just continue waiting
                pass
                
        # Ensure the progress bar shows 100% completion
        if not stop_event.is_set():
            progress.update(progress_task, completed=total_files)
    
    # Process files and track progress with Rich
    generated_images = []
    stop_monitor = threading.Event()
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(bar_width=50),
        TextColumn("[progress.percentage]{task.percentage:>3.1f}%"),
        TimeRemainingColumn(),
        MofNCompleteColumn(),
        console=console,
        refresh_per_second=10,  # Increase refresh rate
    ) as progress:
        # Add main task to track progress
        main_task = progress.add_task("[yellow]Processing neuroimaging files", total=num_files)
        
        # Start progress monitor thread
        monitor_thread = threading.Thread(
            target=progress_monitor,
            args=(progress_queue, num_files, main_task, stop_monitor),
            daemon=True,
        )
        monitor_thread.start()
        
        try:
            if n_jobs > 1:
                # Parallel processing
                # Prepare arguments for each file
                file_args = [
                    (file_path, input_folder, output_folder, slice_positions, ignore_value, overwrite)
                    for file_path in neuroimaging_files
                ]
                
                with ProcessPoolExecutor(max_workers=n_jobs) as executor:
                    # Submit all tasks
                    future_to_file = {
                        executor.submit(_process_single_file, args): args[0] 
                        for args in file_args
                    }
                    
                    # Process results as they complete
                    for future in as_completed(future_to_file):
                        file_path = future_to_file[future]
                        try:
                            success, result = future.result()
                            if success and result:
                                generated_images.append(result)
                                progress_queue.put((True, result))
                            else:
                                progress_queue.put((False, result))
                        except Exception as e:
                            error_msg = f"Error processing {file_path}: {str(e)}"
                            logging.error(error_msg)
                            progress_queue.put((False, error_msg))
            else:
                # Sequential processing
                for file_path in neuroimaging_files:
                    success, result = _process_single_file(
                        (file_path, input_folder, output_folder, slice_positions, ignore_value, overwrite)
                    )
                    if success and result:
                        generated_images.append(result)
                        progress_queue.put((True, result))
                    else:
                        progress_queue.put((False, result))
            
            # Allow some time for the queue to process final updates
            time.sleep(0.5)
            
            # Directly set progress to 100% after all processing is done
            progress.update(main_task, completed=num_files, refresh=True)
            
            # Wait for the progress queue to be empty
            progress_queue.join()
            
        finally:
            # Signal the monitor thread to stop
            stop_monitor.set()
            
            # Make absolutely sure progress shows completion
            progress.update(main_task, completed=num_files, refresh=True)
    
    logging.info(f"Successfully generated {len(generated_images)} PNG images")
    return generated_images


def generate_image_selection_webpage(
    root_directory: Union[str, Path],
    output_html: Optional[Union[str, Path]] = None,
    png_pattern: str = "**/*.png",
    title: str = "PNG Image Selection",
    recursive: bool = True,
    show_descriptions: bool = True,
    image_width: str = "1400px",
    overwrite: bool = False
) -> str:
    """
    Generate an HTML webpage to display PNG images in hierarchical folder structure with checkboxes.
    
    Parameters
    ----------
    root_directory : Union[str, Path]
        Root directory to search for PNG files
    output_html : Optional[Union[str, Path]], optional
        Output path for the HTML file. If None, saves as 'png_selection.html' in root_directory
    png_pattern : str, optional
        Glob pattern to find PNG files, by default "**/*.png"
    title : str, optional
        Title for the HTML page, by default "PNG Image Selection"
    recursive : bool, optional
        Whether to search recursively, by default True
    show_descriptions : bool, optional
        Whether to try to extract descriptions from associated JSON files, by default True
    image_width : str, optional
        CSS width for images, by default "1400px"
    overwrite : bool, optional
        Whether to overwrite existing HTML file, by default False
    
    Returns
    -------
    str
        Path to the generated HTML file
    """
    
    console = Console()
    root_directory = Path(root_directory)
    
    # Set output HTML path
    if output_html is None:
        output_html = root_directory / "png_selection.html"
    else:
        output_html = Path(output_html)
    
    # Check if output file already exists and handle overwrite logic
    if output_html.exists() and not overwrite:
        console.print(f"[yellow]HTML file already exists and overwrite=False: {output_html}")
        return str(output_html)
    
    # Find all PNG files
    if recursive:
        png_files = list(root_directory.glob(png_pattern))
    else:
        png_files = list(root_directory.glob("*.png"))
    
    console.print(f"Found {len(png_files)} PNG files")
    
    if not png_files:
        console.print("[yellow]No PNG files found!")
        return str(output_html)
    
    # Dictionary to store images organized by hierarchy
    image_dict = {}
    
    # Process each PNG file
    with Progress() as progress:
        task = progress.add_task("[cyan]Processing PNG files...", total=len(png_files))
        
        for i, png_file in enumerate(png_files):
            progress.update(task, completed=i+1, description=f"[cyan]Processing: {png_file.name}")
            
            # Get relative path from root directory
            try:
                relative_path = png_file.relative_to(root_directory)
                path_parts = relative_path.parts[:-1]  # Exclude filename
                
                # Build hierarchical structure
                current_dict = image_dict
                hierarchy_path = []
                
                for part in path_parts:
                    hierarchy_path.append(part)
                    if part not in current_dict:
                        current_dict[part] = {}
                    current_dict = current_dict[part]
                
                # Initialize the final level if needed
                if 'files' not in current_dict:
                    current_dict['files'] = []
                
                # Try to get description from associated files
                description = None
                original_nii = None
                
                if show_descriptions:
                    # Look for associated JSON file (try different naming patterns)
                    json_candidates = [
                        png_file.with_suffix('.json'),  # Same name with .json
                        png_file.parent / f"{png_file.stem}.json",  # Same directory
                    ]
                    
                    # Also try to find original NIfTI file and its JSON
                    nii_candidates = [
                        png_file.with_suffix('.nii.gz'),
                        png_file.with_suffix('.nii'),
                        png_file.parent / f"{png_file.stem}.nii.gz",
                        png_file.parent / f"{png_file.stem}.nii",
                    ]
                    
                    # Check for JSON files
                    for json_candidate in json_candidates:
                        if json_candidate.exists():
                            try:
                                with open(json_candidate, 'r') as f:
                                    json_data = json.load(f)
                                    description = json_data.get("SeriesDescription", 
                                                             json_data.get("Description", None))
                                break
                            except:
                                continue
                    
                    # Check for original NIfTI files
                    for nii_candidate in nii_candidates:
                        if nii_candidate.exists():
                            original_nii = str(nii_candidate)
                            
                            # Try to get JSON description for this NIfTI
                            if description is None:
                                json_for_nii = nii_candidate.with_suffix('.json')
                                if json_for_nii.exists():
                                    try:
                                        with open(json_for_nii, 'r') as f:
                                            json_data = json.load(f)
                                            description = json_data.get("SeriesDescription", 
                                                                       json_data.get("Description", None))
                                    except:
                                        pass
                            break
                
                # Store file information
                file_info = {
                    'png_path': str(png_file),
                    'relative_path': str(relative_path),
                    'name': png_file.stem,
                    'description': description,
                    'original_nii': original_nii,
                    'hierarchy': ' / '.join(hierarchy_path) if hierarchy_path else 'Root'
                }
                
                current_dict['files'].append(file_info)
                
            except ValueError:
                # PNG file is not under root_directory
                console.print(f"[yellow]Skipping {png_file} (not under root directory)")
                continue
    
    # Generate HTML content
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <style>
    body {{ 
      font-family: Arial, sans-serif; 
      background-color: #121212; 
      color: white; 
      margin: 20px;
      line-height: 1.6;
    }}
    
    h1, h2, h3, h4, h5 {{ 
      color: #ffcc00; 
      margin-top: 30px;
      margin-bottom: 15px;
    }}
    
    h1 {{ font-size: 2.5em; text-align: center; }}
    h2 {{ font-size: 2em; border-bottom: 2px solid #ffcc00; padding-bottom: 10px; }}
    h3 {{ font-size: 1.5em; margin-left: 20px; }}
    h4 {{ font-size: 1.3em; margin-left: 40px; }}
    h5 {{ font-size: 1.1em; margin-left: 60px; }}
    
    .image-container {{ 
      margin: 20px 0; 
      padding: 15px;
      background-color: #1e1e1e;
      border-radius: 8px;
      border-left: 4px solid #ffcc00;
    }}
    
    .checkbox-label {{ 
      font-size: 16px; 
      margin-bottom: 10px;
      display: block;
      cursor: pointer;
      padding: 8px;
      background-color: #2a2a2a;
      border-radius: 4px;
      transition: background-color 0.3s;
    }}
    
    .checkbox-label:hover {{
      background-color: #3a3a3a;
    }}
    
    .hierarchy-info {{
      font-size: 14px;
      color: #aaa;
      margin-bottom: 5px;
      font-style: italic;
    }}
    
    img {{ 
      width: {image_width}; 
      max-width: 100%;
      height: auto;
      border: 2px solid #ffcc00; 
      border-radius: 5px; 
      display: block; 
      margin: 10px 0;
      cursor: pointer;
      transition: transform 0.3s, border-color 0.3s;
    }}
    
    img:hover {{
      transform: scale(1.02);
      border-color: #fff;
    }}
    
    input[type="checkbox"] {{ 
      transform: scale(1.5); 
      margin-right: 10px; 
      accent-color: #ffcc00;
    }}
    
    .controls {{
      position: sticky;
      top: 20px;
      background-color: #1e1e1e;
      padding: 20px;
      border-radius: 8px;
      margin-bottom: 30px;
      border: 2px solid #ffcc00;
      text-align: center;
    }}
    
    .download-btn, .select-btn {{ 
      background: #ffcc00; 
      color: black; 
      padding: 12px 20px; 
      border: none; 
      font-size: 16px; 
      cursor: pointer; 
      border-radius: 5px;
      margin: 5px;
      font-weight: bold;
      transition: background-color 0.3s;
    }}
    
    .download-btn:hover, .select-btn:hover {{
      background: #ffd700;
    }}
    
    .stats {{
      margin-top: 15px;
      font-size: 14px;
      color: #aaa;
    }}
    
    .description {{
      color: #ccc;
      font-style: italic;
      font-size: 14px;
      margin-top: 5px;
    }}
    
    .folder-section {{
      margin-left: 20px;
      border-left: 2px solid #444;
      padding-left: 20px;
      margin-bottom: 20px;
    }}
  </style>
  <script>
    function downloadChecked() {{
      // Get all checkboxes
      var allBoxes = document.querySelectorAll('input[type="checkbox"]');
      var selected = [];
      var unselected = [];

      allBoxes.forEach(function(box) {{
        var filename = box.value;
        var label = box.parentElement.textContent || filename;
        if (box.checked) {{
          selected.push(filename);
        }} else {{
          unselected.push({{filename: filename, label: label}});
        }}
      }});

      // Prompt for justification for each unselected image
      var justifications = [];
      var options = ["bad quality", "different contrast", "redundant", "other"];
      var optionsText = options.map(function(opt, idx) {{ return (idx+1) + ". " + opt; }}).join("\\n");

      for (let i = 0; i < unselected.length; i++) {{
        var img = unselected[i];
        var msg = "Unselected image:\\n" + img.label + "\\n\\nChoose justification:\\n" + optionsText + "\\n\\nEnter 1, 2, 3, or 4:";
        var choice = prompt(msg, "1");
        if (!choice) continue;
        var idx = parseInt(choice) - 1;
        var justification = options[idx] || options[0];
        if (justification === "other") {{
          var custom = prompt("Please enter your justification for:\\n" + img.label, "");
          if (custom && custom.trim() !== "") {{
            justification = custom.trim();
          }}
        }}
        justifications.push(img.filename + "\\t" + justification);
      }}

      // Download unselected justifications
      if (justifications.length > 0) {{
        var outputText = justifications.join("\\n");
        var blob = new Blob([outputText], {{ type: 'text/plain' }});
        var url = URL.createObjectURL(blob);

        var a = document.createElement('a');
        a.href = url;
        a.download = "unselected_images_justifications.txt";
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
      }}

      // Download selected images list
      if (selected.length > 0) {{
        var outputText2 = selected.join("\\n");
        var blob2 = new Blob([outputText2], {{ type: 'text/plain' }});
        var url2 = URL.createObjectURL(blob2);

        var a2 = document.createElement('a');
        a2.href = url2;
        a2.download = "selected_images.txt";
        document.body.appendChild(a2);
        a2.click();
        document.body.removeChild(a2);
        URL.revokeObjectURL(url2);
      }}

      updateStats();
    }}

    function selectAll() {{
      var checkboxes = document.querySelectorAll('input[type="checkbox"]');
      checkboxes.forEach(function(box) {{
        box.checked = true;
      }});
      updateStats();
    }}

    function selectNone() {{
      var checkboxes = document.querySelectorAll('input[type="checkbox"]');
      checkboxes.forEach(function(box) {{
        box.checked = false;
      }});
      updateStats();
    }}

    function updateStats() {{
      var total = document.querySelectorAll('input[type="checkbox"]').length;
      var selected = document.querySelectorAll('input[type="checkbox"]:checked').length;
      document.getElementById('stats').innerHTML = `Selected: ${{selected}} / ${{total}} images`;
    }}

    document.addEventListener('change', function(e) {{
      if (e.target.type === 'checkbox') {{
        updateStats();
      }}
    }});

    window.onload = function() {{
      updateStats();
    }};
  </script>
</head>
<body>
  <h1>{title}</h1>
  
  <div style="text-align: center; margin-bottom: 20px; padding: 15px; background-color: #2a2a2a; border-radius: 8px; border: 1px solid #555;">
    <h3 style="margin: 0; color: #ffcc00;">📁 Root Directory</h3>
    <p style="margin: 5px 0; font-family: monospace; color: #ccc; font-size: 16px; word-break: break-all;">{root_directory}</p>
  </div>
  
  <div class="controls">
    <button class="select-btn" onclick="selectAll()">Select All</button>
    <button class="select-btn" onclick="selectNone()">Select None</button>
    <button class="download-btn" onclick="downloadChecked()">Download Selection</button>
    <div id="stats" class="stats">Loading...</div>
  </div>
"""

    def render_hierarchy(data_dict, level=0):
        """Recursively render the hierarchical structure"""
        content = ""
        
        for key, value in sorted(data_dict.items()):
            if key == 'files':
                # Render files at this level
                for file_info in value:
                    png_path = file_info['relative_path']
                    name = file_info['name']
                    description = file_info['description']
                    hierarchy = file_info['hierarchy']
                    original_nii = file_info['original_nii']
                    
                    # Use original NIfTI path as checkbox value if available, otherwise PNG path
                    checkbox_value = original_nii if original_nii else file_info['png_path']
                    
                    content += f'''
      <div class="image-container">
        <div class="hierarchy-info">📁 {hierarchy}</div>
        <label class="checkbox-label">
          <input type="checkbox" id="{name}" value="{checkbox_value}"> 
          <strong>{name}</strong>
        </label>'''
                    
                    if description:
                        content += f'<div class="description">📝 {description}</div>'
                    
                    content += f'''
        <img src="{png_path}" alt="{name}" onclick="document.getElementById('{name}').checked = !document.getElementById('{name}').checked; updateStats();">
      </div>'''
            else:
                # Render subfolder
                header_level = min(level + 2, 5)  # h2 to h5
                content += f'<h{header_level}>📂 {key}</h{header_level}>\n'
                content += '<div class="folder-section">\n'
                content += render_hierarchy(value, level + 1)
                content += '</div>\n'
        
        return content

    # Add the hierarchical content
    html_content += render_hierarchy(image_dict)
    
    # Close HTML
    html_content += """
    <div class="controls" style="margin-top: 40px;">
    <button class="select-btn" onclick="selectAll()">Select All</button>
    <button class="select-btn" onclick="selectNone()">Select None</button>
    <button class="download-btn" onclick="downloadChecked()">Download Selection</button>
    <div id="stats" class="stats">Loading...</div>
    </div>
</body>
</html>"""

    # Save HTML file
    with open(output_html, "w", encoding='utf-8') as f:
        f.write(html_content)
    
    console.print(f"[green]HTML file saved: {output_html}")
    return str(output_html)


# Example usage function
def create_png_webpage_from_generated_slices(
    root_directory: Union[str, Path],
    output_html: Optional[Union[str, Path]] = None,
    overwrite: bool = False
) -> str:
    """
    Convenience function to create a webpage from PNG files generated by the slice generation functions.
    
    Parameters
    ----------
    root_directory : Union[str, Path]
        Root directory containing the generated PNG files
    output_html : Optional[Union[str, Path]], optional
        Output path for HTML file
    overwrite : bool, optional
        Whether to overwrite existing HTML file, by default False
    
    Returns
    -------
    str
        Path to generated HTML file
    """
    return generate_image_selection_webpage(
        root_directory=root_directory,
        output_html=output_html,
        title="Generated Brain Slice Images Selection",
        png_pattern="**/*.png",
        show_descriptions=True,
        image_width="1200px",
        overwrite=overwrite
    )

