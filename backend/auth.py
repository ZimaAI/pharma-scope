"""Password hashing for administrator-provisioned accounts."""
import hashlib
import hmac
import secrets

def hash_password(password: str) -> str:
    if not 12 <= len(password) <= 256:
        raise ValueError('Passwords must contain 12 to 256 characters')
    salt=secrets.token_hex(16)
    digest=hashlib.scrypt(password.encode(),salt=salt.encode(),n=16384,r=8,p=1).hex()
    return f'scrypt${salt}${digest}'

def verify_password(password: str, encoded: str) -> bool:
    try:
        if not isinstance(password, str) or len(password) > 256: return False
        scheme,salt,digest=encoded.split('$')
        if scheme != 'scrypt': return False
        actual=hashlib.scrypt(password.encode(),salt=salt.encode(),n=16384,r=8,p=1).hex()
        return hmac.compare_digest(actual,digest)
    except (ValueError,TypeError): return False
