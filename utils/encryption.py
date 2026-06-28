
import os
from cryptography.fernet import Fernet
from dotenv import load_dotenv

load_dotenv()

ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")

fernet = Fernet(ENCRYPTION_KEY.encode())


def encrypt_text(text):
    if not text:
        return None

    return fernet.encrypt(text.encode()).decode()


def decrypt_text(encrypted_text):
    if not encrypted_text:
        return ""

    return fernet.decrypt(encrypted_text.encode()).decode()