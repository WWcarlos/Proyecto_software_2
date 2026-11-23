import base64
import hashlib
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

JWT_SECRET = os.environ["JWT_SECRET"]
JWT_ALGORITMO = "HS256"
JWT_EXPIRA_SEGUNDOS = int(os.getenv("JWT_EXPIRES_SECONDS", "3600"))


def _prehash(password: str) -> bytes:
    # bcrypt solo admite 72 bytes; se normaliza la longitud con SHA-256 antes de aplicarlo.
    return base64.b64encode(hashlib.sha256(password.encode("utf-8")).digest())


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_prehash(password), bcrypt.gensalt()).decode("utf-8")


def verificar_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(_prehash(password), password_hash.encode("utf-8"))
    except ValueError:
        return False


def crear_token(usuario_id: int, email: str) -> str:
    emitido = datetime.now(timezone.utc)
    claims = {
        "sub": str(usuario_id),
        "email": email,
        "iat": emitido,
        "exp": emitido + timedelta(seconds=JWT_EXPIRA_SEGUNDOS),
        "jti": uuid.uuid4().hex,  # identificador del token: permite revocarlo al cerrar sesión
    }
    return jwt.encode(claims, JWT_SECRET, algorithm=JWT_ALGORITMO)


def generar_codigo_recuperacion() -> str:
    """Código numérico de 6 dígitos para restablecer la contraseña."""
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_codigo(codigo: str) -> str:
    # El código se guarda como hash, igual que las contraseñas (pero basta SHA-256: expira en minutos).
    return hashlib.sha256(codigo.encode("utf-8")).hexdigest()


def decodificar_token(token: str) -> dict:
    """Lanza jwt.PyJWTError si el token es inválido o expiró."""
    return jwt.decode(
        token,
        JWT_SECRET,
        algorithms=[JWT_ALGORITMO],
        options={"require": ["exp", "sub"]},
    )
