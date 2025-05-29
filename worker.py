from PyQt5.QtCore import QThread, pyqtSignal
from utils import OpenAIHelper, create_output_directory, sanitize_for_script, split_text_into_chunks, get_first_paragraph
from logging import Logger
import os, shutil, subprocess, random, math, traceback, json, requests, base64
import time
import gc  # Add garbage collection
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

POOL_SIZE = 10


class GenerationWorker(QThread):
    progress_update = pyqtSignal(int)
    operation_update = pyqtSignal(str)
    finished = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self, api_key, video_title,
                 thumbnail_prompt, images_prompt,
                 intro_prompt, looping_prompt, outro_prompt,
                 loop_length, word_limit, image_count, image_word_limit,
                 workflow_file, 
                 logger: Logger):
        super().__init__()
        self.api_key = api_key
        self.video_title = video_title
        self.thumbnail_prompt = thumbnail_prompt
        self.images_prompt = images_prompt
        self.intro_prompt = intro_prompt
        self.looping_prompt = looping_prompt
        self.outro_prompt = outro_prompt
        self.loop_length = loop_length
        self.word_limit = word_limit
        self.image_count = image_count
        self.image_word_limit = image_word_limit
        self.logger = logger
        self._is_cancelled = False
        
        # Runtime tracking
        self.start_time = None
        self.step_times = {}
        
        # Initialize threading components for parallel audio generation
        self.audio_progress_lock = threading.Lock()
        self.completed_audio_count = 0
        
        try:
            with open(workflow_file, 'r') as f:
                self.comfy_workflow = json.load(f)
        except Exception as e:
            self.logger.error(f"Failed to load workflow file: {e}")
            raise

    def cancel(self):
        """Allow cancellation of the worker thread"""
        self._is_cancelled = True
        self.quit()

    def _check_cancelled(self):
        """Check if operation was cancelled"""
        if self._is_cancelled:
            raise Exception("Operation cancelled by user")

    def _log_step_time(self, step_name, start_time):
        """Log the time taken for a specific step"""
        step_duration = time.time() - start_time
        self.step_times[step_name] = step_duration
        self.logger.info(f"⏱️ {step_name} completed in {step_duration:.2f} seconds")

    def _format_duration(self, seconds):
        """Format duration in a human-readable format"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = seconds % 60
        
        if hours > 0:
            return f"{hours}h {minutes}m {secs:.1f}s"
        elif minutes > 0:
            return f"{minutes}m {secs:.1f}s"
        else:
            return f"{secs:.1f}s"

    def _log_runtime_summary(self):
        """Log a comprehensive summary of runtime statistics"""
        total_runtime = time.time() - self.start_time
        
        self.logger.info("=" * 60)
        self.logger.info("🎬 VIDEO GENERATION RUNTIME SUMMARY")
        self.logger.info("=" * 60)
                
        # Total runtime
        self.logger.info(f"📊 TOTAL RUNTIME: {self._format_duration(total_runtime)}")
        self.logger.info("-" * 40)
        
        # Individual step times
        self.logger.info("📋 STEP-BY-STEP BREAKDOWN:")
        step_order = [
            "Initialization",
            "Script Generation", 
            "Thumbnail Generation",
            "Image Generation",
            "Audio Generation", 
            "Video Assembly"
        ]
        
        for step in step_order:
            if step in self.step_times:
                duration = self.step_times[step]
                percentage = (duration / total_runtime) * 100
                self.logger.info(f"   {step}: {self._format_duration(duration)} ({percentage:.1f}%)")
        
        self.logger.info("-" * 40)
        
        # Performance metrics
        if "Script Generation" in self.step_times:
            scripts_per_sec = (1 + self.loop_length + 1) / self.step_times["Script Generation"]
            self.logger.info(f"📝 Script generation rate: {scripts_per_sec:.2f} scripts/second")
            
        if "Image Generation" in self.step_times:
            images_per_sec = self.image_count / self.step_times["Image Generation"]
            self.logger.info(f"🖼️  Image generation rate: {images_per_sec:.2f} images/second")
            
        if "Audio Generation" in self.step_times:
            estimated_chunks = len(split_text_into_chunks("dummy text " * 100, -1, self.word_limit))
            audio_per_sec = estimated_chunks / self.step_times["Audio Generation"]
            self.logger.info(f"🎵 Audio generation rate: {audio_per_sec:.2f} clips/second")
        
        self.logger.info("-" * 40)
        self.logger.info(f"🎯 Video Title: {self.video_title}")
        self.logger.info(f"📅 Completed at: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        self.logger.info("=" * 60)

    def _safe_api_call(self, func, *args, max_retries=3, **kwargs):
        """Wrapper for API calls with retry logic and timeout"""
        for attempt in range(max_retries):
            try:
                self._check_cancelled()
                result = func(*args, **kwargs)
                # Force garbage collection after heavy operations
                gc.collect()
                return result
            except requests.exceptions.Timeout:
                self.logger.warning(f"API call timeout, attempt {attempt + 1}/{max_retries}")
                if attempt == max_retries - 1:
                    raise
                time.sleep(2 ** attempt)
            except requests.exceptions.RequestException as e:
                self.logger.warning(f"API call failed, attempt {attempt + 1}/{max_retries}: {e}")
                if attempt == max_retries - 1:
                    raise
                time.sleep(2 ** attempt)
            except Exception as e:
                self.logger.error(f"Unexpected error in API call: {e}")
                raise

    def _safe_subprocess_run(self, cmd, timeout=300, **kwargs):
        """Wrapper for subprocess calls with timeout and error handling"""
        try:
            self._check_cancelled()
            self.logger.info(f"Running command: {' '.join(cmd[:3])}...")
            
            # Set default kwargs for subprocess
            subprocess_kwargs = {
                'check': True,
                'timeout': timeout,
                'stdout': subprocess.PIPE,
                'stderr': subprocess.PIPE,
                'text': True
            }
            subprocess_kwargs.update(kwargs)
            
            result = subprocess.run(cmd, **subprocess_kwargs)
            return result
            
        except subprocess.TimeoutExpired:
            self.logger.error(f"Command timed out after {timeout}s")
            raise Exception(f"FFmpeg operation timed out after {timeout} seconds")
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Command failed with exit code {e.returncode}")
            self.logger.error(f"stderr: {e.stderr}")
            raise Exception(f"FFmpeg operation failed: {e.stderr}")
       
    def _generate_single_audio(self, audio_task):
        """Generate a single audio file - thread-safe function"""
        idx, audio_chunk, output_dir = audio_task
        
        try:
            self._check_cancelled()
            
            data = {
                'text': audio_chunk,
                'voice': "am_michael",
                'speed': 1,
                'language': "a"
            }
            
            result = self._safe_requests_call("http://localhost:8000/tts/base64", data, timeout=180)
            
            if 'audio_base64' not in result:
                raise Exception("No audio data in TTS response")
                
            audio_data = base64.b64decode(result['audio_base64'])
            
            # Save to file with correct naming
            filename = os.path.join(output_dir, f"audio{idx+1}.wav")
            with open(filename, 'wb') as f:
                f.write(audio_data)
            
            # Thread-safe progress update
            with self.audio_progress_lock:
                self.completed_audio_count += 1
                progress = int(45 + (self.completed_audio_count / self.total_audio_chunks) * 20)
                self.progress_update.emit(progress)
            
            self.logger.info(f"🎵 Generated audio {idx + 1} for chunk (parallel)")
            
            # Clear audio data and force garbage collection
            del audio_data
            gc.collect()
            
            return idx, True, None
            
        except Exception as e:
            self.logger.error(f"Failed to generate audio {idx + 1}: {e}")
            return idx, False, str(e)

    def _generate_audio_parallel(self, audio_chunks, output_dir, max_workers=4):
        """Generate audio files in parallel with up to 4 concurrent threads"""
        self.logger.info(f"🎵 Starting parallel audio generation with {max_workers} workers")
        
        # Reset progress tracking
        with self.audio_progress_lock:
            self.completed_audio_count = 0
            self.total_audio_chunks = len(audio_chunks)
        
        # Create list of tasks (index, chunk, output_dir)
        audio_tasks = [(idx, chunk, output_dir) for idx, chunk in enumerate(audio_chunks)]
        
        # Track results to ensure all files are generated
        results = {}
        failed_tasks = []
        
        # Use ThreadPoolExecutor for parallel processing
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks
            future_to_task = {
                executor.submit(self._generate_single_audio, task): task 
                for task in audio_tasks
            }
            
            # Process completed tasks as they finish
            for future in as_completed(future_to_task):
                task = future_to_task[future]
                idx = task[0]
                
                try:
                    result_idx, success, error = future.result()
                    results[result_idx] = success
                    
                    if not success:
                        failed_tasks.append((result_idx, error))
                        
                except Exception as e:
                    self.logger.error(f"Audio generation task {idx + 1} failed: {e}")
                    failed_tasks.append((idx, str(e)))
                    results[idx] = False
        
        # Check if all audio files were generated successfully
        if failed_tasks:
            failed_indices = [str(idx + 1) for idx, _ in failed_tasks]
            raise Exception(f"Failed to generate audio files: {', '.join(failed_indices)}")
        
        # Verify all files exist with correct naming
        missing_files = []
        for idx in range(len(audio_chunks)):
            filename = os.path.join(output_dir, f"audio{idx+1}.wav")
            if not os.path.exists(filename):
                missing_files.append(f"audio{idx+1}.wav")
        
        if missing_files:
            raise Exception(f"Missing audio files after generation: {', '.join(missing_files)}")
        
        self.logger.info(f"✅ Successfully generated {len(audio_chunks)} audio files in parallel")
        return True
    
    def _safe_requests_call(self, url, data=None, timeout=300, max_retries=3):
        """Safe wrapper for requests with proper session management"""
        session = None
        try:
            for attempt in range(max_retries):
                try:
                    self._check_cancelled()
                    
                    # Create new session for each attempt
                    session = requests.Session()
                    session.headers.update({
                        'Connection': 'close',
                        'Content-Type': 'application/json'
                    })
                    
                    response = session.post(url, json=data, timeout=timeout)
                    response.raise_for_status()
                    
                    result = response.json()
                    return result
                    
                except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                    self.logger.warning(f"Request failed, attempt {attempt + 1}/{max_retries}: {e}")
                    if attempt == max_retries - 1:
                        raise
                    time.sleep(2 ** attempt)
                finally:
                    if session:
                        session.close()
                        
        except Exception as e:
            self.logger.error(f"Request failed after {max_retries} attempts: {e}")
            raise
        finally:
            if session:
                session.close()

    def run(self):
        # Start timing the entire process
        self.start_time = time.time()
        self.logger.info(f"🚀 Starting video generation at {time.strftime('%Y-%m-%d %H:%M:%S')}")
        
        temp_folder_path = "__temp__"
        output_dir = None
        
        try:
            # 1. Initialize for video generation
            step_start = time.time()
            self.logger.info(f"Step 1/6: Initializing")
            self.operation_update.emit("Initializing")
            output_dir = create_output_directory(self.video_title)

            # Check if folder exists
            if not os.path.exists(temp_folder_path):
                os.makedirs(temp_folder_path, exist_ok=True)
                self.logger.info(f"Folder '{temp_folder_path}' created successfully")
            else:
                self.logger.info(f"Folder '{temp_folder_path}' already exists")

            # Initialize OpenAI helper
            openai_helper = OpenAIHelper(self.api_key)
            self.progress_update.emit(5)
            self._log_step_time("Initialization", step_start)

            # 2. Generating the scripts
            step_start = time.time()
            self.logger.info(f"Step 2/6: Generating Scripts")
            self.operation_update.emit("Generating Scripts")
            
            # Generate intro script with error handling
            self.logger.info(f"Generating intro scripts....")
            try:
                (intro_script, prev_id) = self._safe_api_call(
                    openai_helper.generate_text,
                    prompt=self.intro_prompt
                )
                
                if intro_script is None:
                    raise Exception(f"Failed to generate intro script: {prev_id}")
                    
                self.logger.info(f"Intro script generated successfully!")
                self.progress_update.emit(6)
                
            except Exception as e:
                self.logger.error(f"Failed to generate intro script: {e}")
                raise

            # Generate looping scripts
            looping_script = ""
            for idx in range(1, self.loop_length + 1):
                self._check_cancelled()
                
                self.logger.info(f"Generating looping scripts({idx}/{self.loop_length})....")
                try:
                    (script, prev_id) = self._safe_api_call(
                        openai_helper.generate_text,
                        prompt=self.looping_prompt, 
                        prev_id=prev_id
                    )
                    
                    if script is None:
                        raise Exception(f"Failed to generate looping script {idx}: {prev_id}")
                        
                    looping_script += script + '\n\n'
                    self.logger.info(f"Looping script({idx}/{self.loop_length}) generated successfully!")
                    self.progress_update.emit(int(6 + idx / self.loop_length * 3))
                    
                    # Small delay to prevent overwhelming the API
                    time.sleep(0.5)
                    
                except Exception as e:
                    self.logger.error(f"Failed to generate looping script {idx}: {e}")
                    raise

            # Generate outro script
            self.logger.info(f"Generating outro scripts....")
            try:
                (outro_script, prev_id) = self._safe_api_call(
                    openai_helper.generate_text,
                    prompt=self.outro_prompt,
                    prev_id=prev_id
                )
                
                if outro_script is None:
                    raise Exception(f"Failed to generate outro script: {prev_id}")
                    
                self.logger.info(f"Outro script generated successfully!")
                self.progress_update.emit(10)
                
            except Exception as e:
                self.logger.error(f"Failed to generate outro script: {e}")
                raise

            total_script = intro_script + '\n\n' + looping_script + '\n\n' + outro_script
            total_script = sanitize_for_script(total_script)
            intro_script = sanitize_for_script(intro_script)

            # Save script as a file
            with open(os.path.join(output_dir, 'script.txt'), 'w', encoding='utf-8') as file:
                file.write(total_script)

            # Force garbage collection after script generation
            gc.collect()
            self._log_step_time("Script Generation", step_start)

            # 3. Generate the thumbnail Image
            step_start = time.time()
            self.logger.info(f"Step 3/6: Generating Thumbnail")
            self.operation_update.emit("Generating Thumbnail")

            try:
                data = {
                    "prompt": self.thumbnail_prompt,
                    "workflow": self.comfy_workflow,
                    "width": 1280,
                    "height": 720,
                    "format": "base64"
                }
                
                result = self._safe_requests_call("http://localhost:5000/generate", data, timeout=300)
                images = result.get('images', {})
                
                # Get the first image from the first node
                image_data = None
                for node_id, node_images in images.items():
                    if node_images:
                        image_data = node_images[0]
                        break
                        
                if not image_data:
                    raise Exception("No image data found in response")
                
                with open(os.path.join(output_dir, 'thumbnail.jpg'), 'wb') as f:
                    f.write(base64.b64decode(image_data))

                self.logger.info(f"Thumbnail image generated successfully!")
                self.progress_update.emit(25)
                
                # Clear image data from memory
                del image_data
                gc.collect()
                
            except Exception as e:
                self.logger.error(f"Failed to generate thumbnail: {e}")
                raise
            
            self._log_step_time("Thumbnail Generation", step_start)

            # 4. Generate the images based on the script
            step_start = time.time()
            self.logger.info(f"Step 4/6: Generating Images")
            self.operation_update.emit("Generating Images")
            
            image_chunks = split_text_into_chunks(
                total_script,
                chunks_count=self.image_count,
                word_limit=self.image_word_limit
            )

            for idx, chunk in enumerate(image_chunks):
                self._check_cancelled()
                
                try:
                    chunk_prompt = self.images_prompt.replace('$chunk', chunk)
                    with open(os.path.join(output_dir, f"image{idx + 1}-prompt.txt"), 'w') as f:
                        f.write(chunk_prompt)
                    
                    data = {
                        "prompt": chunk_prompt,
                        "workflow": self.comfy_workflow,
                        "width": 1920,
                        "height": 1080,
                        "format": "base64"
                    }
                    
                    result = self._safe_requests_call("http://localhost:5000/generate", data, timeout=300)
                    images = result.get('images', {})
                    
                    # Get the first image from the first node
                    image_data = None
                    for node_id, node_images in images.items():
                        if node_images:
                            image_data = node_images[0]
                            break
                            
                    if not image_data:
                        raise Exception("No image data found in response")
                    
                    # FIX: Save to correct filename (was saving to thumbnail.jpg)
                    with open(os.path.join(output_dir, f'image{idx + 1}.jpg'), 'wb') as f:
                        f.write(base64.b64decode(image_data))
                    
                    progress = 25 + ((idx + 1) / len(image_chunks) * 20)
                    self.progress_update.emit(int(progress))
                    self.logger.info(f"Generated image {idx + 1}/{len(image_chunks)}!")
                    
                    # Clear image data and force garbage collection
                    del image_data
                    gc.collect()
                    
                    # Small delay between image generations
                    time.sleep(1)
                    
                except Exception as e:
                    self.logger.error(f"Failed to generate image {idx + 1}: {e}")
                    raise

            self._log_step_time("Image Generation", step_start)

            # 5. Generate Audios
            step_start = time.time()
            self.logger.info(f"Step 5/6: Generating Audios")
            self.operation_update.emit("Generating Audios")
            
            audio_chunks = split_text_into_chunks(
                total_script,
                chunks_count=-1,
                word_limit=self.word_limit
            )

            self._generate_audio_parallel(audio_chunks, output_dir, max_workers=4)

            self._log_step_time("Audio Generation", step_start)

            # 6. Make video
            step_start = time.time()
            self.logger.info(f"Step 6/6: Generating Video")
            self.operation_update.emit("Generating Video")

            # === Step 1: Merge audio files ===
            audio_list_file = os.path.join(temp_folder_path, 'audios.txt')
            
            num_audios = len(audio_chunks)
            # num_audios =11 

            # Create list file for WAV files
            with open(audio_list_file, 'w') as f:
                for i in range(1, num_audios + 1):
                    path = os.path.abspath(os.path.join(output_dir, f"audio{i}.wav"))  # Changed to .wav
                    f.write(f"file '{path}'\n")

            merged_audio = os.path.join(temp_folder_path, 'merged_audio.wav')  # Keep as WAV initially

            # Merge WAV files - this should work smoothly since they're all the same format
            cmd_concat_audio = [
                'ffmpeg', '-y', '-f', 'concat', '-safe', '0',
                '-i', audio_list_file, 
                '-c', 'copy',  # Can safely copy WAV files
                merged_audio
            ]

            self.logger.info("🎵 Merging WAV audio files...")
            self._safe_subprocess_run(cmd_concat_audio, timeout=180)

            # Optional: Convert merged WAV to MP3 for final video (smaller file size)
            merged_audio_mp3 = os.path.join(temp_folder_path, 'merged_audio.mp3')
            cmd_wav_to_mp3 = [
                'ffmpeg', '-y', '-i', merged_audio,
                '-c:a', 'libmp3lame',
                '-b:a', '128k',
                '-ar', '44100',
                merged_audio_mp3
            ]

            self.logger.info("🎵 Converting merged audio to MP3...")
            self._safe_subprocess_run(cmd_wav_to_mp3, timeout=120)

            # Update merged_audio path to use MP3 version for final video
            merged_audio = merged_audio_mp3

            # Get total audio duration
            def get_duration(file):
                cmd = [
                    'ffprobe', '-v', 'error', '-show_entries',
                    'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', file
                ]
                result = self._safe_subprocess_run(cmd, timeout=30)
                return float(result.stdout.strip())

            audio_duration = get_duration(merged_audio)
            particle_duration = get_duration(os.path.join("./reference", "particles.webm"))
            self.logger.info(f"⏱ Total audio duration: {audio_duration:.2f}s")

            particle_loops = math.ceil(audio_duration / particle_duration)
            self.progress_update.emit(65)

            # === Parameters ===
            output_video = 'final_slideshow_with_audio.mp4'
            zoom_duration = 4  # seconds per image (except last)
            output_size = '1920x1080'

            # === Step 2: Create zoomed clips ===
            zoom_clips = []
            # num_images = 3
            num_images = len(image_chunks)
            
            for idx in range(1, num_images + 1):
                self._check_cancelled()
                
                img = os.path.join(output_dir, f"image{idx}.jpg")
                out_clip = os.path.join(temp_folder_path, f'zoom{idx}.mp4')
                zoom_clips.append(os.path.abspath(out_clip))

                speed = 0.001
                zoom_directions = [
                    f"scale=8000x4500, zoompan=z='zoom+{speed}':x='trunc(iw/2-(iw/zoom/2))':y='trunc(ih/2-(ih/zoom/2))':d=120:fps=30,scale=1920:1080",
                    f"scale=8000x4500, zoompan=z='zoom+{speed}':x='0':y='0':d=120:fps=30,scale=1920:1080",
                    f"scale=8000x4500, zoompan=z='zoom+{speed}':x='trunc(iw-(iw/zoom))':y='0':d=120:fps=30,scale=1920:1080",
                    f"scale=8000x4500, zoompan=z='zoom+{speed}':x='0':y='trunc(ih-(ih/zoom))':d=120:fps=30,scale=1920:1080",
                    f"scale=8000x4500, zoompan=z='zoom+{speed}':x='trunc(iw-(iw/zoom))':y='trunc(ih-(ih/zoom))':d=120:fps=30,scale=1920:1080",
                ]

                zoom_filter = random.choice(zoom_directions)

                try:
                    if idx < num_images:
                        duration = zoom_duration
                        cmd = [
                            'ffmpeg', '-y', '-loop', '1', '-i', img,
                            '-preset', 'ultrafast',
                            '-threads', '4',  # Reduced thread count
                            '-vf', zoom_filter,
                            '-s', output_size,
                            '-t', str(duration), '-pix_fmt', 'yuv420p', out_clip
                        ]
                        self.logger.info(f"🎥 Creating zoom clip for {img} (duration: {duration:.2f}s)")
                        self._safe_subprocess_run(cmd, timeout=120)
                    else:
                        # Apply particle effect to the last image
                        particle_effect = os.path.join(temp_folder_path, 'last_with_particles.mp4')
                        extended_particle_effect = os.path.join(temp_folder_path, 'extended_last_with_particles.mp4')

                        # Combine image with particle effect
                        cmd_particle = [
                            'ffmpeg', '-loop', '1', '-i', img, '-i', os.path.join("reference", 'particles.webm'),
                            '-filter_complex', "[0:v]scale=1920:1080,setsar=1[bg];"
                            "[1:v]scale=1920:1080,format=rgba,colorchannelmixer=aa=0.3[particles];"
                            "[bg][particles]overlay=format=auto",
                            '-shortest', '-pix_fmt', 'yuv420p',
                            '-s', output_size, "-y", particle_effect
                        ]
                        self.logger.info(f"✨ Applying particle effect to {img}")
                        self._safe_subprocess_run(cmd_particle, timeout=180)

                        # Extend the particle effect video
                        cmd_extend = [
                            'ffmpeg', '-stream_loop', f'{str(particle_loops)}', '-i', particle_effect,
                            '-c', 'copy', extended_particle_effect
                        ]
                        self.logger.info(f"🔄 Extending particle effect video duration")
                        self._safe_subprocess_run(cmd_extend, timeout=120)

                        zoom_clips[-1] = os.path.abspath(extended_particle_effect)

                    self.progress_update.emit(int(65 + idx / num_images * 25))
                    
                except Exception as e:
                    self.logger.error(f"Failed to create video clip {idx}: {e}")
                    raise

            # === Step 3: Concatenate video clips ===
            ts_clips = []
            for clip in zoom_clips:
                self._check_cancelled()
                
                ts_path = clip.replace(".mp4", ".ts")
                self._safe_subprocess_run([
                    "ffmpeg", "-y", "-i", clip,
                    "-c", "copy", "-bsf:v", "h264_mp4toannexb",
                    "-f", "mpegts", ts_path
                ], timeout=120)
                ts_clips.append(ts_path)

            full_video = os.path.join(temp_folder_path, 'slideshow.mp4')
            concat_input = '|'.join(ts_clips)
            cmd_concat_video = [
                "ffmpeg", "-y", "-i", f"concat:{concat_input}",
                "-c", "copy", "-bsf:a", "aac_adtstoasc", full_video
            ]
            self._safe_subprocess_run(cmd_concat_video, timeout=300)

            # === Step 4: Combine the video and audio ===
            cmd_final = [
                'ffmpeg', '-y', '-i', full_video, '-i', merged_audio,
                '-c:v', 'copy', '-c:a', 'aac', '-shortest', 
                os.path.join(output_dir, output_video)
            ]
            self.logger.info(f"🔗 Combining video and audio into {output_video}...")
            self._safe_subprocess_run(cmd_final, timeout=600)

            self.logger.info("✅ Final video with audio created successfully!")
            self.progress_update.emit(100)
            self._log_step_time("Video Assembly", step_start)

            # Log comprehensive runtime summary
            self._log_runtime_summary()

            # Final cleanup
            if os.path.exists(temp_folder_path):
                shutil.rmtree(temp_folder_path)
                
            self.operation_update.emit("Completed")

        except Exception as e:
            # Log error with runtime info
            if self.start_time:
                error_runtime = time.time() - self.start_time
                self.logger.error(f"❌ Video generation failed after {self._format_duration(error_runtime)}: {e}")
            else:
                self.logger.error(f"❌ Video generation failed: {e}")
                
            self.operation_update.emit(f"Error: {str(e)}")
            self.error_occurred.emit(str(e))
            traceback.print_exc()
            
            # Cleanup on error
            try:
                if os.path.exists(temp_folder_path):
                    shutil.rmtree(temp_folder_path)
            except:
                pass

        finally:
            try:
                if 'intro_script' in locals():
                    description = get_first_paragraph(intro_script)
                    self.finished.emit(description)
                else:
                    self.finished.emit("Generation failed")
            except:
                self.finished.emit("Generation completed with errors")