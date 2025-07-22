from PIL import Image
from io import BytesIO
import onnxruntime as ort
import numpy as np
import string
from abc import ABC, abstractmethod
import logging

logger = logging.getLogger(__name__)

class CaptchaHandle(ABC):
    """Base class for CAPTCHA handlers"""
    
    @abstractmethod
    def solve(self, image: bytes) -> str:
        """Solve the CAPTCHA from image bytes"""
        pass

class OnnxCaptchaHandle(CaptchaHandle):
    """ONNX-based CAPTCHA solver for CEAC"""
    
    def __init__(self, onnx_model_path: str = 'captcha.onnx') -> None:
        super().__init__()
        self.__onnx_model_path = onnx_model_path
        try:
            # Test loading the model
            self.__ort_sess = ort.InferenceSession(self.__onnx_model_path)
            logger.info(f"ONNX model loaded successfully from {onnx_model_path}")
        except Exception as e:
            logger.error(f"Failed to load ONNX model: {e}")
            raise

    def __decode(self, sequence):
        """Decode the sequence to text"""
        characters = '-' + string.digits + string.ascii_uppercase
        a = ''.join([characters[x] for x in sequence])
        s = ''.join([x for j, x in enumerate(a[:-1]) if x != characters[0] and x != a[j+1]])
        if len(s) == 0:
            return ''
        if a[-1] != characters[0] and s[-1] != a[-1]:
            s += a[-1]
        return s

    def solve(self, image: bytes) -> str:
        """Solve the CAPTCHA from image bytes"""
        try:
            # Convert bytes to PIL Image
            img = Image.open(BytesIO(image))
            
            # Resize image to expected dimensions (200x50 based on the error)
            # The model expects width=200, and typical CAPTCHA height is 50
            img = img.resize((200, 50), Image.Resampling.LANCZOS)
            
            # Convert to numpy array and normalize
            img_array = np.asarray(img, dtype=np.float32) / 255.0
            
            # Transpose to match expected input shape (C, H, W) and add batch dimension
            img_array = np.expand_dims(np.transpose(img_array, (2, 0, 1)), axis=0)
            
            # Log the shape for debugging
            logger.info(f"Input shape to model: {img_array.shape}")
            
            # Run inference
            outputs = self.__ort_sess.run(None, {'input': img_array})
            x = outputs[0]
            
            # Decode the output
            t = np.argmax(np.transpose(x, (1, 0, 2)), -1)
            pred = self.__decode(t[0])
            
            logger.info(f"CAPTCHA solved: {pred}")
            return pred
            
        except Exception as e:
            logger.error(f"Error solving CAPTCHA: {e}")
            raise

class ManualCaptchaHandle(CaptchaHandle):
    """Manual CAPTCHA handler that returns None, requiring user input"""
    
    def solve(self, image: bytes) -> str:
        """Returns None to indicate manual solving is needed"""
        logger.info("Manual CAPTCHA solving required")
        return None 