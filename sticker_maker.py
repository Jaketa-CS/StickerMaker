import os
import sys
import subprocess
import json
import shutil

# --- Configuration ---
MAX_SIZE_KB = 256
TARGET_DIMENSION = 512
SAFE_BITRATE_FACTOR = 0.75 # Lowered to 75% to safer size targets
MAX_FPS = 30
MAX_DURATION_SEC = 3.0

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
        
        # Get FPS (frame rate)
        fps_str = video_stream.get('r_frame_rate', '30/1')
        try:
            num, den = map(int, fps_str.split('/'))
            fps = num / den if den != 0 else 30.0
        except:
            fps = 30.0

        return duration, width, height, fps

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
    
    # Clean up the name: strip '!!' from front, and all '_sticker', '_fixed', or '_#' from end
    name = name.lstrip("!")
    import re
    # Remove trailing _sticker and any trailing numbers/fixed tags
    name = re.sub(r'(_sticker)?(_fixed)?(_\d+)?$', '', name)
        
    # Find the next available version number
    counter = 1
    while True:
        output_path = os.path.join(directory, f"!!{name}_sticker_{counter}.webm")
        # Ensure we don't collision with input OR an existing file
        if not os.path.exists(output_path) and os.path.abspath(output_path) != os.path.abspath(input_path):
            break
        counter += 1
    
    # Locate ffprobe
    ffprobe_path = find_tool("ffprobe")
    if not ffprobe_path:
        print("Error: Could not find ffprobe.exe")
        return

    print(f"Analyzing {filename}...")
    duration, width, height, fps = get_video_info(ffprobe_path, input_path)
    
    # Smart FPS: Keep original if <= 30, otherwise cap at 30
    target_fps = fps if fps <= MAX_FPS else MAX_FPS
    
    print(f"  Duration: {duration:.2f}s")
    print(f"  Original Size: {width}x{height}")
    print(f"  FPS:           {target_fps:.2f} (Original: {fps:.2f})")
    
    # Duration handling - give user options if over limit
    duration_choice = None  # None = no change, 'speed' = speed up, 'trim' = trim, 'cut' = custom cut
    effective_duration = duration
    cut_start = 0
    
    if duration > MAX_DURATION_SEC:
        speed_factor = duration / MAX_DURATION_SEC
        print(f"\n  [!] Duration {duration:.2f}s exceeds Telegram's {MAX_DURATION_SEC}s limit.")
        print(f"  What would you like to do?")
        print(f"\n  [Quick Solutions]")
        print(f"    1) Speed up {speed_factor:.1f}x to fit in {MAX_DURATION_SEC}s")
        print(f"    2) Trim to the first {MAX_DURATION_SEC}s")
        print(f"    3) Keep as-is ({duration:.2f}s duration, will be WebM)")
        print(f"\n  [Advanced]")
        print(f"    4) Custom cut (pick start & end time)")
        
        while True:
            choice = input("  Enter choice (1/2/3/4): ").strip()
            if choice == '1':
                duration_choice = 'speed'
                effective_duration = MAX_DURATION_SEC
                print(f"  -> Speeding up {speed_factor:.1f}x")
                break
            elif choice == '2':
                duration_choice = 'trim'
                effective_duration = MAX_DURATION_SEC
                print(f"  -> Trimming to first {MAX_DURATION_SEC}s")
                break
            elif choice == '3':
                print(f"  -> Keeping original duration")
                break
            elif choice == '4':
                duration_choice = 'cut'
                ffplay_path = find_tool("ffplay")
                print(f"\n--- Custom Cut Mode ---")
                print(f"  Find the perfect 3-second window. The script will suggest")
                print(f"  an end time automatically to help you hit the 3s limit.")
                print(f"  Timeline: 0.00s -------- {duration:.2f}s")
                while True:
                    try:
                        start_input = input(f"  Start time in seconds [0.00]: ").strip()
                        cut_start = float(start_input) if start_input else 0.0
                        
                        time_left = duration - cut_start
                        if time_left < MAX_DURATION_SEC:
                            print(f"  Note: Only {time_left:.2f}s remains until the end of the video.")
                        
                        # Suggest an end time that hits exactly the 3s limit
                        suggested_end = min(cut_start + MAX_DURATION_SEC, duration)
                        print(f"  (For a 3.0s clip, pick end time: {suggested_end:.2f})")
                        
                        end_input = input(f"  End time in seconds [{suggested_end:.2f}]: ").strip()
                        cut_end = float(end_input) if end_input else suggested_end
                        
                        cut_len = cut_end - cut_start
                        if cut_start < 0 or cut_end > duration or cut_start >= cut_end:
                            print(f"  Invalid range. Start must be before end, within 0-{duration:.2f}s.")
                            continue

                        # Warn immediately if still over the limit
                        if cut_len > MAX_DURATION_SEC:
                            print(f"\n  [!] Selection is {cut_len:.2f}s, which exceeds Telegram's {MAX_DURATION_SEC}s limit.")
                            if input("      Are you sure you want to use this? (y/n) [n]: ").strip().lower() != 'y':
                                continue

                        # Visual Preview
                        if ffplay_path:
                            print(f"\n  [Previewing {cut_len:.2f}s loop...] (Close the window to continue)")
                            # Use a filter for the preview - it's much more accurate for GIFs/MOV seeking
                            trim_vf = f"trim=start={cut_start}:duration={cut_len},setpts=PTS-STARTPTS"
                            preview_cmd = [
                                ffplay_path, "-i", input_path,
                                "-vf", trim_vf,
                                "-loop", "0", "-autoexit", "-noborder", "-window_title", f"PREVIEW ({cut_len:.2f}s) - Close me",
                                "-x", "512", "-y", "512"
                            ]
                            subprocess.run(preview_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                            
                            confirm = input(f"  Use this {cut_len:.2f}s selection? (y/n): ").strip().lower()
                            if confirm == 'n':
                                print("  Let's try again...")
                                continue
                            print(f"  [√] Selection approved!")
                        
                        effective_duration = cut_len
                        print(f"  -> Final Selection: {cut_start:.2f}s - {cut_end:.2f}s ({cut_len:.2f}s total)")
                        break
                    except ValueError:
                        print("  Please enter a valid number.")
                break
            else:
                print("  Invalid choice. Enter 1, 2, 3, or 4.")
    
    new_w, new_h, bitrate_k = calculate_target_details(effective_duration, width, height)
    print(f"  Target Size:   {new_w}x{new_h}")

    # Build video filter chain
    vf_parts = ["format=rgba"]
    
    # Add speed-up filter if chosen (setpts changes presentation timestamps)
    if duration_choice == 'speed':
        speed_factor = duration / MAX_DURATION_SEC
        vf_parts.append(f"setpts=PTS/{speed_factor:.4f}")
    
    vf_parts.append(f"scale={new_w}:{new_h}:flags=lanczos")
    vf_parts.append("format=yuva420p")
    vf_chain = ",".join(vf_parts)
    
    # Trim/cut args (applied in ffmpeg command, not filter chain)
    trim_args = []
    if duration_choice == 'trim':
        trim_args = ["-t", str(MAX_DURATION_SEC)]
    elif duration_choice == 'speed':
        # Hard cap at 3s just in case rounding makes it 3.01s
        trim_args = ["-t", str(MAX_DURATION_SEC)]
    elif duration_choice == 'cut':
        trim_args = ["-ss", str(cut_start), "-t", str(effective_duration)]
    
    # 2-Pass Encoding Loop for strict size compliance
    max_attempts = 3
    current_bitrate = bitrate_k

    for attempt in range(max_attempts):
        print(f"--- Encoding Attempt {attempt + 1}/{max_attempts} (Target: {current_bitrate}k) ---")
        
        # Pass 1
        cmd_pass1 = [
            ffmpeg_path, "-y",
            "-i", input_path,
        ] + trim_args + [
            "-c:v", "libvpx-vp9",
            "-pix_fmt", "yuva420p",
            "-r", str(target_fps),
            "-b:v", f"{current_bitrate}k",
            "-vf", vf_chain,
            "-row-mt", "1",
            "-an",
            "-map_metadata", "-1",
            "-pass", "1",
            "-f", "null", "NUL"
        ]
        subprocess.run(cmd_pass1, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        
        # Pass 2
        cmd_pass2 = [
            ffmpeg_path, "-y",
            "-i", input_path,
        ] + trim_args + [
            "-c:v", "libvpx-vp9",
            "-pix_fmt", "yuva420p",
            "-r", str(target_fps),
            "-b:v", f"{current_bitrate}k",
            "-vf", vf_chain,
            "-row-mt", "1", 
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
    print("--- Sticker Compressor v1.2 (Interactive) ---")
    
    ffmpeg_path = find_tool("ffmpeg")
    if not ffmpeg_path:
        print("Error: Could not find ffmpeg.exe in current folder or subfolders.")
        input("Press Enter to exit...")
        sys.exit(1)
        
    # Persistent loop so you can process multiple or retry failed ones
    while True:
        # Get input file from args first time, then from input()
        if len(sys.argv) > 1 and sys.argv[1].strip():
            input_file = sys.argv[1]
            sys.argv[1] = "" # Clear it so we don't loop on the same arg forever
        else:
            print("\n-------------------------------------------")
            input_file = input("Drag & Drop a video here (or 'q' to quit): ").strip()
            
        if input_file.lower() == 'q':
            break
            
        # Aggressive cleaning for messy drag-and-drop paths
        # Removes: " " (double quotes), ' ' (single quotes), and trailing whitespace
        input_file = input_file.strip().strip('"').strip("'").strip()
        
        if not input_file:
            continue

        if not os.path.exists(input_file):
            print(f"Error: File not found: {input_file}")
            print("Make sure the path is correct and try again.")
            continue

        try:
            compress_video(ffmpeg_path, input_file)
            print("\n[√] Processing Complete!")
        except Exception as e:
            print(f"\n[X] An error occurred: {e}")
        
        # If we started with an arg, we might want to exit after one go
        # But for stickers, a loop is usually better.
        # Just ask to continue or wait.
        print("\nReady for the next one!")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nExiting...")
