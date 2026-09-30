from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Optional as _Optional

DESCRIPTOR: _descriptor.FileDescriptor

class PedidoCadastro(_message.Message):
    __slots__ = ("email", "senha", "nome", "bio", "foto", "extensao_foto")
    EMAIL_FIELD_NUMBER: _ClassVar[int]
    SENHA_FIELD_NUMBER: _ClassVar[int]
    NOME_FIELD_NUMBER: _ClassVar[int]
    BIO_FIELD_NUMBER: _ClassVar[int]
    FOTO_FIELD_NUMBER: _ClassVar[int]
    EXTENSAO_FOTO_FIELD_NUMBER: _ClassVar[int]
    email: str
    senha: str
    nome: str
    bio: str
    foto: bytes
    extensao_foto: str
    def __init__(self, email: _Optional[str] = ..., senha: _Optional[str] = ..., nome: _Optional[str] = ..., bio: _Optional[str] = ..., foto: _Optional[bytes] = ..., extensao_foto: _Optional[str] = ...) -> None: ...

class RespostaCadastro(_message.Message):
    __slots__ = ("user_id",)
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    def __init__(self, user_id: _Optional[str] = ...) -> None: ...

class PedidoLogin(_message.Message):
    __slots__ = ("email", "senha")
    EMAIL_FIELD_NUMBER: _ClassVar[int]
    SENHA_FIELD_NUMBER: _ClassVar[int]
    email: str
    senha: str
    def __init__(self, email: _Optional[str] = ..., senha: _Optional[str] = ...) -> None: ...

class RespostaLogin(_message.Message):
    __slots__ = ("user_id",)
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    def __init__(self, user_id: _Optional[str] = ...) -> None: ...
