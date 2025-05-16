from PyQt5.QtCore import QThread, pyqtSignal, QTimer
from utils import OpenAIHelper, create_output_directory, sanitize_for_script, save_image_base64, split_text_into_chunks, save_audio_as_file
from threading import Thread
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
import os
import shutil
import subprocess
import random
import math


def call_with_future(fn, future, args, kwargs):
    try:
        result = fn(*args, **kwargs)
        future.set_result(result)
    except Exception as exc:
        future.set_exception(exc)


def threaded(fn):
    def wrapper(*args, **kwargs):
        future = Future()
        Thread(target=call_with_future, args=(
            fn, future, args, kwargs)).start()
        return future
    return wrapper


POOL_SIZE = 10


class GenerationWorker(QThread):
    progress_update = pyqtSignal(int)
    operation_update = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, api_key, video_title,
                 thumbnail_prompt, images_prompt,
                 intro_prompt, looping_prompt, outro_prompt,
                 loop_length, word_limit, image_count,
                 image_word_limit, logger):
        super().__init__()
        self.api_key = api_key
        self.video_title = video_title
        self.thumbnail_prompt = thumbnail_prompt
        self.images_prompt = images_prompt
        self.images_prompt = images_prompt
        self.intro_prompt = intro_prompt
        self.looping_prompt = looping_prompt
        self.outro_prompt = outro_prompt
        self.loop_length = loop_length
        self.word_limit = word_limit
        self.image_count = image_count
        self.image_word_limit = image_word_limit
        self.logger = logger

    def generate_audio_chunk(self, openai_helper, chunk, output_dir, idx):
        """Generate a single audio file asynchronously"""
        try:
            audio_data = openai_helper.generate_audio(prompt=chunk)
            save_audio_as_file(
                audio_data=audio_data,
                output_file=os.path.join(output_dir, f"audio{idx + 1}.mp3")
            )
            # Update progress for this specific audio generation
            return
        except Exception as e:
            self.logger.error(f"Error generating audio: {str(e)}")
            return None

    def safe_emit_progress(self, value):
        QTimer.singleShot(0, lambda: self.progress_update.emit(value))

    def update_audio_progress(self):
        """Update the progress specifically for audio generation"""
        self.completed_audio_chunks += 1
        progress = 45 + (self.completed_audio_chunks /
                         self.total_audio_chunks * 20)
        self.safe_emit_progress(int(progress))
        self.logger.info(
            f"Generated audio {self.completed_audio_chunks}/{self.total_audio_chunks}!")

    def update_image_progress(self):
        """Update the progress specifically for audio generation"""
        self.completed_image_chunks += 1
        progress = 25 + (self.completed_image_chunks /
                         self.total_image_chunks * 20)
        self.safe_emit_progress(int(progress))
        self.logger.info(
            f"Generated image {self.completed_image_chunks}/{self.total_image_chunks}!")

    def generate_audios(self, openai_helper, chunks, output_dir):
        futures = []
        # Limit pool size based on chunk count
        pool_size = min(POOL_SIZE, len(chunks))
        self.completed_audio_chunks = 0
        self.total_audio_chunks = len(chunks)
        with ThreadPoolExecutor(max_workers=pool_size) as executor:
            # Submit all tasks
            for idx, chunk in enumerate(chunks):
                future = executor.submit(
                    self.generate_audio_chunk, openai_helper, chunk, output_dir, idx)
                futures.append(future)

            # Process completed tasks and update progress
            for future in as_completed(futures):
                try:
                    # Update progress on the main thread using QTimer
                    QTimer.singleShot(0, self.update_audio_progress)
                except Exception as e:
                    self.logger.error(f"Task failed with exception: {e}")

    def generate_chunk_image(self, openai_helper, prompt, output_dir, idx):
        """Generate a single image file asynchronously"""
        try:
            image_data = openai_helper.generate_image(
                prompt=prompt,
                size="landscape",
                quality="low"
            )
            save_image_base64(
                image_data=image_data,
                output_file=os.path.join(output_dir, f"image{idx + 1}.jpg"),
                width=1920,
                height=1080
            )
            # Update progress for this specific audio generation
            return
        except Exception as e:
            self.logger.error(f"Error generating video: {str(e)}")
            return None

    def generate_images(self, openai_helper, chunks, images_prompt, output_dir, script_base):
        futures = []
        # Limit pool size based on chunk count
        pool_size = min(POOL_SIZE, len(chunks))
        self.total_image_chunks = len(chunks)
        self.completed_image_chunks = 0
        with ThreadPoolExecutor(max_workers=pool_size) as executor:
            # Submit all tasks
            for idx, chunk in enumerate(chunks):
                prompt = images_prompt.replace('$intro', script_base).replace('$chunk', chunk)
                future = executor.submit(
                    self.generate_chunk_image, openai_helper, prompt, output_dir, idx)
                futures.append(future)

            # Process completed tasks and update progress
            for future in as_completed(futures):
                try:
                    # Update progress on the main thread using QTimer
                    QTimer.singleShot(0, self.update_image_progress)
                except Exception as e:
                    self.logger.error(f"Task failed with exception: {e}")

    def run(self):
        temp_folder_path = "__temp__"
        try:
            # 1. Initialize for video generation
            self.logger.info(f"Step 1/6: Initializing")
            self.operation_update.emit("Initializing")
            output_dir = create_output_directory(self.video_title)

            # Check if folder exists
            if not os.path.exists(temp_folder_path):
                os.mkdir(temp_folder_path)
                print(f"Folder '{temp_folder_path}' created successfully")
            else:
                print(f"Folder '{temp_folder_path}' already exists")

            # Initialize OpenAI helper
            openai_helper = OpenAIHelper(self.api_key)

            self.progress_update.emit(5)

            # 2. Generating the scripts
            self.logger.info(f"Step 2/6: Generating Scripts")
            self.operation_update.emit("Generating Scripts")
            prev_id = ""

            looping_script = ""
            self.logger.info(f"Generating intro scripts....")
            (intro_script, prev_id) = openai_helper.generate_text(
                prompt=self.intro_prompt)
            self.logger.info(f"Intro script is generated successfully!")
            self.progress_update.emit(6)
            i = 0

            while i < self.loop_length:
                self.logger.info(
                    f"Generating looping scripts({i+1}/{self.loop_length})....")
                (script, prev_id) = openai_helper.generate_text(
                    prompt=self.looping_prompt, prev_id=prev_id)
                looping_script += script + '\n\n'
                i = i + 1
                self.progress_update.emit(6 + i / self.loop_length * 3)
                self.logger.info(
                    f"Looping script({i}/{self.loop_length}) is generated successfully!")

            self.logger.info(f"Generating outro scripts....")
            (outro_script, prev_id) = openai_helper.generate_text(
                prompt=self.outro_prompt)
            self.progress_update.emit(10)
            self.logger.info(f"Outro script is generated successfully!")

            total_script = intro_script + '\n\n' + looping_script + '\n\n' + outro_script

            sanitize_for_script(total_script)
            sanitize_for_script(intro_script)

            # Save script as a file
            with open(os.path.join(output_dir, 'script.txt'), 'w') as file:
                file.write(total_script)

            # 3. Generate the thumbnail Image
            self.logger.info(f"Step 3/6: Generating Thumbnail")
            self.operation_update.emit("Generating Thumbnail")

            self.thumbnail_prompt = self.thumbnail_prompt.replace(
                "$intro", intro_script)

            img_data = openai_helper.generate_image(
                prompt=self.thumbnail_prompt,
                quality='low',
                size="landscape",
            )
            save_image_base64(
                image_data=img_data,
                output_file=os.path.join(output_dir, "thumbnail.jpg"),
                width=1280,
                height=720
            )
            self.logger.info(f"Thumbnail image is generated successfully!")
            self.progress_update.emit(25)

            # 4. Generate the images based on the script
            self.logger.info(f"Step 4/6: Generating Images")
            self.operation_update.emit("Generating Images")
            image_chunks = split_text_into_chunks(
                total_script,
                chunks_count=self.image_count,
                word_limit=self.image_word_limit
            )

            self.generate_images(openai_helper, image_chunks, self.images_prompt,
                                 output_dir, intro_script)

            # 5. Generate Audios
            self.logger.info(f"Step 5/6: Generating Audios")
            self.operation_update.emit("Generating Audios")
            audio_chunks = split_text_into_chunks(
                total_script,
                chunks_count=-1,
                word_limit=self.word_limit
            )

            self.generate_audios(openai_helper, audio_chunks, output_dir)

            # 6. Make video
            self.logger.info(f"Step 6/6: Generating Video")
            self.operation_update.emit("Generating Video")

            # === Step 1: Merge audio files ===
            audio_list_file = os.path.join(temp_folder_path, 'audios.txt')
            # num_audios = 9
            num_audios = len(audio_chunks)
            with open(audio_list_file, 'w') as f:
                for i in range(1, num_audios + 1):
                    path = os.path.abspath(os.path.join(output_dir, f"audio{i}.mp3"))
                    f.write(
                        f"file '{path}'\n")

            merged_audio = os.path.join(temp_folder_path, 'merged_audio.mp3')
            cmd_concat_audio = [
                'ffmpeg', '-y', '-f', 'concat', '-safe', '0',
                '-i', audio_list_file, '-c', 'copy', merged_audio
            ]
            self.logger.info("🎵 Merging audio files...")
            subprocess.run(cmd_concat_audio, check=True)

            # Get total audio duration
            def get_duration(file):
                cmd = [
                    'ffprobe', '-v', 'error', '-show_entries',
                    'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', file
                ]
                result = subprocess.run(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                return float(result.stdout.strip())

            audio_duration = get_duration(merged_audio)
            particle_duration = get_duration(
                os.path.join("./reference", "particles.webm"))
            self.logger.info(f"⏱ Total audio duration: {audio_duration:.2f}s")

            particle_loops = math.ceil(audio_duration / particle_duration)
            print(particle_loops)
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
                img = os.path.join(output_dir, f"image{idx}.jpg")
                out_clip = os.path.join(temp_folder_path, f'zoom{idx}.mp4')
                zoom_clips.append(os.path.abspath(out_clip))

                speed = 0.001
                zoom_directions = [
                    # Center zoom
                    f"scale=8000x4500, zoompan=z='zoom+{speed}':x='trunc(iw/2-(iw/zoom/2))':y='trunc(ih/2-(ih/zoom/2))':d=120:fps=30,scale=1920:1080",
                    # Left->Right, Top->Bottom zoom
                    f"scale=8000x4500, zoompan=z='zoom+{speed}':x='0':y='0':d=120:fps=30,scale=1920:1080",
                    # Right->Left, Top->Bottom zoom
                    f"scale=8000x4500, zoompan=z='zoom+{speed}':x='trunc(iw-(iw/zoom))':y='0':d=120:fps=30,scale=1920:1080",
                    # Left->Right, Bottom->Top zoom
                    f"scale=8000x4500, zoompan=z='zoom+{speed}':x='0':y='trunc(ih-(ih/zoom))':d=120:fps=30,scale=1920:1080",
                    # Right->Left, Bottom->Top zoom
                    f"scale=8000x4500, zoompan=z='zoom+{speed}':x='trunc(iw-(iw/zoom))':y='trunc(ih-(ih/zoom))':d=120:fps=30,scale=1920:1080",
                ]

                zoom_filter = random.choice(zoom_directions)

                if idx < num_images:
                    duration = zoom_duration
                    cmd = [
                        'ffmpeg', '-y', '-loop', '1', '-i', img,
                        '-preset', 'superfast',
                        '-threads', '4',
                        '-vf', zoom_filter,
                        '-s', output_size,
                        '-t', str(duration), '-pix_fmt', 'yuv420p', out_clip
                    ]
                    self.logger.info(
                        f"🎥 Creating zoom clip for {img} (duration: {duration:.2f}s)")
                    subprocess.run(cmd, check=True)
                else:
                    # Apply particle effect to the last image
                    particle_effect = os.path.join(
                        temp_folder_path, 'last_with_particles.mp4')
                    extended_particle_effect = os.path.join(
                        temp_folder_path, 'extended_last_with_particles.mp4')

                    # Combine image with particle effect
                    cmd_particle = [
                        'ffmpeg', '-loop', '1', '-i', img, '-i', os.path.join(
                            "reference", 'particles.webm'),
                        '-filter_complex', "[0:v]scale=1920:1080,setsar=1[bg];"
                        "[1:v]scale=1920:1080,format=rgba,colorchannelmixer=aa=0.3[particles];"
                        "[bg][particles]overlay=format=auto",
                        '-shortest', '-pix_fmt', 'yuv420p',
                        '-s', output_size,
                        "-y", particle_effect
                    ]
                    self.logger.info(f"✨ Applying particle effect to {img}")
                    subprocess.run(cmd_particle, check=True)

                    # Extend the particle effect video to match the remaining audio duration
                    cmd_extend = [
                        'ffmpeg', '-stream_loop', f'{str(particle_loops)}', '-i', particle_effect,
                        '-c', 'copy', extended_particle_effect
                    ]
                    self.logger.info(
                        f"🔄 Extending particle effect video duration")
                    subprocess.run(cmd_extend, check=True)

                    zoom_clips[-1] = os.path.abspath(extended_particle_effect)

                self.progress_update.emit(65 + idx / num_images * 30)

            # === Step 3: Concatenate video clips ===
            ts_clips = []
            for clip in zoom_clips:
                ts_path = clip.replace(".mp4", ".ts")
                subprocess.run([
                    "ffmpeg", "-y", "-i", clip,
                    "-c", "copy", "-bsf:v", "h264_mp4toannexb",
                    "-f", "mpegts", ts_path
                ], check=True)
                ts_clips.append(ts_path)

            full_video = os.path.join(temp_folder_path, 'slideshow.mp4')
            concat_input = '|'.join(ts_clips)
            cmd_concat_video = [
                "ffmpeg", "-y", "-i", f"concat:{concat_input}",
                "-c", "copy", "-bsf:a", "aac_adtstoasc", full_video
            ]
            subprocess.run(cmd_concat_video, check=True)

            # === Step 4: Combine the video and audio ===
            cmd_final = [
                'ffmpeg', '-y', '-i', full_video, '-i', merged_audio,
                '-c:v', 'copy', '-c:a', 'aac', '-shortest', os.path.join(
                    output_dir, output_video)
            ]
            # cmd_final = [
            #     'ffmpeg', '-y', '-i', full_video, '-i', merged_audio,
            #     '-c:v', 'libx264', '-preset', 'fast', '-pix_fmt', 'yuv420p',
            #     '-c:a', 'aac', '-b:a', '192k',
            #     '-shortest', os.path.join(output_dir, output_video)
            # ]
            self.logger.info(
                f"🔗 Combining video and audio into {output_video}...")
            subprocess.run(cmd_final, check=True)

            print("✅ Final video with audio created successfully!")
            self.progress_update.emit(100)

            # Final progress
            shutil.rmtree(temp_folder_path)
            self.progress_update.emit(100)
            self.operation_update.emit("Completed")

        except Exception as e:
            self.logger.error(f"Error during generation: {str(e)}")
            self.operation_update.emit(f"Error: {str(e)}")

        finally:
            self.finished.emit()
