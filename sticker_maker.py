import os
import sys
import subprocess
import json
import shutil

# --- Configuration ---
MAX_SIZE_KB = 256
TARGET_DIMENSION = 512
SAFE_BITRATE_FACTOR = 0.75 # Lowered to 75% to safer size targets

def find_tool(tool_name):
    """Finds the tool executable in the script's directory or subdirectories."""
    # check if on path
    if shutil.which(tool_name):
        return shutil.which(tool_name)
    
    # Check local dirs
    script_dir = os.path.dirname(os.path.abspath(__file__))
    for root, dirs, files in os.walk(script_dir):
        if f"{tool_name}.exe" in files:
            return os.path.join(root, f"{tool_name}.exe")
    
    return None

def get_video_info(ffprobe_path, file_path):
    """Retrieves duration and dimensions using ffprobe."""
    cmd = [
        ffprobe_path,
        "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        "-show_format",
        file_path
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
        
        # Get Duration
        duration = float(data['format'].get('duration', 0))
        
        # Get Video Stream Info
        video_stream = next((s for s in data['streams'] if s['codec_type'] == 'video'), None)
        if not video_stream:
            raise Exception("No video stream found.")
            
        width = int(video_stream['width'])
        height = int(video_stream['height'])
        
        return duration, width, height
    except Exception as e:
        print(f"Error analyzing video: {e}")
        sys.exit(1)

def calculate_target_details(duration, width, height, current_bitrate_factor=None):
    """Calculates target bitrate and dimensions."""
    if current_bitrate_factor is None:
        current_bitrate_factor = SAFE_BITRATE_FACTOR

    # 1. Dimensions: Fit within 512x512 converting keeping aspect ratio
    if width > height:
        new_width = TARGET_DIMENSION
        new_height = int((TARGET_DIMENSION / width) * height)
    else:
        new_height = TARGET_DIMENSION
        new_width = int((TARGET_DIMENSION / height) * width)
    
    # Ensure they are even numbers
    if new_width % 2 != 0: new_width -= 1
    if new_height % 2 != 0: new_height -= 1
    
    # 2. Bitrate: Size = Bitrate * Duration
    # Target Bits = (SizeKB * 1024 * 8)
    target_total_bits = MAX_SIZE_KB * 1024 * 8
    
    # Use safety factor
    safe_bits = target_total_bits * current_bitrate_factor
    
    bitrate_bps = safe_bits / duration
    bitrate_kbps = int(bitrate_bps / 1000)
    
    if bitrate_kbps < 10: bitrate_kbps = 10 # Hard floor
    
    return new_width, new_height, bitrate_kbps

def compress_video(ffmpeg_path, input_path):
    directory = os.path.dirname(input_path)
    filename = os.path.basename(input_path)
    name, _ = os.path.splitext(filename)
    output_path = os.path.join(directory, f"{name}_sticker.webm")
    
    # Locate ffprobe
    ffprobe_path = find_tool("ffprobe")
    if not ffprobe_path:
        print("Error: Could not find ffprobe.exe")
        return

    print(f"Analyzing {filename}...")
    duration, width, height = get_video_info(ffprobe_path, input_path)
    
    new_w, new_h, bitrate_k = calculate_target_details(duration, width, height)
    
    print(f"  Duration: {duration:.2f}s")
    print(f"  Original Size: {width}x{height}")
    print(f"  Target Size:   {new_w}x{new_h}")
    # print(f"  Target Bitrate: {bitrate_k}k") # Printed in loop now
    
    # 2-Pass Encoding Loop for strict size compliance
    max_attempts = 3
    current_bitrate = bitrate_k

    for attempt in range(max_attempts):
        print(f"--- Encoding Attempt {attempt + 1}/{max_attempts} (Target: {current_bitrate}k) ---")
        
        # Pass 1
        cmd_pass1 = [
            ffmpeg_path, "-y",
            "-i", input_path,
            "-c:v", "libvpx-vp9",
            "-pix_fmt", "yuva420p",
            "-b:v", f"{current_bitrate}k",
            "-vf", f"scale={new_w}:{new_h}",
            "-an",
            "-map_metadata", "-1",
            "-pass", "1",
            "-f", "null", "NUL"
        ]
        subprocess.run(cmd_pass1, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True) # Silence output for cleaner loop
        
        # Pass 2
        cmd_pass2 = [
            ffmpeg_path, "-y",
            "-i", input_path,
            "-c:v", "libvpx-vp9",
            "-pix_fmt", "yuva420p",
            "-b:v", f"{current_bitrate}k",
            "-vf", f"scale={new_w}:{new_h}",
            "-an",
            "-map_metadata", "-1",
            "-pass", "2",
            output_path
        ]
        subprocess.run(cmd_pass2, check=True)
        
        # Cleanup logs
        for f in os.listdir("."):
            if f.startswith("ffmpeg2pass") and f.endswith(".log"):
                try: os.remove(f)
                except: pass
        
        final_size = os.path.getsize(output_path) / 1024
        print(f"Result: {final_size:.2f} KB")
        
        if final_size <= MAX_SIZE_KB:
            print("Success! File is within limits.")
            break
        else:
            if attempt < max_attempts - 1:
                print(f"Overshot limit by {final_size - MAX_SIZE_KB:.2f}KB. Retrying with lower bitrate...")
                current_bitrate = int(current_bitrate * 0.80) # Reduce by 20%
                if current_bitrate < 10: current_bitrate = 10
            else:
                 print(f"WARNING: Could not fit under {MAX_SIZE_KB}KB even after {max_attempts} attempts.")
    
    print(f"Done! Created: {output_path}")

def main():
    print("--- Sticker Compressor v1.2 (Retry Logic) ---")
    
    ffmpeg_path = find_tool("ffmpeg")
    if not ffmpeg_path:
        print("Error: Could not find ffmpeg.exe in current folder or subfolders.")
        print("Please ensure ffmpeg is downloaded/extracted here.")
        input("Press Enter to exit...")
        sys.exit(1)
        
    # Get input file
    input_file = ""
    if len(sys.argv) > 1:
        input_file = sys.argv[1]
    else:
        # Interactive mode
        input_file = input("Enter path to video file (drag & drop here): ").strip().strip('"')
    
    if not os.path.exists(input_file):
        print("Error: File not found.")
        return

    compress_video(ffmpeg_path, input_file)

if __name__ == "__main__":
    main()
