from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class DadosPerfil(_message.Message):
    __slots__ = ("user_id", "nome", "bio", "extensao_foto")
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    NOME_FIELD_NUMBER: _ClassVar[int]
    BIO_FIELD_NUMBER: _ClassVar[int]
    EXTENSAO_FOTO_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    nome: str
    bio: str
    extensao_foto: str
    def __init__(self, user_id: _Optional[str] = ..., nome: _Optional[str] = ..., bio: _Optional[str] = ..., extensao_foto: _Optional[str] = ...) -> None: ...

class PedacoCadastro(_message.Message):
    __slots__ = ("dados", "pedaco_foto")
    DADOS_FIELD_NUMBER: _ClassVar[int]
    PEDACO_FOTO_FIELD_NUMBER: _ClassVar[int]
    dados: DadosPerfil
    pedaco_foto: bytes
    def __init__(self, dados: _Optional[_Union[DadosPerfil, _Mapping]] = ..., pedaco_foto: _Optional[bytes] = ...) -> None: ...

class PerfilCriado(_message.Message):
    __slots__ = ("user_id", "tamanho_foto_bytes")
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    TAMANHO_FOTO_BYTES_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    tamanho_foto_bytes: int
    def __init__(self, user_id: _Optional[str] = ..., tamanho_foto_bytes: _Optional[int] = ...) -> None: ...

class PedidoAtualizarPerfil(_message.Message):
    __slots__ = ("user_id", "nome", "bio")
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    NOME_FIELD_NUMBER: _ClassVar[int]
    BIO_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    nome: str
    bio: str
    def __init__(self, user_id: _Optional[str] = ..., nome: _Optional[str] = ..., bio: _Optional[str] = ...) -> None: ...

class PedidoFeed(_message.Message):
    __slots__ = ("user_id", "incluir_avaliados")
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    INCLUIR_AVALIADOS_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    incluir_avaliados: bool
    def __init__(self, user_id: _Optional[str] = ..., incluir_avaliados: _Optional[bool] = ...) -> None: ...

class PedidoQuemMeCurtiu(_message.Message):
    __slots__ = ("user_id",)
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    def __init__(self, user_id: _Optional[str] = ...) -> None: ...

class PedidoPerfil(_message.Message):
    __slots__ = ("user_id",)
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    def __init__(self, user_id: _Optional[str] = ...) -> None: ...

class Perfil(_message.Message):
    __slots__ = ("user_id", "nome", "bio", "foto", "tipo_foto")
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    NOME_FIELD_NUMBER: _ClassVar[int]
    BIO_FIELD_NUMBER: _ClassVar[int]
    FOTO_FIELD_NUMBER: _ClassVar[int]
    TIPO_FOTO_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    nome: str
    bio: str
    foto: bytes
    tipo_foto: str
    def __init__(self, user_id: _Optional[str] = ..., nome: _Optional[str] = ..., bio: _Optional[str] = ..., foto: _Optional[bytes] = ..., tipo_foto: _Optional[str] = ...) -> None: ...

class PedidoAvaliacao(_message.Message):
    __slots__ = ("de_user_id", "para_user_id")
    DE_USER_ID_FIELD_NUMBER: _ClassVar[int]
    PARA_USER_ID_FIELD_NUMBER: _ClassVar[int]
    de_user_id: str
    para_user_id: str
    def __init__(self, de_user_id: _Optional[str] = ..., para_user_id: _Optional[str] = ...) -> None: ...

class Confirmacao(_message.Message):
    __slots__ = ("mensagem",)
    MENSAGEM_FIELD_NUMBER: _ClassVar[int]
    mensagem: str
    def __init__(self, mensagem: _Optional[str] = ...) -> None: ...
