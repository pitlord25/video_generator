import json, os, logging, base64, io
from typing import Literal, Dict, Any, Optional
from openai import OpenAI
from PIL import Image

class OpenAIHelper:
    """Helper class for interacting with OpenAI APIs"""

    def __init__(
        self,
        api_key: str
    ):
        """
        Initialize OpenAI helper
        Args:
            api_key: OpenAI API key
        """
        self.openai_client = OpenAI(api_key=api_key)
        self.logger = logging.getLogger(__name__)
        self.logger.info("OpenAI helper initialized")

    def generate_text(
        self,
        prompt: str,
        model="gpt-4o-mini",
        max_tokens=16000,
        temperature=1.0,
        top_p=1.0,
        prev_id: str = None,
    ):
        response = self.openai_client.responses.create(
            model=model,
            input=prompt,
            max_output_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            previous_response_id=prev_id
        )
        if response.error is not None:
            return (None, response.error)
        return (response.output_text, response.id)

    def generate_image(
        self,
        prompt: str,
        model="gpt-image-1",
        size: Literal['square', 'landscape', 'portrait'] = 'square',
        quality: Literal['high', 'medium', 'low', 'hd', 'standard'] = 'high'
    ):
        sizeData = {
            "square": "1024x1024",
            "landscape": "1536x1024",
            "portrait": "1024x1536"
        }
        response = self.openai_client.images.generate(
            model=model,
            prompt=prompt,
            size=sizeData[size],
            quality=quality,
            moderation='low'
        )
        result_b64 = response.data[0].b64_json
        image_data = base64.b64decode(result_b64)
        
        return image_data
    
    def generate_audio(
        self,
        prompt: str,
        model = "gpt-4o-mini-tts",
        voice = "onyx"
    ) :
        result = self.openai_client.audio.speech.create(
            model = "gpt-4o-mini-tts",
            voice=voice,
            input= prompt
        )
        return result.content

def save_image_base64(
    image_data: bytes,
    output_file: str,
    width = 1280,
    height = 720,
) :
    img = Image.open(io.BytesIO(image_data))
    resized_img = img.resize((width, height), Image.Resampling.LANCZOS)
    with open(output_file, 'wb') as f:
        resized_img.save(f, format="JPEG")

def save_audio_as_file(
    audio_data,
    output_file,
) :
    with open(output_file, 'wb') as f:
        f.write(audio_data)
    pass

def create_output_directory(base_dir: str = "output") -> str:
    """
    Create output directory with timestamp
    Args:
        base_dir: Base directory name
    Returns:
        Path to created directory
    """
    from datetime import datetime
    try:
        os.makedirs(base_dir, exist_ok=True)
        logging.info(f"Created output directory: {base_dir}")
        return base_dir
    except Exception as e:
        logging.error(f"Failed to create output directory: {str(e)}")
        # Fall back to base directory
        os.makedirs(base_dir, exist_ok=True)
        return base_dir

def save_config(config: Dict[str, Any], directory: str) -> bool:
    """
    Save configuration to a JSON file
    Args:
        config: Configuration dictionary
        directory: Directory to save the file
    Returns:
        True if successful, False otherwise
    """
    try:
        # Remove API key from the config before saving
        safe_config = config.copy()
        if "api_key" in safe_config:
            safe_config["api_key"] = "[REDACTED]"
        filepath = os.path.join(directory, "config.json")
        with open(filepath, "w") as f:
            json.dump(safe_config, f, indent=2)
        logging.info(f"Saved configuration to {filepath}")
        return True
    except Exception as e:
        logging.error(f"Failed to save configuration: {str(e)}")
        return False

def load_config(filepath: str) -> Optional[Dict[str, Any]]:
    """
    Load configuration from a JSON file
    Args:
        filepath: Path to the configuration file
    Returns:
        Configuration dictionary if successful, None otherwise
    """
    try:
        with open(filepath, "r") as f:
            config = json.load(f)
        logging.info(f"Loaded configuration from {filepath}")
        return config
    except Exception as e:
        logging.error(f"Failed to load configuration: {str(e)}")
        return None

def get_default_settings() -> Dict[str, Any]:
    """
    Get default settings for the application
    Returns:
        Dictionary with default settings
    """
    return {
        "api_key": "",
        "video_title": "",
        "thumbnail_prompt": "",
        "images_prompt": "",
        "disclaimer": "",
        "intro_prompt": "",
        "looping_prompt": "",
        "outro_prompt": "",
        "loop_length": 3,
        "audio_word_limit": 400,
        "image_count": 3,
        "image_word_limit": 15
    }

def get_settings_filepath() -> str:
    """
    Get the filepath for the settings file
    Returns:
        Path to settings file
    """
    # Create settings directory if it doesn't exist
    os.makedirs("settings", exist_ok=True)
    return os.path.join("settings", "video_generator_settings.json")

def sanitize_for_script(text) -> str:
    return (text
        .replace('\u2018', "'")        # curly single quotes
        .replace('\u2019', "'")        # curly single quotes
        .replace('\u201C', '"')        # curly double quotes
        .replace('\u201D', '"')        # curly double quotes
        .replace('\u2013', '-')        # en dash
        .replace('\u2014', '-')        # em dash
        .replace('\u2026', '...')      # ellipsis
        .replace('\u00a0', ' ')        # non-breaking spaces
        .replace('\\', '\\\\')         # escape backslashes
        .replace('"', '\\"')           # escape double quotes
        .replace('\r\n', '\\n')        # escape windows newlines
        .replace('\n', '\\n')          # escape unix newlines
        .replace('\t', ' ')            # remove tabs
        .strip()                       # trim
    )

def split_text_into_chunks(
    text: str,
    chunks_count,
    word_limit = 10,
) -> list:
    """
    Split text into chunks based on sentences, respecting word limit per chunk.
    
    Args:
        text: Input text to be split
        word_limit: Maximum number of words per chunk
        chunks_count: Maximum number of chunks to return
        
    Returns:
        List of text chunks
    """
    import re
    
    # Clean the text (similar to JavaScript version)
    raw = text
    cleaned = raw.replace("\\n", "\n")  # Convert literal \n into real newlines
    cleaned = re.sub(r"\s+", " ", cleaned)  # Collapse multiple spaces/newlines
    cleaned = cleaned.strip()
    
    # Split into sentences
    sentences = re.findall(r'[^\.!\?]+[\.!\?]+(?:\s|$)', cleaned) or []
    
    chunks = []
    current_words = []
    
    for sentence in sentences:
        sentence = sentence.strip()
        sentence_words = sentence.split()
        
        if len(current_words) + len(sentence_words) <= word_limit:
            current_words.extend(sentence_words)
        else:
            chunks.append(" ".join(current_words))
            current_words = sentence_words
    
    # Add the last chunk if there are any words left
    if current_words:
        chunks.append(" ".join(current_words))
    
    # Limit the number of chunks returned
    if chunks_count == -1:
        return chunks
    
    return chunks[:chunks_count]