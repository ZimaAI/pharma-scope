"""Password hashing for administrator-provisioned accounts."""
import hashlib
import hmac
import secrets

def hash_password(password: str) -> str:
    if len(password) < 12:
        raise ValueError('Live passwords must contain at least 12 characters')
    salt=secrets.token_hex(16)
    digest=hashlib.scrypt(password.encode(),salt=salt.encode(),n=16384,r=8,p=1).hex()
    return f'scrypt${salt}${digest}'

def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme,salt,digest=encoded.split('$')
        if scheme != 'scrypt': return False
        actual=hashlib.scrypt(password.encode(),salt=salt.encode(),n=16384,r=8,p=1).hex()
        return hmac.compare_digest(actual,digest)
    except (ValueError,TypeError): return False
